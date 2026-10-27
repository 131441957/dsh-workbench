#!/usr/bin/env python3
"""wb.py — DSH 工作台（Workbench）工具链

只用标准库（Python 3.10+）。工作台自己的插件必须用 JS（Cordis 加载器只认 JS），
这个脚本是**运维工具**：装/启停/备份/装插件/分发/体检。

═══ 命令地图（按用途分组，全部幂等、可重复跑）══════════════════════════════════
【装与修】  install（复制运行时 + 建 profile + 起服务 + 自愈）│ sync-app │ rollback
【启与停】  start │ stop │ restart │ restart-safe（维护模式）│ suspend │ resume
            start-safe（只禁第三方插件，界面还能开）
【状态】    status │ info（机器可读 JSON）│ doctor │ paths │ caps │ compat
            watch（采集主驾快照）│ api（接口基线）│ logs
【备份】    backup │ backups [--json] │ restore --from <zip>
【插件】    plugins list/install/add/remove │ plugin-info │ install-plugin
            uninstall-plugin │ fix-ui │ plugin-search │ plugin-update [--apply]
【体检】    preflight --install <目录>（三档：compatible/degraded/incompatible）
【接入层】  attach / detach（把桥装进**目标** harness 的 profile，默认干跑）
【分发】    pack │ prepublish │ registry [--refresh] │ sync-bed <根目录>
【内部】    watchdog --main-pids 1,2 │ supervise │ serve

═══ 铁律（改这个文件前先看）══════════════════════════════════════════════════
① **绝不写主 harness**：E:\\SSS、E:\\DSH\\home（含 profiles\\desktop）只读。
   唯一例外是 attach/detach 动目标 profile 的 package.json —— 而且默认干跑、要 --apply。
② **绝不重装主 harness**：只升级；工作台的「同步运行时」是把主驾当前安装**复制**到 app\\。
③ 根目录从 `__file__` 推导（可用 DSH_WORKBENCH_ROOT 覆盖），**不许写死路径**：
   同一台机器会并存多套工作台（主套 E:\\DSH-WORKBENCH、测试床 E:\\WB-RC3）。
④ 改任何**宿主侧**插件或主驾桥都要**重启对应 harness** 才生效；改 ui/ 只要刷新页面。
⑤ 说"已经能用"之前必须有运行时证据（端口在听、/wb-ui 认领、页面模块表、boot-diag）。

═══ 三个必须懂的内部机制 ═══════════════════════════════════════════════════════
· safe_restart()：suspend → 等端口释放 → start → resume。
  为什么：supervisor 看到 59430 空出来会**抢先**起一个实例，与新实例撞端口 →
  EADDRINUSE → webserver 起不来 → 日志报 "startup failed: N required plugins did not activate"。
  维护型重启一律走它，别用裸 restart。
· 装前快照 + 失败回滚：install-plugin 先存 profile 三件套（package.json/pnpm-lock/ui-config/
  installed.json）到 backups\\pre-install-<ts>，验证不过就 restore_install_snapshot() 回滚。
· preflight 门禁：install 之前先跑 _preflight_verdict()，incompatible 直接中止
  （一个字节运行时都不复制），degraded 先打印降级项再继续。

═══ 验证入口 ═══════════════════════════════════════════════════════════════════
    python tools\\test-http.py [--bridge]        # 接口 + 桥 17 项
    python tools\\probe-ui.py --root <根>        # 页面自报（cssFrameApplied / sidebarVisibleRows）
    python tools\\wb.py prepublish               # 公开前自检（退出码 0 = 硬性项全过）
"""
from __future__ import annotations

import argparse
import atexit
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
# 工作台根：从本文件位置推导（tools\wb.py → 上两级），可用环境变量覆盖。
# 注意：这里**故意不写死**，因为本机同时存在主套与测试床两套工作台。
WB_ROOT = Path(os.environ.get("DSH_WORKBENCH_ROOT") or Path(__file__).resolve().parent.parent)
# 主驾的默认位置只是**兜底**：真正用哪个由 load_paths() 探测并缓存到 config.json。
# （用户机器上主驾可能在别的盘；存量 config 失效时会自动重探。）
MAIN_HOME = Path(r"E:\DSH\home")
MAIN_INSTALL = Path(r"E:\SSS")

APP_ROOT = WB_ROOT / "app"
APP_EXE = APP_ROOT / "DeepSeek Harness.exe"
APP_DSH_CMD = APP_ROOT / r"resources\runtime\cli\bin\dsh.cmd"

WB_HOME = WB_ROOT / "home"
WB_PROFILE = "bench"
WB_PORT_DEFAULT = 59430
WB_PORT = WB_PORT_DEFAULT            # 运行期由 load_port() 覆盖（config.json / 环境变量）
RESERVED_PORTS = {59420, 59430}      # 旧副驾 / 工作台：同一个 exe，别算成主驾
LOG_DIR = WB_ROOT / "logs"
STATE_DIR = WB_ROOT / "state"
PIDS_FILE = STATE_DIR / "pids.json"

def _find_node() -> Path:
    if os.environ.get("NODE_EXE"):
        return Path(os.environ["NODE_EXE"])
    for cand in (Path(r"E:\nodejs\node.exe"), Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe"):
        if cand.exists():
            return cand
    found = shutil.which("node")
    return Path(found) if found else Path("node")


def _find_git() -> Path:
    for cand in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe"):
        if cand.exists():
            return cand
    found = shutil.which("git")
    return Path(found) if found else Path("git")


def pnpm_mjs() -> Path | None:
    """pnpm 随 harness 的分发目录走，别写死本机 home；找不到返回 None（只有装插件时才需要）。"""
    candidates = [
        Path(MAIN_HOME) / r"dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs",
        Path(MAIN_HOME) / r"dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.cjs",
        Path(MAIN_HOME) / "dsh-runtimes" / "primary-runtime" / "dependencies" / "pnpm" / "bin" / "pnpm.mjs",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def memory_db() -> Path | None:
    """记忆库位置随工作区变化；本机没有就当没有，别报错。"""
    env = os.environ.get("MEOW_MEMORY_DB")
    candidates = [Path(env)] if env else []
    candidates += [Path(r"E:\肥鱼工作区\.dsh-meow\memory.db"),
                   Path(os.getcwd()) / ".dsh-meow" / "memory.db"]
    for c in candidates:
        if c.exists():
            return c
    return None


NODE_EXE = _find_node()
GIT_EXE = _find_git()
MEMORY_DB = None   # 运行时用 memory_db() 现查
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


# ── 路径探测：主驾安装目录 + 数据目录（写进 config.json 缓存）──────────────────
# 判定顺序：参数显式指定 → config 缓存 → 自动探测（运行中进程 → 快捷方式 → 注册表 → 常见位置）。
# 三条坑（都踩过）：
#  ① 探测结果要连同**来源**一起存（installSource/homeSource），排障时才分得清"这个值是猜的还是人给的"。
#  ② 重写 config 时先拷原 cfg 再更新 4 个键 —— 否则 port 之类自定义键会被抹掉。
#  ③ **显式指定过的 home 不许被环境变量顶掉**：多套工作台共存时，一旦回退到 DSH_HOME，
#     测试床就会去用主套的 home。判据：homeSource == 手动指定 且目录存在。
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
    else:
        cfg_home = Path(cfg.get("home") or "")
        # 显式指定过的 home（哪怕还是空目录）不许被环境变量顶掉——多套工作台共存时
        # 这条一旦失守，第二套会静默用上主 home。
        explicit_home = cfg.get("homeSource") == "手动指定" and cfg_home.is_dir() and str(cfg_home) not in ("", ".")
        if redetect or not cfg.get("home") or not (valid_home(cfg_home) or explicit_home):
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
        # 保留已有的其它键（port / 自定义字段），别把整个文件重写成 4 个键
        out = dict(cfg)
        out.update({
            "install": str(MAIN_INSTALL),
            "installSource": inst_src,
            "home": str(MAIN_HOME),
            "homeSource": home_src,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        CONFIG_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

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
    """主驾（桌面壳）在听的端口。

    ⚠️ 进程名是同一个（DeepSeek Harness.exe），工作台/测试床的 headless 进程也叫这个名字，
    所以必须按**可执行路径**把工作台自己的进程剔掉，否则会把 59430/59480 当主驾端口。
    """
    env_url = os.environ.get("DSH_WEB_URL", "")
    if ":" in env_url:
        tail = env_url.rsplit(":", 1)[-1].split("/")[0]
        if tail.isdigit() and int(tail) not in RESERVED_PORTS:
            return [int(tail)]
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name = 'DeepSeek Harness.exe'\" | "
             "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.ExecutablePath }"],
            capture_output=True, text=True, timeout=25, creationflags=RUNFLAGS,
            encoding="utf-8", errors="replace",
        ).stdout
    except Exception:
        return []
    app_pids: set[int] = set()
    for line in (ps or "").splitlines():
        pid_s, _, path = line.strip().partition("|")
        if not pid_s.strip().isdigit():
            continue
        # 只认"安装目录里的 exe"：排除任何工作台根（本工作台、测试床）
        low = path.lower().replace("/", "\\")
        if "\\dsh-workbench\\app\\" in low or "\\wb-" in low:
            continue
        app_pids.add(int(pid_s.strip()))
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
def memory_counts(db: Path | None) -> dict:
    if db is None:
        return {"note": "本机没有记忆库（跳过，不影响工作台）"}
    if not db.exists():
        return {"note": f"记忆库不存在：{db}（跳过）"}
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
    """按命令行扫 pythonw 里的 `wb.py supervise`（防止记录丢失/重复）。

    ⚠️ 必须按**根目录**过滤：本机可能并存多套工作台（主套 / 测试床），
    早期版本不带过滤，卸载/暂停其中一套会把另一套的 supervisor 一起杀掉（2026-10-27 踩过）。
    """
    root = str(WB_ROOT).replace("\\", "\\\\")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name = 'pythonw.exe' or Name = 'python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*wb.py*supervise*' } | "
          "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=40, creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout
    except Exception:
        return []
    pids = []
    for line in (out or "").splitlines():
        pid_s, _, cmd = line.strip().partition("|")
        if not pid_s.strip().isdigit():
            continue
        # 只认命令行里带**本根**路径的那个
        if str(WB_ROOT).lower() in cmd.lower().replace("/", "\\"):
            pids.append(int(pid_s.strip()))
    return pids


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
            # 必须写绝对路径：link: 是相对 profile 目录解析的，写相对路径会指向不存在的目录
            src = src.resolve()
            meta = json.loads((src / "package.json").read_text(encoding="utf-8"))
            name = name or meta.get("name", src.name)
            deps[name] = "link:" + src.as_posix()
        else:
            # 名字和版本要分开：`dshmarket@1.71.1` 的依赖名是 dshmarket、值是 1.71.1。
            # 以前整串当成了名字 → pnpm 报 ERR_PNPM_INVALID_DEPENDENCY_NAME。
            pkg, ver = split_npm_spec(spec)
            name = bundle or pkg
            if ver:
                value = ver
                ok(f"锁定版本：{name}@{value}")
            else:
                # 优先用注册表缓存里的版本（离线可用），没有再问 npm，最后退 latest
                item = registry_lookup(pkg)
                resolved = str(item.get("version")) if item and item.get("version") else ""
                if not resolved:
                    resolved = npm_latest_version(pkg) or ""
                value = resolved or "latest"
                (ok if resolved else warn)(
                    f"版本：{name}@{value}" + ("" if resolved else "（没查到确切版本，写成 latest）"))
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


def ui_config_path() -> Path:
    return STATE_DIR / "ui-config.json"


def ui_config_load() -> dict:
    try:
        data = json.loads(ui_config_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def ui_config_save(cfg: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ui_config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def detect_ui_entries(pkg: Path) -> dict:
    """猜这个插件会露在哪里：客户端入口文件、注册的槽位、设置分区标题。"""
    out = {"titles": [], "sidebar": False, "client": False, "clientPath": "", "slots": []}

    # ① 客户端入口：优先按 package.json 的 exports["./client"] 解析，别猜路径
    meta = {}
    try:
        meta = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    candidates = []
    exports = meta.get("exports")
    if isinstance(exports, dict):
        entry = exports.get("./client")
        if isinstance(entry, str):
            candidates.append(entry)
        elif isinstance(entry, dict):
            for key in ("default", "import", "require"):
                if isinstance(entry.get(key), str):
                    candidates.append(entry[key])
                    break
    candidates += ["client/client.js", "client.js", "src/client.js", "dist/client.js", "lib/client.js"]
    for rel in candidates:
        p = pkg / rel.lstrip("./")
        if p.exists():
            out["client"] = True
            out["clientPath"] = rel
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            # ② 注册了哪些槽位（决定它的界面能不能在工作台里出现）
            #    很多插件写成常量：const SLOT = 'conversation.message.actions'，所以要先把常量表建出来
            consts = {}
            for cm in re.finditer(r"""const\s+([A-Za-z_$][\w$]*)\s*=\s*['"]([^'"]+)['"]""", text):
                consts[cm.group(1)] = cm.group(2)

            def resolve(token: str) -> str:
                token = token.strip()
                if token in consts:
                    return consts[token]
                return token

            found = []
            for m in re.finditer(r"""slots\.inject\(\s*([A-Za-z_$][\w$]*|['"][^'"]+['"])""", text):
                found.append(resolve(m.group(1).strip("'\"")))
            for m in re.finditer(r"""register\(\s*\{[^}]*?name:\s*([A-Za-z_$][\w$]*|['"][^'"]+['"])""", text, re.S):
                found.append(resolve(m.group(1).strip("'\"")))
            for slot in found:
                if slot and slot not in out["slots"] and not slot.startswith(("sidebar.panellist", "main")):
                    out["slots"].append(slot)
            out["sidebar"] = "sidebar.panellist" in found or "sidebar.panellist" in text
            break

    # ③ 设置分区标题（locale 里的 meta.title 一类）
    locale_dir = pkg / "locale"
    if locale_dir.exists():
        for loc in sorted(locale_dir.glob("*.json")):
            try:
                data = json.loads(loc.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            title = None
            if isinstance(data, dict):
                meta_loc = data.get("meta")
                if isinstance(meta_loc, dict):
                    title = meta_loc.get("title")
                if not title:
                    for key in ("title", "name", "section.title", "settings.title"):
                        if isinstance(data.get(key), str):
                            title = data[key]
                            break
            if isinstance(title, str) and title.strip() and title.strip() not in out["titles"]:
                out["titles"].append(title.strip())
    return out


def http_get_text(url: str, timeout: float = 25.0) -> str:
    """带 cookie 的 GET：工作台首页要先拿 token 种 cookie，跳转后才是正文。"""
    import http.cookiejar as cookiejar
    from urllib.request import HTTPCookieProcessor, Request, build_opener
    jar = cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    req = Request(url, headers={"accept": "text/html"})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def port_listening(port: int) -> bool:
    import socket as _socket
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_json(url: str, timeout: float = 10.0):
    from urllib.request import urlopen
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def wait_ui_ready(timeout: float = 20.0) -> bool:
    """等注入层就绪：/wb-ui 能答且 uiDir 是我们自己的。用来发现"服务起来了但插件没加载"。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_our_workbench(WB_PORT):
            return True
        time.sleep(0.6)
    return False


def _bench_deps() -> dict:
    try:
        meta = json.loads((WB_HOME / "profiles" / WB_PROFILE / "package.json").read_text(encoding="utf-8-sig"))
        deps = meta.get("dependencies")
        return deps if isinstance(deps, dict) else {}
    except Exception:
        return {}


def _bundle_ids_of(pkg: str) -> list[str]:
    """从插件自己的 cordis.patch.yml 里抠出它注册的 entry id（安全模式要靠 id 禁用）。"""
    patch = WB_HOME / "profiles" / WB_PROFILE / "node_modules" / pkg / "cordis.patch.yml"
    if not patch.exists():
        return []
    ids = []
    try:
        text = patch.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    for line in text.splitlines():
        m = re.match(r"^\s*-\s*id:\s*(\S+)", line.strip()) or re.match(r"^-\s*id:\s*(\S+)", line.strip())
        if m:
            ids.append(m.group(1))
    return ids


def cmd_start_safe() -> int:
    """安全模式：只禁用**第三方**插件（保留内置与工作台自己的 3 个），让界面还能打开。

    场景：装了某个插件后工作台起不来/白屏。安全模式能进去 → 在「插件」面板里卸掉它，或用
    `wb.py uninstall-plugin <包名>`。
    """
    head("安全模式启动（禁用第三方插件）")
    deps = _bench_deps()
    builtin = [n for n in deps if n.startswith("@deepseek-ai/")]
    ours = [n for n in deps if n.startswith("dsh-wb-")]
    others = [n for n in deps if n not in builtin and n not in ours]
    if not others:
        warn("没有第三方插件，安全模式 = 普通启动")
        return cmd_restart_safe()

    ids: list[str] = []
    for name in others:
        found = _bundle_ids_of(name)
        if found:
            ids.extend(found)
        else:
            warn(f"{name} 的 cordis.patch.yml 里没找到 entry id，无法禁用（可先 uninstall-plugin 它）")
    if not ids:
        bad("没有可禁用的第三方 entry id")
        return 1

    patch = STATE_DIR / "safe-mode.patch.yml"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    body = ["# 安全模式（wb.py start-safe 生成，仅本次启动叠加，不写进 profile）"]
    for entry_id in ids:
        body.append(f"- id: {entry_id}")
        body.append("  disabled: true")
    patch.write_text("\n".join(body) + "\n", encoding="utf-8")
    info(f"将禁用第三方 entry：{', '.join(ids)}")
    info(f"保留：内置 + {', '.join(ours) or '（无）'}")

    cmd_suspend()
    waited = 0.0
    while port_listening(WB_PORT) and waited < 20:
        time.sleep(0.5)
        waited += 0.5
    if port_listening(WB_PORT):
        bad(f"端口 {WB_PORT} 没释放，放弃")
        cmd_resume()
        return 1
    if cmd_start(True, ["--patch", str(patch)]) != 0:
        cmd_resume()
        return 1
    up = wait_ui_ready(25)
    msg = "注入层已就绪" if up else "注入层没就绪（看 logs/workbench.err.log）"
    (ok if up else bad)(msg)
    cmd_resume()
    head("下一步")
    info("现在可以在页面「插件」面板里卸掉可疑插件，或：wb.py uninstall-plugin <包名>")
    info("退出安全模式（恢复正常启动）：wb.py restart-safe")
    return 0 if up else 1


def cmd_restart_safe() -> int:
    """维护模式重启（suspend → 等端口释放 → start → resume），供 GUI/客户用。"""
    head("安全重启工作台（维护模式）")
    ok_flag = safe_restart()
    (ok if ok_flag else bad)(f"工作台{'已就绪' if ok_flag else '没起来，看日志'}")
    return 0 if ok_flag else 1


def cmd_plugin_info(name: str) -> int:
    """只看不装：这个插件会露在哪个槽位、有没有设置分区、peer 约束是什么。"""
    if not name:
        bad("用法：wb.py plugin-info <包名>")
        return 2
    prof = WB_HOME / "profiles" / WB_PROFILE
    pkg_dir = prof / "node_modules" / name
    head(f"插件侦察：{name}")
    if not pkg_dir.exists():
        warn("这个包还没装到 bench profile（装上后再看会更准；这里只能看 npm 元信息）")
        ver = npm_latest_version(name)
        info(f"npm 最新版本：{ver or '查不到'}")
        return 0
    try:
        meta = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        bad(f"读不到 package.json：{exc}")
        return 1
    ok(f"{meta.get('name')} v{meta.get('version')}")
    peers = meta.get("peerDependencies") or {}
    if peers:
        for k, v in peers.items():
            info(f"peer {k} {v}")
    else:
        info("没有声明 peer 依赖（升级时靠人工验证）")
    dsh = meta.get("dsh") or {}
    info(f"dsh.client：{json.dumps(dsh.get('client'), ensure_ascii=False)}")
    entries = detect_ui_entries(pkg_dir)
    if entries.get("client"):
        ok(f"客户端入口：{entries.get('clientPath')}")
    else:
        warn("没有客户端入口（纯宿主插件，界面里不会有它）")
    if entries.get("slots"):
        info(f"注册槽位：{', '.join(entries['slots'][:12])}")
    if entries.get("titles"):
        info(f"设置分区标题：{', '.join(entries['titles'])}")
    if entries.get("sidebar"):
        info("有侧栏入口候选（可能在顶栏出现）")
    return 0


def ledger_path() -> Path:
    return STATE_DIR / "installed.json"


def ledger_load() -> dict:
    try:
        data = json.loads(ledger_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def ledger_save(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path().write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def profile_dir() -> Path:
    return WB_HOME / "profiles" / WB_PROFILE


def pkg_dir_of(name: str) -> Path:
    return profile_dir() / "node_modules" / name


def normalize_pkg_name(spec: str) -> str:
    """目录 → 取它的 package.json name；`name@ver` → 只留 name；纯包名原样。"""
    p = Path(spec)
    if p.exists() and (p / "package.json").exists():
        try:
            return str(json.loads((p / "package.json").read_text(encoding="utf-8")).get("name") or spec).strip()
        except Exception:
            return spec
    pkg, _ver = split_npm_spec(spec)
    return pkg.strip()


def pre_install_snapshot() -> Path:
    """装前快照：只留三件套（几十 KB），回滚够用。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / f"pre-install-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for src, name in (
        (profile_dir() / "package.json", "package.json"),
        (profile_dir() / "pnpm-lock.yaml", "pnpm-lock.yaml"),
        (STATE_DIR / "ui-config.json", "ui-config.json"),
        (ledger_path(), "installed.json"),
    ):
        if src.exists():
            shutil.copy2(src, dest / name)
    return dest


def restore_install_snapshot(dest: Path) -> None:
    for name, target in (
        ("package.json", profile_dir() / "package.json"),
        ("pnpm-lock.yaml", profile_dir() / "pnpm-lock.yaml"),
        ("ui-config.json", STATE_DIR / "ui-config.json"),
        ("installed.json", ledger_path()),
    ):
        src = dest / name
        if src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        elif target.exists():
            target.unlink()


def register_nav_titles(pkg: str, titles: list[str]) -> list[str]:
    """把插件的设置分区标题登记进白名单，并记住"哪个插件写的"，卸载时才好清。"""
    cfg = ui_config_load()
    keep = [t for t in (cfg.get("keepNav") or []) if isinstance(t, str)]
    nav_by = cfg.get("navByPlugin") if isinstance(cfg.get("navByPlugin"), dict) else {}
    added = []
    for t in titles:
        if t not in keep:
            keep.append(t)
            added.append(t)
    nav_by[pkg] = sorted(set((nav_by.get(pkg) or []) + titles))
    cfg["keepNav"] = keep
    cfg["navByPlugin"] = nav_by
    ui_config_save(cfg)
    return added


def unregister_nav_titles(pkg: str) -> list[str]:
    cfg = ui_config_load()
    nav_by = cfg.get("navByPlugin") if isinstance(cfg.get("navByPlugin"), dict) else {}
    owned = [t for t in (nav_by.pop(pkg, []) or []) if isinstance(t, str)]
    keep = [t for t in (cfg.get("keepNav") or []) if isinstance(t, str) and t not in owned]
    cfg["keepNav"] = keep
    cfg["navByPlugin"] = nav_by
    ui_config_save(cfg)
    return owned


def safe_restart() -> bool:
    """维护模式重启：**先 suspend 停掉自动伴随**（否则 supervisor 看到端口空出来会抢先
    起一个实例，和我们这次的启动抢端口 → EADDRINUSE 假故障），起完再 resume。"""
    cmd_suspend()
    waited = 0.0
    while port_listening(WB_PORT) and waited < 20:
        time.sleep(0.5)
        waited += 0.5
    if port_listening(WB_PORT):
        bad(f"端口 {WB_PORT} 20 秒内没释放，放弃自动启动")
        cmd_resume()
        return False
    cmd_start(True)
    up = False
    for _ in range(40):
        if port_listening(WB_PORT):
            up = True
            break
        time.sleep(0.5)
    cmd_resume()
    return up


# ── 卸载插件：三处都要清干净，否则会有"幽灵插件"────────────────────────────────
# ① profile 依赖与 bundles list ② node_modules 里的链接（含空的 scope 目录）
# ③ state\ui-config.json 里这个插件登记的设置分区标题（keepNav + navByPlugin）
# ④ 安装台账 installed.json ⑤ 维护模式重启并验证它真的不在了。
def cmd_uninstall_plugin(name: str, no_restart: bool = False) -> int:
    """卸载一个插件并把痕迹清干净：profile / node_modules / 设置白名单 / 安装台账。"""
    if not name:
        bad("用法：wb.py uninstall-plugin <包名> [--no-restart]")
        return 2
    target = normalize_pkg_name(name)
    head(f"卸载插件：{target}")

    prof_meta_path = profile_dir() / "package.json"
    try:
        prof_meta = json.loads(prof_meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        bad(f"读不到 profile 清单：{exc}")
        return 1
    known = target in (prof_meta.get("dependencies") or {}) or target in (
        ((prof_meta.get("dsh") or {}).get("profile") or {}).get("bundles") or [])
    if not known:
        warn(f"profile 里没有 {target}（继续清理残留）")

    if known and cmd_plugins("remove", target, "") != 0:
        bad("卸载失败")
        return 1

    # ① node_modules 残留（含 scope 目录）
    pkg_dir = pkg_dir_of(target)
    if pkg_dir.exists():
        try:
            shutil.rmtree(pkg_dir)
            ok(f"已删除 node_modules 残留：{pkg_dir}")
        except Exception as exc:  # noqa: BLE001
            warn(f"删 node_modules 失败：{exc}")
        scope_dir = pkg_dir.parent
        if target.startswith("@") and scope_dir.exists() and not any(scope_dir.iterdir()):
            try:
                scope_dir.rmdir()
                ok(f"已删除空的 scope 目录：{scope_dir}")
            except Exception:
                # rmdir 在 Windows 上偶尔会因句柄未释放失败，退一步用递归删除
                try:
                    shutil.rmtree(scope_dir)
                    ok(f"已删除空的 scope 目录：{scope_dir}")
                except Exception as exc:  # noqa: BLE001
                    warn(f"scope 目录残留（手动删也行）：{scope_dir}（{exc}）")

    # ② 设置白名单里它写过的标题
    owned = unregister_nav_titles(target)
    if owned:
        ok(f"白名单已清理：{owned}")
    else:
        info("白名单里没有它登记的标题")

    # ③ 台账
    led = ledger_load()
    if led.pop(target, None) is not None:
        ledger_save(led)
        ok("安装台账已移除该条")

    if no_restart:
        warn("已跳过重启；界面上的入口会在下次重启页面后消失")
        return 0
    if not safe_restart():
        return 1
    try:
        data = http_json(f"http://127.0.0.1:{WB_PORT}/wb-api/plugins")
        still = next((p for p in data.get("plugins", []) if p.get("name") == target), None)
        (bad if still else ok)(f"插件清单里{'仍有' if still else '已没有'} {target}")
    except Exception as exc:  # noqa: BLE001
        warn(f"读插件清单失败：{exc}")
    return 0


def cmd_fix_ui() -> int:
    """重新对齐界面：把已装插件的设置分区补进白名单，并检查客户端是否真被页面加载。

    用于"从别处装的插件"（比如插件市场里点安装）——它们绕过 install-plugin，
    白名单没登记就会出现"装了但看不见"。
    """
    head("重新对齐界面")
    try:
        prof_meta = json.loads((profile_dir() / "package.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        bad(f"读不到 profile 清单：{exc}")
        return 1
    deps = prof_meta.get("dependencies") or {}
    builtins = {"@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"}

    page_html = ""
    try:
        url = current_url()
        if url:
            page_html = http_get_text(url)
    except Exception as exc:  # noqa: BLE001
        warn(f"抓首页失败（模块表/加载状态这项会跳过）：{exc}")

    added_total = []
    rows = []
    for name in sorted(deps):
        if name in builtins:
            continue
        pkg_dir = pkg_dir_of(name)
        if not pkg_dir.exists():
            rows.append((name, "目录缺失", "-", "✗"))
            continue
        entries = detect_ui_entries(pkg_dir)
        titles = entries.get("titles") or []
        if titles:
            added_total.extend(register_nav_titles(name, titles))
        loaded = "-"
        if entries.get("client") and page_html:
            loaded = "✓" if f"{name}/client.js" in page_html else "✗"
        rows.append((name, "有 " + str(entries.get("clientPath") or ""), ",".join(titles) or "-", loaded))
        led = ledger_load()
        item = led.get(name) or {}
        item.update({
            "name": name,
            "version": item.get("version") or _pkg_version(pkg_dir),
            "source": item.get("source") if item.get("source") not in (None, "", "unknown") else (deps.get(name) or "unknown"),
            "client": entries.get("clientPath") or "",
            "slots": entries.get("slots") or [],
            "navTitles": titles,
            "lastFixAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        led[name] = item
        ledger_save(led)

    for name, client, titles, loaded in rows:
        head_line = f"{name}  客户端:{client}  设置分区:{titles}  页面已加载:{loaded}"
        (ok if loaded in ("✓", "-") else warn)(head_line)
    if added_total:
        ok(f"白名单新增：{added_total}（刷新页面即可生效，不用重启）")
    else:
        info("白名单没有新增（都已登记）")
    if page_html:
        miss = [r[0] for r in rows if r[3] == "✗"]
        if miss:
            warn(f"这些插件的客户端没被页面加载：{', '.join(miss)}（看 home\\logs\\startup-*.log）")
    return 0


def _pkg_version(pkg_dir: Path) -> str:
    try:
        return str(json.loads((pkg_dir / "package.json").read_text(encoding="utf-8")).get("version") or "?")
    except Exception:
        return "?"


def client_module_id(pkg_dir: Path) -> str:
    """从 client.js 里抠出 `__ModuleLoader__.load({ id: '...' })` 的 id。

    这个 id 必须等于包名，否则浏览器端会报
    `could not load "<包名>"` / `duplicate factory registration`，**整个客户端都起不来**。
    实测踩过：复制模板只改 package.json，没改这个 id → 装完白页。
    """
    for name in ("client.js", "client/client.js", "dist/client.js", "index.client.js"):
        f = pkg_dir / name
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = re.search(r"__ModuleLoader__\.load\(\s*\{[^}]*?id:\s*['\"]([^'\"]+)['\"]", text, re.S)
        if m:
            return m.group(1)
    return ""


# ── 装插件：一条命令装完就能用（零代码接入的唯一入口）──────────────────────────
# 流程：⓪ 静态闸门（client.js 里 `__ModuleLoader__.load({id})` 必须等于包名，否则整页白屏）
#       → ⓪ 装前快照（profile 三件套 + 台账 → backups\pre-install-<ts>）
#       → ① plugins add（写 profile + pnpm）→ ② 侦察 client 入口/槽位/设置分区
#       → ③ 设置分区标题写进 state\ui-config.json 的 keepNav（裁剪白名单，卸载时按插件清）
#       → ④ 写安装台账（包名/版本/来源/时间/client/槽位）→ ⑤ safe_restart
#       → ⑥ 验证三件事：profile 里 bundle+linked、页面模块表含 <包>/client.js、本次启动无 EADDRINUSE
#       失败 → restore_install_snapshot() 自动回滚到装前状态。
# 坑：① 页面模块表里有 ≠ 客户端真的激活了（模块 id 不一致时白屏），所以⓪那道闸门必须在最前面；
#     ② 很多插件只注册 conversation.* 槽位，工作台没会话界面 → 装得上但看不见（会提示）。
def cmd_install_plugin(spec: str, keep_nav: str = "", no_restart: bool = False) -> int:
    """可视化插件统一安装：装 → 认出界面入口 → 登记白名单 → 安全重启 → 验证。

    一条命令装完就能用，不需要再改 ui\\workbench.js。
    """
    if not spec:
        bad("用法：wb.py install-plugin <npm 包名 或 插件目录> [--keep-nav 标题1,标题2] [--no-restart]")
        return 2
    head("可视化插件统一安装")
    target = normalize_pkg_name(spec)

    # ⓪-1 静态闸门：client.js 的模块 id 必须等于包名
    #      （复制模板最容易漏这一步；一旦不一致，浏览器整页 Failed to load plugins）
    src_dir = Path(spec)
    if not (src_dir.is_dir() and (src_dir / "package.json").exists()):
        src_dir = WB_HOME / "profiles" / WB_PROFILE / "node_modules" / target
    if src_dir.is_dir():
        mod_id = client_module_id(src_dir)
        if mod_id and mod_id != target:
            bad(f"client.js 里的模块 id 是「{mod_id}」，但包名是「{target}」")
            bad("这个 id 必须等于包名，否则浏览器会整页报 Failed to load plugins（实测踩过）")
            info(f"改法：把 {src_dir / 'client.js'} 里 __ModuleLoader__.load({{ id: '{mod_id}' … }}) 改成 '{target}'")
            return 1

    # ⓪ 装前快照（profile 三件套 + 台账），验证不过就靠它回滚
    snapshot = pre_install_snapshot()
    info(f"装前快照：{snapshot}")

    # ① 装进 bench profile（内部会跑 pnpm；失败就回滚）
    if cmd_plugins("add", spec, "") != 0:
        bad("安装失败，正在回滚")
        restore_install_snapshot(snapshot)
        cmd_plugins("install", "", "")
        return 1

    # ② 定位装好的包
    pkg_dir = pkg_dir_of(target)
    entries = detect_ui_entries(pkg_dir) if pkg_dir.exists() else {"titles": [], "sidebar": False, "client": False, "slots": []}
    ok(f"包：{target}（{'目录' if pkg_dir.exists() else '未找到目录'}，client={'有 ' + str(entries.get('clientPath') or '') if entries.get('client') else '无'}）")
    if entries.get("slots"):
        info(f"注册槽位：{', '.join(entries['slots'][:8])}")

    # ③ 设置分区标题写进 UI 白名单（并记住是哪个插件写的，卸载时好清）
    titles = [t.strip() for t in keep_nav.split(",") if t.strip()] or entries.get("titles") or []
    if titles:
        added = register_nav_titles(target, titles)
        cfg = ui_config_load()
        ok(f"设置导航白名单：新增 {added or '无（已在白名单）'}；当前 {cfg.get('keepNav')}")
    else:
        warn("没认出设置分区标题；如果它确实在设置里加了分区，用 --keep-nav 指定")

    # 安装台账：谁、什么版本、来源、声明能力、注册槽位
    led = ledger_load()
    ledger_item = led.get(target) or {}
    ledger_item.update({
        "name": target,
        "version": _pkg_version(pkg_dir),
        "source": spec,
        "client": entries.get("clientPath") or "",
        "slots": entries.get("slots") or [],
        "navTitles": titles,
        "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    led[target] = ledger_item
    ledger_save(led)
    info(f"台账：state\\installed.json 记下 {target} v{ledger_item.get('version')}")

    if no_restart:
        warn("已跳过重启；改动要 wb.py restart 后才生效")
        return 0

    # ④ 安全重启：先停、等端口真的释放、再启动（避免 EADDRINUSE 造成假故障）
    err_log = LOG_DIR / "workbench.err.log"
    err_offset = err_log.stat().st_size if err_log.exists() else 0
    started = safe_restart()

    # ⑤ 验证（任何一条硬指标不过 → 回滚，别把坏状态留给用户）
    head("验证")
    up = started and port_listening(WB_PORT)
    (ok if up else bad)(f"端口 {WB_PORT} {'在听' if up else '没起来'}")
    healthy = False
    if up:
        try:
            data = http_json(f"http://127.0.0.1:{WB_PORT}/wb-api/plugins")
            row = next((p for p in data.get("plugins", []) if p.get("name") == target), None)
            if row:
                healthy = bool(row.get("inBundles") and row.get("linked"))
                (ok if healthy else bad)(
                    f"{target}: bundle={'✓' if row.get('inBundles') else '✗'} linked={'✓' if row.get('linked') else '✗'} v={row.get('version')}")
            else:
                bad(f"插件清单里没有 {target}")
        except Exception as exc:  # noqa: BLE001
            warn(f"读插件清单失败：{exc}")

    if not (up and healthy):
        bad("验证没过，回滚到装前状态")
        restore_install_snapshot(snapshot)
        cmd_plugins("install", "", "")
        safe_restart()
        warn(f"已回滚；插件 {target} 未生效（快照：{snapshot}）")
        return 1

    try:
        url = current_url()
        if url:
            html = http_get_text(url)
            has_client = f"{target}/client.js" in html
            (ok if has_client else warn)(
                f"页面模块表{'包含' if has_client else '不含'} {target}/client.js（决定它的界面能不能渲染）")
    except Exception as exc:  # noqa: BLE001
        warn(f"检查页面模块表失败：{exc}")

    # 只看“本次启动之后新写入”的错误，别把历史 EADDRINUSE 当成本次故障
    if err_log.exists():
        try:
            with open(err_log, "rb") as fh:
                fh.seek(err_offset)
                fresh = fh.read().decode("utf-8", "replace")
        except Exception:
            fresh = ""
        if "EADDRINUSE" in fresh or "startup failed" in fresh:
            warn(f"本次启动日志里有 EADDRINUSE / startup failed —— 确认 {WB_PORT} 只有一个 owner（见 docs）")
        else:
            ok("本次启动没有 EADDRINUSE / startup failed")

    if entries.get("sidebar"):
        info("它声明了侧栏入口：如果自带「侧栏显示」开关，点一下就会出现在顶栏（顶栏自动发现）")
    if titles:
        info(f"打开 设置 → {titles[0]} 就能看到它的界面")
    # 界面能不能在工作台里露出来：工作台只有我们自己做的面板，没有会话/聊天界面
    slots = entries.get("slots") or []
    invisible = [s for s in slots if s.startswith(("conversation.", "chat.", "composer.", "message."))]
    if invisible and not entries.get("sidebar") and not titles:
        warn(f"它只注册了 {', '.join(invisible[:4])} 这类槽位——工作台没有会话界面，装了也看不到（功能可能仍可用）")
    info("入口：wb.py url / wb.py page")
    return 0


BRIDGE_PKG = "dsh-workbench-bridge"


def bridge_dir() -> Path:
    return WB_ROOT / "plugins" / BRIDGE_PKG


def bridge_is_soft() -> tuple[bool, str]:
    """桥必须是软依赖：inject 为空 + 用 ctx.get 取服务。硬依赖会把目标 harness 打死。"""
    index = bridge_dir() / "index.js"
    if not index.exists():
        return False, f"找不到 {index}"
    text = index.read_text(encoding="utf-8", errors="replace")
    if re.search(r"export\s+const\s+inject\s*=\s*\[\s*\]", text):
        return True, "inject = []（软依赖）"
    return False, "没有 export const inject = [] —— 硬依赖会拖垮目标 harness，拒绝安装"


def resolve_target_home(arg: str) -> Path:
    if arg:
        return Path(arg)
    try:
        cfg = json.loads((WB_ROOT / "config.json").read_text(encoding="utf-8"))
        if cfg.get("home"):
            return Path(cfg["home"])
    except Exception:
        pass
    return Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))


def _profile_manifest(prof: Path) -> dict:
    # utf-8-sig：目标机的 package.json 可能带 BOM（PowerShell Set-Content 就爱写 BOM）
    return json.loads((prof / "package.json").read_text(encoding="utf-8-sig"))


def _bundles_of(meta: dict) -> list:
    dsh = meta.get("dsh") if isinstance(meta.get("dsh"), dict) else {}
    profile = dsh.get("profile") if isinstance(dsh.get("profile"), dict) else {}
    bundles = profile.get("bundles")
    return bundles if isinstance(bundles, list) else []


def _backup_profile_manifest(prof: Path, tag: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / f"{tag}-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "pnpm-lock.yaml", "cordis.patch.yml"):
        p = prof / name
        if p.exists():
            shutil.copy2(p, dest / name)
    return dest


def _run_profile_install(home: Path, profile: str) -> int:
    cli = APP_ROOT / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd"
    if not cli.exists():
        bad(f"找不到 dsh CLI：{cli}")
        return 1
    env = dict(os.environ, DSH_HOME=str(home), DSH_PROFILE=profile)
    proc = subprocess.run(
        ["cmd", "/c", str(cli), "plugin", "--profile", profile, "install"],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900, creationflags=RUNFLAGS,
    )
    tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()][-4:]
    for ln in tail:
        info(ln)
    (ok if proc.returncode == 0 else bad)(f"profile install 退出码 {proc.returncode}")
    return proc.returncode


def cmd_attach(target_home: str = "", target_profile: str = "desktop",
               apply: bool = False, no_install: bool = False) -> int:
    """把接入层（软依赖桥）装进目标 harness 的 profile。默认只预览，--apply 才动手。"""
    home = resolve_target_home(target_home)
    prof = home / "profiles" / target_profile
    head(f"接入层安装：{prof}")
    if not (prof / "package.json").exists():
        bad(f"目标 profile 不存在：{prof / 'package.json'}")
        return 1
    soft, why = bridge_is_soft()
    (ok if soft else bad)(f"软依赖检查：{why}")
    if not soft:
        return 1

    meta = _profile_manifest(prof)
    deps = meta.get("dependencies") if isinstance(meta.get("dependencies"), dict) else {}
    bundles = _bundles_of(meta)
    if not bundles:
        bad("目标 package.json 里没有 dsh.profile.bundles —— 看着不像 DSH profile，拒绝操作")
        return 1
    spec = "link:" + bridge_dir().resolve().as_posix()
    need_dep = deps.get(BRIDGE_PKG) != spec
    need_bundle = BRIDGE_PKG not in bundles

    info(f"目标 harness home：{home}")
    info(f"目标 profile：{target_profile}（现有 bundle {len(bundles)} 个）")
    if need_dep:
        info(f"依赖：{BRIDGE_PKG} → {spec}（原值：{deps.get(BRIDGE_PKG) or '无'}）")
    if need_bundle:
        info(f"bundles：追加 {BRIDGE_PKG}")
    if not need_dep and not need_bundle:
        ok("已经装好了，无需改动")
        return 0
    if not apply:
        warn("这是预览。确认无误后加 --apply 执行（会先备份目标 profile 的清单）")
        return 0

    backup = _backup_profile_manifest(prof, "attach")
    info(f"已备份目标清单：{backup}")
    deps[BRIDGE_PKG] = spec
    meta["dependencies"] = deps
    dsh = meta.setdefault("dsh", {})
    profile_meta = dsh.setdefault("profile", {})
    profile_meta["bundles"] = bundles + ([BRIDGE_PKG] if need_bundle else [])
    (prof / "package.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok("package.json 已写入")

    if no_install:
        warn("跳过 pnpm install（--no-install）；链接要等目标 harness 下次启动或手动 install 才有")
    elif _run_profile_install(home, target_profile) != 0:
        warn("pnpm install 失败；清单已改好，可修好网络后重跑 wb.py attach --apply")
        return 1

    link = prof / "node_modules" / BRIDGE_PKG
    (ok if link.exists() else warn)(f"node_modules 链接：{'已就位' if link.exists() else '还没生成'}")
    head("下一步")
    info("重启目标 harness 才生效（桥是 host 代码，不热重载）")
    info("验证：目标 harness 里应出现 workbench_status / workbench_api / workbench_plugins / workbench_call 四个工具")
    return 0


def cmd_detach(target_home: str = "", target_profile: str = "desktop",
               apply: bool = False, no_install: bool = False) -> int:
    """把接入层从目标 harness 的 profile 里摘干净（含 node_modules 链接）。"""
    home = resolve_target_home(target_home)
    prof = home / "profiles" / target_profile
    head(f"接入层卸载：{prof}")
    if not (prof / "package.json").exists():
        bad(f"目标 profile 不存在：{prof / 'package.json'}")
        return 1
    meta = _profile_manifest(prof)
    deps = meta.get("dependencies") if isinstance(meta.get("dependencies"), dict) else {}
    bundles = _bundles_of(meta)
    has_dep = BRIDGE_PKG in deps
    has_bundle = BRIDGE_PKG in bundles
    if not has_dep and not has_bundle:
        ok("目标 profile 里没有接入层，无需改动")
        return 0
    info(f"将移除：依赖{'有' if has_dep else '无'} / bundles{'有' if has_bundle else '无'}")
    if not apply:
        warn("这是预览。加 --apply 执行（会先备份目标清单）")
        return 0

    backup = _backup_profile_manifest(prof, "detach")
    info(f"已备份目标清单：{backup}")
    deps.pop(BRIDGE_PKG, None)
    meta["dependencies"] = deps
    if has_bundle:
        dsh = meta.setdefault("dsh", {})
        dsh.setdefault("profile", {})["bundles"] = [b for b in bundles if b != BRIDGE_PKG]
    (prof / "package.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok("package.json 已清理")

    link = prof / "node_modules" / BRIDGE_PKG
    if link.exists():
        try:
            if link.is_dir() and not link.is_symlink():
                shutil.rmtree(link)
            else:
                os.remove(link)
        except Exception:
            try:
                subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True, creationflags=RUNFLAGS)
            except Exception:
                pass
        (ok if not link.exists() else warn)(f"node_modules 链接{'已移除' if not link.exists() else '没删掉，手动清一下'}")

    if not no_install:
        _run_profile_install(home, target_profile)
    warn("重启目标 harness 后桥才真正卸载（在那之前它还在进程里跑着）")
    return 0


def config_path() -> Path:
    return WB_ROOT / "config.json"


def config_load() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def config_save(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_port() -> int:
    """端口优先级：config.json 的 port → 环境变量 DSH_WORKBENCH_PORT → 59430。"""
    global WB_PORT
    port = config_load().get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        try:
            port = int(os.environ.get("DSH_WORKBENCH_PORT") or 0) or WB_PORT_DEFAULT
        except Exception:
            port = WB_PORT_DEFAULT
    WB_PORT = port
    RESERVED_PORTS.add(WB_PORT)
    return WB_PORT


def port_free(port: int) -> bool:
    import socket as _socket
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def pick_port(preferred: int, tries: int = 30) -> int:
    """从 preferred 往上找一个没人占的端口（客户机上 59430 可能被别人占了）。"""
    for offset in range(tries):
        candidate = preferred + offset
        if candidate > 65535:
            break
        if candidate in RESERVED_PORTS and candidate != preferred:
            continue
        if port_free(candidate):
            return candidate
    return preferred


def save_port(port: int) -> None:
    global WB_PORT
    WB_PORT = port
    RESERVED_PORTS.add(port)
    cfg = config_load()
    cfg["port"] = port
    cfg["portUpdatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    config_save(cfg)


# ── 分发包 ────────────────────────────────────────────────────────────
DIST_EXCLUDE_DIRS = {"app", "home", "state", "logs", "backups", "attic", "ref", "dist",
                     ".git", "node_modules", "__pycache__", ".pnpm-store"}
DIST_EXCLUDE_PLUGINS = {"dshmarket"}   # 测试插件，不进分发版
DIST_EXCLUDE_FILES = {"fix-sos-start.ps1"}  # 本机维护脚本（针对某个安装的排障），不给客户


def _dist_version() -> str:
    f = WB_ROOT / "VERSION"
    if f.exists():
        try:
            return f.read_text(encoding="utf-8-sig").strip() or "0.0.0"
        except Exception:
            pass
    return "0.1.0-" + time.strftime("%Y%m%d")


# ── 分发：打一个可直接拷给客户的目录 dist\DSH-Workbench-<版本>\ ─────────────────
# 收：tools / plugins / ui / seeds / 客户向 docs / config.template.json / README / MANIFEST.json
# 不收：app（运行时副本太大，由客户机 install 时复制）、home、state、logs、backups、attic、ref、
#       以及**内部文档**（前缀排除：handoff / upgrade-policy / plugin-manager-gaps / tools-plan /
#       publish-checklist / sos- / test-round-）和**测试插件**（DIST_EXCLUDE_PLUGINS = dshmarket）。
# 硬指标：MANIFEST.absolutePathHits 必须为 0（本机绝对路径会让客户机上跑不起来）。
#   计数用单反斜杠字面量 `"E:" + chr(92) + "DSH-WORKBENCH"`——写成双反斜杠会数出 0（踩过）。
def cmd_pack(out: str = "", include_test: bool = False, force: bool = False,
             make_zip: bool = False) -> int:
    """打一个可分发目录：源码/插件/界面/文档/种子，不含运行时、状态、备份与本机配置。"""
    ver = _dist_version()
    dest = Path(out) if out else (WB_ROOT / "dist" / f"DSH-Workbench-{ver}")
    head(f"打包工作台 {ver} → {dest}")
    if dest.exists():
        if not force:
            bad("目标已存在；加 --force 覆盖")
            return 1
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    def ignore(_dir, names):
        return [n for n in names if n in DIST_EXCLUDE_DIRS or n in DIST_EXCLUDE_FILES or n.endswith(".pyc")]

    for name in ("tools", "ui", "docs", "seeds"):
        src = WB_ROOT / name
        if not src.exists():
            continue
        if name == "docs":
            # 只带面向使用者的文档；内部交接/事故记录里的本机路径不进分发包
            (dest / "docs").mkdir(parents=True, exist_ok=True)
            for f in sorted(src.glob("*")):
                if not f.is_file():
                    continue
                if any(f.name.startswith(p) for p in ("handoff", "upgrade-policy", "meow-memory-", "dsh-issue-", "plugin-manager-gaps", "tools-plan", "publish-checklist", "sos-", "test-round-")):
                    continue
                shutil.copy2(f, dest / "docs" / f.name)
            info(f"已复制 docs/（内部记录已排除）")
            continue
        shutil.copytree(src, dest / name, ignore=ignore, dirs_exist_ok=True)
        info(f"已复制 {name}/")

    (dest / "plugins").mkdir(exist_ok=True)
    plugins = []
    excluded_plugins = []
    for p in sorted((WB_ROOT / "plugins").iterdir()):
        if not p.is_dir() or p.name in DIST_EXCLUDE_DIRS:
            continue
        if p.name in DIST_EXCLUDE_PLUGINS and not include_test:
            excluded_plugins.append(p.name)
            continue
        try:
            meta = json.loads((p / "package.json").read_text(encoding="utf-8-sig"))
        except Exception:
            meta = {}
        shutil.copytree(p, dest / "plugins" / p.name, ignore=ignore, dirs_exist_ok=True)
        plugins.append({"name": meta.get("name", p.name), "version": meta.get("version", "?")})
    info(f"已复制 plugins/{len(plugins)} 个" + (f"（排除 {excluded_plugins}）" if excluded_plugins else ""))

    (dest / "config.template.json").write_text(json.dumps({
        "port": 59430,
        "note": "复制为 config.json 后按需改端口；install/home 路径在首次运行 wb.py doctor 时自动识别",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 双击安装器：installer\ 下的两个文件复制到**包根**（它们会找同级的 tools\wb.py）
    installer_dir = WB_ROOT / "installer"
    if installer_dir.is_dir():
        for name in ("install.cmd", "install.ps1"):
            src_file = installer_dir / name
            if src_file.exists():
                shutil.copy2(src_file, dest / name)
        info("已复制双击安装器 install.cmd / install.ps1")

    (dest / "README.md").write_text(f"""# DSH 工作台 {ver}（分发包）

> ## ⚠️ 本项目由 AI 生成
>
> 这里的代码与文档**绝大部分由 AI 编程助手（DeepSeek Harness 里的 agent）编写**，人类负责定需求、
> 做判断、跑验收。**不是人类从零手写的项目**——请据此判断代码质量与风险。
>
> **English**: This project is largely AI-generated (written by an AI coding agent), with human
> direction and acceptance testing.

工作台 = 独立的 DSH 运行时副本 + 自带插件宿主，用来装/改插件而不碰你的主 harness。
主 harness 只加一个**软依赖**接入层（`dsh-workbench-bridge`），可随时 `detach` 撤掉。

## 前置

- Windows；已安装 DeepSeek Harness（本包不含它的运行时，会从你的安装复制一份）
- Python 3.10+（`python` 在 PATH 里）

## 三步装好

```powershell
# 1) 安装：复制一份你自己的 harness 运行时到 workbench\\app，并准备好 profile
python tools\\wb.py install

# 2) 接入：把软依赖桥装进你的 harness profile（先预览，确认后加 --apply）
python tools\\wb.py attach
python tools\\wb.py attach --apply

# 3) 打开页面（装完 attach 后要重启一次 harness 才生效）
python tools\\wb.py page
```

## 改界面

界面改造全部走 `ui\\`（`workbench.css` + `workbench.js`），由 `plugins\\dsh-wb-ui` 用
`webServer.tapIndex` 注入首页——**和 harness 改 webui 是同一套机制**，见 `ui\\README.md`。
删掉 `ui\\` 里的文件即恢复原版界面。

## 装插件

```powershell
python tools\\wb.py plugin-info   <包名>          # 侦察：会露在哪、要什么权限
python tools\\wb.py install-plugin <包名>         # 装 + 登记界面白名单 + 安全重启 + 验证
python tools\\wb.py uninstall-plugin <包名>       # 卸干净
python tools\\wb.py fix-ui                        # 从别处装的插件，跑这个补齐治理
```

## 不要提交/分发的东西

`app\\`（运行时副本，1.7GB）、`home\\`、`state\\`、`logs\\`、`backups\\`。
`tools\\wb.py backup` 只备份源码类内容；`state\\plugin-notes.json` 与 `state\\ui-config.json` 会一起备份。
""", encoding="utf-8")

    marker = "E:" + chr(92) + "DSH-WORKBENCH"   # 本机绝对路径标记（别写成双反斜杠，会数出 0）
    hits = 0
    for f in dest.rglob("*"):
        if f.is_file() and f.suffix.lower() in {".py", ".js", ".mjs", ".json", ".yml", ".md", ".cmd", ".ps1"}:
            try:
                hits += f.read_text(encoding="utf-8", errors="replace").count(marker)
            except Exception:
                pass

    manifest = {
        "name": "DSH-Workbench",
        "version": ver,
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "plugins": plugins,
        "excludedPlugins": excluded_plugins,
        "testOnlyPlugins": sorted(DIST_EXCLUDE_PLUGINS),
        "excludedDirs": sorted(DIST_EXCLUDE_DIRS),
        "files": sum(1 for f in dest.rglob("*") if f.is_file()),
        "absolutePathHits": hits,
        "note": "testOnlyPlugins 是仅用于本机试验的插件（如插件市场），不进分发版；absolutePathHits 必须为 0 才算可移植",
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 许可协议要跟着包走（客户拿到的是一份 MIT 授权的软件）
    lic = WB_ROOT / "LICENSE"
    if lic.exists():
        shutil.copy2(lic, dest / "LICENSE")

    ok(f"分发包就绪：{dest}")
    info(f"文件 {manifest['files']} 个，插件 {len(plugins)} 个，本机绝对路径残留 {hits} 处")
    if hits:
        warn("还有本机绝对路径，客户机上可能出问题（台账 DIST-02/03）")

    # --zip：给 GitHub Release / 直接发给客户用（zip 放 dist\ 根，不进 git）
    if make_zip:
        import zipfile as _zip
        zip_path = WB_ROOT / "dist" / f"DSH-Workbench-{ver}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with _zip.ZipFile(zip_path, "w", _zip.ZIP_DEFLATED) as zf:
            for f in sorted(dest.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(dest.parent))
        ok(f"已打包 zip：{zip_path}（{zip_path.stat().st_size / 1048576:.1f} MB）")
    return 0


def _git(args: list[str]) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=str(WB_ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120, creationflags=RUNFLAGS)
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"__ERR__ {exc}"


def cmd_prepublish() -> int:
    """公开仓库前自检：第三方代码、密钥、本机路径、体积、许可。

    `ref/` 里是官方 bundle 反解出来的源码与第三方插件源码——**只允许留在私有库里**。
    """
    head("公开前自检（publish checklist）")
    fails: list[str] = []
    warns: list[str] = []

    tracked = [ln.strip() for ln in _git(["ls-files"]).splitlines() if ln.strip()]
    if tracked and not tracked[0].startswith("__ERR__"):
        info(f"已跟踪文件：{len(tracked)} 个")
    else:
        bad("读不到 git 跟踪列表（这里不是 git 仓库？）")
        return 1

    # ① ref/ 是否还在 HEAD
    ref_tracked = [t for t in tracked if t.startswith("ref/")]
    if ref_tracked:
        fails.append(f"HEAD 里还有 {len(ref_tracked)} 个 ref/ 文件（第三方/官方反解源码）")
    else:
        ok("HEAD 里没有 ref/（第三方与官方反解源码已移出）")

    # ② 历史里是否还有 ref/
    hist = _git(["log", "--all", "--name-only", "--pretty=format:", "--", "ref"])
    hist_files = {ln.strip() for ln in hist.splitlines() if ln.strip().startswith("ref/")}
    if hist_files:
        warns.append(f"**历史提交**里仍有 {len(hist_files)} 个 ref/ 文件 —— 公开前要么重写历史摘掉，要么确认授权")
    else:
        ok("历史里也没有 ref/")

    # ③ 密钥/凭据
    secret_pat = re.compile(r"(gho_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                            r"|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
    hits = []
    for rel in tracked:
        p = WB_ROOT / rel
        if not p.is_file() or p.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in secret_pat.finditer(text):
            hits.append(f"{rel}: {m.group(0)[:12]}…")
    if hits:
        fails.append(f"疑似密钥 {len(hits)} 处：" + "; ".join(hits[:5]))
    else:
        ok("已跟踪文件里没有疑似密钥")

    # ④ 本机绝对路径
    marker = "E:" + chr(92) + "DSH-WORKBENCH"
    abs_hits = []
    for rel in tracked:
        p = WB_ROOT / rel
        if not p.is_file() or p.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        n = text.count(marker)
        if n:
            abs_hits.append(f"{rel}({n})")
    if abs_hits:
        warns.append(f"本机绝对路径 {sum(int(x.split('(')[1].rstrip(')')) for x in abs_hits)} 处：" + ", ".join(abs_hits[:6]))
    else:
        ok("已跟踪文件里没有本机绝对路径")

    # ⑤ 不该进仓库的大目录
    for bad_dir in ("dist", "app", "home", "state", "backups", "attic"):
        if any(t.startswith(bad_dir + "/") for t in tracked):
            fails.append(f"{bad_dir}/ 里还有文件被 git 跟踪")
    if not any(f.startswith(tuple(f"{d}/" for d in ("dist", "app", "home", "state", "backups", "attic"))) for f in fails):
        ok("dist/ app/ home/ state/ backups/ attic/ 都没进 git")

    # ⑥ 体积
    big = []
    for rel in tracked:
        p = WB_ROOT / rel
        if p.is_file() and p.stat().st_size > 1024 * 1024:
            big.append(f"{rel} {p.stat().st_size // 1024} KB")
    if big:
        warns.append("有超过 1MB 的文件：" + ", ".join(big[:5]))
    else:
        ok("没有超过 1MB 的已跟踪文件")

    # ⑦ 许可
    if not any(t.upper().startswith("LICENSE") for t in tracked):
        warns.append("没有 LICENSE 文件（公开前决定许可协议）")

    # ⑧ 测试插件痕迹（文档里提到没问题，但别进分发包）
    if "plugins/dshmarket" in " ".join(tracked):
        fails.append("仓库里跟踪了 dshmarket（测试插件）")

    head("结论")
    for w in warns:
        warn(w)
    for f in fails:
        bad(f)
    if fails:
        bad(f"不能公开：{len(fails)} 项必须先处理（清单见 docs\\publish-checklist.md）")
        return 1
    ok("硬性检查全过" + ("（还有 {} 条提醒，公开前过一眼）".format(len(warns)) if warns else ""))
    return 0


REGISTRY_URL = "https://awesome-dsh-plugin.com/plugins.json"


def registry_path() -> Path:
    return STATE_DIR / "registry.json"


def registry_load() -> dict:
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def cmd_registry(refresh: bool = False) -> int:
    """插件注册表缓存（插件市场用的那份 json）——搜索/更新/能力徽章都靠它。

    只读外部公共数据，不依赖插件市场那个插件本身。
    """
    head("插件注册表")
    cached = registry_load()
    if cached and not refresh:
        items = cached.get("items") or []
        ok(f"已有缓存：{len(items)} 条（{cached.get('fetchedAt', '?')}）")
        info("要刷新：wb.py registry --refresh")
        return 0
    try:
        from urllib.request import urlopen
        raw = urlopen(REGISTRY_URL, timeout=60).read().decode("utf-8", "replace")
        data = json.loads(raw)
        items = data if isinstance(data, list) else (data.get("plugins") or data.get("items") or [])
        if not items:
            bad("注册表格式不符（没拿到条目）")
            return 1
        payload = {"fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "url": REGISTRY_URL, "items": items}
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        registry_path().write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        ok(f"已缓存 {len(items)} 条 → {registry_path()}")
        return 0
    except Exception as exc:  # noqa: BLE001
        warn(f"拉注册表失败（离线也能用，只是没有搜索/能力信息）：{exc}")
        return 1


def split_npm_spec(spec: str) -> tuple[str, str]:
    """把 `name@1.2.3` / `@scope/name@1.2.3` 拆成 (名字, 版本)；本地/URL 原样返回。"""
    if spec.startswith(("file:", "link:", "github:", "http", "git+")):
        return spec, ""
    if spec.startswith("@"):
        scope, _, rest = spec.partition("/")
        if "@" in rest:
            pkg, _, ver = rest.rpartition("@")
            return f"{scope}/{pkg}", ver
        return spec, ""
    if "@" in spec:
        name, _, ver = spec.rpartition("@")
        return name, ver
    return spec, ""


def registry_items() -> list[dict]:
    data = registry_load()
    items = data.get("items")
    return items if isinstance(items, list) else []


def registry_lookup(name: str) -> dict | None:
    """按 npm 包名（或短名）在注册表里找一条。"""
    for item in registry_items():
        if not isinstance(item, dict):
            continue
        if item.get("npm") == name or item.get("name") == name:
            return item
    return None


def _desc_of(item: dict) -> str:
    d = item.get("description")
    if isinstance(d, dict):
        return str(d.get("zh") or d.get("en") or "").strip()
    return str(d or "").strip()


def cmd_plugin_search(query: str, limit: int = 20) -> int:
    """在社区注册表里搜插件（离线则提示先 wb.py registry --refresh）。"""
    if not query:
        bad("用法：wb.py plugin-search <关键词> [--limit N]")
        return 2
    items = registry_items()
    if not items:
        bad("还没有注册表缓存：先跑 wb.py registry --refresh")
        return 1
    q = query.lower()
    hits = []
    for item in items:
        if not isinstance(item, dict):
            continue
        blob = " ".join(str(item.get(k) or "") for k in ("name", "npm", "category")) + " " + _desc_of(item)
        if q in blob.lower():
            hits.append(item)
    hits.sort(key=lambda x: int(x.get("downloads") or 0), reverse=True)
    head(f"搜索结果：{query}（{len(hits)} 条，显示前 {min(limit, len(hits))}）")
    if not hits:
        warn("没找到；换个关键词，或先 wb.py registry --refresh 更新缓存")
        return 0
    installed = set(_bench_deps().keys())
    for item in hits[:limit]:
        npm = str(item.get("npm") or item.get("name") or "")
        mark = "已装" if npm in installed else "   "
        caps = item.get("capabilities") or []
        risky = [c for c in caps if c in ("credentials", "fs-write", "network", "shell", "dynamic-code")]
        info(f"[{mark}] {npm}  v{item.get('version', '?')}  ↓{item.get('downloads', 0)}  "
             f"{'⚠' + ','.join(risky) if risky else '能力: ' + (','.join(caps) if caps else '无')}")
        desc = _desc_of(item)
        if desc:
            info(f"        {desc[:96]}")
    info("安装：wb.py install-plugin <npm 包名>")
    return 0


def cmd_plugin_update(name: str = "", apply: bool = False) -> int:
    """检查（并可升级）已装插件到注册表里的最新版本。"""
    items = registry_items()
    if not items:
        bad("还没有注册表缓存：先跑 wb.py registry --refresh")
        return 1
    deps = _bench_deps()
    rows = []
    for pkg, spec in deps.items():
        if pkg.startswith("@deepseek-ai/"):      # 内置，别动
            continue
        if str(spec).startswith("link:"):        # 本地自研，没有"新版本"概念
            continue
        item = registry_lookup(pkg)
        if not item:
            continue
        installed_version = _pkg_version(pkg_dir_of(pkg))
        latest = str(item.get("version") or "")
        if latest and installed_version and latest != installed_version:
            rows.append((pkg, installed_version, latest))
    head("插件更新检查")
    if not rows:
        ok("已装插件都是最新（或注册表里查不到更新）")
        return 0
    for pkg, cur, new in rows:
        info(f"{pkg}: {cur} → {new}")
    if not apply:
        info("升级一个：wb.py plugin-update <包名> --apply（会走装前快照 + 验证 + 失败回滚）")
        return 0
    targets = [r for r in rows if (not name or r[0] == name)]
    if not targets:
        bad(f"没有可升级的条目匹配 {name}")
        return 1
    pkg, cur, new = targets[0]
    warn(f"开始升级 {pkg}: {cur} → {new}（失败会自动回滚）")
    return cmd_install_plugin(f"{pkg}@{new}", "", False)


def _asar_markers(asar: Path, markers: dict[str, bytes]) -> dict[str, int]:
    """在 app.asar 里数一下关键字符串出现次数（只读）。用来静态判断某个 harness 版本能不能挂工作台。"""
    out: dict[str, int] = {k: 0 for k in markers}
    try:
        data = asar.read_bytes()
        for key, needle in markers.items():
            out[key] = data.count(needle)
    except Exception as exc:  # noqa: BLE001
        out["__error__"] = str(exc)  # type: ignore[assignment]
    return out


# PM-06 兼容分级：三档结论 + 每档的降级说明
PREFLIGHT_BLOCKERS = {
    "webServer": ("服务 webServer", "注入层和状态面板都靠它挂路由；缺了页面什么都显示不出来"),
    "sidebar.panellist": ("槽位 sidebar.panellist", "顶栏入口靠它注册；缺了没有工作台入口"),
}
PREFLIGHT_DEGRADERS = {
    "sessionController": ("服务 sessionController", "「Harness会话」面板不可用（列表/历史/发送全废），其余照常"),
    "reflect": ("服务 reflect", "状态面板的「宿主服务」实时枚举不可用（只能看静态快照）"),
    "settings.section": ("槽位 settings.section", "插件在设置页里的分区不出现（插件市场等设置入口看不见）"),
}
PREFLIGHT_CLIENTS = {
    "dsh-client-ui-plugin-manager": "插件管理器（提供 pluginNavigation）",
    "dsh-client-ui-settings-general": "设置-通用（预览说明/设置裁剪补丁落点）",
    "dsh-client-ui-schedule": "自动化任务（对应 disabled 补丁会被忽略，只打 warning）",
    "dsh-client-ui-entry-customization": "入口自定义（rc.3 起依赖 pluginNavigation）",
}
PREFLIGHT_KNOWN = {"0.2.1-alpha.1", "0.2.1-rc.3"}


def _preflight_verdict(install: str) -> dict:
    """算兼容结论，供 CLI 与 install 门禁共用。返回 {grade, version, blockers, degradations, notes, checks}。"""
    target = Path(install) if install else MAIN_INSTALL
    out: dict = {"install": str(target), "version": "?", "grade": "incompatible",
                 "blockers": [], "degradations": [], "notes": [], "checks": []}
    if not valid_install(target):
        out["blockers"].append(f"不是有效的 harness 安装目录：{target}")
        return out
    rt = target / "resources" / "runtime" / "primary-runtime" / "runtime.json"
    try:
        out["version"] = json.loads(rt.read_text(encoding="utf-8-sig")).get("desktopVersion") or "?"
    except Exception:
        pass
    asar = target / "resources" / "app.asar"
    if not asar.exists():
        out["blockers"].append("找不到 resources\\app.asar")
        return out

    marks = _asar_markers(asar, {k: k.encode() for k in
                                 (*PREFLIGHT_BLOCKERS, *PREFLIGHT_DEGRADERS, *PREFLIGHT_CLIENTS, "pluginNavigation")})
    if "__error__" in marks:
        out["blockers"].append(f"读 asar 失败：{marks['__error__']}")
        return out

    for key, (label, impact) in PREFLIGHT_BLOCKERS.items():
        present = marks.get(key, 0) > 0
        out["checks"].append({"key": key, "label": label, "present": present, "level": "blocker", "impact": impact})
        if not present:
            out["blockers"].append(f"{label} 缺失 —— {impact}")
    for key, (label, impact) in PREFLIGHT_DEGRADERS.items():
        present = marks.get(key, 0) > 0
        out["checks"].append({"key": key, "label": label, "present": present, "level": "degradation", "impact": impact})
        if not present:
            out["degradations"].append(f"{label} 缺失 —— {impact}")
    for key, label in PREFLIGHT_CLIENTS.items():
        present = marks.get(key, 0) > 0
        out["checks"].append({"key": key, "label": label, "present": present, "level": "client", "impact": ""})

    has_pn = marks.get("pluginNavigation", 0) > 0
    has_ec = marks.get("dsh-client-ui-entry-customization", 0) > 0
    out["pluginNavigation"] = {"present": has_pn, "entryCustomization": has_ec}
    if has_pn and has_ec:
        out["notes"].append("该版本的「入口自定义」依赖 pluginNavigation → 补丁里必须保留 ui-plugin-manager"
                            "（当前已保留；若禁用会让客户端整页报 Failed to load plugins，rc.3 上踩过）")
    elif has_pn:
        out["notes"].append("该版本有 pluginNavigation 但无「入口自定义」依赖 → 禁用插件管理器也不会炸（alpha.1 就是这样）")
    if out["version"] not in PREFLIGHT_KNOWN:
        out["notes"].append(f"{out['version']} 不在已验证清单（{'/'.join(sorted(PREFLIGHT_KNOWN))}）里："
                            "静态检查只能保证接口在，实际表现要跑一次 install + 开页面确认")

    if out["blockers"]:
        out["grade"] = "incompatible"
    elif out["degradations"]:
        out["grade"] = "degraded"
    else:
        out["grade"] = "compatible"
    return out


def cmd_preflight(install: str, as_json: bool = False) -> int:
    """体检：目标 harness 安装能不能挂这套工作台（静态检查，不复制、不启动）。

    三档结论：compatible（能用）/ degraded（能跑但有功能降级）/ incompatible（装不了）。
    """
    v = _preflight_verdict(install)
    if as_json:
        print(json.dumps(v, ensure_ascii=False))
        return 0 if v["grade"] != "incompatible" else 1

    head("兼容体检（目标 harness）")
    ok(f"安装目录 {v['install']}")
    ok(f"版本 {v['version']}")
    if any(c["level"] == "blocker" and c["key"] == "app.asar" for c in v["checks"]):
        pass
    for c in v["checks"]:
        if c["level"] == "client":
            # 客户端包只是"有/没有"，缺了不影响能不能跑
            info(f"{c['label']}：{'有' if c['present'] else '无（该版本没有，不影响跑）'}")
        elif c["present"]:
            ok(f"{c['label']}：有")
        elif c["level"] == "blocker":
            bad(f"{c['label']}：没找到")
        else:
            warn(f"{c['label']}：没找到")

    head("结论")
    grade = v["grade"]
    if grade == "incompatible":
        for b in v["blockers"]:
            bad(b)
        bad("不兼容：这套工作台装不上（装了也是白页）")
        return 1
    for d in v["degradations"]:
        warn(f"降级：{d}")
    for n in v["notes"]:
        info(n)
    if grade == "degraded":
        warn(f"可跑但有降级：{v['version']} 上 {len(v['degradations'])} 项功能会缺（见上）")
        warn("装法一样：wb.py paths --install <该目录> 然后 wb.py install")
        return 0
    ok(f"兼容：这套工作台可以完整跑在 {v['version']} 上（静态检查通过；动态仍需 install + 开页面确认）")
    info("下一步：wb.py paths --install <该目录> 然后 wb.py install")
    return 0


def cmd_sync_bed(target: str) -> int:
    """把当前开发态的 code（tools/plugins/ui/seeds/config.template.json）同步到另一套工作台根目录。

    测试床最大的坑是漂移：床里的代码是手工 copy 的，改完主套不同步，测出来的结论就不算数。
    """
    head("同步代码到测试床")
    if not target:
        bad("用法：wb.py sync-bed <目标根目录>")
        return 2
    dst_root = Path(target).resolve()
    if not dst_root.is_dir() or dst_root.resolve() == WB_ROOT.resolve():
        bad(f"目标不合法：{dst_root}")
        return 2
    if not (dst_root / "tools" / "wb.py").exists():
        bad(f"{dst_root} 看起来不是工作台根目录（缺 tools\\wb.py）")
        return 2
    ok(f"源 {WB_ROOT} → 目标 {dst_root}")
    copied = 0
    for sub in ("tools", "plugins", "ui", "seeds"):
        src_dir = WB_ROOT / sub
        if not src_dir.is_dir():
            continue
        for item in src_dir.rglob("*"):
            if item.is_dir() or item.suffix in (".pyc",):
                continue
            if "__pycache__" in item.parts:
                continue
            rel = item.relative_to(WB_ROOT)
            out = dst_root / rel
            if out.exists() and out.stat().st_size == item.stat().st_size and out.read_bytes() == item.read_bytes():
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(item.read_bytes())
            copied += 1
    tpl = WB_ROOT / "config.template.json"
    if tpl.exists():
        (dst_root / "config.template.json").write_bytes(tpl.read_bytes())
    ok(f"已同步 {copied} 个变更文件（{WB_ROOT.name} → {dst_root.name}）")
    info("宿主侧插件代码改过的话，测试床要重启才生效：到该目录跑 wb.py restart-safe")
    return 0


def current_url() -> str | None:
    """取最新的带 token 入口（token 每次重启都换）。"""
    log = LOG_DIR / "workbench.out.log"
    if log.exists():
        # 以日志里最后一条 "dsh web: http://127.0.0.1:<端口>/?token=<token>" 为准，
        # 不要用 WB_PORT 去拼——端口被自动避让/手工改过时拼出来是错的。
        hits = re.findall(r"dsh web: (http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_\-]+)", 
                          log.read_text(encoding="utf-8", errors="replace"))
        if hits:
            url = hits[-1]
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / "workbench-url.txt").write_text(url, encoding="ascii")
            return url
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


# ── 一键安装：preflight → install → attach（客户机/双击安装器的入口）────────────
# 为什么要有它：分步（paths→preflight→install→attach）对开发者清晰，对客户太啰嗦。
# 这里把它们串成一条，仍然保持所有安全性质：
#   · 门禁照跑（incompatible 直接中止，一个字节运行时都不复制）
#   · 运行时已存在就跳过复制（幂等，重复点不会再多占 1.6GB）
#   · attach 默认**只在没接过时**才做；目标 profile 自动挑（desktop 优先）
#   · 不自动打开的页面要显式 --open（打开页面永远无副作用）
def cmd_setup(no_attach: bool = False, do_open: bool = False, yes: bool = False) -> int:
    head("一键安装（preflight → install → attach）")
    paths = load_paths()
    ok(f"目标 harness：{MAIN_INSTALL}（{paths.get('installSource', '?')}）")
    ok(f"数据目录：{MAIN_HOME}（{paths.get('homeSource', '?')}）")

    verdict = _preflight_verdict(str(MAIN_INSTALL))
    ok(f"版本 {verdict['version']}｜兼容档位 {verdict['grade']}")
    if verdict["grade"] == "incompatible":
        bad("目标 harness 不兼容，安装中止：")
        for b in verdict["blockers"]:
            bad(f"  · {b}")
        return 1
    for d in verdict["degradations"]:
        warn(f"降级：{d}")

    if cmd_install(False) != 0:
        bad("install 失败，setup 中止")
        return 1

    if no_attach:
        info("跳过接入层（--no-attach）")
    else:
        home = MAIN_HOME
        prof_names = [p.name for p in (home / "profiles").glob("*") if (p / "package.json").exists()] if (home / "profiles").exists() else []
        if not prof_names:
            warn(f"{home}\\profiles 下没有可用 profile，跳过接入层（装好 harness 后跑 wb.py attach --apply）")
        else:
            target = "desktop" if "desktop" in prof_names else prof_names[0]
            meta = _profile_manifest(home / "profiles" / target)
            deps = meta.get("dependencies") if isinstance(meta.get("dependencies"), dict) else {}
            if BRIDGE_PKG in deps:
                ok(f"接入层已装在该 profile（{target}），跳过")
            else:
                if not yes:
                    info(f"接下来会把接入层装进 {home}\\profiles\\{target}（只改 package.json，先备份；要撤销用 detach）")
                if cmd_attach(str(home), target, apply=True) != 0:
                    warn("接入层安装失败——工作台本体已经可用，可以稍后手动跑 wb.py attach --apply 重试")
                else:
                    info("接入层改完需要**重启你的 harness** 才生效（桥是宿主代码）")

    if do_open:
        cmd_open()
    else:
        url = current_url()
        if url:
            info(f"入口（复制到浏览器）：{url}")
        info("打开页面：wb.py page，或点桌面「DSH 工作台」")
    head("完成")
    ok("可以重复执行 setup（幂等）：升级后用 install --force，回滚用 rollback")
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
            open_landing(f"工作台进程没起来（端口 {WB_PORT} 无响应）")
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


# ── 快捷方式修复：把桌面/启动项指回**当前这个根** ─────────────────────────────
# 场景：在多套工作台之间折腾（例如给测试床跑 install）会把宿主的快捷方式改指向测试目录，
# 测完删掉目录就变成死链。这条命令用来一条命令修回来。
# ── 卸载工作台本体：停服务 → 摘快捷方式 →（可选）摘接入层 →（可选）删目录 ──────
# 默认**只演练**：打印"会停什么、删哪些快捷方式、删哪些目录、多大"，不动手。
#   --apply            真的执行（停服务 + 删指向本根的快捷方式）
#   --purge            连目录一起删（要配合 --apply）。删除动作交给 %TEMP% 里的小脚本，
#                      否则正在运行的 python 会被自己删掉一半。
#   --detach           顺带把主驾 profile 里的接入层摘掉（会重启目标 harness 才生效）
# 注意：只删**指向本根**的快捷方式——多套工作台共存时，别把别人的入口删了。
def cmd_uninstall(purge: bool = False, do_detach: bool = False, apply: bool = False) -> int:
    head("卸载工作台" + ("" if apply else "（演练，不改动）"))
    ok(f"根目录 {WB_ROOT}")
    size = dir_size(WB_ROOT)
    info(f"占用：{size[0]} 文件 / {size[1] / 1048576:.0f} MB")

    # ① 会停掉什么
    head("将停止")
    pids = read_pids()
    for name in ("serve", "watchdog", "supervisor"):
        pid = int(pids.get(name) or 0)
        info(f"{name:<12} pid={pid or '-'}{'（运行中）' if pid and pid_alive(pid) else ''}")
    if find_supervisors():
        info(f"supervisor  另有进程在跑")

    # ② 哪些快捷方式指向本根（只动这些）
    head("将移除的快捷方式（只删指向本根的）")
    desktop = Path(os.environ.get("USERPROFILE", r"C:\Users\Administrator")) / "Desktop"
    startup = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    targets = [desktop / "DSH 工作台.lnk", desktop / "DSH 工作台 安装器.lnk",
               startup / "DSH 工作台（自动伴随）.lnk"]
    ours: list[Path] = []
    for lnk in targets:
        if not lnk.exists():
            continue
        hit = False
        try:
            probe = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}').Arguments"],
                capture_output=True, text=True, timeout=30, creationflags=RUNFLAGS,
                encoding="utf-8", errors="replace")
            hit = str(WB_ROOT) in (probe.stdout or "")
        except Exception:
            hit = False
        if hit:
            ours.append(lnk)
            info(f"{lnk}")
        else:
            warn(f"{lnk} 指向别处，跳过")

    # ③ 接入层
    if do_detach:
        head("接入层")
        profiles = [(p.name) for p in (MAIN_HOME / "profiles").glob("*") if (p / "package.json").exists()] \
            if (MAIN_HOME / "profiles").exists() else []
        for name in profiles:
            meta = _profile_manifest(MAIN_HOME / "profiles" / name)
            deps = meta.get("dependencies") if isinstance(meta.get("dependencies"), dict) else {}
            if BRIDGE_PKG in deps:
                info(f"{name}：里有 {BRIDGE_PKG}，将摘掉（要重启那个 harness 才生效）")

    if not apply:
        head("演练结束")
        info("真删加参数：--apply（停服务 + 删上面的快捷方式）")
        info("连目录一起删：--apply --purge")
        info(f"要删的目录：{WB_ROOT}（{size[1] / 1048576:.0f} MB）")
        return 0

    # ④ 真执行
    cmd_suspend()
    removed = 0
    for lnk in ours:
        try:
            lnk.unlink()
            ok(f"已删除 {lnk.name}")
            removed += 1
        except Exception as exc:  # noqa: BLE001
            warn(f"删不掉 {lnk.name}：{exc}")

    if do_detach:
        for p in (MAIN_HOME / "profiles").glob("*"):
            if (p / "package.json").exists():
                meta = _profile_manifest(p)
                deps = meta.get("dependencies") if isinstance(meta.get("dependencies"), dict) else {}
                if BRIDGE_PKG in deps:
                    cmd_detach(str(MAIN_HOME), p.name, True, True)

    if purge:
        # 自己删自己不行：写一个临时脚本，延迟 2 秒后删根目录并自杀
        tmp = Path(os.environ.get("TEMP", ".")) / f"wb-uninstall-{int(time.time())}.cmd"
        tmp.write_text(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'rmdir /s /q "{WB_ROOT}"\r\n'
            f'del /f /q "%~f0"\r\n',
            encoding="gbk", errors="replace")
        subprocess.Popen(["cmd", "/c", str(tmp)], creationflags=DETACHED | NO_WINDOW,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok("已启动清理脚本（2 秒后删除整个目录）")
        info(f"目录：{WB_ROOT}（{size[1] / 1048576:.0f} MB）——几秒后自己消失")
    else:
        head("卸载完成（目录保留）")
        info(f"要彻底删掉，直接删除这个目录：{WB_ROOT}")
        info("或者重跑：wb.py uninstall --apply --purge")
    info(f"快捷方式处理：{removed} 个，其余未指向本根的不动")
    return 0


def cmd_shortcuts() -> int:
    head("重建快捷方式（指向当前根）")
    ok(f"根目录 {WB_ROOT}")
    make_shortcuts(force=True)
    desk = Path(os.environ.get("USERPROFILE", r"C:\Users\Administrator")) / "Desktop"
    for name in ("DSH 工作台.lnk", "DSH 工作台 安装器.lnk"):
        p = desk / name
        (ok if p.exists() else warn)(f"桌面 {name}：{'存在' if p.exists() else '没生成'}")
    return 0


def make_shortcuts(force: bool = False) -> None:
    """桌面「仅打开页面」+ 启动项「自动伴随」两个快捷方式（幂等，重复执行无副作用）。

    force=True 时忽略 DSH_WB_NO_SHORTCUTS（给 `wb.py shortcuts` 修复死链用）。
    """
    if os.environ.get("DSH_WB_NO_SHORTCUTS") and not force:
        # 演练/CI/客户机批量部署时用：别去动用户桌面与开机启动项
        info("跳过快捷方式（DSH_WB_NO_SHORTCUTS=1）")
        return
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


# ── 主流程：install（装 / 修 / 升级，幂等）───────────────────────────────────
# 顺序（改之前先理解为什么是这个顺序）：
#   ① 建目录 → ② **preflight 门禁**（不兼容直接中止，一个字节运行时都不复制；
#      degraded 先打印降级项再继续）→ ③ sync-app 复制主驾运行时到 app\（不碰主驾）
#   ④ ensure_profile（渲染 seeds，生成 bench profile）→ ⑤ sync_credentials（拷 API 凭据，
#      否则页面会要求填 key）→ ⑥ pnpm plugin install → ⑦ 逐个核对 node_modules 里
#      dsh-wb-* 的 package.json 是否真的可读（缺了就再装一次）
#   ⑧ 起服务（端口被占会自动避让）→ ⑨ resume 自动伴随 → ⑩ **等 /wb-ui 就绪**：
#      不就绪就自动 restart-safe 一次（实测"服务先起、插件后解析"会让三个插件全被跳过），
#      仍失败才报错并指向 startup-*.log。
# 坑：① 不要把启动放在 pnpm 之前；② 别指望"端口在听"就算成功——要验注入层。
# ── 安装锁：防止"同时点两次安装" ──────────────────────────────────────────────
# 场景：客户双击两次 install.cmd（或两个窗口同时跑 setup）。首次安装会复制 1.6GB + 跑 pnpm +
# 抢端口，两个进程同时来就可能把 profile 装坏、起两个守护。
# 锁文件写 state\setup.lock（pid + 时间）；进程退出时自动删；pid 已死视为残留锁，自动清掉。
SETUP_LOCK = STATE_DIR / "setup.lock"


def _acquire_setup_lock() -> bool:
    try:
        if SETUP_LOCK.exists():
            parts = SETUP_LOCK.read_text(encoding="utf-8", errors="replace").split()
            pid = int(parts[0]) if parts and parts[0].isdigit() else 0
            at = parts[1] if len(parts) > 1 else "?"
            if pid and pid != os.getpid() and pid_alive(pid):
                bad(f"另一个安装正在进行（pid={pid}，开始于 {at}）——等它跑完再点，别同时点两次")
                return False
            warn("清理上次残留的安装锁（进程已退出）")
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SETUP_LOCK.write_text(f"{os.getpid()} {time.strftime('%H:%M:%S')}", encoding="utf-8")
        return True
    except Exception:
        return True   # 拿不到锁也别挡住安装本身


def _release_setup_lock() -> None:
    try:
        if SETUP_LOCK.exists():
            first = SETUP_LOCK.read_text(encoding="utf-8", errors="replace").split()
            if first and first[0].isdigit() and int(first[0]) == os.getpid():
                SETUP_LOCK.unlink()
    except Exception:
        pass


def cmd_install(force: bool = False) -> int:
    """自主安装 / 修复 / 升级：幂等，可以反复跑。"""
    head("工作台安装器")
    ok(f"根目录 {WB_ROOT}")
    if not _acquire_setup_lock():
        return 1
    atexit.register(_release_setup_lock)


    for name in ("app", "home", "plugins", "ui", "state", "logs", "seeds", "docs", "backups", "tools"):
        (WB_ROOT / name).mkdir(parents=True, exist_ok=True)
    ok("目录结构就绪")

    # 门禁：目标 harness 版本如果不满足要求，装了也是白页 → 先拦下来（--force 可越过）
    if not force:
        verdict = _preflight_verdict(str(MAIN_INSTALL))
        if verdict["grade"] == "incompatible":
            bad("目标 harness 不兼容，安装中止：")
            for b in verdict["blockers"]:
                bad(f"  · {b}")
            bad("确要试装请加 --force")
            return 1
        if verdict["grade"] == "degraded":
            warn(f"目标 harness {verdict['version']} 能跑但有降级：")
            for d in verdict["degradations"]:
                warn(f"  · {d}")
            info("（继续安装；这些功能在该版本上会缺失）")

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

    # 装完必须确认插件真能解析：链接没就位时，服务会"起得来但插件全被跳过"
    missing = [n for n in ("dsh-wb-api-browser", "dsh-wb-sessions", "dsh-wb-ui")
               if not (WB_HOME / "profiles" / WB_PROFILE / "node_modules" / n / "package.json").exists()]
    if missing:
        warn(f"插件链接还没就位：{missing}，再跑一次 pnpm install")
        subprocess.run(
            ["cmd", "/c", str(APP_DSH_CMD), "plugin", "--profile", WB_PROFILE, "install"],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=900, creationflags=RUNFLAGS,
        )
        missing = [n for n in missing if not (WB_HOME / "profiles" / WB_PROFILE / "node_modules" / n / "package.json").exists()]
        (ok if not missing else bad)(f"插件链接：{'全部就位' if not missing else '仍缺 ' + str(missing)}")

    make_shortcuts()

    if not listening_pids(WB_PORT):
        cmd_start(True)
    else:
        ok(f"工作台已在运行（{WB_PORT}）")
    if not find_supervisors():
        cmd_resume()
    else:
        ok("自动伴随已在运行")

    # 首次启动有时序问题（服务先起来、插件后解析）：这里自愈一次并明确报告
    if not wait_ui_ready(25):
        warn("注入层没就绪（/wb-ui 不应答）——自动重启一次")
        cmd_restart_safe()
        if wait_ui_ready(25):
            ok("重启后注入层已就绪")
        else:
            bad("注入层仍未就绪：检查 home\\profiles\\bench\\node_modules 与 home\\logs\\startup-*.log")
            return 1
    else:
        ok("注入层已就绪（/wb-ui 应 respawn）")

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

    info("按名调用已打通：插件在 package.json 的 dsh.workbench.capabilities 里声明能力 →")
    info("  工作台 /wb-api/capabilities 汇总 → 主驾桥 /wb-bridge/capabilities 与 /wb-bridge/call → 工具 workbench_call。")
    info("  校验声明对不对：node tools\\test-capabilities.mjs（route 必须落在本插件 PREFIX 下）。")
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
BACKUP_STATE_FILES = ["plugin-notes.json", "ui-config.json"]
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


# ── 备份：整包快照（zip），并逐文件回读校验 sha256 ──────────────────────────────
# 收：tools / plugins / seeds / docs / ui + config.json + bench profile 清单
#     + BACKUP_STATE_FILES（plugin-notes.json / ui-config.json）
# 不收：app（1.65GB 运行时副本，随时可 sync-app 重建）、home（工作台自己的 DSH_HOME）、
#       logs、以及 .credentials.yaml（敏感，绝不进 zip）。
# 顺序纪律：**先做干净基线，再搞破坏，再 restore**——反过来会把坏状态存进快照。
# 快照比代码旧时 restore 会把代码一起回滚：修完代码要重做基线，旧快照是陷阱。
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


def cmd_backups(as_json: bool = False) -> int:
    head("已有快照")
    if not BACKUP_ROOT.exists():
        warn("还没有快照：wb.py backup")
        return 0
    items = sorted(BACKUP_ROOT.glob("snapshot-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not items:
        warn("还没有快照")
        return 0
    rows = []
    for p in items:
        note = ""
        try:
            with zipfile.ZipFile(p) as zf:
                note = json.loads(zf.read("MANIFEST.json").decode("utf-8")).get("note", "")
        except Exception:
            pass
        rows.append({
            "name": p.name,
            "bytes": p.stat().st_size,
            "kb": round(p.stat().st_size / 1024, 1),
            "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)),
            "mtime": int(p.stat().st_mtime),
            "note": note,
        })
    if as_json:
        # 给界面用的机器可读出口（别让 GUI 去解析上面那些人类可读的行）
        print(json.dumps({"ok": True, "items": rows, "dir": str(BACKUP_ROOT)}, ensure_ascii=False))
        return 0
    for r in rows:
        info(f"{r['name']}  {r['kb']} KB  {r['time']}  {r['note']}")
    write_backup_readme()
    return 0


# ── 还原：用快照覆盖 tools/plugins/seeds/docs/ui + profile 清单 ─────────────────
# 不动 app\（运行时）与 home\ 里的数据；还原前会把当前文件另存到 backups\before-restore-<ts>\。
# 还原完会顺带跑一次 install（所以它会重启工作台、刷新 token——页面要重新打开）。
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


def render_seed(text: str) -> str:
    """种子里的 ${WB_ROOT} / ${WB_HOME} 换成当前机器的真实路径（分发版靠这个保持可移植）。"""
    return (text
            .replace("${WB_ROOT}", WB_ROOT.resolve().as_posix())
            .replace("${WB_HOME}", WB_HOME.resolve().as_posix()))


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
                    try:
                        text = f.read_text(encoding="utf-8-sig")
                    except Exception:
                        (pkg.parent / f.name).write_bytes(f.read_bytes())
                        continue
                    (pkg.parent / f.name).write_text(render_seed(text), encoding="utf-8")
            ok(f"已套用种子：{seed_dir}（${{WB_ROOT}} 已渲染成本机路径）")
    if not pkg.exists():
        bad(f"profile 创建失败：{pkg}")
        return 1
    patch = prof_dir / "cordis.patch.yml"
    patch.write_text(BENCH_PATCH, encoding="utf-8")
    ok(f"profile {WB_PROFILE} 就绪：{prof_dir}")
    return 0


# ── 启动 / 停止 ─────────────────────────────────────────────────────────
def is_our_workbench(port: int) -> bool:
    """端口上那个进程是不是**我们这一份**工作台：比 /wb-ui 报的 uiDir 是否等于自己的 ui 目录。"""
    try:
        data = http_json(f"http://127.0.0.1:{port}/wb-ui", timeout=2.0)
        ui_dir = str(data.get("uiDir") or "")
        if not data.get("ok") or not ui_dir:
            return False
        return Path(ui_dir).resolve() == (WB_ROOT / "ui").resolve()
    except Exception:
        return False


# ── 启动：把 app\ 那份运行时用 bench profile 起成服务 ─────────────────────────
# 要点：
# ① 端口：WB_PORT 被占就 pick_port 往上找，并 save_port 写回 config.json（客户机上 59430 常被占）。
# ② 参数顺序是坑：启动器选项（--profile / --patch）必须排在 app 参数（--port / --no-open）**前面**，
#    否则会报 `unknown option '--patch'`，表现为"端口 120 秒起不来"。
# ③ 看门狗：WMI 起（父进程 WmiPrvSE，脱离主程序 Job），盯主驾**当次**监听 pid；
#    主驾重启 → 工作台被关闭 → 由 supervisor 重新拉起（这是"主驾关则关"的实现）。
#    测试床不想被牵连就传 with_watchdog=False。
# ④ 起了之后别只看端口：注入层（/wb-ui）是否就绪才是"能用"的判据。
def cmd_start(with_watchdog: bool = True, extra_args: list[str] | None = None) -> int:
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
        if is_our_workbench(WB_PORT):
            warn(f"已经在跑（端口 {WB_PORT}，pid={pids_existing}）")
            return 0
        new_port = pick_port(WB_PORT + 1)
        if new_port == WB_PORT:
            bad(f"端口 {WB_PORT} 被别的程序占着，且找不到可用端口")
            return 1
        warn(f"端口 {WB_PORT} 被别的程序占了，改用 {new_port}（已写进 config.json）")
        save_port(new_port)

    if ensure_profile() != 0:
        return 1
    sync_credentials()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, DSH_HOME=str(WB_HOME), DSH_PROFILE=WB_PROFILE)
    out_log = LOG_DIR / "workbench.out.log"
    err_log = LOG_DIR / "workbench.err.log"
    with open(out_log, "ab") as fo, open(err_log, "ab") as fe:
        # ⚠️ 顺序要紧：启动器选项（--profile/--patch）必须在 app 参数（--port/--no-open）之前，
        #    否则 `--patch` 会被当成 app 参数报 "unknown option '--patch'"。
        serve = subprocess.Popen(
            ["cmd", "/c", str(APP_DSH_CMD), "--profile", WB_PROFILE, *(extra_args or []),
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
    pnpm = pnpm_mjs()
    (ok if pnpm else warn)(
        f"pnpm       {pnpm}" if pnpm else "pnpm       没找到（只在装插件时用到：确认 harness 自带或已 sync-app）")
    (ok if GIT_EXE.exists() else warn)(f"git         {GIT_EXE}")
    try:
        pipv = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True,
                              timeout=25, creationflags=RUNFLAGS, encoding="utf-8", errors="replace").stdout.strip()
    except Exception:
        pipv = ""
    (ok if pipv else warn)(f"pip         {pipv or '不可用'}")
    java = shutil.which("java") or ""
    (ok if java else warn)(f"java        {java or '未安装（可选，只有少数工具链需要）'}")

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
    counts = memory_counts(memory_db())
    if "error" in counts:
        bad(counts["error"])
    else:
        ok("可只读访问：" + " / ".join(f"{k}={v}" for k, v in counts.items()))

    head("工作台")
    (ok if APP_EXE.exists() else warn)(f"独立安装    {APP_EXE if APP_EXE.exists() else '未同步（wb.py sync-app）'}")
    (ok if (WB_HOME / 'profiles' / WB_PROFILE / 'package.json').exists() else warn)(f"profile     {WB_HOME / 'profiles' / WB_PROFILE}")
    pids = listening_pids(WB_PORT)
    if pids and is_our_workbench(WB_PORT):
        ok(f"端口 {WB_PORT} 在听 pid={pids}")
    elif pids:
        warn(f"端口 {WB_PORT} 被别的程序占着（不是这一份工作台）——wb.py start 会自动换端口")
    else:
        warn(f"端口 {WB_PORT} 空闲")
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
    counts = memory_counts(memory_db())
    info("记忆        " + ("无法读取: " + counts["error"] if "error" in counts
                          else " / ".join(f"{k}={v}" for k, v in counts.items())))

    head("工作台")
    pids = listening_pids(WB_PORT)
    if pids and is_our_workbench(WB_PORT):
        ok(f"端口 {WB_PORT} 在听 (pid={','.join(map(str, pids))})")
    elif pids:
        warn(f"端口 {WB_PORT} 被别的程序占着（不是这一份工作台）——wb.py start 会自动换端口")
    else:
        warn(f"端口 {WB_PORT} 没在听（wb.py start）")
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
        "memory": memory_counts(memory_db()),
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
    ap.add_argument("--keep-nav", dest="keep_nav", default="")
    ap.add_argument("--no-restart", dest="no_restart", action="store_true")
    ap.add_argument("--target-home", dest="target_home", default="")
    ap.add_argument("--target-profile", dest="target_profile", default="desktop")
    ap.add_argument("--apply", dest="apply", action="store_true")
    ap.add_argument("--no-install", dest="no_install", action="store_true")
    ap.add_argument("--out", dest="out", default="")
    ap.add_argument("--include-test", dest="include_test", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--refresh", dest="force", action="store_true")
    ap.add_argument("--zip", dest="zip_out", action="store_true")
    # uninstall 专用
    ap.add_argument("--purge", dest="purge", action="store_true")
    ap.add_argument("--detach", dest="detach_bridge", action="store_true")
    # setup 专用开关
    ap.add_argument("--no-attach", dest="no_attach", action="store_true")
    ap.add_argument("--open", dest="open_page", action="store_true")
    ap.add_argument("-y", "--yes", dest="yes", action="store_true")
    ap.add_argument("-n", type=int, default=40)
    ap.add_argument("--limit", dest="n", type=int)
    args = ap.parse_args(argv[1:])

    # 除 watchdog 外，所有命令先确定路径（自动识别 + config.json 缓存）
    if args.command not in ("watchdog",):
        try:
            load_paths(redetect=args.redetect, install=args.install or None, home=args.home or None)
        except Exception as exc:  # noqa: BLE001
            warn(f"路径识别失败，用默认值：{exc}")
        try:
            load_port()  # 端口同理：config.json 优先，其次环境变量，最后 59430
        except Exception as exc:  # noqa: BLE001
            warn(f"端口读取失败，用默认值 {WB_PORT_DEFAULT}：{exc}")

    table = {
        "doctor": lambda: cmd_doctor(),
        "status": lambda: cmd_status(),
        "watch": lambda: cmd_watch(),
        "api": lambda: cmd_api(),
        "compat": lambda: cmd_compat(),
        "plugins": lambda: cmd_plugins(args.sub or "list", (args.rest[0] if args.rest else ""), args.bundle),
        "install-plugin": lambda: cmd_install_plugin(
            (args.rest[0] if args.rest else (args.sub or args.spec or "")), args.keep_nav, args.no_restart),
        "plugin-info": lambda: cmd_plugin_info(
            (args.rest[0] if args.rest else (args.sub or args.spec or ""))),
        "uninstall-plugin": lambda: cmd_uninstall_plugin(
            (args.rest[0] if args.rest else (args.sub or args.spec or "")), args.no_restart),
        "fix-ui": lambda: cmd_fix_ui(),
        "attach": lambda: cmd_attach(args.target_home, args.target_profile, args.apply, args.no_install),
        "detach": lambda: cmd_detach(args.target_home, args.target_profile, args.apply, args.no_install),
        "pack": lambda: cmd_pack(args.out or "", args.include_test, args.force, args.zip_out),
        "prepublish": lambda: cmd_prepublish(),
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
        "backups": lambda: cmd_backups(args.as_json),
        "restore": lambda: cmd_restore(args.from_archive),
        "rollback": lambda: cmd_rollback(),
        "sync-app": lambda: cmd_sync_app(args.force),
        "start": lambda: cmd_start(args.with_watchdog),
        "stop": lambda: cmd_stop(),
        "restart": lambda: cmd_restart(args.with_watchdog),
        "restart-safe": lambda: cmd_restart_safe(),
        "start-safe": lambda: cmd_start_safe(),
        "registry": lambda: cmd_registry(args.force),
        "preflight": lambda: cmd_preflight(args.install or "", args.as_json),
        "setup": lambda: cmd_setup(args.no_attach, args.open_page, args.yes),
        "sync-bed": lambda: cmd_sync_bed(args.out or (args.rest[0] if args.rest else (args.sub or ""))),
        "plugin-search": lambda: cmd_plugin_search(
            (args.rest[0] if args.rest else (args.sub or "")), args.n),
        "plugin-update": lambda: cmd_plugin_update(
            (args.rest[0] if args.rest else (args.sub or "")), args.apply),
        "logs": lambda: cmd_logs(args.n),
        "shortcuts": lambda: cmd_shortcuts(),
        "uninstall": lambda: cmd_uninstall(args.purge, args.detach_bridge, args.apply),
        "watchdog": lambda: cmd_watchdog([int(x) for x in args.main_pids.split(",") if x.strip()]),
    }
    if args.command not in table:
        print(__doc__)
        return 2
    return table[args.command]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
