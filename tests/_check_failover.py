# -*- coding: utf-8 -*-
"""验证 base.run 的故障转移：首选超时/报错 → 切下一个候选；全失败抛错。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents import base                       # noqa: E402
from core.provider import LLMError            # noqa: E402
from core import router                       # noqa: E402


class FakeProv:
    def __init__(self, label, behavior):
        self.label = label
        self.behavior = behavior

    def stream(self, messages, model="", temperature=0.7, max_tokens=0, timeout=0):
        if self.behavior == "error":
            raise LLMError("模拟失败")
        if self.behavior == "timeout":
            raise TimeoutError("模拟超时")
        yield {"kind": "content", "text": "结果是"}
        yield {"kind": "usage", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


cfg = {"defaults": {"step_timeout": 180}}
_orig_resolve_all = router.resolve_all

# T1: 首选超时 → 切第二个成功
router.resolve_all = lambda c, r: [(FakeProv("A", "timeout"), "mA", {}), (FakeProv("B", "ok"), "mB", {})]
text, meta = base.run("planner", "planner", {}, cfg=cfg)
assert text == "结果是" and meta["provider"] == "B" and meta["failover"] and meta["attempts"] == 2, meta
print("T1 PASS 超时→切换:", meta["provider"])

# T2: 首选报错 → 切第二个
router.resolve_all = lambda c, r: [(FakeProv("A", "error"), "mA", {}), (FakeProv("B", "ok"), "mB", {})]
text, meta = base.run("planner", "planner", {}, cfg=cfg)
assert meta["provider"] == "B" and meta["failover"], meta
print("T2 PASS 报错→切换:", meta["provider"])

# T3: 首选直接成功（无failover）
router.resolve_all = lambda c, r: [(FakeProv("A", "ok"), "mA", {})]
text, meta = base.run("planner", "planner", {}, cfg=cfg)
assert meta["provider"] == "A" and not meta["failover"] and meta["attempts"] == 1, meta
print("T3 PASS 成功不切换:", meta["provider"])

# T4: 全部失败 → 抛错
router.resolve_all = lambda c, r: [(FakeProv("A", "timeout"), "mA", {}), (FakeProv("B", "error"), "mB", {})]
try:
    base.run("planner", "planner", {}, cfg=cfg)
    print("T4 FAIL 未抛错")
    sys.exit(1)
except Exception as e:
    print("T4 PASS 全失败抛错:", type(e).__name__)

# T5: resolve_all 解析真实配置链（不联网，只解析）
import json
real = json.load(open(os.path.join(ROOT, "config.local.json"), encoding="utf-8"))
router.resolve_all = _orig_resolve_all
cands = router.resolve_all(real, "auditor")
print("T5 auditor 链:", [c[1] for c in cands])
assert [c[1] for c in cands] == ["deepseek-v4-1-flash-economy-261017", "kimi-k3-1-pro-261024"], cands
cands2 = router.resolve_all(real, "planner")
assert [c[1] for c in cands2] == ["deepseek-v4-1-flash-economy-261017", "qiniu/conatus-free"], cands2
print("T5 PASS 链解析顺序正确")

print("ALL_FAILOVER_TESTS_PASS")
