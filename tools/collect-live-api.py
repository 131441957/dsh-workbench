#!/usr/bin/env python3
"""collect-live-api.py — 把 cordis_inspect 的原始输出整理成接口基线。

用法（由 wb.py api 或人工调用）：
    python collect-live-api.py service.json slots.json [--out state/api-live.json]

输入：cordis_inspect_query 的返回体（含 data 字段的 JSON 文本，允许带前后缀文本）。
输出：state/api-live.json，包含
    version   取自 app 的 runtime.json（desktopVersion）
    services  [{key, description, methodCount}]
    slots     [{name, kind, scope, purpose, replaceRisk, taken}]
    counts    汇总
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WB_ROOT = Path(r"E:\DSH-WORKBENCH")
APP_ROOT = WB_ROOT / "app"
OUT_DEFAULT = WB_ROOT / "state" / "api-live.json"


def load_json(path: Path) -> dict:
    """从可能带前缀/后缀的文本里抠出第一个完整 JSON 对象。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find("{")
    if start < 0:
        raise SystemExit(f"没找到 JSON：{path}")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise SystemExit(f"JSON 不完整：{path}")


def app_version() -> str:
    rt = APP_ROOT / r"resources\runtime\primary-runtime\runtime.json"
    try:
        return json.loads(rt.read_text(encoding="utf-8")).get("desktopVersion", "unknown")
    except Exception:
        return "unknown"


def walk_slots(node: dict, out: list[dict]) -> None:
    if node.get("type") == "slot":
        key_domain = node.get("keyDomain", "")
        taken = []
        if isinstance(key_domain, str) and "already taken:" in key_domain:
            tail = key_domain.split("already taken:", 1)[1]
            taken = [x.strip() for x in tail.split(",") if x.strip()]
        out.append({
            "name": node.get("name", ""),
            "kind": node.get("kind", ""),
            "scope": node.get("scope", ""),
            "purpose": (node.get("purpose") or "").strip(),
            "replaceRisk": node.get("replaceRisk", ""),
            "registration": [r.get("name") for r in node.get("registration", []) or []],
            "taken": taken[:40],
        })
    for child in node.get("children", []) or []:
        walk_slots(child, out)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    svc_path = Path(argv[1])
    slots_path = Path(argv[2])
    out = Path(argv[4]) if len(argv) > 4 and argv[3] == "--out" else OUT_DEFAULT

    svc_doc = load_json(svc_path).get("data", {})
    slots_doc = load_json(slots_path).get("data", {})

    services = [
        {"key": s.get("key", ""), "description": (s.get("description") or "").strip(),
         "methodCount": len(s.get("methods") or [])}
        for s in svc_doc.get("services", []) or []
    ]

    slots: list[dict] = []
    for tree in slots_doc.get("trees", []) or []:
        walk_slots(tree, slots)

    payload = {
        "version": app_version(),
        "source": "cordis_inspect_query (host Service / client Slots)",
        "counts": {"services": len(services), "slots": len(slots)},
        "services": services,
        "slots": slots,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"services={len(services)}  slots={len(slots)}  →  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
