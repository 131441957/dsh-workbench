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
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15).stdout
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
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        app_pids = {int(x) for x in ps.split(",") if x.strip().isdigit()}
    except Exception:
        app_pids = set()
    if not app_pids:
        return []
    return sorted({p for p, pid in netstat_listen() if pid in app_pids and p not in RESERVED_PORTS})


def kill_tree(pid: int) -> bool:
    try:
        subprocess.run([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                        "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=25)
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
    try:
        return json.loads(PIDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_pids(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PIDS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 核心：安装同步 ──────────────────────────────────────────────────────
def cmd_sync_app(force: bool = False) -> int:
    head("同步安装到工作台")
    if (APP_EXE.exists()) and not force:
        ok(f"已存在 {APP_EXE}（要重新同步加 --force）")
        return 0
    if not MAIN_INSTALL.exists():
        bad(f"主安装不存在：{MAIN_INSTALL}")
        return 1
    if APP_ROOT.exists():
        info("清理旧副本…")
        shutil.rmtree(APP_ROOT, ignore_errors=True)
    info("复制中（约 1.7GB，请稍等）…")
    started = time.time()
    rc = subprocess.run(
        ["robocopy", str(MAIN_INSTALL), str(APP_ROOT), "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).returncode
    if rc > 7:
        bad(f"robocopy 失败（退出码 {rc}）")
        return 1
    files, size = dir_size(APP_ROOT)
    ok(f"完成：{files} 文件 / {size / 1048576:.0f} MB，用时 {time.time() - started:.0f}s")
    ok(f"exe:   {APP_EXE}")
    ok(f"cli:   {APP_DSH_CMD}")
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
                       encoding="utf-8", errors="replace", timeout=180)
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
            watch = subprocess.Popen(
                [str(exe), str(Path(__file__).resolve()), "watchdog",
                 "--main-pids", ",".join(map(str, main_pids))],
                creationflags=DETACHED | NO_WINDOW, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            pids["watchdog"] = watch.pid
            ok(f"看门狗已挂（盯主驾 pid={main_pids}，主驾一关工作台自动退）")
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
    write_pids({})
    if not stopped:
        warn("没有在跑的工作台")
    return 0


def cmd_restart(with_watchdog: bool = True) -> int:
    cmd_stop()
    time.sleep(1.5)
    return cmd_start(with_watchdog)


# ── 看门狗：主驾一死就关工作台 ──────────────────────────────────────────
def cmd_watchdog(main_pids: list[int], interval: float = 4.0) -> int:
    log = LOG_DIR / "watchdog.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    def note(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(line)

    note(f"watchdog start, main pids={main_pids}, wb port={WB_PORT}")
    while True:
        time.sleep(interval)
        if not listening_pids(WB_PORT):
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
        pipv = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True, timeout=25).stdout.strip()
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
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--with-watchdog", action="store_true", default=True)
    ap.add_argument("--no-watchdog", dest="with_watchdog", action="store_false")
    ap.add_argument("--main-pids", default="")
    ap.add_argument("-n", type=int, default=40)
    args = ap.parse_args(argv[1:])

    table = {
        "doctor": lambda: cmd_doctor(),
        "status": lambda: cmd_status(),
        "watch": lambda: cmd_watch(),
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
