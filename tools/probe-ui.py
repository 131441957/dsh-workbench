"""在指定工作台实例上加载一次页面，读回 boot-diag 的关键字段。

为什么用它而不是截屏：截屏要抓窗口、会碰到用户正在用的屏幕，而且看不出"CSS 到底命中没有"。
这里改用**独立 user-data-dir 的 Edge** 打开一次页面（不抢用户的标签/窗口，跑完按自己启动的
pid 关掉），页面里注入的 workbench.js 会自己把诊断写到 state\\boot-diag.json，本脚本再读出来。

用法：
    python tools/probe-ui.py --root .                  # 当前这一套
    python tools/probe-ui.py --root E:\\WB-<版本>       # 测试床
    python tools/probe-ui.py --root . --wait-field settingsProbe   # 等静默探测跑完再读
                                                                  # （第一份诊断 4.6 秒就写，
                                                                  #   探测结果在 5~7 秒才落盘）

关键字段（换 harness 版本后先看这两个）：
    shellClasses.cssFrameApplied → "flex" 才算布局 CSS 命中（"grid" = 选择器没匹配上）
    sidebarVisibleRows           → 必须是 0（原版侧栏没藏干净就会 >0）

设置相关字段：
    settingsProbe → {ran, opened, attempts, titles, sections, ms}：页面有没有静默扫过设置分区
    settingsOpen  → 扫完必须回到 false（还开着就说明弹层没被关掉）
    closeDebug    → 关弹层用的是什么（clicked=点了 × / escaped=按了 Esc 兜底）

坑：
 ① 入口 URL 的 token 是**一次性**的：拿旧 URL 再开一次会得到 "dsh web authentication required"，
    所以每次都用 wb.current_url() 现取（它从日志尾部读最新那条）。
 ② 别用 `msedge --headless --dump-dom` 验这套 SPA：页面保持长连接、load 事件不结束，会挂住。
 ③ 只关自己启动的进程，绝不用 GetForegroundWindow() 去猜窗口（那会打到用户正在看的窗口）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--keep-open", action="store_true")
ap.add_argument("--query", default="", help="附在入口 URL 后的 hash 参数，例如 wb-selftest=settings")
ap.add_argument("--wait-field", default="",
                help="等到 boot-diag 里出现这个顶层字段再读（例如 settingsProbe：静默探测要 5~7 秒才写完，"
                     "默认的第一份 4.6 秒诊断里没有它）")
ap.add_argument("--timeout", type=float, default=25.0, help="最长等多久（秒），默认 25")
args = ap.parse_args()

ROOT = Path(args.root)
sys.path.insert(0, str(ROOT / "tools"))
os.environ["DSH_WORKBENCH_ROOT"] = str(ROOT)
import wb  # noqa: E402

diag = ROOT / "state" / "boot-diag.json"
try:
    diag.unlink()
except Exception:
    pass
if diag.exists():
    diag.unlink()

url = wb.current_url()
if not url:
    print("拿不到入口 URL（实例没起？）")
    sys.exit(1)
if args.query:
    # token 会重定向到 /，但 hash 会保留 —— 所以调试开关一律走 hash
    url = url.split("#")[0] + "#" + args.query

edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
if not edge.exists():
    edge = Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
# Edge 需要一个独立的 user-data-dir（避免抢用户正在用的 Edge 实例）。
# 优先用 TEMP；TEMP 写不了（受限沙箱）就退到工作台自己的 state 目录。
ud = Path(os.environ.get("TEMP") or ".") / f"_wb_probe_{ROOT.name}"
try:
    ud.parent.mkdir(parents=True, exist_ok=True)
    (ud / "probe.ok").write_text("1", encoding="utf-8")
    (ud / "probe.ok").unlink()
except Exception:
    ud = ROOT / "state" / f"_probe_edge_{ROOT.name}"
    ud.parent.mkdir(parents=True, exist_ok=True)
if ud.exists():
    import shutil
    shutil.rmtree(ud, ignore_errors=True)

proc = subprocess.Popen([str(edge), f"--user-data-dir={ud}", "--no-first-run", "--new-window", url])
deadline = time.time() + max(5.0, args.timeout)
data = None
while time.time() < deadline:
    time.sleep(1.0)
    if diag.exists():
        try:
            data = json.loads(diag.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 页面会写多份诊断（4.6 秒一份、静默探测后一份）。要等某个字段就继续轮询，
        # 否则拿到的永远是最早那份（踩过：settingsProbe 永远读不到）。
        # 注意判**真假**而不是"键在不在"：那份早期诊断里字段存在但值是 null。
        if args.wait_field and not data.get(args.wait_field):
            data = None
            continue
        break
if not args.keep_open:
    proc.terminate()

if not data:
    print("没有 boot-diag（页面没加载成功）")
    sys.exit(1)

print("root          :", ROOT)
print("at            :", data.get("at"))
print("hasPanel      :", data.get("hasPanel"), "| errors:", len(data.get("errors") or []))
print("topbarTabs    :", " / ".join(data.get("topbarTabs") or []))
print("discovered    :", " / ".join(data.get("discovered") or []))
print("sidebarRows   :", data.get("sidebarVisibleRows"))
print("shellClasses  :", json.dumps(data.get("shellClasses") or {}, ensure_ascii=False))
# 设置相关：确认"静默探测"到底跑没跑、跑完有没有把设置关掉
print("settingsOpen  :", data.get("settingsOpen"), "| sidebarKept:", data.get("sidebarKept"))
if data.get("settingsProbe") is not None:
    print("settingsProbe :", json.dumps(data.get("settingsProbe"), ensure_ascii=False)[:400])
if data.get("closeDebug") is not None:
    print("closeDebug    :", json.dumps(data.get("closeDebug"), ensure_ascii=False)[:200])
