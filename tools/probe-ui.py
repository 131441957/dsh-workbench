"""在指定工作台实例上加载一次页面，读回 boot-diag 的关键字段（不截屏、不碰用户窗口）。

用法：python tools/probe-ui.py --root <工作台根> [--port 59430]
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
