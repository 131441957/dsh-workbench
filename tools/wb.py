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
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
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


# ── 路径自动识别 ────────────────────────────────────────────────────────
CONFIG_FILE = WB_ROOT / "config.json"


def valid_install(p: Path) -> bool:
    return (p / "DeepSeek Harness.exe").exists() and (p / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd").exists()


def valid_home(p: Path) -> bool:
    return (p / "profiles").is_dir()


def _ps_lines(script: str, timeout: float = 60) -> list[str]:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             timeout=timeout, creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def detect_install() -> tuple[Path | None, str]:
    """识别主 harness 安装目录：运行中进程 → 快捷方式 → 注册表 → 常见位置。"""
    # 1) 正在运行的主程序（排除工作台自己那份副本）
    for line in _ps_lines("Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue | "
                          "Select-Object -ExpandProperty Path"):
        try:
            p = Path(line).parent
        except Exception:
            continue
        if str(p).lower().startswith(str(WB_ROOT).lower()):
            continue
        if valid_install(p):
            return p, "运行中的主程序"

    # 2) 桌面 / 开始菜单快捷方式
    ps = r'''
$sh = New-Object -ComObject WScript.Shell
$dirs = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('StartMenu'),
          [Environment]::GetFolderPath('CommonStartMenu'))
foreach ($d in $dirs) {
  if (-not (Test-Path $d)) { continue }
  Get-ChildItem $d -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
    try { $t = $sh.CreateShortcut($_.FullName).TargetPath; if ($t) { $t } } catch {}
  }
}
'''
    for line in _ps_lines(ps):
        if line.lower().endswith("deepseek harness.exe"):
            p = Path(line).parent
            if valid_install(p):
                return p, "快捷方式"

    # 3) 注册表卸载项
    ps_reg = r'''
$keys = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
          'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
          'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
foreach ($k in $keys) {
  Get-ItemProperty $k -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like '*DeepSeek Harness*' } |
    ForEach-Object { $_.InstallLocation; $_.DisplayIcon }
}
'''
    for line in _ps_lines(ps_reg):
        raw = line.split(",")[0].strip('"')
        cand = Path(raw).parent if raw.lower().endswith(".exe") else Path(raw)
        if valid_install(cand):
            return cand, "注册表"

    # 4) 常见位置兜底
    guesses = [Path(r"E:\SSS"), Path(r"E:\SOS"), Path(r"D:\SSS"),
               Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "DeepSeek Harness",
               Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DeepSeek Harness"]
    for g in guesses:
        if valid_install(g):
            return g, "常见位置"
    return None, "未找到"


def detect_home(install: Path | None) -> tuple[Path | None, str]:
    """识别主 harness 数据目录（DSH_HOME）。"""
    env = os.environ.get("DSH_HOME")
    if env and valid_home(Path(env)):
        return Path(env), "DSH_HOME 环境变量"

    cands: list[tuple[Path, str]] = []
    if install:
        cands.append((install.parent / "DSH" / "home", "安装目录旁的 DSH\\home"))
        cands.append((install / "home", "安装目录内 home"))
        cands.append((install.parent / "home", "安装目录上一级 home"))
    cands.append((Path(os.environ.get("USERPROFILE", "")) / ".dsh", "用户目录 .dsh"))
    cands.append((Path(r"E:\DSH\home"), "已知位置 E:\\DSH\\home"))

    for path, why in cands:
        if valid_home(path) and (path / "profiles" / "desktop" / "package.json").exists():
            return path, why
    for path, why in cands:
        if valid_home(path):
            return path, why + "（无 desktop profile）"
    return None, "未找到"


def load_paths(redetect: bool = False, install: str | None = None, home: str | None = None,
               quiet: bool = True) -> dict:
    """读取/识别并缓存路径到 config.json；可用参数强制覆盖。"""
    global MAIN_INSTALL, MAIN_HOME

    cfg: dict = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}

    changed = False
    inst_src = cfg.get("installSource", "")
    home_src = cfg.get("homeSource", "")

    if install:
        MAIN_INSTALL = Path(install)
        inst_src = "手动指定"
        changed = True
    elif redetect or not cfg.get("install") or not valid_install(Path(cfg.get("install", ""))):
        found, why = detect_install()
        if found:
            MAIN_INSTALL = found
            inst_src = why
        else:
            MAIN_INSTALL = Path(cfg.get("install") or MAIN_INSTALL)
        changed = True
    else:
        MAIN_INSTALL = Path(cfg["install"])

    if home:
        MAIN_HOME = Path(home)
        home_src = "手动指定"
        changed = True
    elif redetect or not cfg.get("home") or not valid_home(Path(cfg.get("home", ""))):
        found, why = detect_home(MAIN_INSTALL if valid_install(MAIN_INSTALL) else None)
        if found:
            MAIN_HOME = found
            home_src = why
        else:
            MAIN_HOME = Path(cfg.get("home") or MAIN_HOME)
        changed = True
    else:
        MAIN_HOME = Path(cfg["home"])

    if changed or not CONFIG_FILE.exists():
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({
            "install": str(MAIN_INSTALL),
            "installSource": inst_src,
            "home": str(MAIN_HOME),
            "homeSource": home_src,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    if not quiet:
        ok(f"安装目录 {MAIN_INSTALL}（{inst_src}）")
        ok(f"数据目录 {MAIN_HOME}（{home_src}）")
    return {"install": MAIN_INSTALL, "installSource": inst_src, "home": MAIN_HOME, "homeSource": home_src}


def cmd_paths(redetect: bool = False, install: str | None = None, home: str | None = None) -> int:
    head("路径")
    info(f"工作台根目录 {WB_ROOT}（固定）")
    res = load_paths(redetect=redetect, install=install, home=home, quiet=False)
    valid = valid_install(res["install"])
    (ok if valid else bad)(f"安装目录有效性：{'OK' if valid else '找不到 dsh.cmd / exe'}")
    if res["home"]:
        (ok if (res["home"] / "profiles" / "desktop" / "package.json").exists() else warn)(
            f"desktop profile：{'存在' if (res['home'] / 'profiles' / 'desktop' / 'package.json').exists() else '不存在'}")
    ok(f"已写入 {CONFIG_FILE}")
    return 0 if valid else 1


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
        if src.exists() and (src / "package.json").exists():
            # 必须写绝对路径：link: 是相对 profile 目录解析的，写相对路径会指向不存在的目录
            src = src.resolve()
            name = bundle
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

    if action == "remove":
        target = spec or bundle
        if not target:
            bad("用法：wb.py plugins remove <包名或插件目录>")
            return 2
        name = target
        src = Path(target)
        if src.exists() and (src / "package.json").exists():
            try:
                name = json.loads((src / "package.json").read_text(encoding="utf-8")).get("name", src.name)
            except Exception:
                name = src.name
        if name not in deps and name not in bundles:
            bad(f"profile 里没有这个插件：{name}")
            return 1
        deps.pop(name, None)
        if name in bundles:
            bundles.remove(name)
        pkg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ok(f"已从 profile 移除：{name}")
        return cmd_plugins("install")

    bad(f"未知动作：{action}（list/install/add/remove）")
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
LOCK_FILE = STATE_DIR / "page.lock"
BACKUP_ROOT = WB_ROOT / "backups"


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
            if main_up:
                # 让工作台随时能拿到主驾端口（会话面板要用）
                try:
                    cmd_watch(True)
                except Exception as exc:  # noqa: BLE001
                    note(f"watch failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            note(f"loop error: {exc}")
        time.sleep(interval)


def acquire_page_lock() -> bool:
    """单实例锁：连点几次也只处理一次，避免同时弹出多个浏览器页。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if LOCK_FILE.exists():
            try:
                pid = int((LOCK_FILE.read_text(encoding="utf-8-sig").strip() or "0"))
            except Exception:
                pid = 0
            if pid and pid != os.getpid() and pid_alive(pid):
                return False
            LOCK_FILE.unlink(missing_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return True


def release_page_lock() -> None:
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text(encoding="utf-8-sig").strip() == str(os.getpid()):
            LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


LAST_OPEN_FILE = STATE_DIR / "last-open.txt"
LANDING = WB_ROOT / "ui" / "landing.html"
OPEN_COOLDOWN_SEC = 5


def recently_opened() -> bool:
    try:
        ts = float(LAST_OPEN_FILE.read_text(encoding="utf-8-sig").strip())
    except Exception:
        return False
    return (time.time() - ts) < OPEN_COOLDOWN_SEC


def mark_opened() -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_OPEN_FILE.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


def open_landing(reason: str) -> None:
    """工作台不可达时给用户一张本地说明页（比“点了没反应”强）。"""
    try:
        LANDING.parent.mkdir(parents=True, exist_ok=True)
        LANDING.write_text(f"""<!doctype html>
<meta charset="utf-8">
<title>DSH 工作台没有打开</title>
<style>
 body{{font:15px/1.7 "Segoe UI",system-ui;margin:0;padding:40px;background:#16181d;color:#e6e6e6}}
 h1{{font-size:20px;margin:0 0 6px}} .why{{color:#f0a;font-size:13px;margin-bottom:18px}}
 li{{margin:6px 0}} code{{background:#22262e;padding:2px 6px;border-radius:4px}}
 .tip{{color:#8a8f98;font-size:12px;margin-top:18px}}
</style>
<h1>DSH 工作台现在打不开</h1>
<div class="why">原因：{reason}</div>
<ol>
  <li>工作台是**跟着主程序开关**的：主 harness 没开，它就不会运行。</li>
  <li>先把主 harness 打开，等 5~10 秒（守护会自动把工作台拉起来）。</li>
  <li>再双击桌面的「DSH 工作台」。</li>
</ol>
<div class="tip">如果主程序已经开着、还是打不开：双击桌面「DSH 工作台 安装器」，点「安装 / 修复」，日志里会写清楚卡在哪。</div>
</body>
""", encoding="utf-8")
        os.startfile(str(LANDING))  # noqa: S606
    except Exception as exc:  # noqa: BLE001
        warn(f"连说明页也没打开：{exc}")


def cmd_page() -> int:
    """只打开页面：不安装、不升级；主驾没开就直接告诉你，不干等。"""
    if not acquire_page_lock():
        info("已经有一个打开请求在处理，这次忽略（防止弹出多个页面）")
        return 0
    try:
        if recently_opened():
            info(f"刚刚已经打开过（{OPEN_COOLDOWN_SEC} 秒内），这次忽略")
            return 0
        if not APP_DSH_CMD.exists():
            warn(f"还没装运行时（{APP_DSH_CMD} 不存在）。")
            info("请双击桌面「DSH 工作台 安装器」，或运行：wb.py install")
            open_landing("还没有安装工作台运行时")
            return 1

        mv, wv = main_version(), app_version()
        if mv not in ("unknown", "") and wv != mv:
            warn(f"版本不一致（主驾 {mv} / 工作台 {wv}）。要跟进请在安装器里点「同步运行时」。")

        if not port_open(WB_PORT):
            if not main_harness_ports():
                warn("主 harness 没开 → 工作台不会运行（它是跟着主程序开关的）")
                open_landing("主 harness 没开，工作台不会运行")
                return 1
            if not find_supervisors():
                info("自动伴随没在跑 → 拉起")
                cmd_resume()
            deadline = time.time() + 20
            while time.time() < deadline and not port_open(WB_PORT):
                time.sleep(0.5)

        if not port_open(WB_PORT):
            bad(f"工作台没起来（{WB_PORT} 无响应）。看日志：wb.py logs")
            open_landing("工作台进程没起来（端口 59430 无响应）")
            return 1

        url = current_url()
        if not url:
            bad("拿不到入口 URL")
            return 1
        try:
            mark_opened()
            os.startfile(url)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            warn(f"打开失败（{exc}），手动复制：")
            print(url)
            return 1
        ok(f"已打开 → {url}")
        return 0
    finally:
        release_page_lock()


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


def make_shortcuts() -> None:
    """桌面「仅打开页面」+ 启动项「自动伴随」两个快捷方式（幂等，重复执行无副作用）。"""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    script = str(Path(__file__).resolve())
    desktop = Path(os.environ.get("USERPROFILE", r"C:\Users\Administrator")) / "Desktop"
    startup = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    icon = WB_ROOT / "app" / "resources" / "tray.ico"
    ps = f'''
$ws = New-Object -ComObject WScript.Shell
$d = $ws.CreateShortcut("{desktop}\\DSH 工作台.lnk")
$d.TargetPath = "{exe}"
$d.Arguments = '"{script}" page'
$d.WorkingDirectory = "{WB_ROOT}"
$d.Description = "仅打开 DSH 工作台页面（不安装、不改动文件）"
$d.IconLocation = "{icon},0"
$d.Save()
$s = $ws.CreateShortcut("{startup}\\DSH 工作台（自动伴随）.lnk")
$s.TargetPath = "{exe}"
$s.Arguments = '"{script}" supervise'
$s.WorkingDirectory = "{WB_ROOT}"
$s.Description = "主程序在时自动拉起 DSH 工作台，关闭时自动收掉"
$s.IconLocation = "{icon},0"
$s.Save()
$g = $ws.CreateShortcut("{desktop}\\DSH 工作台 安装器.lnk")
$g.TargetPath = "{exe}"
$g.Arguments = '"{WB_ROOT}\\tools\\wb_gui.py"'
$g.WorkingDirectory = "{WB_ROOT}"
$g.Description = "可视化安装/修复/启停 DSH 工作台（用户自己点）"
$g.IconLocation = "{icon},0"
$g.Save()
Write-Output "shortcuts-ok"
'''
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         timeout=90, creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout
    if "shortcuts-ok" in (out or ""):
        ok(f"快捷方式已就绪：{desktop}\\DSH 工作台.lnk")
        ok(f"开机自启已就绪：{startup}\\DSH 工作台（自动伴随）.lnk")
    else:
        warn(f"快捷方式创建异常：{(out or '').strip()[:200]}")


def cmd_install(force: bool = False) -> int:
    """自主安装 / 修复 / 升级：幂等，可以反复跑。"""
    head("工作台安装器")
    ok(f"根目录 {WB_ROOT}")

    for name in ("app", "home", "plugins", "ui", "state", "logs", "seeds", "docs", "backups", "tools"):
        (WB_ROOT / name).mkdir(parents=True, exist_ok=True)
    ok("目录结构就绪")

    if force or not APP_DSH_CMD.exists():
        if cmd_sync_app(force) != 0:
            bad("运行时同步失败，安装中止")
            return 1
    else:
        ok(f"运行时已存在：{app_version()}（要重装用 install --force）")

    if ensure_profile() != 0:
        return 1
    sync_credentials()

    env = dict(os.environ, DSH_HOME=str(WB_HOME), DSH_PROFILE=WB_PROFILE)
    proc = subprocess.run(
        ["cmd", "/c", str(APP_DSH_CMD), "plugin", "--profile", WB_PROFILE, "install"],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900, creationflags=RUNFLAGS,
    )
    (ok if proc.returncode == 0 else warn)(f"插件依赖安装：退出码 {proc.returncode}")

    make_shortcuts()

    if not listening_pids(WB_PORT):
        cmd_start(True)
    else:
        ok(f"工作台已在运行（{WB_PORT}）")
    if not find_supervisors():
        cmd_resume()
    else:
        ok("自动伴随已在运行")

    head("自检")
    cmd_doctor()
    url = current_url()
    if url:
        ok(f"入口：{url}")
    ok("安装完成（可重复执行：install / install --force）")
    return 0


# 与主驾自带能力重复的工作台能力（登记表里要标出来，避免重复造轮子）
# 目前为空：`/wb-web/search` 已于 2026-10-27 随 dsh-wb-web 插件一并卸载（它只是当初用来测工作台的样板）。
DUPLICATE_WITH_MAIN = {}


def cmd_caps() -> int:
    """列出工作台独有的能力（插件路由 + 工具命令），并标出与主驾重复的。只读。"""
    head("工作台能力清单")
    plugins_dir = WB_ROOT / "plugins"
    rows = []
    if plugins_dir.exists():
        for pkg in sorted(plugins_dir.glob("*/package.json")):
            d = pkg.parent
            try:
                meta = json.loads(pkg.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            name = meta.get("name", d.name)
            routes = set()
            index = d / "index.js"
            if index.exists():
                text = index.read_text(encoding="utf-8", errors="replace")
                # 常量前缀，例如 const PREFIX = '/wb-api'
                consts = {}
                for m in re.finditer(r"const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"`]([^'\"`]+)['\"`]", text):
                    consts[m.group(1)] = m.group(2)
                # 直接写死的路径
                for m in re.finditer(r"path:\s*['\"`](/[^'\"`]+)['\"`]", text):
                    routes.add(m.group(1))
                # path: PREFIX 这类常量引用
                for m in re.finditer(r"path:\s*([A-Za-z_][A-Za-z0-9_]*)", text):
                    value = consts.get(m.group(1))
                    if value and value.startswith("/"):
                        routes.add(value)
            has_client = (d / "client.js").exists()
            declared = (((meta.get("dsh") or {}).get("workbench") or {}).get("capabilities") or [])
            rows.append({
                "name": name,
                "version": meta.get("version", "?"),
                "routes": sorted(routes),
                "client": has_client,
                "declared": [c.get("name") for c in declared if isinstance(c, dict)],
            })

    for r in rows:
        info(f"{r['name']} v{r['version']}{'  +client' if r['client'] else ''}")
        if not r["routes"]:
            info("    路由：无（纯 UI 注入或空壳）")
        for route in r["routes"]:
            dup = None
            for key, why in DUPLICATE_WITH_MAIN.items():
                if key == route or key.startswith(route + "/") or route.startswith(key):
                    dup = why
                    break
            if dup:
                warn(f"    {route}  ← 与主驾重复（{dup}）")
            elif r["name"] == "dsh-workbench-bridge":
                info(f"    {route}  ← 主驾侧接入层（挂在主 profile，不算工作台独有能力）")
            else:
                ok(f"    {route}  ← 工作台独有")
        if r["declared"]:
            ok(f"    声明能力：{', '.join(r['declared'])}")

    head("工具命令（wb.py，主驾进程没有）")
    for name, desc in [
        ("install / install --force", "安装或复制运行时"),
        ("start / stop / restart / suspend / resume", "工作台进程与自动伴随"),
        ("backup / backups / restore / rollback", "快照与运行时回滚"),
        ("plugins list|add|remove", "工作台 profile 的插件管理（与主驾 plugin_manager 不同）"),
        ("api / compat / info / paths / status / watch", "接口基线与状态"),
    ]:
        ok(f"{name:<42} {desc}")

    info("提示：自研插件将来在 package.json 的 dsh.workbench.capabilities 里声明能力，")
    info("      主驾即可按名字调用；现在没有自研插件，所以这张表以路由为主。")
    return 0


def cmd_info() -> int:
    """机器可读状态（给 GUI / 脚本用）。"""
    cfg = {}
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        cfg = {}
    wd = int(read_pids().get("watchdog") or 0)
    sup = int(read_pids().get("supervisor") or 0)
    data = {
        "workbenchRoot": str(WB_ROOT),
        "main": {
            "install": str(MAIN_INSTALL),
            "installSource": cfg.get("installSource", "?"),
            "installValid": valid_install(MAIN_INSTALL),
            "home": str(MAIN_HOME),
            "homeSource": cfg.get("homeSource", "?"),
            "version": main_version(),
            "ports": main_harness_ports(),
        },
        "workbench": {
            "version": app_version(),
            "installed": APP_DSH_CMD.exists(),
            "port": WB_PORT,
            "listening": port_open(WB_PORT),
            "watchdog": wd if (wd and pid_alive(wd)) else 0,
            "supervisor": sup if (sup and pid_alive(sup)) else 0,
            "supervisors": find_supervisors(),
        },
    }
    print(json.dumps(data, ensure_ascii=False))
    return 0


BACKUP_DIRS = ["tools", "plugins", "seeds", "docs", "ui"]
BACKUP_FILES = ["config.json", ".gitignore"]
# state/ 整体不进快照（临时快照、日志、token 之类），但这个文件是用户亲手写的插件备注，必须留住
BACKUP_STATE_FILES = ["plugin-notes.json"]
BACKUP_PROFILE_FILES = ["package.json", "cordis.patch.yml", "pnpm-lock.yaml", "pnpm-workspace.yaml"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _backup_entries() -> list[tuple[Path, str]]:
    """要进快照的东西：源码/工具/插件/种子/文档/ui + profile 清单。运行时与 home 数据不进。"""
    out: list[tuple[Path, str]] = []
    for name in BACKUP_DIRS:
        base = WB_ROOT / name
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and "node_modules" not in p.parts and "__pycache__" not in p.parts and p.suffix != ".pyc":
                out.append((p, p.relative_to(WB_ROOT).as_posix()))
    for name in BACKUP_FILES:
        p = WB_ROOT / name
        if p.exists():
            out.append((p, name))
    prof = WB_HOME / "profiles" / WB_PROFILE
    for name in BACKUP_PROFILE_FILES:
        p = prof / name
        if p.exists():
            out.append((p, f"home/profiles/{WB_PROFILE}/{name}"))
    # 工作台没有会话数据（会话都在主驾），home 里唯一值得备份的是 storages 下的 json
    # （工作区注册表等）。.credentials.yaml 含 API Key，绝不入快照。
    storages = WB_HOME / "storages"
    if storages.exists():
        for p in sorted(storages.glob("*.json")):
            out.append((p, f"home/storages/{p.name}"))
    for name in BACKUP_STATE_FILES:
        p = STATE_DIR / name
        if p.exists():
            out.append((p, f"state/{name}"))
    return out


def write_backup_readme() -> None:
    """在 backups\\README.md 里维护一份快照清单（名字/时间/备注/文件数），方便人看。"""
    items = sorted(BACKUP_ROOT.glob("snapshot-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if BACKUP_ROOT.exists() else []
    lines = ["# 快照清单（自动生成）", "", "由 `wb.py backup` 写入；`wb.py restore --from <文件名>` 还原。", "",
             "| 快照 | 时间 | 文件数 | 备注 |", "|---|---|---|---|"]
    for p in items:
        note = ""
        count = 0
        try:
            with zipfile.ZipFile(p) as zf:
                meta = json.loads(zf.read("MANIFEST.json").decode("utf-8"))
                note = meta.get("note", "")
                count = meta.get("fileCount", 0)
        except Exception:
            pass
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
        safe_note = note.replace("|", "\\|")
        lines.append(f"| `{p.name}` | {stamp} | {count} | {safe_note} |")
    lines += ["", f"运行时备份：`backups\\app-*`（`wb.py rollback` 秒回）", ""]
    try:
        (BACKUP_ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass


def cmd_backup(note: str = "") -> int:
    """完整快照（含安装器/工具链），并回读校验每个文件的 sha256。"""
    head("完整快照")
    entries = _backup_entries()
    if not entries:
        bad("没有可备份的内容")
        return 1
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = BACKUP_ROOT / f"snapshot-{stamp}.zip"

    files_meta = []
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path, arc in entries:
            zf.write(path, arc)
            files_meta.append({"arc": arc, "size": path.stat().st_size, "sha256": _sha256(path)})
        head_git = ""
        try:
            head_git = subprocess.run([str(GIT_EXE), "-C", str(WB_ROOT), "rev-parse", "--short", "HEAD"],
                                      capture_output=True, text=True, timeout=30,
                                      creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout.strip()
        except Exception:
            pass
        manifest = {
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": note,
            "gitHead": head_git,
            "versions": {"main": main_version(), "workbench": app_version()},
            "paths": {"root": str(WB_ROOT), "profile": f"home/profiles/{WB_PROFILE}"},
            "fileCount": len(files_meta),
            "totalBytes": sum(m["size"] for m in files_meta),
            "files": files_meta,
            "excluded": ["app/（运行时，可 sync-app 重建）", "home/sessions|storages（数据）", "logs/", "state/", "backups/", "node_modules/"],
        }
        zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    # 回读校验
    bad_files = []
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        for meta in files_meta:
            if meta["arc"] not in names:
                bad_files.append(meta["arc"] + "（缺失）")
                continue
            with zf.open(meta["arc"]) as fh:
                h = hashlib.sha256()
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != meta["sha256"]:
                bad_files.append(meta["arc"] + "（哈希不符）")

    size = archive.stat().st_size
    ok(f"快照 {archive.name}（{len(files_meta)} 文件 / 压缩后 {size / 1024:.1f} KB）")
    ok(f"含：工具链 {len([e for e in entries if e[1].startswith('tools/')])} 个（含安装器 wb_gui.py）、"
       f"插件 {len([e for e in entries if e[1].startswith('plugins/')])} 个、"
       f"种子 {len([e for e in entries if e[1].startswith('seeds/')])} 个、"
       f"文档 {len([e for e in entries if e[1].startswith('docs/')])} 个")
    if bad_files:
        bad(f"校验失败 {len(bad_files)} 个：{', '.join(bad_files[:5])}")
        return 1
    ok("回读校验通过（每个文件的 sha256 都对上了）")
    write_backup_readme()
    info(f"回滚：wb.py restore --from {archive.name}")
    return 0


def cmd_backups() -> int:
    head("已有快照")
    if not BACKUP_ROOT.exists():
        warn("还没有快照：wb.py backup")
        return 0
    items = sorted(BACKUP_ROOT.glob("snapshot-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not items:
        warn("还没有快照")
        return 0
    for p in items:
        note = ""
        try:
            with zipfile.ZipFile(p) as zf:
                note = json.loads(zf.read("MANIFEST.json").decode("utf-8")).get("note", "")
        except Exception:
            pass
        info(f"{p.name}  {p.stat().st_size / 1024:.1f} KB  {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}  {note}")
    write_backup_readme()
    return 0


def cmd_restore(target: str = "latest") -> int:
    """从快照还原工具/插件/种子/文档/ui/profile（不动 app/ 与 home 数据）。"""
    head("从快照还原")
    if not target or target == "latest":
        items = sorted(BACKUP_ROOT.glob("snapshot-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if BACKUP_ROOT.exists() else []
        if not items:
            bad("没有快照可用")
            return 1
        archive = items[0]
    else:
        archive = BACKUP_ROOT / target if (BACKUP_ROOT / target).exists() else Path(target)
    if not archive.exists():
        bad(f"找不到快照：{archive}")
        return 1
    info(f"使用 {archive.name}")
    # 旧快照会把后续代码一起倒回去，先提醒
    try:
        newest = sorted(BACKUP_ROOT.glob("snapshot-*.zip"), key=lambda p: p.stat().st_mtime)[-1]
        if newest.name != archive.name:
            warn(f"这不是最新快照（最新是 {newest.name}）：还原会把此后的改动一起回滚")
    except Exception:
        pass

    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("MANIFEST.json").decode("utf-8"))
        broken = []
        for meta in manifest.get("files", []):
            with zf.open(meta["arc"]) as fh:
                h = hashlib.sha256()
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != meta["sha256"]:
                broken.append(meta["arc"])
        if broken:
            bad(f"快照自身损坏（{len(broken)} 个文件哈希不符），中止还原")
            return 1
        ok(f"快照校验通过（{manifest.get('fileCount')} 文件，创建于 {manifest.get('createdAt')}）")

        cmd_stop()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safety = BACKUP_ROOT / f"before-restore-{stamp}"
        safety.mkdir(parents=True, exist_ok=True)
        for name in BACKUP_DIRS + BACKUP_FILES:
            src = WB_ROOT / name
            if src.exists():
                dst = safety / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
        ok(f"当前状态已另存 → {safety}")

        for meta in manifest.get("files", []):
            zf.extract(meta["arc"], WB_ROOT)
        ok("快照已还原到工作台根目录（只还原清单里的文件，MANIFEST 不落地）")

    if ensure_profile() != 0:
        warn("profile 复原失败，检查 seeds/bench 与快照内容")
    else:
        ok("profile 复原完成")
    cmd_install(False)
    ok("还原完成（如需回滚这次还原，把 before-restore-<时间> 里的文件拷回去即可）")
    return 0


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
    if APP_ROOT.exists() and any(APP_ROOT.iterdir()):
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

    pids = read_pids()
    kept_supervisor = int(pids.get("supervisor") or 0)
    pids = {"serve": serve.pid, "watchdog": 0, "supervisor": kept_supervisor,
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
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
    cfg = {}
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        cfg = {}
    inst_src = cfg.get("installSource", "?")
    home_src = cfg.get("homeSource", "?")
    (ok if valid_install(MAIN_INSTALL) else bad)(f"安装        {MAIN_INSTALL}（{inst_src}）")
    (ok if MAIN_HOME.exists() else bad)(f"数据        {MAIN_HOME}（{home_src}）")
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


def cmd_watch(quiet: bool = False) -> int:
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
    if not quiet:
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
    ap.add_argument("--redetect", action="store_true")
    ap.add_argument("--install", default="")
    ap.add_argument("--home", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--from", dest="from_archive", default="latest")
    ap.add_argument("-n", type=int, default=40)
    args = ap.parse_args(argv[1:])

    # 除 watchdog 外，所有命令先确定路径（自动识别 + config.json 缓存）
    if args.command not in ("watchdog",):
        try:
            load_paths(redetect=args.redetect, install=args.install or None, home=args.home or None)
        except Exception as exc:  # noqa: BLE001
            warn(f"路径识别失败，用默认值：{exc}")

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
        "install": lambda: cmd_install(args.force),
        "paths": lambda: cmd_paths(args.redetect, args.install or None, args.home or None),
        "info": lambda: cmd_info(),
        "caps": lambda: cmd_caps(),
        "backup": lambda: cmd_backup(args.note),
        "backups": lambda: cmd_backups(),
        "restore": lambda: cmd_restore(args.from_archive),
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
