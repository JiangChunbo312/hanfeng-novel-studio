# -*- coding: utf-8 -*-
"""
冒烟测试：用一个假的 OpenAI 兼容服务跑通整条流水线。

    python tests/smoke_test.py

不联网、不花钱。验证：配置 → 建书 → 规划 → 写章(流式) → 审计 → 修订 → 抽取事实
→ 摘要 → 采纳写入，以及成本台账与真相文件是否落盘。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = sys.executable
MOCK_PORT = 8899
APP_PORT = 8788
MOCK = os.path.join(ROOT, "tests", "mock_llm.py")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ((" · " + str(extra)) if extra else ""))


def http(method, url, body=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def sse_post(url, body, timeout=60):
    """读 SSE 流，返回 (累积文本, 最终 result 事件载荷)。

    事件类型取自 `event:` 行（服务端 _sse 写成 `event: xxx\\ndata: ...`），
    数据载荷里不一定带 type 字段（如 /run 的 result 事件）。
    """
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    text = []
    result_ev = None
    cur_event = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            s = raw.decode("utf-8", "ignore").strip()
            if s.startswith("event: "):
                cur_event = s[len("event: "):].strip()
                continue
            if not s.startswith("data: "):
                continue
            try:
                ev = json.loads(s[6:])
            except Exception:
                continue
            if cur_event == "delta":
                text.append(ev.get("text", ""))
            elif cur_event in ("result", "done"):
                result_ev = ev
            elif cur_event == "error":
                raise RuntimeError(ev.get("text") or ev.get("error"))
            elif cur_event == "end":
                return "".join(text), result_ev or {}
    return "".join(text), result_ev or {}


def wait_up(url, tag, tries=40):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.3)
    print("服务未起来：%s (%s)" % (url, tag))
    return False


def _backup_config():
    """备份真实配置。本测试会把路由全改成假模型，跑完必须还原，
    否则真实服务下一笔调用会打到不存在的 mock 端点，表现为 [WinError 10054]。"""
    p = os.path.join(ROOT, "config.local.json")
    if not os.path.exists(p):
        return p, None
    with open(p, "r", encoding="utf-8") as f:
        return p, f.read()


def _restore_config(p, text):
    if text is None:
        return False
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def main():
    procs = []
    bid = None
    cfg_path, cfg_backup = _backup_config()
    try:
        print("\n=== 1. 启动假模型服务与工作台 ===")
        procs.append(subprocess.Popen([PY, MOCK, "--port", str(MOCK_PORT)]))
        procs.append(subprocess.Popen([PY, os.path.join(ROOT, "server.py"),
                                       "--port", str(APP_PORT), "--no-browser"],
                                      cwd=ROOT,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        base = "http://127.0.0.1:%d" % APP_PORT
        ok = wait_up("http://127.0.0.1:%d/v1/models" % MOCK_PORT, "mock") and wait_up(base + "/api/health", "app")
        check("两个服务启动成功", ok)
        if not ok:
            return 1

        print("\n=== 2. 配置服务商（指向假模型） ===")
        r = http("POST", base + "/api/config/provider", {"provider": {
            "id": "mock", "label": "假模型", "base_url": "http://127.0.0.1:%d/v1" % MOCK_PORT,
            "api_key": "sk-test", "model": "mock-1", "timeout": 30}})
        check("添加服务商", r.get("ok"), r.get("id"))
        cfg = r["config"]
        cfg["routes"] = {k: "" for k in cfg["routes"]}
        cfg["routes"]["default"] = "mock:mock-1"
        cfg["prices"]["mock:mock-1"] = {"in": 1.0, "out": 4.0}
        r = http("POST", base + "/api/config", cfg)
        check("保存路由与单价", r.get("ok"))

        r = http("POST", base + "/api/models/test", {"provider": {
            "id": "mock", "label": "假模型", "base_url": "http://127.0.0.1:%d/v1" % MOCK_PORT,
            "api_key": "sk-test", "model": "mock-1"}})
        check("连接测试通过", r.get("ok"), r.get("message"))

        print("\n=== 3. 建项目 ===")
        r = http("POST", base + "/api/books", {
            "title": "冒烟测试之书", "genre": "测试", "chapter_words": 800,
            "premise": "一个关于测试的故事", "style": "简洁", "taboos": "不许写刀",
            "outline": "第1章：开场"})
        check("创建项目", r.get("ok"))
        bid = r["book"]["id"]
        bidq = urllib.parse.quote(bid)   # URL 里的中文项目名需要转义

        print("\n=== 4. 规划 ===")
        r = http("POST", base + "/api/books/%s/plan" % bidq, {"chapter": 1})
        check("生成写作意图", r.get("ok") and "本章功能" in r.get("plan", ""),
              r.get("plan", "")[:40].replace("\n", " "))

        print("\n=== 5. 写章（流式） ===")
        text, done = sse_post(base + "/api/books/%s/write" % bidq, {"chapter": 1})
        check("流式写出正文", len(text) > 50, "%d 字" % len(text))
        check("流式返回 meta", "model" in (done.get("meta") or {}), (done.get("meta") or {}).get("model"))

        print("\n=== 6. 审计 ===")
        r = http("POST", base + "/api/books/%s/audit" % bidq, {"chapter": 1, "text": text})
        check("审计返回报告", r.get("ok") and "issues" in r, "score=%s passed=%s" % (r.get("score"), r.get("passed")))
        issues = r.get("issues") or []
        check("审计能给出问题条目", len(issues) > 0, "%d 条" % len(issues))

        print("\n=== 7. 定点改写 ===")
        r = http("POST", base + "/api/books/%s/revise" % bidq, {"chapter": 1, "text": text, "issues": issues})
        check("修订返回新稿", r.get("ok") and bool(r.get("text")), "changed=%s" % r.get("changed"))

        print("\n=== 8. 事实抽取 → 真相文件 ===")
        r = http("POST", base + "/api/books/%s/extract" % bidq, {"chapter": 1, "text": text})
        check("抽取并应用 delta", r.get("applied"), r.get("reason", ""))
        d = http("GET", base + "/api/books/" + bidq)
        check("角色状态已写入", bool((d["state"].get("characters") or {})),
              list((d["state"].get("characters") or {}).keys())[:3])
        check("伏笔池已写入", len((d["hooks"].get("hooks") or [])) > 0,
              "%d 条" % len((d["hooks"].get("hooks") or [])))
        check("资源账本已写入", bool((d["ledger"].get("items") or {})))

        print("\n=== 9. 摘要 ===")
        r = http("POST", base + "/api/books/%s/summary" % bidq, {"chapter": 1, "text": text})
        check("摘要已生成", bool(r.get("summary")))

        print("\n=== 10. 采纳写入正文 ===")
        r = http("POST", base + "/api/books/%s/accept" % bidq, {"chapter": 1, "text": text})
        check("写入章节文件", r.get("ok"), r.get("file"))
        check("生成了状态快照", bool(r.get("snapshot")))
        d = http("GET", base + "/api/books/" + bidq)
        check("章节列表出现第1章", any(c["num"] == 1 for c in d["chapters"]),
              "%d 章" % len(d["chapters"]))

        print("\n=== 11. 成本台账 ===")
        c = d["cost"]
        check("有调用记录", c.get("calls", 0) > 0, "%d 次 · %d tok · ¥%s" % (
            c.get("calls", 0), c.get("total_tokens", 0), c.get("total_cost", 0)))
        check("按角色聚合有效", bool(c.get("by_role")), list((c.get("by_role") or {}).keys()))

        print("\n=== 12. 一键全流程（第2章） ===")
        # /run 是 SSE 流，必须用 sse_post 读取；结果在 type=result 事件中
        _, r = sse_post(base + "/api/books/%s/run" % bidq, {"chapter": 2, "auto_revise": 1}, timeout=120)
        check("full_chapter 跑通", r.get("ok"), "score=%s 用时%ss" % (r.get("score"), r.get("elapsed")))
        check("步骤链完整", [x["step"] for x in (r.get("log") or [])][:1] == ["plan"],
              " → ".join(x["step"] for x in (r.get("log") or [])))
        check("含抽事实与摘要步骤", bool(r.get("observe")) and bool(r.get("summary")),
              "observe=%s summary=%d字" % (bool(r.get("observe")), len(r.get("summary") or "")))
        check("透出完整抽事实delta", bool(r.get("observe_delta")),
              "delta键=%s" % list((r.get("observe_delta") or {}).keys()))
        # 抽事实 delta 应落盘，供「已抽事实」标签刷新后恢复
        ext_file = os.path.join("projects", bid, "extractions", "ch002.json")
        check("抽事实delta已落盘", os.path.exists(ext_file), ext_file)
        d2 = http("GET", base + "/api/books/%s/chapter/2" % bidq)
        check("chapter接口返回extraction", bool(d2.get("extraction")), "extraction键=%s" % list((d2.get("extraction") or {}).keys()))

        print("\n=== 12.5 刷新恢复（/run/last） ===")
        rl = http("GET", base + "/api/books/%s/run/last?chapter=2" % bidq)
        check("run/last 返回 done", rl.get("status") == "done", rl.get("status"))
        check("run/last 含流程结果", bool((rl.get("result") or {}).get("log")),
              "log=%d步" % len((rl.get("result") or {}).get("log") or []))

        print("\n=== 12.6 复用意图（同章二次跑不重生成） ===")
        # 步骤12已为第2章生成并存盘意图；再次 /run 同章应直接复用，不再消耗额度
        _, r2 = sse_post(base + "/api/books/%s/run" % bidq,
                         {"chapter": 2, "reuse_plan": True, "auto_revise": 1}, timeout=120)
        plan0 = (r2.get("log") or [{}])[0]
        check("同章二次跑复用意图(reused=true)", plan0.get("reused") is True,
              "plan.reused=%s" % plan0.get("reused"))

        print("\n=== 13. 文件落盘检查 ===")
        bd = os.path.join(ROOT, "projects", bid)
        for fn in ["book.json", "state.json", "ledger.json", "hooks.json", "usage.jsonl"]:
            check("存在 %s" % fn, os.path.exists(os.path.join(bd, fn)))
        check("存在章节正文", os.path.exists(os.path.join(bd, "chapters"))
              and len(os.listdir(os.path.join(bd, "chapters"))) >= 1,
              os.listdir(os.path.join(bd, "chapters")))
        check("存在摘要", len(os.listdir(os.path.join(bd, "summaries"))) >= 1)
        check("存在快照", len(os.listdir(os.path.join(bd, "snapshots"))) >= 1)

        print("\n" + "=" * 58)
        print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
        if FAIL:
            print("失败项：")
            for f in FAIL:
                print("  - " + f)
        print("=" * 58)
        return 1 if FAIL else 0
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        if _restore_config(cfg_path, cfg_backup):
            print("\n已还原真实配置 config.local.json（路由/Key 回到你设置的状态）")
        else:
            print("\n[警告] 未找到可还原的配置备份，config.local.json 仍指向假模型")
        # 清理本测试自建的项目，避免污染真实书籍列表
        if bid:
            import shutil
            bd = os.path.join(ROOT, "projects", bid)
            if os.path.isdir(bd):
                shutil.rmtree(bd)
                print("已清理测试项目：%s" % bid)


if __name__ == "__main__":
    sys.exit(main())
