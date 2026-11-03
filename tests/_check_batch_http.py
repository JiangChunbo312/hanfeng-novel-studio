# -*- coding: utf-8 -*-
"""HTTP 批量接口冒烟：start(count=0, 不调LLM) → state → 404 分支。"""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8787/api"


def call(path, method="GET", body=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# 1) 拿一本书
st, books = call("/books")
bid = urllib.parse.quote(books["books"][0]["id"])
print("book:", books["books"][0]["id"])

# 2) 启动批量 count=0（不触发 LLM）
st, r = call("/books/%s/batch" % bid, "POST", {"start": 1, "count": 0, "auto_accept": True})
print("start http=%d ok=%s task_id=%s" % (st, r.get("ok"), r.get("task_id")))
assert st == 200 and r.get("ok") and r.get("task_id"), "start 失败"
tid = r["task_id"]

time.sleep(1.2)

# 3) 查状态
st, s = call("/books/%s/batch/%s" % (bid, tid))
print("state http=%d status=%s results=%d current=%s" % (st, s.get("status"), len(s.get("results", [])), s.get("current")))
assert st == 200 and s["status"] == "done" and not s["results"], "count=0 应直接 done"

# 4) 假 task → 404
st, _ = call("/books/%s/batch/nonexistent" % bid)
print("fake-state http=%d" % st)
assert st == 404, "假任务应 404"

# 5) 假 stop → 404
st, _ = call("/books/%s/batch_stop" % bid, "POST", {"task_id": "nonexistent"})
print("fake-stop http=%d" % st)
assert st == 404, "假停止应 404"

print("HTTP_BATCH_SMOKE_PASS")
