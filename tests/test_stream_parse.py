# -*- coding: utf-8 -*-
"""流式解析健壮性单测：收尾包 choices 为空数组时不得越界。"""
import json
import sys

sys.path.insert(0, ".")
from core.provider import Provider  # noqa: E402


def fake_resp(lines):
    class R:
        def __init__(self, ls):
            self._ls = ls

        def __iter__(self):
            return iter(self._ls)

        def close(self):
            pass

    return R(lines)


def sse(obj):
    return ("data: " + json.dumps(obj, ensure_ascii=False)).encode("utf-8") + b"\n"


p = Provider({"id": "t", "base_url": "x", "timeout": 5})


def run_stream(lines):
    p._post = lambda *a, **k: fake_resp(lines)
    return list(p.stream([{"role": "user", "content": "hi"}], model="m",
                         temperature=1, max_tokens=100))


# 场景1：正文包 + 只带 usage、choices 为空的收尾包（原 bug：list index out of range）
lines1 = [
    sse({"choices": [{"delta": {"content": "你好"}}]}),
    sse({"choices": [{"delta": {"content": "世界"}}]}),
    sse({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}),
    b"data: [DONE]\n",
]
got = run_stream(lines1)
text = "".join(x.get("text", "") for x in got if x.get("kind") == "content")
usage = [x for x in got if x.get("kind") == "usage"]
assert text == "你好世界", repr(text)
assert usage and usage[0]["usage"]["completion_tokens"] == 2, usage
print("场景1 OK：空 choices 收尾包不越界，正文=%r 真实usage=%s" % (text, usage[0]["usage"]))

# 场景2：usage 与 choices 同包（另一家厂商风格）
lines2 = [
    sse({"choices": [{"delta": {"content": "甲"}, "finish_reason": None}],
         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
    b"data: [DONE]\n",
]
got = run_stream(lines2)
text = "".join(x.get("text", "") for x in got if x.get("kind") == "content")
usage = [x for x in got if x.get("kind") == "usage"]
assert text == "甲" and usage, (text, got)
print("场景2 OK：同包 usage 正常解析，正文=%r" % text)

# 场景3：思考包与正文包正确分流
lines3 = [
    sse({"choices": [{"delta": {"reasoning_content": "想一下"}}]}),
    sse({"choices": [{"delta": {"content": "乙"}}]}),
    b"data: [DONE]\n",
]
got = run_stream(lines3)
assert [x["kind"] for x in got] == ["think", "content"], got
print("场景3 OK：思考包分流为 think，正文为 content")

# 场景4：非流式 chat() 遇到空 choices 不再抛异常


class Resp2:
    def read(self):
        return json.dumps({"choices": [], "usage": {"prompt_tokens": 1,
                                                     "completion_tokens": 0,
                                                     "total_tokens": 1}}).encode("utf-8")


p._post = lambda *a, **k: Resp2()
text, u = p.chat([{"role": "user", "content": "hi"}], model="m")
assert text == "" and u["estimated"] is False, (text, u)
print("场景4 OK：非流式空 choices 返回空文本而非异常")

print()
print("全部 4 个场景通过 —— list index out of range 已修复")
