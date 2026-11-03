"""定点改写触发回归测试（不依赖真实模型）。

验证用户要求：审计出现的【所有】问题（critical/major/minor）都要在定点改写里修复，
不再只等出现致命问题才改。

场景A：审计通过（无 critical）但仍有 1 条 minor 问题 → 必须跑定点改写。
场景B：审计干净（0 问题） → 不应浪费一轮改写。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock
import agents.pipeline as P


def _plan(book_id, chapter, cfg):
    return {"plan": "意图P", "meta": {"model": "mock"}}


def _write(book_id, chapter, cfg, plan=""):
    return {"text": "这是正文内容，约二十字左右的测试文本用于统计字数。", "meta": {"model": "mock"}}


def _observe(book_id, chapter, text, cfg):
    return {"applied": True, "characters": 1, "facts": 1, "items": 0,
            "new_hooks": 0, "relations": 0, "emotions": 0, "reason": ""}


def _summarize(book_id, chapter, text, cfg):
    return {"summary": "本章摘要测试文本。"}


def test_revise_runs_on_minor_issue():
    """场景A：passed=True（无 critical）但 issues 非空 → revise 必须被调用。"""
    calls = {"revise": 0, "audit_rounds": 0}

    def _audit(book_id, chapter, text, plan, cfg):
        calls["audit_rounds"] += 1
        # 第一次审计：通过但留 1 条 minor 问题；改写后第二次：干净
        if calls["audit_rounds"] == 1:
            return {"passed": True, "score": 85, "critical_count": 0,
                    "issues": [{"id": "M1", "level": "minor", "desc": "小问题"}],
                    "summary": "基本通过", "text": text}
        return {"passed": True, "score": 95, "critical_count": 0,
                "issues": [], "summary": "干净", "text": text}

    def _revise(book_id, chapter, text, issues, cfg):
        calls["revise"] += 1
        return {"text": text + "（已修）", "changed": True,
                "report": [{"id": "M1", "handled": True, "how": "改了"}]}

    with mock.patch.object(P, "plan_chapter", _plan), \
         mock.patch.object(P, "write_chapter", _write), \
         mock.patch.object(P, "audit_chapter", _audit), \
         mock.patch.object(P, "revise_chapter", _revise), \
         mock.patch.object(P, "observe_and_apply", _observe), \
         mock.patch.object(P, "summarize_chapter", _summarize):
        r = P.full_chapter("B", 1, {}, auto_revise=3, do_apply=True,
                           do_summary=True, reuse_plan=False)

    steps = [x["step"] for x in r["log"]]
    print("场景A 步骤:", " → ".join(steps))
    print("  revise 调用次数:", calls["revise"], "| audit 轮数:", calls["audit_rounds"])
    assert calls["revise"] >= 1, "❌ 审计通过但有 minor 问题时，定点改写没跑！"
    assert any(s.startswith("revise#") for s in steps), "❌ 流程里没有 revise 步骤"
    assert r["score"] == 95, "❌ 改写后应重新审计得到 95 分"
    print("  [OK] 审计通过但有问题时定点改写已跑，并修复到 0 问题\n")


def test_revise_skipped_when_clean():
    """场景B：审计干净（0 问题）→ 不应跑改写，避免浪费。"""
    calls = {"revise": 0}

    def _audit(book_id, chapter, text, plan, cfg):
        return {"passed": True, "score": 98, "critical_count": 0,
                "issues": [], "summary": "完美", "text": text}

    def _revise(book_id, chapter, text, issues, cfg):
        calls["revise"] += 1
        return {"text": text, "changed": False, "report": []}

    with mock.patch.object(P, "plan_chapter", _plan), \
         mock.patch.object(P, "write_chapter", _write), \
         mock.patch.object(P, "audit_chapter", _audit), \
         mock.patch.object(P, "revise_chapter", _revise), \
         mock.patch.object(P, "observe_and_apply", _observe), \
         mock.patch.object(P, "summarize_chapter", _summarize):
        r = P.full_chapter("B", 1, {}, auto_revise=3, do_apply=True,
                           do_summary=True, reuse_plan=False)

    steps = [x["step"] for x in r["log"]]
    print("场景B 步骤:", " → ".join(steps))
    print("  revise 调用次数:", calls["revise"])
    assert calls["revise"] == 0, "❌ 审计干净时不应跑改写"
    assert not any(s.startswith("revise#") for s in steps), "❌ 干净流程里不应出现 revise 步骤"
    print("  [OK] 审计干净时未浪费改写轮次\n")


if __name__ == "__main__":
    test_revise_runs_on_minor_issue()
    test_revise_skipped_when_clean()
    print("✅ 定点改写触发回归测试全部通过")
