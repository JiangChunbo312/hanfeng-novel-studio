# -*- coding: utf-8 -*-
"""验证 BatchRunner 状态机（打桩 full_chapter / accept_chapter，不真调 LLM）。

用法: python tests/_check_batch.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents import batch as batch_mod   # noqa: E402
from agents import pipeline             # noqa: E402

calls = {"n": 0}


def fake_full(book_id, chapter, cfg, auto_revise, do_apply, do_summary):
    calls["n"] += 1
    return {"passed": True, "score": 88, "elapsed": 1.2,
            "text": "第%d章正文..." % chapter}


def fake_fail(book_id, chapter, cfg, auto_revise, do_apply, do_summary):
    raise RuntimeError("模拟LLM故障")


def wait_done(runner, timeout=6):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if runner.snapshot()["status"] in ("done", "stopped", "stalled"):
            return runner.snapshot()
        time.sleep(0.05)
    return runner.snapshot()


ok = True

# T1: 全成功 + 自动采纳
pipeline.full_chapter = fake_full
pipeline.accept_chapter = lambda b, c, t, x: {"ok": True}
r1 = batch_mod.BatchRunner("B", 1, 3, {}, auto_accept=True)
r1.start_run()
s1 = wait_done(r1)
print("T1 status=%s results=%d" % (s1["status"], len(s1["results"])))
assert s1["status"] == "done" and len(s1["results"]) == 3
assert all(x["ok"] and x["accepted"] for x in s1["results"]), "T1 未全部采纳"
assert [x["chapter"] for x in s1["results"]] == [1, 2, 3], "T1 章节序错"
print("T1 PASS")

# T2: 连续失败熔断（第3次失败即停）
pipeline.full_chapter = fake_fail
r2 = batch_mod.BatchRunner("B", 1, 10, {}, max_fail_streak=3)
r2.start_run()
s2 = wait_done(r2)
print("T2 status=%s results=%d" % (s2["status"], len(s2["results"])))
assert s2["status"] == "stopped" and len(s2["results"]) == 3, "T2 熔断位置错"
assert all(not x["ok"] for x in s2["results"])
print("T2 PASS")

# T3: 手动停止（用慢桩，确保 stop 发生在跑章途中）
def fake_slow(book_id, chapter, cfg, auto_revise, do_apply, do_summary):
    time.sleep(1.0)
    return {"passed": True, "score": 70, "elapsed": 1.0,
            "text": "第%d章正文..." % chapter}


pipeline.full_chapter = fake_slow
r3 = batch_mod.BatchRunner("B", 1, 10, {})
r3.start_run()
time.sleep(0.3)
r3.stop()
s3 = wait_done(r3)
print("T3 status=%s results=%d" % (s3["status"], len(s3["results"])))
assert s3["status"] == "stopped", "T3 应停止而非跑完"
print("T3 PASS")

# T4: count=0 直接完成（HTTP 冒烟用）
r4 = batch_mod.BatchRunner("B", 1, 0, {})
r4.start_run()
s4 = wait_done(r4)
print("T4 status=%s results=%d" % (s4["status"], len(s4["results"])))
assert s4["status"] == "done" and not s4["results"]
print("T4 PASS")

print("ALL_BATCH_TESTS_PASS")
