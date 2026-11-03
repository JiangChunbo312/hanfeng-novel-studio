# -*- coding: utf-8 -*-
"""
用量与成本台账。每次模型调用追加一行 JSONL 到项目下的 usage.jsonl。

没有成本面板的长篇工具，跑一周就会给你惊喜账单。
"""
import json
import os
import time
from typing import Dict


def _path(book_dir: str) -> str:
    return os.path.join(book_dir, "usage.jsonl")


def record(book_dir: str, role: str, provider: str, model: str, usage: dict,
           price: dict, chapter: int = 0) -> dict:
    pin = float(price.get("in", 0) or 0)
    pout = float(price.get("out", 0) or 0)
    tin = int(usage.get("prompt_tokens", 0) or 0)
    tout = int(usage.get("completion_tokens", 0) or 0)
    cost = (tin / 1_000_000 * pin) + (tout / 1_000_000 * pout)
    row = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chapter": chapter,
        "role": role,
        "provider": provider,
        "model": model,
        "prompt_tokens": tin,
        "completion_tokens": tout,
        "total_tokens": int(usage.get("total_tokens", 0) or (tin + tout)),
        "estimated": bool(usage.get("estimated")),
        "cost": round(cost, 4),
    }
    try:
        with open(_path(book_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return row


def summary(book_dir: str) -> dict:
    """按角色 / 模型 / 章节聚合。"""
    rows = []
    p = _path(book_dir)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass

    def agg(keyfn) -> Dict[str, dict]:
        out = {}
        for r in rows:
            k = keyfn(r)
            d = out.setdefault(k, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                   "total_tokens": 0, "cost": 0.0})
            d["calls"] += 1
            d["prompt_tokens"] += r.get("prompt_tokens", 0)
            d["completion_tokens"] += r.get("completion_tokens", 0)
            d["total_tokens"] += r.get("total_tokens", 0)
            d["cost"] = round(d["cost"] + r.get("cost", 0), 4)
        return out

    total_cost = round(sum(r.get("cost", 0) for r in rows), 4)
    total_tokens = sum(r.get("total_tokens", 0) for r in rows)
    estimated = sum(1 for r in rows if r.get("estimated"))
    return {
        "calls": len(rows),
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "estimated_calls": estimated,
        "by_role": agg(lambda r: r.get("role", "-")),
        "by_model": agg(lambda r: "%s · %s" % (r.get("provider", "-"), r.get("model", "-"))),
        "by_chapter": agg(lambda r: "第%s章" % r.get("chapter", 0) if r.get("chapter") else "未归属"),
        "recent": rows[-30:],
    }
