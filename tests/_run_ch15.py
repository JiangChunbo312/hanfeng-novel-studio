# -*- coding: utf-8 -*-
"""跑第15章完整流程并逐步打印进度，用于检查不通的环节。"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents import pipeline

bid = "恋综编剧她只想搞钱"
CH = 15

def progress(step, status, detail=None):
    d = detail or {}
    extra = ""
    if d.get("words"):
        extra = " words=%d" % d["words"]
    if d.get("score") is not None:
        extra += " score=%s" % d["score"]
    if d.get("passed") is not None:
        extra += " passed=%s" % d["passed"]
    if d.get("remaining") is not None:
        extra += " remaining=%d" % d["remaining"]
    if d.get("round"):
        extra += " round=%d" % d["round"]
    if d.get("error"):
        extra += " ERROR=%s" % d["error"][:120]
    print("[%s] %-8s %s%s" % (time.strftime("%H:%M:%S"), step, status, extra), flush=True)

t0 = time.time()
print("=== 开始 ch%d 全流程 %s ===" % (CH, time.strftime("%H:%M:%S")), flush=True)
r = pipeline.full_chapter(bid, CH, auto_revise=1, do_apply=True, do_summary=True,
                          progress=progress, reuse_plan=True)
dt = time.time() - t0
print("\n=== 完成，总耗时 %.1fs ===" % dt, flush=True)
print("passed:", r["passed"], "| score:", r["score"], "| words:", r.get("words"), flush=True)
print("title:", repr(r.get("title")), flush=True)
print("observe:", json.dumps(r.get("observe"), ensure_ascii=False), flush=True)
print("summary(len):", len(r.get("summary") or ""), flush=True)
print("\n--- 各步骤 log ---", flush=True)
for e in r.get("log", []):
    print(" ", json.dumps(e, ensure_ascii=False)[:200], flush=True)
# 存结果供后续检查
with open("tests/_ch15_result.json", "w", encoding="utf-8") as f:
    json.dump({"elapsed": dt, "passed": r["passed"], "score": r["score"],
               "title": r.get("title"), "observe": r.get("observe"),
               "log": r.get("log"), "summary_len": len(r.get("summary") or "")},
              f, ensure_ascii=False, indent=2)
print("\n结果已存 tests/_ch15_result.json", flush=True)
