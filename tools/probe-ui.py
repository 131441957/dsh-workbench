"""在指定工作台实例上加载一次页面，读回 boot-diag 的关键字段。

为什么用它而不是截屏：截屏要抓窗口、会碰到用户正在用的屏幕，而且看不出"CSS 到底命中没有"。
这里改用**独立 user-data-dir 的 Edge** 打开一次页面（不抢用户的标签/窗口，跑完按自己启动的
pid 关掉），页面里注入的 workbench.js 会自己把诊断写到 state\\boot-diag.json，本脚本再读出来。

用法：
    python tools/probe-ui.py --root .                  # 当前这一套
    python tools/probe-ui.py --root E:\\WB-<版本>       # 测试床

关键字段（换 harness 版本后先看这两个）：
    shellClasses.cssFrameApplied → "flex" 才算布局 CSS 命中（"grid" = 选择器没匹配上）
    sidebarVisibleRows           → 必须是 0（原版侧栏没藏干净就会 >0）

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

edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
if not edge.exists():
    edge = Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
ud = Path(os.environ.get("TEMP") or ".") / f"_wb_probe_{ROOT.name}"
if ud.exists():
    import shutil
    shutil.rmtree(ud, ignore_errors=True)

proc = subprocess.Popen([str(edge), f"--user-data-dir={ud}", "--no-first-run", "--new-window", url])
deadline = time.time() + 25
data = None
while time.time() < deadline:
    time.sleep(1.0)
    if diag.exists():
        try:
            data = json.loads(diag.read_text(encoding="utf-8"))
            break
        except Exception:
            pass
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
