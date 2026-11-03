# -*- coding: utf-8 -*-
"""
统一模型适配层。

设计原则：只认 OpenAI 兼容协议 /chat/completions，不引任何第三方 SDK。
所有厂商（DeepSeek / Kimi / 智谱 / 通义 / 豆包 / Gemini 兼容层 / OpenRouter /
Ollama / LM Studio / 各种中转站）都通过填 Base URL 接入。
"""
import json
import math
import re
import time
import urllib.error
import urllib.request
from typing import Dict, Iterator, List, Optional, Tuple

# 常见服务商预设。Base URL 以各家官方文档为准，可随时在界面里改。
PRESETS: Dict[str, dict] = {
    "deepseek":   {"label": "DeepSeek",       "base_url": "https://api.deepseek.com/v1",                    "model": "deepseek-chat"},
    "openai":     {"label": "OpenAI",         "base_url": "https://api.openai.com/v1",                      "model": "gpt-4o-mini"},
    "moonshot":   {"label": "Kimi(月之暗面)", "base_url": "https://api.moonshot.cn/v1",                     "model": "moonshot-v1-32k"},
    "zhipu":      {"label": "智谱 GLM",       "base_url": "https://open.bigmodel.cn/api/paas/v4",           "model": "glm-4.6"},
    "dashscope":  {"label": "通义千问",       "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "volcengine": {"label": "火山豆包",       "base_url": "https://ark.cn-beijing.volces.com/api/v3",       "model": "doubao-seed-1-6-250615"},
    "siliconflow":{"label": "硅基流动",       "base_url": "https://api.siliconflow.cn/v1",                   "model": "Qwen/Qwen2.5-72B-Instruct"},
    "openrouter": {"label": "OpenRouter",     "base_url": "https://openrouter.ai/api/v1",                    "model": "deepseek/deepseek-chat"},
    "ollama":     {"label": "Ollama(本地)",   "base_url": "http://127.0.0.1:11434/v1",                       "model": "qwen2.5:14b"},
    "lmstudio":   {"label": "LM Studio(本地)","base_url": "http://127.0.0.1:1234/v1",                        "model": "local-model"},
    "custom":     {"label": "自定义 / 中转站","base_url": "",                                                 "model": ""},
}


class LLMError(Exception):
    """模型调用失败。message 里带可直接展示的原因。"""
    pass


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def estimate_tokens(text: str) -> int:
    """无 usage 返回时的粗略估算：中文约 1 字 0.75 token，英文约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    rest = len(text) - cjk
    return int(math.ceil(cjk * 0.75 + rest / 4))


class Provider:
    """一个服务商连接（Base URL + Key），可承载多个模型。"""

    def __init__(self, spec: dict):
        # spec: {id, label, base_url, api_key, model, timeout}
        self.id = spec.get("id") or spec.get("label") or "custom"
        self.label = spec.get("label") or self.id
        self.base_url = (spec.get("base_url") or "").strip()
        self.api_key = (spec.get("api_key") or "").strip()
        self.default_model = (spec.get("model") or "").strip()
        self.timeout = int(spec.get("timeout") or 180)
        # 自定义认证头：部分厂商（如 Dots 用 api-key）不走 Authorization: Bearer。
        # 指定 auth_header 后，Key 放进该请求头；不指定则默认 Bearer。
        self.auth_header = (spec.get("auth_header") or "").strip()
        # 附加请求体字段（如 Dots 关闭深度思考 chat_template_kwargs.enable_thinking）。
        self.body_extra = dict(spec.get("body_extra") or {})
        # 自定义额外请求头（直接合并，覆盖默认）
        self.extra_headers = dict(spec.get("headers") or {})

    # ---------- 底层 ----------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            if self.auth_header:
                h[self.auth_header] = self.api_key
            else:
                h["Authorization"] = "Bearer " + self.api_key
        h.update(self.extra_headers)
        return h

    def _post(self, path: str, payload: dict, stream: bool = False, timeout: int = 0, retries: int = 2):
        if not self.base_url:
            raise LLMError("未配置 Base URL")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            _join_url(self.base_url, path),
            data=data,
            headers=self._headers(),
            method="POST",
        )
        last_err = None
        for attempt in range(retries + 1):
            try:
                return urllib.request.urlopen(req, timeout=timeout or self.timeout)
            except urllib.error.HTTPError as e:
                # 5xx 网关错误 / 429 限流 / 502 上游抖动 —— 属临时故障，退避后重试
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    last_err = e
                    time.sleep(1.5 * (attempt + 1))
                    continue
                # 401 认证失败 / 404 模型不存在 / 400 参数错误 —— 重试无意义
                body = ""
                try:
                    body = e.read().decode("utf-8", "ignore")[:500]
                except Exception:
                    pass
                raise LLMError("HTTP %s %s %s" % (e.code, e.reason, body))
            except (urllib.error.URLError, ConnectionResetError, BrokenPipeError,
                    ConnectionAbortedError, TimeoutError) as e:
                # 远端强制断开 / 连接重置 / 超时 —— 退避后重试，可自愈
                last_err = e
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                reason = getattr(e, "reason", None) or e
                raise LLMError("连接失败：%s（检查 Base URL / 网络 / 代理；已重试 %d 次）" % (reason, retries))
            except Exception as e:  # noqa
                raise LLMError("请求异常：%s" % e)
        raise LLMError("请求异常：%s" % last_err)

    # ---------- 能力 ----------
    def list_models(self) -> Tuple[bool, List[str] or str]:
        """拉取模型列表。部分中转站不支持，失败不影响使用。"""
        try:
            req = urllib.request.Request(_join_url(self.base_url, "/models"), headers=self._headers())
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = json.loads(r.read().decode("utf-8", "ignore"))
            items = raw.get("data", raw if isinstance(raw, list) else [])
            ids = []
            for it in items:
                mid = it.get("id") if isinstance(it, dict) else str(it)
                if mid:
                    ids.append(mid)
            return True, sorted(set(ids))
        except Exception as e:
            return False, str(e)

    def test(self) -> Tuple[bool, str]:
        """连接测试：发一条极短对话。"""
        try:
            text, usage = self.chat(
                [{"role": "user", "content": "回复两个字：正常"}],
                max_tokens=128, temperature=0.1, timeout=30,
            )
            return True, "连通 · 模型回复：%s" % (text.strip()[:20] or "(空)")
        except Exception as e:
            return False, str(e)

    # ---------- 对话 ----------
    def chat(self, messages: List[dict], model: str = "", temperature: float = 0.7,
             max_tokens: int = 0, stream: bool = False, timeout: int = 0
             ) -> Tuple[str, dict]:
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
        }
        if self.body_extra:
            payload.update(self.body_extra)
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
            return self._chat_stream(payload, timeout or self.timeout)
        resp = self._post("/chat/completions", payload, timeout=timeout or self.timeout)
        raw = resp.read().decode("utf-8", "ignore")
        try:
            data = json.loads(raw)
        except Exception:
            raise LLMError("返回不是合法 JSON：%s" % raw[:300])
        if "error" in data and isinstance(data["error"], dict):
            raise LLMError(data["error"].get("message", str(data["error"])))
        try:
            choices = data.get("choices") or [{}]
            text = (choices[0].get("message") or {}).get("content") or ""
            finish = (choices[0] or {}).get("finish_reason", "")
        except Exception:
            raise LLMError("返回结构异常：%s" % raw[:300])
        usage = data.get("usage") or {}
        return text, {
            "model": data.get("model", payload["model"]),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "finish_reason": finish,
            "estimated": not usage,
        }

    def stream(self, messages: List[dict], model: str = "", temperature: float = 0.7,
               max_tokens: int = 0, timeout: int = 0) -> Iterator[dict]:
        """流式输出：yield {"kind":"think"|"content","text":...}。

        推理模型（Kimi/DeepSeek 思考型）会把思考过程放在 delta.reasoning_content，
        最终答案在 delta.content。两者都回传，前端可把 think 显示为「思考中」提示。
        """
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            # 让服务商在最后一个 chunk 里回传真实 usage（不支持的会忽略）
            "stream_options": {"include_usage": True},
        }
        if self.body_extra:
            payload.update(self.body_extra)
        if max_tokens:
            payload["max_tokens"] = max_tokens
        resp = self._post("/chat/completions", payload, stream=True, timeout=timeout or self.timeout)
        usage_seen = None
        try:
            for line in resp:
                line = line.decode("utf-8", "ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                if chunk.get("usage"):
                    usage_seen = {
                        "prompt_tokens": chunk["usage"].get("prompt_tokens", 0),
                        "completion_tokens": chunk["usage"].get("completion_tokens", 0),
                        "total_tokens": chunk["usage"].get("total_tokens", 0),
                    }
                # 收尾包可能只带 usage 而 choices 是空列表（开启 include_usage 时常见），
                # 必须跳过，否则 [0] 越界抛 list index out of range
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0] or {}).get("delta", {}) or {}
                if delta.get("reasoning_content"):
                    yield {"kind": "think", "text": delta["reasoning_content"]}
                piece = delta.get("content")
                if piece:
                    yield {"kind": "content", "text": piece}
        finally:
            try:
                resp.close()
            except Exception:
                pass
        if usage_seen:
            yield {"kind": "usage", "usage": usage_seen}

    def _chat_stream(self, payload: dict, timeout: int) -> Tuple[str, dict]:
        buf = []
        usage_seen = None
        for piece in self.stream(payload["messages"], payload.get("model"),
                                 payload.get("temperature", 0.7),
                                 payload.get("max_tokens", 0), timeout):
            if not isinstance(piece, dict):
                buf.append(piece)
                continue
            kind = piece.get("kind")
            if kind == "think":
                continue
            if kind == "usage":
                usage_seen = piece["usage"]
                continue
            buf.append(piece.get("text", ""))
        text = "".join(buf)
        if usage_seen:
            u = dict(usage_seen)
            u["model"] = payload.get("model")
            u["estimated"] = False
            return text, u
        return text, {
            "model": payload.get("model"),
            "prompt_tokens": estimate_tokens("".join(m.get("content", "") for m in payload["messages"])),
            "completion_tokens": estimate_tokens(text),
            "total_tokens": 0,
            "estimated": True,
        }


def build_provider(spec: dict) -> Provider:
    return Provider(spec)
