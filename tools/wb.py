#!/usr/bin/env python3
"""wb.py — DSH 工作台（Workbench）工具链 v0.2

只用标准库。工具用 Python，DSH 插件仍必须用 JS（Cordis 加载器只认 JS）。

用法：
    python wb.py doctor                 # 环境/依赖/接口自检
    python wb.py status                 # 主驾 + 工作台状态（只读）
    python wb.py watch                  # 采集主驾快照 → state/main-status.json
    python wb.py sync-app [--force]     # 把安装同步到 E:\\DSH-WORKBENCH\\app（独立整套）
    python wb.py start [--with-watchdog]  # 无窗口启动工作台（默认带看门狗）
    python wb.py stop                   # 停工作台（含看门狗）
    python wb.py restart
    python wb.py watchdog --main-pids 1,2  # 内部命令：主驾一死就把工作台关掉
    python wb.py logs [-n 40]

约定：
    主 harness home  E:\\DSH\\home        安装 E:\\SSS
    工作台根          E:\\DSH-WORKBENCH   安装 app\\    home\\    port 59430
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ── 常量 ────────────────────────────────────────────────────────────────
WB_ROOT = Path(r"E:\DSH-WORKBENCH")
MAIN_HOME = Path(r"E:\DSH\home")
MAIN_INSTALL = Path(r"E:\SSS")

APP_ROOT = WB_ROOT / "app"
APP_EXE = APP_ROOT / "DeepSeek Harness.exe"
APP_DSH_CMD = APP_ROOT / r"resources\runtime\cli\bin\dsh.cmd"

WB_HOME = WB_ROOT / "home"
WB_PROFILE = "bench"
WB_PORT = 59430
RESERVED_PORTS = {59420, 59430}      # 旧副驾 / 工作台：同一个 exe，别算成主驾
LOG_DIR = WB_ROOT / "logs"
STATE_DIR = WB_ROOT / "state"
PIDS_FILE = STATE_DIR / "pids.json"

NODE_EXE = Path(r"E:\nodejs\node.exe")
GIT_EXE = Path(r"C:\Program Files\Git\cmd\git.exe")
PNPM_MJS = MAIN_HOME / r"dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs"
MEMORY_DB = Path(r"E:\肥鱼工作区\.dsh-meow\memory.db")
LEVELS = ["soul", "user", "project", "fact", "lesson", "topic", "rules"]

DETACHED = 0x00000008
NO_WINDOW = 0x08000000
# 重要：pythonw 起进程时若不带 CREATE_NO_WINDOW，每 spawn 一个控制台程序
# （netstat/taskkill/powershell…）桌面就会闪一个黑窗。所有 subprocess 都必须带上它。
RUNFLAGS = NO_WINDOW

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


# ── 输出小工具 ──────────────────────────────────────────────────────────
def ok(m): print(f"  [ok]   {m}")
def warn(m): print(f"  [warn] {m}")
def bad(m): print(f"  [FAIL] {m}")
def info(m): print(f"  {m}")
def head(t): print(f"\n── {t} " + "─" * max(0, 58 - len(t)))


# ── 进程 / 端口 ─────────────────────────────────────────────────────────
def app_version() -> str:
    rt = APP_ROOT / r"resources\runtime\primary-runtime\runtime.json"
    try:
        return json.loads(rt.read_text(encoding="utf-8")).get("desktopVersion", "unknown")
    except Exception:
        return "unknown"


def main_version() -> str:
    rt = MAIN_INSTALL / r"resources\runtime\primary-runtime\runtime.json"
    try:
        return json.loads(rt.read_text(encoding="utf-8")).get("desktopVersion", "unknown")
    except Exception:
        return "unknown"


def plugin_dirs() -> list[Path]:
    """会挂进 harness 的插件源码目录（工作台 plugins + 现有工作区的喵插件）。"""
    dirs = [p for p in (WB_ROOT / "plugins").glob("*") if (p / "package.json").exists()]
    for guess in [Path(r"E:\肥鱼工作区\meow-panel"), Path(r"E:\肥鱼工作区\persona-preset"),
                  Path(r"E:\肥鱼工作区\_plugin-packages\meow-memory")]:
        if (guess / "package.json").exists():
            dirs.append(guess)
    return dirs


def _k32():
    return ctypes.windll.kernel32


def pid_alive(pid: int) -> bool:
    """不误杀进程的存活检查（不要用 os.kill，Windows 上它会 TerminateProcess）。"""
    if pid <= 0:
        return False
    k32 = _k32()
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def netstat_listen() -> list[tuple[int, int]]:
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             timeout=15, creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING":
            try:
                rows.append((int(parts[1].rsplit(":", 1)[1]), int(parts[4])))
            except ValueError:
                pass
    return rows


def listening_pids(port: int) -> list[int]:
    return [pid for p, pid in netstat_listen() if p == port]


def port_open(port: int, timeout: float = 0.3) -> bool:
    """不 spawn 任何子进程的端口探测（看门狗必须用它，否则桌面会闪黑窗）。"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def main_harness_ports() -> list[int]:
    env_url = os.environ.get("DSH_WEB_URL", "")
    if ":" in env_url:
        tail = env_url.rsplit(":", 1)[-1].split("/")[0]
        if tail.isdigit() and int(tail) not in RESERVED_PORTS:
            return [int(tail)]
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) -join ','"],
            capture_output=True, text=True, timeout=20, creationflags=RUNFLAGS,
            encoding="utf-8", errors="replace",
        ).stdout.strip()
        app_pids = {int(x) for x in ps.split(",") if x.strip().isdigit()}
    except Exception:
        app_pids = set()
    if not app_pids:
        return []
    return sorted({p for p, pid in netstat_listen() if pid in app_pids and p not in RESERVED_PORTS})


def wmi_spawn(cmdline: str) -> int:
    """用 WMI 起进程：父进程是 WmiPrvSE，脱离调用方的 Job 对象，主程序关掉也不会被带走。"""
    ps = (
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{CommandLine = '{cmdline}'}}; $r.ProcessId"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, timeout=60, creationflags=RUNFLAGS,
        encoding="utf-8", errors="replace",
    )
    try:
        return int((proc.stdout or "").strip().splitlines()[-1])
    except Exception:
        return 0


def kill_tree(pid: int) -> bool:
    try:
        subprocess.run([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                        "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=25, creationflags=RUNFLAGS)
        return True
    except Exception:
        return False


# ── 目录 / 状态 ─────────────────────────────────────────────────────────
def memory_counts(db: Path) -> dict:
    if not db.exists():
        return {"error": f"数据库不存在: {db}"}
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"只读打开失败: {exc}"}
    try:
        out = {}
        for level in LEVELS:
            try:
                out[level] = conn.execute(f"SELECT COUNT(*) FROM {level} WHERE status='active'").fetchone()[0]
            except Exception:
                out[level] = None
        return out
    finally:
        conn.close()


def dir_size(path: Path) -> tuple[int, int]:
    files = total = 0
    for root, _d, names in os.walk(path):
        for name in names:
            try:
                total += (Path(root) / name).stat().st_size
                files += 1
            except OSError:
                pass
    return files, total


def read_pids() -> dict:
    if not PIDS_FILE.exists():
        return {}
    for enc in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return json.loads(PIDS_FILE.read_text(encoding=enc))
        except Exception:
            continue
    return {}


def find_supervisors() -> list[int]:
    """按命令行扫 pythonw 里的 `wb.py supervise`（防止记录丢失/重复）。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name = 'pythonw.exe' or Name = 'python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*wb.py*supervise*' } | "
          "Select-Object -ExpandProperty ProcessId")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=40, creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout
        return [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:
        return []


def write_pids(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PIDS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 核心：安装同步 ──────────────────────────────────────────────────────
def bench_profile_json() -> Path:
    return WB_HOME / "profiles" / WB_PROFILE / "package.json"


def npm_latest_version(pkg: str) -> str:
    """查 npm 上的最新版本（先官方源，失败再腾讯镜像）。"""
    npm = Path(r"E:\nodejs\npm.cmd")
    if not npm.exists():
        return ""
    for reg in ("https://registry.npmjs.org/", "https://mirrors.cloud.tencent.com/npm/"):
        try:
            out = subprocess.run(["cmd", "/c", f'"{npm}"', "view", pkg, "version", "--registry", reg],
                                 capture_output=True, text=True, timeout=120, creationflags=RUNFLAGS,
                                 encoding="utf-8", errors="replace").stdout.strip()
            last = [ln.strip() for ln in out.splitlines() if ln.strip()]
            if last and re.match(r"^\d+\.\d+\.\d+", last[-1]):
                return last[-1]
        except Exception:
            continue
    return ""


def cmd_plugins(action: str = "list", spec: str = "", bundle: str = "") -> int:
    """工作台插件管理：list / install / add。"""
    pkg_path = bench_profile_json()
    if not pkg_path.exists():
        bad(f"profile 清单不存在：{pkg_path}")
        return 1
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    deps = data.setdefault("dependencies", {})
    bundles = data.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])

    if action == "list":
        head(f"工作台插件（profile={WB_PROFILE}）")
        for name, spec_v in deps.items():
            in_bundle = name in bundles
            linked = (pkg_path.parent / "node_modules" / name).exists()
            mark = (ok if (in_bundle and linked) else warn)
            mark(f"{name:<28} {'bundle ✓' if in_bundle else 'bundle ✗'}  {'linked ✓' if linked else 'node_modules ✗'}  {spec_v}")
        builtin = [b for b in bundles if b.startswith("@deepseek-ai/")]
        info("底座：" + ", ".join(builtin))
        return 0

    if action == "install":
        env = dict(os.environ, DSH_HOME=str(WB_HOME), DSH_PROFILE=WB_PROFILE)
        proc = subprocess.run(
            ["cmd", "/c", str(APP_DSH_CMD), "plugin", "--profile", WB_PROFILE, "install"],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, creationflags=RUNFLAGS,
        )
        tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()][-4:]
        for ln in tail:
            info(ln)
        (ok if proc.returncode == 0 else bad)(f"install 退出码 {proc.returncode}")
        return 0 if proc.returncode == 0 else 1

    if action == "add":
        if not spec:
            bad("用法：wb.py plugins add <插件目录或包名> [--bundle 名字]")
            return 2
        src = Path(spec)
        name = bundle
        if src.exists() and (src / "package.json").exists():
            meta = json.loads((src / "package.json").read_text(encoding="utf-8"))
            name = name or meta.get("name", src.name)
            deps[name] = "link:" + src.as_posix()
        else:
            name = name or spec
            # 依赖值必须是版本/标签：裸包名先查 npm 拿确切版本，查不到就退 latest
            tail = spec.split("/")[-1]
            if re.search(r"[@^~><=*]", tail) or spec.startswith(("file:", "link:", "github:", "http")):
                value = spec
            else:
                ver = npm_latest_version(spec)
                value = ver or "latest"
                if ver:
                    ok(f"npm 最新版本：{spec}@{ver}")
            deps[name] = value
        if name not in bundles:
            bundles.append(name)
        pkg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ok(f"已写入 profile：{name} → {deps[name]}")
        return cmd_plugins("install")

    bad(f"未知动作：{action}（list/install/add）")
    return 2


def current_url() -> str | None:
    """取最新的带 token 入口（token 每次重启都换）。"""
    log = LOG_DIR / "workbench.out.log"
    if log.exists():
        tokens = re.findall(r"token=([A-Za-z0-9_\-]+)", log.read_text(encoding="utf-8", errors="replace"))
        if tokens:
            url = f"http://127.0.0.1:{WB_PORT}/?token={tokens[-1]}"
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / "workbench-url.txt").write_text(url, encoding="ascii")
            return url
    p = STATE_DIR / "workbench-url.txt"
    return p.read_text(encoding="ascii").strip() if p.exists() else None


def cmd_url() -> int:
    url = current_url()
    if not url:
        bad("还没有入口（工作台没启动过）：wb.py start")
        return 1
    print(url)
    return 0


def cmd_open() -> int:
    """确保工作台在跑，然后用默认浏览器打开带 token 的入口（裸 URL 会 401）。"""
    if not port_open(WB_PORT):
        info("工作台没在跑，先启动…")
        if cmd_start(True) != 0:
            return 1
        time.sleep(1)
    url = current_url()
    if not url:
        bad("拿不到入口 URL")
        return 1
    try:
        os.startfile(url)  # noqa: S606  (Windows 专用，打开默认浏览器)
    except Exception as exc:  # noqa: BLE001
        warn(f"自动打开失败（{exc}），手动复制这个地址：")
        print(url)
        return 1
    ok(f"已在浏览器打开 → {url}")
    return 0


SUPERVISOR_FILE = STATE_DIR / "supervisor.json"


def cmd_supervise(interval: float = 8.0) -> int:
    """自动伴随：主程序在 → 确保工作台在跑；主程序关 → 收掉工作台。常驻、无窗口。"""
    log = LOG_DIR / "supervisor.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # 用 supervisor.json 判重（pids.json 会被 stop 改动，不能当唯一依据）
    for candidate in (SUPERVISOR_FILE, PIDS_FILE):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        pid = int(data.get("pid") or data.get("supervisor") or 0) if candidate is SUPERVISOR_FILE else int(data.get("supervisor") or 0)
        if pid and pid != os.getpid() and pid_alive(pid):
            print(f"supervisor 已在运行 pid={pid}")
            return 0
    SUPERVISOR_FILE.write_text(
        json.dumps({"pid": os.getpid(), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
        encoding="utf-8",
    )
    pids = read_pids()
    pids["supervisor"] = os.getpid()
    write_pids(pids)

    def note(msg: str) -> None:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

    note(f"supervisor start pid={os.getpid()} interval={interval}s")
    was_up = None
    while True:
        try:
            main_ports = main_harness_ports()
            main_up = bool(main_ports)
            wb_up = port_open(WB_PORT)
            if main_up != was_up:
                note(f"main harness {'up' if main_up else 'down'} ports={main_ports}")
                was_up = main_up
            if main_up and not wb_up:
                note("workbench missing → starting")
                cmd_start(True)
            elif (not main_up) and wb_up:
                note("main harness gone → stopping workbench")
                cmd_stop()
        except Exception as exc:  # noqa: BLE001
            note(f"loop error: {exc}")
        time.sleep(interval)


def cmd_page() -> int:
    """只打开页面：不启动任何东西（工作台没跑就直说）。"""
    if not port_open(WB_PORT):
        warn(f"工作台没在跑（{WB_PORT} 无响应）。先双击「DSH 工作台」，或等自动伴随把它拉起来。")
        return 1
    url = current_url()
    if not url:
        bad("拿不到入口 URL")
        return 1
    try:
        os.startfile(url)  # noqa: S606
    except Exception as exc:  # noqa: BLE001
        warn(f"打开失败（{exc}），手动复制：")
        print(url)
        return 1
    ok(f"已打开 → {url}")
    return 0


def cmd_supervisor_status() -> int:
    head("自动伴随（supervisor）")
    sup = read_pids().get("supervisor") or 0
    if sup and pid_alive(int(sup)):
        ok(f"运行中 pid={sup}")
    else:
        warn("未运行（wb.py supervise，或开机自启快捷方式）")
    log = LOG_DIR / "supervisor.log"
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]:
            info(line)
    return 0


def cmd_suspend() -> int:
    """暂停：先停自动伴随，再停工作台（否则 8 秒后会被拉回来）。"""
    head("暂停自动伴随 + 工作台")
    victims = set()
    sup = int(read_pids().get("supervisor") or 0)
    if sup:
        victims.add(sup)
    if SUPERVISOR_FILE.exists():
        try:
            victims.add(int(json.loads(SUPERVISOR_FILE.read_text(encoding="utf-8-sig")).get("pid") or 0))
        except Exception:
            pass
    victims.update(find_supervisors())
    victims = {p for p in victims if p and pid_alive(p)}
    if not victims:
        warn("没找到运行中的 supervisor")
    for pid in victims:
        kill_tree(pid)
        ok(f"已结束 supervisor（pid={pid}）")
    pids = read_pids()
    pids["supervisor"] = 0
    write_pids(pids)
    cmd_stop()
    info("要恢复：wb.py resume（或重新登录，开机自启会拉起）")
    return 0


def cmd_resume() -> int:
    """恢复：用 WMI 重新起自动伴随。"""
    head("恢复自动伴随")
    pids = read_pids()
    sup = int(pids.get("supervisor") or 0)
    if sup and pid_alive(sup):
        warn(f"supervisor 已在运行 pid={sup}")
        return 0
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    pid = wmi_spawn(f'"{exe}" "{Path(__file__).resolve()}" supervise')
    if pid:
        pids["supervisor"] = pid
        write_pids(pids)
        ok(f"supervisor 已启动 pid={pid}（主程序在的话 8 秒内会拉起工作台）")
        return 0
    bad("启动失败")
    return 1


def cmd_compat() -> int:
    """版本/兼容性视角：主驾 vs 工作台 vs 插件声明的 peer 版本。"""
    head("版本")
    mv, wv = main_version(), app_version()
    info(f"主 harness   {mv}   ({MAIN_INSTALL})")
    info(f"工作台       {wv}   ({APP_ROOT})")
    if mv == wv:
        ok("两边版本一致（接口行为应当相同）")
    else:
        warn(f"版本不一致：主驾 {mv} / 工作台 {wv}")
        info("→ 工作台是独立整套，主驾升级不会动它；是否跟进由你决定：")
        info("  · 继续用旧版：什么都不用做（插件按旧接口跑）")
        info("  · 跟进新版：wb.py sync-app --force  （会先把旧 app 备份成 backups\\app-<ver>-<时间>）")
        info("  · 回滚旧版：wb.py rollback")

    head("插件声明的版本约束")
    dirs = plugin_dirs()
    if not dirs:
        warn("没找到插件源码目录")
        return 0
    for d in dirs:
        try:
            data = json.loads((d / "package.json").read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            warn(f"{d.name}: package.json 解析失败 {exc}")
            continue
        peers = data.get("peerDependencies") or {}
        dsh_peers = {k: v for k, v in peers.items() if "dsh" in k or k.startswith("@deepseek-ai")}
        name = data.get("name", d.name)
        ver = data.get("version", "?")
        if dsh_peers:
            info(f"{name} {ver}  约束: " + ", ".join(f"{k}@{v}" for k, v in dsh_peers.items()))
        else:
            info(f"{name} {ver}  没有声明 dsh peer 版本约束（升级时靠人工验证）")

    live = STATE_DIR / "api-live.json"
    if live.exists():
        try:
            p = json.loads(live.read_text(encoding="utf-8"))
            info(f"活体快照版本 {p.get('version')}（不一致说明需要重新采集：wb.py api）")
        except Exception:
            pass
    return 0


def cmd_sync_app(force: bool = False) -> int:
    head("同步安装到工作台")
    if (APP_EXE.exists()) and not force:
        ok(f"已存在 {APP_EXE}（要重新同步加 --force）")
        return 0
    if not MAIN_INSTALL.exists():
        bad(f"主安装不存在：{MAIN_INSTALL}")
        return 1
    was_running = bool(listening_pids(WB_PORT))
    if APP_ROOT.exists():
        # 先停掉在跑的工作台，再把旧安装改名备份（秒级完成、可回滚；不复制 1.7GB）
        if was_running:
            cmd_stop()
        bak_dir = WB_ROOT / "backups"
        bak_dir.mkdir(parents=True, exist_ok=True)
        bak = bak_dir / f"app-{app_version()}-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            APP_ROOT.rename(bak)
            ok(f"旧安装已备份 → {bak}")
        except Exception:
            warn("改名备份失败，退回直接删除旧副本")
            shutil.rmtree(APP_ROOT, ignore_errors=True)
    info("复制中（约 1.7GB，请稍等）…")
    started = time.time()
    rc = subprocess.run(
        ["robocopy", str(MAIN_INSTALL), str(APP_ROOT), "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=RUNFLAGS,
    ).returncode
    if rc > 7:
        bad(f"robocopy 失败（退出码 {rc}）")
        return 1
    files, size = dir_size(APP_ROOT)
    ok(f"完成：{files} 文件 / {size / 1048576:.0f} MB，用时 {time.time() - started:.0f}s")
    ok(f"exe:   {APP_EXE}")
    ok(f"cli:   {APP_DSH_CMD}")
    ok(f"版本:  {app_version()}")
    if was_running:
        info("之前工作台在跑，重新拉起…")
        cmd_start(True)
    return 0


def cmd_rollback() -> int:
    """把安装回滚到 backups 里最近的一份旧安装。"""
    head("回滚工作台安装")
    bak_dir = WB_ROOT / "backups"
    baks = sorted([p for p in bak_dir.glob("app-*") if p.is_dir()]) if bak_dir.exists() else []
    if not baks:
        bad("没有可回滚的备份（backups\\app-*）")
        return 1
    info("可用备份：")
    for b in baks:
        info(f"  {b.name}")
    target = baks[-1]
    was_running = bool(listening_pids(WB_PORT))
    if was_running:
        cmd_stop()
    cur = bak_dir / f"app-{app_version()}-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        APP_ROOT.rename(cur)
        ok(f"当前安装另存 → {cur}")
    except Exception:
        shutil.rmtree(APP_ROOT, ignore_errors=True)
    target.rename(APP_ROOT)
    ok(f"已回滚到 → {target.name}（现在版本 {app_version()}）")
    if was_running:
        cmd_start(True)
    return 0


# ── 核心：profile ───────────────────────────────────────────────────────
BENCH_PATCH = """# 工作台（bench）补丁层：不接 agent，只当插件宿主
- id: agent-loop
  disabled: true
- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: deepseek-official
    model: deepseek-flash
"""


def sync_credentials() -> None:
    """把主驾的凭据（含 DEEPSEEK_API_KEY）复制到工作台，避免界面反复要求填 API。"""
    src = MAIN_HOME / ".credentials.yaml"
    dst = WB_HOME / ".credentials.yaml"
    if not src.exists():
        warn("主驾没有 .credentials.yaml，工作台会保持匿名（界面可能要求填 API）")
        return
    need = True
    if dst.exists():
        try:
            s, d = src.read_text(encoding="utf-8", errors="replace"), dst.read_text(encoding="utf-8", errors="replace")
            if "DEEPSEEK_API_KEY" in d or "DEEPSEEK_API_KEY" not in s:
                need = False
        except Exception:
            need = True
    if need:
        WB_HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        ok(f"已同步凭据 → {dst}")
    anon = MAIN_HOME / ".anonymous-user-id"
    if anon.exists() and not (WB_HOME / ".anonymous-user-id").exists():
        shutil.copy2(anon, WB_HOME / ".anonymous-user-id")


def ensure_profile() -> int:
    prof_dir = WB_HOME / "profiles" / WB_PROFILE
    pkg = prof_dir / "package.json"
    env = dict(os.environ, DSH_HOME=str(WB_HOME), DSH_PROFILE=WB_PROFILE)
    if not pkg.exists():
        info(f"用 web 模板创建 profile {WB_PROFILE} …")
        WB_HOME.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cmd", "/c", str(APP_DSH_CMD), "--profile", WB_PROFILE,
                        "--from-default-profile", "web", "--dump-config"],
                       env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180, creationflags=RUNFLAGS)
        # 首次创建时套用仓库里的种子（插件清单 + 补丁层），重建时可复原
        seed_dir = WB_ROOT / "seeds" / WB_PROFILE
        if seed_dir.exists() and pkg.exists():
            for f in seed_dir.iterdir():
                if f.is_file():
                    (pkg.parent / f.name).write_bytes(f.read_bytes())
            ok(f"已套用种子：{seed_dir}")
    if not pkg.exists():
        bad(f"profile 创建失败：{pkg}")
        return 1
    patch = prof_dir / "cordis.patch.yml"
    patch.write_text(BENCH_PATCH, encoding="utf-8")
    ok(f"profile {WB_PROFILE} 就绪：{prof_dir}")
    return 0


# ── 启动 / 停止 ─────────────────────────────────────────────────────────
def cmd_start(with_watchdog: bool = True) -> int:
    head("启动工作台")
    if not APP_DSH_CMD.exists():
        warn("还没有工作台自己的安装，先同步")
        if cmd_sync_app(False) != 0:
            return 1
        if not APP_DSH_CMD.exists():
            bad(f"仍找不到 {APP_DSH_CMD}")
            return 1

    pids_existing = listening_pids(WB_PORT)
    if pids_existing:
        warn(f"已经在跑（端口 {WB_PORT}，pid={pids_existing}）")
        return 0

    if ensure_profile() != 0:
        return 1
    sync_credentials()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, DSH_HOME=str(WB_HOME), DSH_PROFILE=WB_PROFILE)
    out_log = LOG_DIR / "workbench.out.log"
    err_log = LOG_DIR / "workbench.err.log"
    with open(out_log, "ab") as fo, open(err_log, "ab") as fe:
        serve = subprocess.Popen(
            ["cmd", "/c", str(APP_DSH_CMD), "--profile", WB_PROFILE,
             "--port", str(WB_PORT), "--no-open"],
            env=env, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL,
            creationflags=DETACHED | NO_WINDOW,
        )
    info(f"工作台进程 pid={serve.pid}，等端口 {WB_PORT} …")

    deadline = time.time() + 120
    while time.time() < deadline:
        if listening_pids(WB_PORT):
            break
        if not pid_alive(serve.pid):
            bad("工作台进程提前退出了，看日志")
            print_logs(20)
            return 1
        time.sleep(0.6)
    else:
        bad(f"120 秒内端口 {WB_PORT} 没起来")
        print_logs(20)
        return 1

    ok(f"端口 {WB_PORT} 已监听")

    pids = {"serve": serve.pid, "watchdog": 0, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if with_watchdog:
        main_ports = main_harness_ports()
        main_pids = sorted({pid for p in main_ports for pid in listening_pids(p)})
        if not main_pids:
            warn("没找到主 harness 进程，看门狗不启用（主驾开起来后再 restart）")
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            exe = pythonw if pythonw.exists() else Path(sys.executable)
            # 关键：用 WMI 起看门狗，脱离主程序的 Job，主程序关闭时它才活着把工作台关掉
            wd_pid = wmi_spawn(f'"{exe}" "{Path(__file__).resolve()}" watchdog --main-pids {",".join(map(str, main_pids))}')
            pids["watchdog"] = wd_pid
            if wd_pid:
                ok(f"看门狗已挂（pid={wd_pid}，独立于主程序；盯主驾 pid={main_pids}）")
            else:
                warn("看门狗启动失败（WMI 返回 0）")
    write_pids(pids)
    ok(f"启动完成。日志：{LOG_DIR}")
    return 0


def cmd_stop() -> int:
    head("停止工作台")
    pids = read_pids()
    stopped = False
    for name in ("watchdog", "serve"):
        pid = int(pids.get(name) or 0)
        if pid and pid_alive(pid):
            kill_tree(pid)
            ok(f"已结束 {name}（pid={pid}）")
            stopped = True
    for pid in listening_pids(WB_PORT):
        kill_tree(pid)
        ok(f"已结束占用 {WB_PORT} 的进程（pid={pid}）")
        stopped = True
    # 只清 serve/watchdog，别把 supervisor 的记录一起抹掉
    pids = read_pids()
    pids["serve"] = 0
    pids["watchdog"] = 0
    write_pids(pids)
    if not stopped:
        warn("没有在跑的工作台")
    return 0


def cmd_restart(with_watchdog: bool = True) -> int:
    cmd_stop()
    time.sleep(1.5)
    return cmd_start(with_watchdog)


# ── 看门狗：主驾一死就关工作台 ──────────────────────────────────────────
def cmd_watchdog(main_pids: list[int], interval: float = 8.0) -> int:
    log = LOG_DIR / "watchdog.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    def note(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(line)

    note(f"watchdog start, main pids={main_pids}, wb port={WB_PORT}")
    while True:
        time.sleep(interval)
        # 全部用 socket + ctypes，不 spawn 子进程：桌面不会再闪窗
        if not port_open(WB_PORT):
            note("workbench not listening any more → watchdog exit")
            return 0
        alive = [pid for pid in main_pids if pid_alive(pid)]
        if not alive:
            note("main harness gone → stopping workbench")
            for pid in listening_pids(WB_PORT):
                kill_tree(pid)
            pids = read_pids()
            pids["serve"] = 0
            write_pids(pids)
            return 0


# ── 诊断 ────────────────────────────────────────────────────────────────
def cmd_doctor() -> int:
    head("运行时")
    info(f"python      {sys.version.split()[0]}  ({sys.executable})")
    (ok if NODE_EXE.exists() else bad)(f"node        {NODE_EXE}")
    (ok if PNPM_MJS.exists() else bad)(f"pnpm.mjs    {PNPM_MJS}")
    (ok if GIT_EXE.exists() else warn)(f"git         {GIT_EXE}")
    try:
        pipv = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True,
                              timeout=25, creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout.strip()
    except Exception:
        pipv = ""
    (ok if pipv else warn)(f"pip         {pipv or '不可用'}")
    java = shutil.which("java") or ""
    (ok if java else warn)(f"java        {java or '缺失（需要时装到 G 盘）'}")

    head("主 harness")
    (ok if MAIN_INSTALL.exists() else bad)(f"安装        {MAIN_INSTALL}")
    (ok if MAIN_HOME.exists() else bad)(f"数据        {MAIN_HOME}")
    ports = main_harness_ports()
    (ok if ports else warn)(f"主 GUI 端口 {', '.join(map(str, ports)) or '未检测到'}")

    head("记忆（只读）")
    counts = memory_counts(MEMORY_DB)
    if "error" in counts:
        bad(counts["error"])
    else:
        ok("可只读访问：" + " / ".join(f"{k}={v}" for k, v in counts.items()))

    head("工作台")
    (ok if APP_EXE.exists() else warn)(f"独立安装    {APP_EXE if APP_EXE.exists() else '未同步（wb.py sync-app）'}")
    (ok if (WB_HOME / 'profiles' / WB_PROFILE / 'package.json').exists() else warn)(f"profile     {WB_HOME / 'profiles' / WB_PROFILE}")
    pids = listening_pids(WB_PORT)
    (ok if pids else warn)(f"端口 {WB_PORT} {'在听 pid=' + str(pids) if pids else '空闲'}")
    wd = read_pids().get("watchdog") or 0
    (ok if (wd and pid_alive(int(wd))) else warn)(f"看门狗      {'运行中 pid=' + str(wd) if (wd and pid_alive(int(wd))) else '未运行'}")
    return 0


def cmd_status() -> int:
    head("主 harness")
    ports = main_harness_ports()
    if ports:
        for port in ports:
            ok(f"端口 {port} 在听 (pid={','.join(map(str, listening_pids(port)))})")
    else:
        warn("主 GUI 没在跑")
    files, size = dir_size(MAIN_HOME)
    info(f"home        {files} 文件 / {size / 1048576:.1f} MB")
    counts = memory_counts(MEMORY_DB)
    info("记忆        " + ("无法读取: " + counts["error"] if "error" in counts
                          else " / ".join(f"{k}={v}" for k, v in counts.items())))

    head("工作台")
    pids = listening_pids(WB_PORT)
    (ok if pids else warn)(f"端口 {WB_PORT} {'在听 (pid=' + ','.join(map(str, pids)) + ')' if pids else '没在听（wb.py start）'}")
    wd = int(read_pids().get("watchdog") or 0)
    (ok if (wd and pid_alive(wd)) else warn)(f"看门狗      {'运行中 pid=' + str(wd) if (wd and pid_alive(wd)) else '未运行'}")
    state_file = STATE_DIR / "main-status.json"
    if state_file.exists():
        ok(f"状态快照    {state_file.name}（{time.time() - state_file.stat().st_mtime:.0f} 秒前）")
    else:
        warn("状态快照    还没有（wb.py watch）")
    return 0


def cmd_watch() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ports = main_harness_ports()
    payload = {
        "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mainHarness": {"ports": ports, "install": str(MAIN_INSTALL), "home": str(MAIN_HOME)},
        "memory": memory_counts(MEMORY_DB),
        "workbench": {"port": WB_PORT, "listening": bool(listening_pids(WB_PORT))},
        "profiles": {},
    }
    prof_dir = MAIN_HOME / "profiles"
    if prof_dir.exists():
        for prof in prof_dir.iterdir():
            pkg = prof / "package.json"
            if pkg.exists():
                try:
                    data = json.loads(pkg.read_text(encoding="utf-8"))
                    payload["profiles"][prof.name] = {
                        "bundles": (data.get("dsh") or {}).get("profile", {}).get("bundles", []),
                        "dependencies": list((data.get("dependencies") or {}).keys()),
                    }
                except Exception as exc:  # noqa: BLE001
                    payload["profiles"][prof.name] = {"error": str(exc)}
    out = STATE_DIR / "main-status.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"已写入 {out}")
    return 0


def cmd_api() -> int:
    """接口基线：①把工作台 profile 的组装结果 dump 出来 ②合上 state/api-live.json（活体快照）。"""
    head("接口基线")
    if not APP_DSH_CMD.exists():
        bad(f"找不到工作台安装：{APP_DSH_CMD}")
        return 1
    env = dict(os.environ, DSH_HOME=str(WB_HOME), DSH_PROFILE=WB_PROFILE)
    proc = subprocess.run(
        ["cmd", "/c", str(APP_DSH_CMD), "--profile", WB_PROFILE, "--dump-config"],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, creationflags=RUNFLAGS,
    )
    if proc.returncode != 0:
        bad(f"dump-config 失败（退出码 {proc.returncode}）")
        for line in (proc.stderr or "").splitlines()[:10]:
            info(line)
        return 1

    layer = "?"
    rows: dict[str, list[dict]] = {}
    order: list[str] = []
    for line in proc.stdout.splitlines():
        s = line.strip()
        m = re.match(r"^#\s*==\s*(.+?)(?:,\s*patched by .*)?$", s)
        if m:
            layer = m.group(1).strip()
            if layer not in rows:
                rows[layer] = []
                order.append(layer)
            continue
        m = re.match(r"^-\s*id:\s*(\S+)", s)
        if m:
            if layer not in rows:
                rows[layer] = []
                order.append(layer)
            rows[layer].append({"id": m.group(1), "name": "", "disabled": False})
            continue
        m = re.match(r"^name:\s*'?([^']+)'?$", s)
        if m and rows.get(layer):
            rows[layer][-1]["name"] = m.group(1).strip()
            continue
        if s.startswith("disabled:"):
            if rows.get(layer):
                rows[layer][-1]["disabled"] = "true" in s.lower()

    build = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workbenchProfile": WB_PROFILE,
        "layers": [{"layer": l, "rows": rows[l]} for l in order],
        "totals": {
            "layers": len(order),
            "rows": sum(len(v) for v in rows.values()),
            "disabled": sum(1 for v in rows.values() for r in v if r["disabled"]),
        },
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    build_path = STATE_DIR / "api-build.json"
    build_path.write_text(json.dumps(build, ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"组装结果 → {build_path}（{build['totals']['rows']} 行 / {build['totals']['layers']} 层）")

    live_path = STATE_DIR / "api-live.json"
    live = {}
    if live_path.exists():
        try:
            live = json.loads(live_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            warn(f"api-live.json 解析失败：{exc}")
    else:
        warn("还没有活体快照（state/api-live.json），先跑 tools/collect-live-api.py")

    app_ver = app_version()
    if live:
        if live.get("version") != app_ver:
            warn(f"活体快照版本 {live.get('version')} ≠ 当前安装 {app_ver}，需要重新采集")
        else:
            ok(f"活体快照版本一致：{app_ver}")
        ok(f"服务 {live['counts']['services']} 个 / 槽位 {live['counts']['slots']} 个")

    doc = WB_ROOT / "docs" / "interface-baseline.md"
    lines = [
        "# 接口基线（自动生成）",
        "",
        f"- 生成时间：{build['generatedAt']}",
        f"- DSH 版本：{app_ver}",
        f"- 工作台 profile：{WB_PROFILE}",
        f"- 组装行数：{build['totals']['rows']}（禁用 {build['totals']['disabled']}）",
        "",
        "## profile 分层（每个 bundle 产出的行）",
        "",
        "| 层 | 行数 | 插件 id |",
        "|---|---|---|",
    ]
    for entry in build["layers"]:
        ids = ", ".join(("~~" + r["id"] + "~~") if r["disabled"] else r["id"] for r in entry["rows"])
        lines.append(f"| {entry['layer']} | {len(entry['rows'])} | {ids} |")

    if live:
        lines += [
            "",
            f"## 活体接口（版本 {live['version']}）",
            "",
            f"- 宿主服务 **{live['counts']['services']}** 个（`ctx.<key>`）",
            f"- 前端槽位 **{live['counts']['slots']}** 个",
            "",
            "### 常用挂载点",
            "",
            "| 槽位 | 类型 | 作用 |",
            "|---|---|---|",
        ]
        want = ["main", "sidebar.panellist", "sidebar.footer.action", "settings.section",
                "settings.general.item", "shell.overlay", "conversation.input.right",
                "conversation.input.left", "plugins.detail.section", "conversation.view",
                "conversation.chat.node", "conversation.composer.dock"]
        by_name = {s["name"]: s for s in live["slots"]}
        for name in want:
            s = by_name.get(name)
            if s:
                purpose = s["purpose"].replace("|", "\\|")
                lines.append(f"| `{name}` | {s['kind']} | {purpose[:110]} |")
        lines += ["", "### 宿主服务（前 30）", "", "| key | 说明 |", "|---|---|"]
        for s in live["services"][:30]:
            desc = (s["description"] or "")[:90].replace("|", "\\|")
            lines.append(f"| `{s['key']}` | {desc} |")

    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok(f"文档 → {doc}")
    return 0


def print_logs(n: int = 40) -> None:
    for name in ("workbench.out.log", "workbench.err.log", "watchdog.log"):
        p = LOG_DIR / name
        head(name)
        if not p.exists():
            info("(空)")
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        for line in lines:
            info(line)


def cmd_logs(n: int = 40) -> int:
    print_logs(n)
    return 0


# ── 入口 ────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wb.py", add_help=True)
    ap.add_argument("command", nargs="?", default="status")
    ap.add_argument("sub", nargs="?", default="")
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--with-watchdog", action="store_true", default=True)
    ap.add_argument("--no-watchdog", dest="with_watchdog", action="store_false")
    ap.add_argument("--main-pids", default="")
    ap.add_argument("--bundle", default="")
    ap.add_argument("--action", default="list")
    ap.add_argument("--spec", default="")
    ap.add_argument("-n", type=int, default=40)
    args = ap.parse_args(argv[1:])

    table = {
        "doctor": lambda: cmd_doctor(),
        "status": lambda: cmd_status(),
        "watch": lambda: cmd_watch(),
        "api": lambda: cmd_api(),
        "compat": lambda: cmd_compat(),
        "plugins": lambda: cmd_plugins(args.sub or "list", (args.rest[0] if args.rest else ""), args.bundle),
        "url": lambda: cmd_url(),
        "open": lambda: cmd_open(),
        "page": lambda: cmd_page(),
        "supervise": lambda: cmd_supervise(),
        "supervisor": lambda: cmd_supervisor_status(),
        "suspend": lambda: cmd_suspend(),
        "resume": lambda: cmd_resume(),
        "rollback": lambda: cmd_rollback(),
        "sync-app": lambda: cmd_sync_app(args.force),
        "start": lambda: cmd_start(args.with_watchdog),
        "stop": lambda: cmd_stop(),
        "restart": lambda: cmd_restart(args.with_watchdog),
        "logs": lambda: cmd_logs(args.n),
        "watchdog": lambda: cmd_watchdog([int(x) for x in args.main_pids.split(",") if x.strip()]),
    }
    if args.command not in table:
        print(__doc__)
        return 2
    return table[args.command]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
