# -*- coding: utf-8 -*-
"""
Agent 基座：提示词外置、模型路由、成本记账。

改提示词不用改代码——所有 prompt 都在 prompts/*.md。
"""
import json
import os
import re
from typing import Iterator, Tuple

from core import cost as cost_mod
from core import router
from core.config import load as load_config

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")

TEMPERATURE = {
    "planner": 0.75,
    "composer": 0.3,
    "writer": 0.85,
    "observer": 0.2,
    "auditor": 0.25,
    "reviser": 0.5,
    "summary": 0.3,
}

# 每个角色的默认 max_tokens。
# 推理模型（Kimi/DeepSeek 思考型）会把预算先花在 reasoning_content 上，
# 不显式给足 token，正文 content 会被截断成空 → 抽取 JSON 失败。故统一留足。
# 审计 12 维检查容易长输出，实测 DeepSeek-V4.1 撞满 16384 被截断，提到 32768。
MAX_TOKENS = {
    "planner": 16384,
    "composer": 16384,
    "writer": 32768,
    "observer": 24576,
    "auditor": 32768,
    "reviser": 24576,
    "summary": 16384,
}

# 推理模型（思考型）要求 temperature 固定为 1，传其它值会被服务商拒绝（HTTP 400）。
# 命中这些关键字的模型一律强制 temp=1，避免写稿时整条流水线 400 失败。
_REASONING_HINTS = ("r1", "reasoning", "thinking", "kimi-k3", "deepseek-v4",
                    "k2-thinking", "-k2-thinking", "qwq", "o1", "glm-z1",
                    "spark-x2", "sensenova")


def is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return any(k in m for k in _REASONING_HINTS)


def effective_temp(role: str, model: str, temperature=None) -> float:
    if is_reasoning_model(model):
        return 1.0
    return temperature if temperature is not None else TEMPERATURE.get(role, 0.7)


def load_prompt(name: str) -> str:
    path = os.path.join(PROMPTS_DIR, name + ".md")
    if not os.path.exists(path):
        raise FileNotFoundError("缺少提示词文件：prompts/%s.md" % name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def render(template: str, variables: dict) -> str:
    out = template
    for k, v in variables.items():
        out = out.replace("{{%s}}" % k, "" if v is None else str(v))
    # 未替换的占位符清掉，避免把 {{xxx}} 喂给模型
    out = re.sub(r"\{\{[^{}]+\}\}", "", out)
    return out


def extract_json(text: str) -> dict:
    """从模型输出里抠出 JSON，容忍代码块和前后废话。

    输出被 max_tokens 截断时（finish_reason=length），尝试按括号栈自动补全
    未闭合的 { } [ ] 和悬挂的字符串，把残缺 JSON 修复成可解析的完整对象。
    """
    if not text:
        return {}
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", t)
    if m:
        t = m.group(1).strip()
    s = t.find("{")
    e = t.rfind("}")
    if s >= 0 and e > s:
        t = t[s:e + 1]
    try:
        return json.loads(t)
    except Exception:
        pass
    # 截断修复：从第一个 { 开始按括号栈补全
    return _repair_truncated_json(t[s:] if s >= 0 else t)


def _repair_truncated_json(t: str) -> dict:
    """按括号栈补全被截断的 JSON；失败返回空 dict。"""
    if not t or "{" not in t:
        return {}
    stack = []       # 未闭合的括号栈
    in_str = False   # 是否处于字符串内
    esc = False      # 上一个字符是否为转义符
    last_safe = -1   # 最后一个"结构完整"的位置（不在字符串里、逗号/引号后干净处）
    for i, ch in enumerate(t):
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
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack and ((ch == "}" and stack[-1] == "{") or (ch == "]" and stack[-1] == "[")):
                stack.pop()
            else:
                return {}  # 括号不匹配，无法修复
    # 去掉悬挂的不完整片段：截到最后一个逗号或完整值边界，再补闭合符
    if in_str:
        t = t + '"'  # 字符串被掐断，补引号
    # 掐掉结尾残缺的值（如 "key": {"a": 1, "b": 后面没了）
    t = re.sub(r"[,:\s]+$", "", t)
    if t and t[-1] in ",:":
        t = t[:-1]
    # 若结尾是 "key": 这种悬挂键，补 null
    t = re.sub(r'("[^"]*")\s*$', r'\1: null', t) if re.search(r'"\s*$', t) and not re.search(r'[}\]\dtruefalsn"]\s*$', t) else t
    for ch in reversed(stack):
        t += "}" if ch == "{" else "]"
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else {}
    except Exception:
        # 最后兜底：砍掉最后一个逗号后的残缺元素再试一次
        cut = t.rfind(",")
        if cut > 0:
            u = t[:cut]
            for ch in reversed([c for c in u if c in "{["]):
                pass
            # 重新计算括号差值补全
            opens = []
            in_s = False
            es = False
            for c in u:
                if in_s:
                    if es:
                        es = False
                    elif c == "\\":
                        es = True
                    elif c == '"':
                        in_s = False
                    continue
                if c == '"':
                    in_s = True
                elif c in "{[":
                    opens.append(c)
                elif c in "}]":
                    if opens:
                        opens.pop()
            u = re.sub(r"[,:\s]+$", "", u)
            for c in reversed(opens):
                u += "}" if c == "{" else "]"
            try:
                v = json.loads(u)
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}
        return {}


def run(role: str, prompt_name: str, variables: dict, book_dir: str = "",
        chapter: int = 0, temperature: float = None, max_tokens: int = 0,
        cfg: dict = None, timeout: int = 0) -> Tuple[str, dict]:
    """执行一次角色调用（内部走流式累积，防长连接被网关掐断），返回 (文本, 元信息)。

    支持故障转移：路由值可配多个候选模型（逗号分隔），某候选在 step_timeout 秒内
    无响应或报错，自动切换下一个候选，保证流水线不因单个模型卡死而中断。
    """
    cfg = cfg or load_config()
    cands = router.resolve_all(cfg, role)
    prompt = render(load_prompt(prompt_name), variables)
    mt = max_tokens or MAX_TOKENS.get(role, 4096)
    step_timeout = int(timeout or cfg.get("defaults", {}).get("step_timeout") or 0)

    last_err = None
    for idx, (provider, model, price) in enumerate(cands):
        temp = effective_temp(role, model, temperature)
        try:
            text, usage = _collect(provider, model, temp, mt, prompt,
                                   step_timeout if step_timeout > 0 else 0)
        except Exception as e:
            last_err = e
            if idx < len(cands) - 1:
                continue            # 换下一个候选
            raise last_err          # 已是最后一个候选，抛给上层
        # 空文本校验：推理模型（讯飞 spark-x2.6-4b 等）可能把所有 token 花在
        # reasoning_content 上，正文 content 输出为空。此时应视为失败，触发故障转移，
        # 否则流水线会卡在「第2步正文空」且不轮换到下一个模型。
        if not text.strip():
            last_err = RuntimeError("模型 %s 返回空正文（可能推理模型 token 全被思考链消耗），触发故障转移" % model)
            if idx < len(cands) - 1:
                continue
            raise last_err
        if usage is None:
            from core.provider import estimate_tokens
            usage = {
                "prompt_tokens": estimate_tokens(prompt),
                "completion_tokens": estimate_tokens(text),
                "total_tokens": 0, "estimated": True,
            }
        meta = {"role": role, "provider": provider.label, "model": model,
                "usage": usage, "attempts": idx + 1, "failover": idx > 0}
        if book_dir:
            meta["cost"] = cost_mod.record(book_dir, role, provider.label, model, usage, price, chapter)
        return text, meta
    raise last_err or RuntimeError("没有可用的模型候选")


def _collect(provider, model: str, temperature: float, max_tokens: int,
             prompt: str, timeout: int) -> Tuple[str, dict]:
    """消费一次流式调用直到结束；timeout>0 时按「无响应秒数」设超时。

    采用响应式超时（socket 读超时）：模型在 timeout 秒内一个 token 都不吐，才判超时。
    这样既不会让卡死/排队的模型拖垮流水线，也不会误伤「正在慢慢吐字但正常」的模型。
    """
    text = ""
    usage = None
    for piece in provider.stream(
        [{"role": "user", "content": prompt}],
        model=model, temperature=temperature, max_tokens=max_tokens,
        timeout=timeout,
    ):
        if isinstance(piece, dict):
            if piece.get("kind") == "usage":
                usage = piece["usage"]
            elif piece.get("kind") != "think":
                text += piece.get("text", "")
        else:
            text += piece
    return text, usage


def stream(role: str, prompt_name: str, variables: dict, book_dir: str = "",
           chapter: int = 0, temperature: float = None, max_tokens: int = 0,
           cfg: dict = None) -> Iterator[dict]:
    """流式执行：yield {"type":"delta","text":...} / {"type":"done","text":...,"meta":...}

    支持故障转移：某候选返回空正文或报错时，自动切换到下一个候选。
    """
    cfg = cfg or load_config()
    cands = router.resolve_all(cfg, role)
    prompt = render(load_prompt(prompt_name), variables)
    mt = max_tokens or MAX_TOKENS.get(role, 4096)
    buf = []
    for idx, (provider, model, price) in enumerate(cands):
        temp = effective_temp(role, model, temperature)
        buf.clear()
        try:
            for piece in provider.stream(
                [{"role": "user", "content": prompt}],
                model=model, temperature=temp, max_tokens=mt,
            ):
                if isinstance(piece, dict):
                    if piece.get("kind") == "think":
                        yield {"type": "think", "text": piece.get("text", "")}
                    else:
                        buf.append(piece.get("text", ""))
                        yield {"type": "delta", "text": piece.get("text", "")}
                else:
                    buf.append(piece)
                    yield {"type": "delta", "text": piece}
            text = "".join(buf)
            if text.strip():
                usage = {
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated": True,
                }
                from core.provider import estimate_tokens
                usage["prompt_tokens"] = estimate_tokens(prompt)
                usage["completion_tokens"] = estimate_tokens(text)
                usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
                meta = {"role": role, "provider": provider.label, "model": model, "usage": usage,
                        "attempts": idx + 1, "failover": idx > 0}
                if book_dir:
                    meta["cost"] = cost_mod.record(book_dir, role, provider.label, model, usage, price, chapter)
                yield {"type": "done", "text": text, "meta": meta}
                return
            # 空正文 → 切换下一个候选
            if idx < len(cands) - 1:
                yield {"type": "think", "text": "模型 %s 返回空正文，切换下一个候选…" % model}
                continue
            yield {"type": "error", "text": "所有候选模型均返回空正文"}
            return
        except Exception as e:
            if idx < len(cands) - 1:
                yield {"type": "think", "text": "模型 %s 失败（%s），切换下一个候选…" % (model, str(e)[:100])}
                continue
            yield {"type": "error", "text": str(e)}
            return
    yield {"type": "error", "text": "没有可用的模型候选"}
