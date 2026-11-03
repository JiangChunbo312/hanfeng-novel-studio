"""复现：审计后观察者（observer 角色）调用为何失败。只发一次 LLM 请求，不改任何状态文件。"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "agents"))

from agents import pipeline  # noqa: E402
from agents.base import load_config  # noqa: E402

book = "恋综编剧她只想搞钱"
cfg = load_config()
text = open(os.path.join(ROOT, "projects", book, "drafts", "ch001.draft.md"), encoding="utf-8").read()
ctx = {
    "chapter": 1,
    "chapter_text": text,
    "current_state": pipeline.store.markdown_projection(book),
}
print("=== 观察者角色实际路由 ===")
from core.router import describe  # noqa: E402
print(describe(cfg))
print()
print("=== 直接调 observer 角色（不发状态变更）===")
try:
    raw, meta = pipeline.base.run("observer", "observer", ctx,
                                  os.path.join(ROOT, "projects", book), 1, cfg=cfg)
    print("RUN OK  raw=%d 字" % len(raw))
    print("head:", raw[:260].replace("\n", " "))
except Exception as e:
    print("RUN EXC  %s: %s" % (type(e).__name__, str(e)[:600]))
    traceback.print_exc()
