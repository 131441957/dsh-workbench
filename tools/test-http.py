"""工作台 HTTP 验收（可重复跑）。

用法：python tools/test-http.py [--root E:\\DSH-WORKBENCH] [--bridge]
默认只测工作台自身接口；--bridge 额外测主驾桥（含无 token 应 401 的反面用例）。
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
# 默认根 = 本文件的上一级目录（不写死路径，换机器/测试床都能跑）
ap.add_argument("--root", default=os.environ.get("DSH_WORKBENCH_ROOT")
                or str(Path(__file__).resolve().parent.parent))
ap.add_argument("--bridge", action="store_true")
args = ap.parse_args()

ROOT = Path(args.root)
sys.path.insert(0, str(ROOT / "tools"))
import wb  # noqa: E402

# ⚠️ 端口必须**现读**：wb.py 的 wb.WB_PORT 是模块常量（默认 59430），不调 load_port()
# 就永远指向主套 —— 2026-10-27 踩过：`--root E:\WB-RC3` 实际打的是 59430，
# 结果"床 11/11 通过"是假的（返回的 uiDir 是主套的）。这里强制解析并打印，
# 后面那条「/wb-ui 认领自己」还会断言 uiDir == 本根的 ui/，双保险。
wb.WB_PORT = wb.load_port()
print(f"目标实例   : {wb.WB_ROOT}  port={wb.WB_PORT}")

results: list[tuple[bool, str, str]] = []
skips: list[tuple[str, str]] = []


class Skip(Exception):
    """这一项在当前环境里没有意义（例如还没接桥的测试床有/没有会话都说明不了问题）。"""


def check(name: str, fn):
    try:
        detail = fn() or ""
        results.append((True, name, str(detail)))
    except Skip as exc:
        skips.append((name, str(exc)))
    except Exception as exc:  # noqa: BLE001
        results.append((False, name, f"{type(exc).__name__}: {exc}"))


def jget(path: str, port: int | None = None):
    port = port or wb.WB_PORT
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30))


# ── 工作台自身 ──────────────────────────────────────────────────
# 「认领自己」不只是打印：uiDir 必须等于**本根**的 ui/，否则说明端口上跑的是另一套工作台
# （多套共存时最容易发生，`--root` 指错/端口读错都会这样）。对不上直接抛，判定为失败。
def claim_self():
    ui = str(jget("/wb-ui").get("uiDir") or "")
    if Path(ui).resolve() != (ROOT / "ui").resolve():
        raise AssertionError(f"端口 {wb.WB_PORT} 上是另一套工作台：uiDir={ui}，本根应为 {ROOT / 'ui'}")
    return "uiDir=" + ui
check("/wb-ui 认领自己", claim_self)
check("/wb-api/health", lambda: f"ok={jget('/wb-api/health').get('ok')}")
check("/wb-api/plugins", lambda: "插件 " + ",".join(p["name"] for p in jget("/wb-api/plugins")["plugins"]))
check("/wb-api/live", lambda: f"服务 {len(jget('/wb-api/live').get('services') or [])} 个")
def build_check():
    # 全新安装还没采过基线时 /wb-api/build 会 503（state\api-build.json 不存在）。
    # 这是预期的首次状态（面板里有「刷新基线」按钮，装完也会自动采一次），判 SKIP 而不是 FAIL。
    port = wb.WB_PORT
    try:
        return f"层 {len(jget('/wb-api/build').get('layers') or [])} 个"
    except urllib.error.HTTPError as exc:
        if exc.code == 503:
            raise Skip("还没采接口基线（state\\api-build.json 不存在）→ 页面「状态 → profile 分层」点「刷新基线」，或跑 wb.py api")
        raise
check("/wb-api/build", build_check)
check("/wb-api/status", lambda: "ok" if jget("/wb-api/status").get("workbench") else "缺 workbench 字段")
check("/wb-api/capabilities", lambda: f"能力 {jget('/wb-api/capabilities').get('count')} 条")
check("/wb-api/notes", lambda: "备注 " + str(len(jget("/wb-api/notes").get("notes") or {})) + " 条")
def first_list(data, *keys):
    for k in keys:
        v = data.get(k)
        if isinstance(v, list):
            return v
    return []


# 会话列表：只有"接入了主驾桥"这一套才有意义。
# 测试床（E:\WB-RC3）本来就没接入任何 harness → 面板如实报"未接入"、会话为空，
# 这时判 SKIP 而不是 FAIL，也不去借别人的 token 假装通过（2026-10-27 用户指出）。
def sessions_check():
    data = jget("/wb-sessions/list")
    if data.get("ok") is False and data.get("reason") == "not-attached":
        raise Skip("未接入主驾桥（本根没有 state\\bridge-token.txt）→ 会话本来就该是空的")
    return f"会话 {len(first_list(data, 'items', 'sessions'))} 条"
check("/wb-sessions/list", sessions_check)
check("/wb-sessions/workspaces", lambda: f"工作区 {len(first_list(jget('/wb-sessions/workspaces'), 'workspaces', 'items'))} 个")


def page_check():
    html = wb.http_get_text(wb.current_url())
    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    title = m.group(1) if m else "?"
    injected = ("wb-ui-css" in html) and ("wb-ui-js" in html)
    mods = [n for n in ("dsh-wb-api-browser", "dsh-wb-sessions") if f"{n}/client.js" in html]
    assert title == "DSH 工作台", f"标题不对：{title}"
    assert injected, "注入层没生效"
    return f"标题={title} 注入=ok 模块={len(mods)}"


check("页面注入/标题", page_check)

# ── 主驾桥（可选） ──────────────────────────────────────────────
if args.bridge:
    probe_ports: list[int] = []
    try:
        probe_ports = [int(p) for p in wb.main_harness_ports()]
    except Exception:
        probe_ports = []
    if not probe_ports:
        try:
            st = json.loads((ROOT / "state" / "main-status.json").read_text(encoding="utf-8-sig"))
            probe_ports = [int(p) for p in ((st.get("mainHarness") or {}).get("ports") or [])]
        except Exception:
            pass
    token = ""
    try:
        token = (ROOT / "state" / "bridge-token.txt").read_text(encoding="ascii").strip()
    except Exception:
        pass
    # 多端口时逐个试，谁能用 token 通就用谁（主驾重启会换端口）
    port = 0
    for cand in probe_ports:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{cand}/wb-bridge/status")
            req.add_header("x-wb-token", token)
            urllib.request.urlopen(req, timeout=8)
            port = cand
            break
        except Exception:
            continue
    if not port and probe_ports:
        port = probe_ports[0]
    if not port:
        results.append((False, "主驾桥", f"找不到可用的主驾端口（候选 {probe_ports}）"))
    elif not token:
        results.append((False, "主驾桥", "找不到 bridge-token.txt（桥没装或没启动过）"))
    else:

        def br(path: str, tok: str | None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
            if tok:
                req.add_header("x-wb-token", tok)
            return urllib.request.urlopen(req, timeout=20)

        check("桥 /wb-bridge/status（带 token）", lambda: "workbench 可达=" + str(json.load(br("/wb-bridge/status", token)).get("workbench", {}).get("reachable")))

        def public_without_token():
            # /status 与 /capabilities 是只读元数据，设计上公开；这里确认它确实不需要 token
            data = json.load(br("/wb-bridge/status", None))
            return "公开可读（设计如此）" if data else "空响应"

        check("桥 /wb-bridge/status（无 token 仍可读）", public_without_token)

        def must_401(path: str):
            try:
                br(path, None)
            except urllib.error.HTTPError as exc:
                assert exc.code == 401, f"应为 401，实际 {exc.code}"
                return "401 ✓"
            raise AssertionError(f"{path} 没带 token 竟然通了")

        def must_401_post(path: str):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         data=json.dumps({"name": "plugins", "params": {}}).encode(),
                                         method="POST")
            req.add_header("content-type", "application/json")
            try:
                urllib.request.urlopen(req, timeout=15)
            except urllib.error.HTTPError as exc:
                assert exc.code == 401, f"应为 401，实际 {exc.code}"
                return "401 ✓"
            raise AssertionError(f"{path} 没带 token 竟然通了")

        # call 是写路由（只收 POST），必须鉴权
        check("桥 /wb-bridge/call（POST 无 token 应 401）", lambda: must_401_post("/wb-bridge/call"))
        check("桥 /wb-bridge/sessions（无 token 应 401）", lambda: must_401("/wb-bridge/sessions"))
        check("桥 /wb-bridge/capabilities", lambda: f"能力 {json.load(br('/wb-bridge/capabilities', token)).get('count')} 条")

        def bridge_call():
            body = json.dumps({"name": "plugins", "params": {}}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/wb-bridge/call", data=body, method="POST")
            req.add_header("x-wb-token", token)
            req.add_header("content-type", "application/json")
            data = json.load(urllib.request.urlopen(req, timeout=30))
            assert data.get("ok"), f"call 失败：{data}"
            return f"plugins 返回 {len((data.get('result') or {}).get('plugins') or [])} 个"

        check("桥 POST /wb-bridge/call(plugins)", bridge_call)

failed = [r for r in results if not r[0]]
for okflag, name, detail in results:
    print(f"  [{'ok' if okflag else 'FAIL'}]  {name}  —— {detail}")
for name, detail in skips:
    print(f"  [skip]  {name}  —— {detail}")
print(f"\n合计 {len(results) + len(skips)} 项，通过 {len(results) - len(failed)}，跳过 {len(skips)}，失败 {len(failed)} 项")
sys.exit(1 if failed else 0)
