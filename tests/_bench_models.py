# -*- coding: utf-8 -*-
"""模型基准：探测可用性 + 真实角色任务计时/质量评估。

用法：python tests/_bench_models.py [--phase probe|task|all]
  probe —— 快速探测全部候选模型是否存活（短消息）
  task  —— 对存活的跑真实角色任务（创意写作 / 结构化抽取）
  all   —— 先 probe 后 task
"""
import json
import sys
import time
import os
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.provider import Provider  # noqa: E402

CFG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.local.json")
cfg = json.load(open(CFG_PATH, encoding="utf-8"))

# 候选全集：12 可测 + 5 路由引用但不在可测集
CANDIDATES = []
for p in cfg["providers"]:
    pid = p["id"]
    for m in str(p.get("model") or "").split(","):
        m = m.strip()
        if m:
            CANDIDATES.append((pid, m))
EXTRA = ["deepseek-v4-flash-ga-260731", "doubao-seed-2-1-turbo-260628",
         "glm-5-2-260617", "glm-5-3-flash-260828", "kimi-k3-1-pro-261024"]
for m in EXTRA:
    if ("volc:" + m) not in ["%s:%s" % c for c in CANDIDATES]:
        CANDIDATES.append(("volc", m))

PROV = {p["id"]: p for p in cfg["providers"]}

WRITER_PROMPT = (
    "你是一位网络小说写手。请以「雨夜，老旧出租屋，敲门声响起」为开头，"
    "续写一段 250 字左右的悬疑叙事片段，要求有画面感、有悬念、语言流畅。只输出正文，不要标题。"
)
OBSERVER_PROMPT = (
    "你是事实抽取器。请从下面这段文字里抽取事实，输出严格 JSON："
    '{"characters":[],"locations":[],"events":[],"items":[]}。只输出 JSON，不要其它文字。\n'
    "文本：林满月把王丽那通压着声音的急电话、小鹿转来的48小时倒计时提醒、导播台端口查询结果叠在一起，"
    "指尖敲着桌上的权责表，确认期限已经启动，倒计时结束会触发陆方违约审查。黑料已经从导播台端口流出，"
    "溯源证据还卡在端口链路层面，没有闭环，她只能抓紧推进权限确认与合规溯源。"
)


def _provider(pid, model):
    spec = dict(PROV[pid])
    spec["model"] = model
    return Provider(spec)


def probe(pid, model):
    t0 = time.time()
    try:
        ok, msg = _provider(pid, model).test()
        return {"key": "%s:%s" % (pid, model), "ok": ok, "msg": msg,
                "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"key": "%s:%s" % (pid, model), "ok": False, "msg": str(e),
                "ms": int((time.time() - t0) * 1000)}


def task_writer(pid, model):
    t0 = time.time()
    try:
        text, usage = _provider(pid, model).chat(
            [{"role": "user", "content": WRITER_PROMPT}],
            max_tokens=1024, temperature=0.85, timeout=120)
        return {"key": "%s:%s" % (pid, model), "ok": True,
                "ms": int((time.time() - t0) * 1000),
                "chars": len([c for c in text if not c.isspace()]),
                "sample": text[:60].replace("\n", " ")}
    except Exception as e:
        return {"key": "%s:%s" % (pid, model), "ok": False,
                "ms": int((time.time() - t0) * 1000), "msg": str(e)[:120]}


def task_observer(pid, model):
    t0 = time.time()
    try:
        text, usage = _provider(pid, model).chat(
            [{"role": "user", "content": OBSERVER_PROMPT}],
            max_tokens=1024, temperature=0.2, timeout=120)
        # 判断是否抽出合法 JSON
        import re
        t = text.strip()
        m = re.search(r"\{[\s\S]*\}", t)
        valid = False
        fields = 0
        if m:
            try:
                obj = json.loads(m.group(0))
                valid = True
                fields = sum(1 for k in ("characters", "locations", "events", "items") if obj.get(k))
            except Exception:
                valid = False
        return {"key": "%s:%s" % (pid, model), "ok": True,
                "ms": int((time.time() - t0) * 1000),
                "json_ok": valid, "fields": fields,
                "sample": text[:60].replace("\n", " ")}
    except Exception as e:
        return {"key": "%s:%s" % (pid, model), "ok": False,
                "ms": int((time.time() - t0) * 1000), "msg": str(e)[:120]}


def run_pool(fn, items, workers=6):
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, pid, m): (pid, m) for pid, m in items}
        for f in concurrent.futures.as_completed(futs):
            try:
                out.append(f.result())
            except Exception as e:
                pid, m = futs[f]
                out.append({"key": "%s:%s" % (pid, m), "ok": False, "msg": str(e)})
    return out


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    if phase in ("probe", "all"):
        print("=== PHASE1 可用性探测（%d 候选）===" % len(CANDIDATES))
        res = run_pool(probe, CANDIDATES)
        res.sort(key=lambda r: (not r["ok"], r["ms"]))
        for r in res:
            tag = "OK  " if r["ok"] else "FAIL"
            print("%-4s %-48s %6dms  %s" % (tag, r["key"], r["ms"], r["msg"][:40]))
        ok_keys = {r["key"] for r in res if r["ok"]}
        print("\n存活 %d / %d\n" % (len(ok_keys), len(CANDIDATES)))
        if phase == "probe":
            return
        alive = [(k.split(":")[0], k.split(":", 1)[1]) for k in ok_keys]
    else:
        alive = CANDIDATES

    print("=== PHASE2 真实角色任务（存活 %d）===" % len(alive))
    wr = run_pool(task_writer, alive)
    ob = run_pool(task_observer, alive)
    wr.sort(key=lambda r: (not r["ok"], r.get("ms", 99999)))
    ob.sort(key=lambda r: (not r["ok"], r.get("ms", 99999)))
    print("\n--- 创意写作任务（写手/规划师类）---")
    for r in wr:
        if r["ok"]:
            print("%-48s %6dms  %4d字  %s" % (r["key"], r["ms"], r["chars"], r["sample"][:30]))
        else:
            print("%-48s FAIL %s" % (r["key"], r.get("msg", "")))
    print("\n--- 结构化抽取任务（观察者/审计员类）---")
    for r in ob:
        if r["ok"]:
            print("%-48s %6dms  json=%s fields=%d  %s" % (r["key"], r["ms"], r["json_ok"], r["fields"], r["sample"][:26]))
        else:
            print("%-48s FAIL %s" % (r["key"], r.get("msg", "")))


if __name__ == "__main__":
    main()
