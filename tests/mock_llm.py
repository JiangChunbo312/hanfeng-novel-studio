# -*- coding: utf-8 -*-
"""
假的 OpenAI 兼容服务，只用于冒烟测试。不联网、不花钱。

    python tests/mock_llm.py --port 8899
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STREAM_DELAY = 0.002   # 每个流式分片之间的停顿（秒），可用 --stream-delay 调大以捕捉“运行中”状态

PLAN = """【本章功能】开场立住主角处境，埋下第一枚伏笔
【核心冲突】主角想活下去 vs 追兵不肯放过
【场景清单】
- 破庙 · 主角、老卒 · 老卒递来半块干粮
- 庙外土路 · 主角、三名骑手 · 骑手远远掠过，没进庙
【必须发生】1. 主角醒来 2. 发现身上多了块木牌 3. 老卒说出追兵来历
【必须规避】1. 不要写大段回忆 2. 不要提前揭示木牌来历
【承接要求】从上一章的逃亡疲惫切入，语气压低
【钩子设计】木牌上的字在火光下变了颜色，老卒脸色骤变
【伏笔动作】埋：木牌变色（预期第8章回收）"""

BODY = """睁开眼的时候，天还没亮。

破庙的屋顶塌了半边，风从缺口灌进来，吹得供桌上的香灰打转。寒峰动了动手指，指缝里全是泥，左腿从膝盖往下没有知觉，压着的是自己的包袱。

他没敢动。

庙门外有马蹄声，三匹，由远及近，又由近及远。蹄声停在庙外十步的地方，骑手说了句什么，风把后半句吹散了。等了约莫半炷香，马蹄声才重新响起，往北去了。

寒峰这才把压着的腿抽出来，疼得眼前发白。

"醒了？"

角落里坐着个老卒，甲片掉了大半，正用一块破布擦他的刀。刀刃豁了三个口子，擦得却仔细。老卒从怀里摸出半块干粮，掰下指甲盖大的一块，剩下的递过来。

"吃。吃完往南走，别走官道。"

寒峰接过干粮，手在抖。他这才发觉自己怀里多了一样东西——一块巴掌大的木牌，边缘磨得圆润，正面刻着一个他认不出的字。木牌怎么会到自己怀里，他一点都想不起来。

"这牌子哪来的？"

老卒擦刀的手停了。

"你不知道？"老卒把刀举到眼前，对着从屋顶缺口漏下来的那点光看了很久，"那你还活着，倒是命大。"

寒峰把木牌翻过来。背面是空的，什么都没有。

供桌底下还留着半截蜡烛，是先前逃难的人留下的。老卒把它点着了，火苗蹿起来的一瞬间，木牌正面那个字被映得发红——不是漆，那颜色是从木头里渗出来的，像浸了血。

老卒的脸色一下子变了。

他把手里的半块干粮扔在地上，站起来就往门外走，走到门槛又停住，回头看了寒峰一眼。那一眼里的东西，寒峰很久以后才想明白。

"往南走。"老卒说，"别跟任何人提这块牌子。" """

DELTA = {
    "characters": {
        "寒峰": {"位置": "破庙", "持有": "木牌", "状态": "左腿受伤，疲惫"},
        "老卒": {"位置": "破庙", "持有": "豁口刀", "态度": "警惕，催促主角南下"},
    },
    "relations": [{"a": "老卒", "b": "寒峰", "type": "临时同盟", "change": "给干粮、示警"}],
    "items": {"木牌": {"delta": "+1", "reason": "主角怀中凭空出现，来源不明"},
              "半块干粮": {"delta": "-1", "reason": "被主角吃掉"}},
    "time_advance": "天未亮→拂晓",
    "facts": ["追兵共三人，骑马，往北去", "木牌遇火光会渗出红色"],
    "new_hooks": [{"text": "木牌上的字遇火变红，老卒认得", "due_chapter": 8}],
    "resolved_hooks": [],
    "emotions": [{"character": "老卒", "turn": "从平静到惊惧"}],
}

AUDIT = {
    "score": 72,
    "issues": [
        {"id": "A12", "level": "critical",
         "desc": "字数不足目标字数的 70%", "evidence": "正文仅约 700 字",
         "fix": "补足场景描写与对话，扩写到目标字数"},
        {"id": "A9", "level": "major", "desc": "中段节奏偏平，缺少信息爆点",
         "evidence": "他把手里的半块干粮扔在地上", "fix": "在老卒脸色变化处补一句真相暗示"},
        {"id": "A11", "level": "minor", "desc": "有一处情绪直陈",
         "evidence": "他一点都想不起来", "fix": "改成动作描写"},
    ],
    "summary": "结构完整、伏笔到位，但篇幅不足、中段缺爆点。",
}

SUMMARY = """【发生了什么】主角在破庙醒来，躲过三名骑手，遇老卒，发现怀中多了一块木牌。
【人物动向】寒峰：受伤、南下；老卒：示警后离开。
【物品/资源变动】木牌 +1（来源不明）；半块干粮 -1。
【新埋伏笔】木牌遇火渗出红色，老卒认得（预期第 8 章）。
【时间推进】天未亮 → 拂晓。"""

REVISED = BODY + """

寒峰低头再看那块木牌时，火光已经灭了。红色褪得干干净净，木头还是那块木头，仿佛刚才的一切都没发生过。他把它塞回怀里，贴着胸口的那面是凉的。

庙外，老卒的脚步声已经听不见了。地上那块没吃完的干粮还在，寒峰捡起来，吹了吹灰，塞进包袱。"""


def pick_role(prompt: str) -> str:
    if "【规划师】" in prompt:
        return "planner"
    if "【写手】" in prompt:
        return "writer"
    if "【观察者】" in prompt:
        return "observer"
    if "【审计员】" in prompt:
        return "auditor"
    if "【修订者】" in prompt:
        return "reviser"
    if "【摘要员】" in prompt:
        return "summary"
    return "chat"


def content_for(role: str) -> str:
    return {"planner": PLAN, "writer": BODY, "observer": json.dumps(DELTA, ensure_ascii=False),
            "auditor": json.dumps(AUDIT, ensure_ascii=False), "reviser": REVISED,
            "summary": SUMMARY}.get(role, "收到。")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._json({"object": "list", "data": [
                {"id": "mock-1"}, {"id": "mock-2"}, {"id": "mock-cheap"}]})
        self._json({"ok": True})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "ignore") if n else "{}"
        try:
            req = json.loads(raw)
        except Exception:
            req = {}
        prompt = ""
        for m in (req.get("messages") or []):
            prompt += (m.get("content") or "")
        role = pick_role(prompt)
        text = content_for(role)
        model = req.get("model", "mock-1")
        usage = {"prompt_tokens": max(1, len(prompt) // 2), "completion_tokens": len(text) // 2,
                 "total_tokens": max(1, len(prompt) // 2) + len(text) // 2}

        if req.get("stream"):
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            for i in range(0, len(text), 24):
                piece = text[i:i + 24]
                chunk = {"choices": [{"delta": {"content": piece}}], "model": model}
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                time.sleep(STREAM_DELAY)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self._json({"id": "chatcmpl-mock", "object": "chat.completion", "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                 "finish_reason": "stop"}],
                    "usage": usage})


def main():
    global STREAM_DELAY
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--stream-delay", type=float, default=0.002,
                    help="每个流式分片停顿秒数，调大可放慢响应便于观察运行中状态")
    args = ap.parse_args()
    STREAM_DELAY = args.stream_delay
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), H)
    print("mock llm on http://127.0.0.1:%d/v1 (stream_delay=%.3fs)" % (args.port, STREAM_DELAY))
    srv.serve_forever()


if __name__ == "__main__":
    main()
