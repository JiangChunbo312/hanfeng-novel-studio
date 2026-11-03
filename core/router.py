# -*- coding: utf-8 -*-
"""
角色 → 模型路由。

省钱的要害在这里：写手用创意强的大模型，审计 / 摘要 / 事实抽取用便宜的快模型。
路由值格式 "providerId:modelId"，留空则回落 default；default 也空则取第一个可用服务商。
"""
from typing import Tuple

from .config import provider_map
from .provider import Provider

ROLES = ["planner", "composer", "writer", "observer", "auditor", "reviser", "summary"]

ROLE_LABELS = {
    "planner": "规划师 · 本章意图",
    "composer": "编排师 · 上下文组装",
    "writer": "写手 · 正文",
    "observer": "观察者 · 事实抽取",
    "auditor": "审计员 · 一致性检查",
    "reviser": "修订者 · 定点改写",
    "summary": "摘要 · 章节梗概",
}


class RouteError(Exception):
    pass


def resolve_all(cfg: dict, role: str) -> list:
    """返回候选链 [(Provider, 模型名, 单价), ...]。

    路由值可写多个候选，用英文逗号分隔，例如：
        "volc:kimi-k3-1-pro-261024,volc:deepseek-v4-1-flash-economy-261017"
    前面的优先；调用超时 / 报错时按顺序切换到下一个（故障转移）。
    留空则回落 default；default 也空则取第一个可用服务商。
    """
    pmap = provider_map(cfg)
    if not pmap:
        raise RouteError("还没有配置任何模型服务商，请先到「模型配置」添加一个。")

    def split(v: str):
        if not v or ":" not in v:
            return None, None
        pid, _, mid = v.partition(":")
        return pid.strip(), mid.strip()

    target = (cfg.get("routes", {}).get(role) or "").strip()
    if not target:
        target = (cfg.get("routes", {}).get("default") or "").strip()
    tokens = [t.strip() for t in target.split(",") if t.strip()]
    if not tokens:
        tokens = [""]

    cands = []
    for t in tokens:
        pid, mid = split(t)
        if not pid or pid not in pmap:
            pid = next(iter(pmap))
            mid = ""
        spec = pmap[pid]
        model = mid or spec.get("model") or ""
        if not model:
            continue                       # 没填模型名，跳过该候选
        if not (spec.get("base_url") or "").strip():
            continue                       # 没填 Base URL，跳过
        price = cfg.get("prices", {}).get("%s:%s" % (pid, model), {}) or {}
        cands.append((Provider(spec), model, price))
    if not cands:
        raise RouteError("没有可用的模型候选（检查服务商 Base URL / 模型名）。")
    # 故障转移只轮换「可用」模型：跳过一键测试中明确标记为不可用的（bad），
    # 未测试（untested）的仍保留，避免把没测过的模型也排除掉而断流。
    status = cfg.get("model_status") or {}
    avail = [c for c in cands if status.get("%s:%s" % (c[0].id, c[1])) != "bad"]
    if avail:
        cands = avail
    return cands


def resolve(cfg: dict, role: str) -> Tuple[Provider, str, dict]:
    """返回首选 (Provider 实例, 模型名, 该模型单价)。"""
    return resolve_all(cfg, role)[0]


def describe(cfg: dict) -> list:
    """给界面用：每个角色当前落到哪个模型。"""
    out = []
    for r in ROLES:
        try:
            p, m, price = resolve(cfg, r)
            out.append({
                "role": r, "label": ROLE_LABELS.get(r, r),
                "provider": p.label, "model": m,
                "ok": True, "price": price,
            })
        except Exception as e:
            out.append({
                "role": r, "label": ROLE_LABELS.get(r, r),
                "provider": "-", "model": str(e), "ok": False, "price": {},
            })
    return out
