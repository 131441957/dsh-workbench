#!/usr/bin/env python3
"""wb.py — DSH 工作台（Workbench）工具链 v0.1

只用标准库，不依赖 pip 安装。命令行入口，后续再包一层可视化。

用法：
    python wb.py doctor      # 环境/依赖/接口自检
    python wb.py status      # 主驾 + 工作台当前状态（只读）
    python wb.py watch       # 采集主 harness 状态快照到 state/main-status.json

约定：
    主 harness home  E:\\DSH\\home
    工作台根目录      E:\\DSH-WORKBENCH
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ── 常量 ────────────────────────────────────────────────────────────────
WB_ROOT = Path(r"E:\DSH-WORKBENCH")
MAIN_HOME = Path(r"E:\DSH\home")
MAIN_INSTALL = Path(r"E:\SSS")
NODE_EXE = Path(r"E:\nodejs\node.exe")
GIT_EXE = Path(r"C:\Program Files\Git\cmd\git.exe")
PNPM_MJS = MAIN_HOME / r"dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs"
MEMORY_DB = Path(r"E:\肥鱼工作区\.dsh-meow\memory.db")
LEVELS = ["soul", "user", "project", "fact", "lesson", "topic", "rules"]
WB_PORT = 59430          # 工作台预留端口（避开主驾的随机端口和旧副驾的 59420）
RESERVED_PORTS = {59420, 59430}   # 旧副驾 / 新工作台：跑的是同一个 exe，别算进主驾

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


# ── 小工具 ──────────────────────────────────────────────────────────────
def ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def warn(msg: str) -> None:
    print(f"  [warn] {msg}")


def bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def head(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 58 - len(title)))


def listening_pids(port: int) -> list[int]:
    """用 netstat 找监听某端口的 PID（避免依赖 psutil）。"""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            try:
                pids.append(int(parts[4]))
            except ValueError:
                pass
    return pids


def main_harness_ports() -> list[int]:
    """主 GUI 端口每次都变：优先用 DSH_WEB_URL，其次按进程名找并排除工作台保留端口。"""
    env_url = os.environ.get("DSH_WEB_URL", "")
    if ":" in env_url:
        tail = env_url.rsplit(":", 1)[-1].split("/")[0]
        if tail.isdigit():
            return [int(tail)]

    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -State Listen | Select-Object LocalPort,OwningProcess | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=25,
        ).stdout.strip()
        rows = json.loads(out) if out else []
        if isinstance(rows, dict):
            rows = [rows]
    except Exception:
        return []

    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) -join ','"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        app_pids = {int(x) for x in ps.split(",") if x.strip().isdigit()}
    except Exception:
        app_pids = set()

    ports = []
    for row in rows:
        try:
            port = int(row.get("LocalPort"))
            pid = int(row.get("OwningProcess"))
        except Exception:
            continue
        if pid in app_pids and port not in RESERVED_PORTS:
            ports.append(port)
    return sorted(set(ports))


def memory_counts(db: Path) -> dict:
    """只读打开记忆库统计各层条数；打不开就返回错误说明。"""
    if not db.exists():
        return {"error": f"数据库不存在: {db}"}
    try:
        uri = f"file:{db.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"只读打开失败: {exc}"}
    counts = {}
    try:
        for level in LEVELS:
            try:
                counts[level] = conn.execute(f"SELECT COUNT(*) FROM {level} WHERE status='active'").fetchone()[0]
            except Exception:
                counts[level] = None
    finally:
        conn.close()
    return counts


def dir_size(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    if not path.exists():
        return 0, 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            fp = Path(root) / name
            try:
                total += fp.stat().st_size
                files += 1
            except OSError:
                pass
    return files, total


# ── 命令 ────────────────────────────────────────────────────────────────
def cmd_doctor() -> int:
    head("运行时")
    print(f"  python      {sys.version.split()[0]}  ({sys.executable})")
    (ok if NODE_EXE.exists() else bad)(f"node        {NODE_EXE if NODE_EXE.exists() else '缺失'}")
    (ok if PNPM_MJS.exists() else bad)(f"pnpm.mjs    {PNPM_MJS if PNPM_MJS.exists() else '缺失（插件安装要用）'}")
    (ok if GIT_EXE.exists() else warn)(f"git         {GIT_EXE if GIT_EXE.exists() else '缺失（备份要用）'}")
    java = subprocess.run(["where", "java"], capture_output=True, text=True).stdout.strip()
    (ok if java else warn)(f"java        {java.splitlines()[0] if java else '缺失（你说要用 Java 的话需要装 JDK）'}")

    head("主 harness")
    (ok if MAIN_INSTALL.exists() else bad)(f"安装目录    {MAIN_INSTALL}")
    (ok if MAIN_HOME.exists() else bad)(f"数据目录    {MAIN_HOME}")
    ports = main_harness_ports()
    if ports:
        ok(f"主 GUI 端口 {', '.join(map(str, ports))}")
    else:
        warn("没检测到主 GUI 端口（主 app 没开？）")

    head("记忆（只读检查）")
    counts = memory_counts(MEMORY_DB)
    if "error" in counts:
        bad(counts["error"])
    else:
        ok("记忆库可只读访问：" + " / ".join(f"{k}={v}" for k, v in counts.items()))

    head("工作台目录")
    for name in ["app", "home", "plugins", "ui", "state", "backups", "tools", "docs"]:
        p = WB_ROOT / name
        (ok if p.exists() else warn)(f"{name:<9} {'存在' if p.exists() else '待建'}  {p}")
    (ok if not listening_pids(WB_PORT) else warn)(
        f"端口 {WB_PORT} {'空闲' if not listening_pids(WB_PORT) else '已被占用'}"
    )
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
    print(f"  home        {files} 文件 / {size / 1048576:.1f} MB  ({MAIN_HOME})")

    counts = memory_counts(MEMORY_DB)
    if "error" in counts:
        warn(counts["error"])
    else:
        print("  记忆        " + " / ".join(f"{k}={v}" for k, v in counts.items()))

    head("工作台")
    pids = listening_pids(WB_PORT)
    if pids:
        ok(f"端口 {WB_PORT} 在听 (pid={','.join(map(str, pids))})")
    else:
        warn(f"端口 {WB_PORT} 没在听（工作台未启动）")

    state_file = WB_ROOT / "state" / "main-status.json"
    if state_file.exists():
        age = time.time() - state_file.stat().st_mtime
        ok(f"状态快照 {state_file.name}（{age:.0f} 秒前更新）")
    else:
        warn("还没有状态快照（运行 wb.py watch 生成）")
    return 0


def cmd_watch() -> int:
    """采集一份主 harness 状态快照，供工作台读取。"""
    state_dir = WB_ROOT / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    ports = main_harness_ports()
    payload = {
        "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mainHarness": {
            "ports": ports,
            "pids": {str(p): listening_pids(p) for p in ports},
            "install": str(MAIN_INSTALL),
            "installExists": MAIN_INSTALL.exists(),
            "home": str(MAIN_HOME),
        },
        "memory": memory_counts(MEMORY_DB),
        "profiles": {},
    }

    prof_dir = MAIN_HOME / "profiles"
    if prof_dir.exists():
        for prof in prof_dir.iterdir():
            pkg = prof / "package.json"
            if not pkg.exists():
                continue
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                payload["profiles"][prof.name] = {
                    "bundles": (data.get("dsh") or {}).get("profile", {}).get("bundles", []),
                    "dependencies": list((data.get("dependencies") or {}).keys()),
                }
            except Exception as exc:  # noqa: BLE001
                payload["profiles"][prof.name] = {"error": str(exc)}

    out = state_dir / "main-status.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"已写入 {out}（{out.stat().st_size} 字节）")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    table = {"doctor": cmd_doctor, "status": cmd_status, "watch": cmd_watch}
    if cmd not in table:
        print(__doc__)
        return 2
    return table[cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
