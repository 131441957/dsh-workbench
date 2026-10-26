#!/usr/bin/env python3
"""wb_gui.py — 工作台安装器（可视化）

用户自己点的安装/修复/启停工具，不隐藏任何动作：
  · 安装 / 修复        → 跑 wb.py install（幂等）
  · 同步运行时(重装)    → wb.py install --force（旧运行时改名备份，可回滚）
  · 回滚运行时          → wb.py rollback
  · 启动 / 停止 / 打开页面 / 暂停守护 / 恢复守护
  · 看日志

只用标准库（tkinter），不需要额外安装依赖。启动时不要控制台窗口：
  用 pythonw.exe 运行本文件，或点桌面「DSH 工作台 安装器」。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

WB_ROOT = Path(r"E:\DSH-WORKBENCH")
WB_PY = WB_ROOT / "tools" / "wb.py"
NODE_EXE = Path(r"E:\nodejs\node.exe")


def python_console() -> str:
    """返回能捕获输出的 python.exe（本程序可能由 pythonw 启动）。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


def run_wb(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        [python_console(), str(WB_PY), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=0x08000000,
    )


def probe_status() -> dict:
    """用 wb.py 的能力做一次只读探测。"""
    out = {}
    try:
        proc = subprocess.run([python_console(), str(WB_PY), "status"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60, creationflags=0x08000000)
        out["text"] = proc.stdout or ""
    except Exception as exc:  # noqa: BLE001
        out["text"] = f"探测失败：{exc}"
    return out


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title("DSH 工作台 安装器")
        root.geometry("820x560")
        root.minsize(720, 460)

        top = ttk.Frame(root, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        self.version_label = ttk.Label(top, text="状态读取中…", font=("Segoe UI", 10, "bold"))
        self.version_label.pack(anchor="w")
        self.detail_label = ttk.Label(top, text="", foreground="#555")
        self.detail_label.pack(anchor="w", pady=(2, 0))
        self.paths_label = ttk.Label(top, text="路径探测中…", foreground="#3a6", font=("Consolas", 9))
        self.paths_label.pack(anchor="w", pady=(2, 0))

        btns = ttk.Frame(root, padding=(12, 6))
        btns.pack(fill="x")
        specs = [
            ("安装 / 修复", ["install"]),
            ("同步运行时（复制主驾安装）", ["install", "--force"]),
            ("回滚运行时", ["rollback"]),
            ("启动工作台", ["start"]),
            ("停止工作台", ["stop"]),
            ("打开页面", ["page"]),
            ("暂停自动伴随", ["suspend"]),
            ("恢复自动伴随", ["resume"]),
            ("重新探测路径", ["paths", "--redetect"]),
        ]
        for col, (label, args) in enumerate(specs):
            b = ttk.Button(btns, text=label, command=lambda a=args, l=label: self.run_action(l, a))
            b.grid(row=col // 5, column=col % 5, sticky="ew", padx=3, pady=3)
        for c in range(5):
            btns.columnconfigure(c, weight=1)

        self.log = scrolledtext.ScrolledText(root, height=18, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=12, pady=(4, 8))
        self.log.insert("end", "点上面的按钮开始。安装/重装会调用 wb.py，不会偷偷复制任何东西。\n")

        self.root.after(100, self.pump)
        self.refresh_status()

    # ── 日志 / 动作 ────────────────────────────────────────────────
    def write(self, text: str) -> None:
        self.log.insert("end", text if text.endswith("\n") else text + "\n")
        self.log.see("end")

    def pump(self) -> None:
        try:
            while True:
                self.write(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self.pump)

    def run_action(self, label: str, args: list[str]) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在忙", "上一个操作还没结束，等它跑完。")
            return
        if args == ["install", "--force"]:
            if not messagebox.askyesno(
                "确认同步运行时",
                "这一步只会把【主驾当前的安装】复制到：\n\n"
                "    E:\\DSH-WORKBENCH\\app\n\n"
                "旧的那份会改名备份到 backups\\（可「回滚运行时」秒回）。\n\n"
                "**不会重装、不会修改主驾，也不碰 E:\\SSS。**\n\n继续吗？",
            ):
                self.write("已取消同步运行时。")
                return
        self.write(f"\n===== {label}  ({time.strftime('%H:%M:%S')}) =====")
        self.worker = threading.Thread(target=self._run, args=(args,), daemon=True)
        self.worker.start()

    def _run(self, args: list[str]) -> None:
        try:
            proc = run_wb(args)
            assert proc.stdout is not None
            for line in proc.stdout:
                self.log_queue.put(line.rstrip("\n"))
            proc.wait()
            self.log_queue.put(f"—— 退出码 {proc.returncode} ——")
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"执行失败：{exc}")
        finally:
            self.root.after(300, self.refresh_status)

    def refresh_status(self) -> None:
        def work() -> None:
            try:
                proc = subprocess.run([python_console(), str(WB_PY), "info"], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=90, creationflags=0x08000000)
                lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
                data = json.loads(lines[-1]) if lines else {"error": "info 没有输出 JSON"}
            except Exception as exc:  # noqa: BLE001
                data = {"error": f"读取状态失败：{exc}"}
            self.root.after(0, lambda: self._apply(data))
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, d: dict) -> None:
        if d.get("error"):
            self.version_label.config(text="状态读取失败")
            self.detail_label.config(text=d["error"])
            self.paths_label.config(text="")
            return
        m = d.get("main", {})
        w = d.get("workbench", {})
        mv = m.get("version", "?")
        wv = w.get("version", "?")
        same = mv == wv
        self.version_label.config(
            text=f"主驾 harness {mv}   ·   工作台 {wv}" + ("" if same else "   ⚠️ 版本不一致，建议「同步运行时」"))
        port = "在听" if w.get("listening") else "未启动"
        wd = "运行中" if w.get("watchdog") else "未运行"
        sup = "运行中" if w.get("supervisors") else "未运行"
        mports = ",".join(str(p) for p in (m.get("ports") or [])) or "未检测到"
        self.detail_label.config(text=f"59430：{port}   看门狗：{wd}   自动伴随：{sup}   主驾端口：{mports}")
        self.paths_label.config(
            text=f"主驾安装：{m.get('install', '?')}（{m.get('installSource', '?')}）   "
                 f"数据：{m.get('home', '?')}（{m.get('homeSource', '?')}）")


def selftest() -> int:
    """--selftest：建窗口 400ms 后自己关，用来验证不崩。"""
    root = tk.Tk()
    App(root)
    root.after(400, root.destroy)
    root.mainloop()
    print("gui selftest ok")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
