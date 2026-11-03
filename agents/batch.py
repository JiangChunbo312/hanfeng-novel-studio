# -*- coding: utf-8 -*-
"""
批量连写流水线（夜间挂机自动跑）。

逐章调用 full_chapter（意图→写作→审计→(修订)→抽取→摘要），失败不中断整个队列，
支持断点续跑。三个关键保护：

  - 自动采纳：每章跑完直接写入正文章节文件（跳过「⑦ 采纳」人工闸门）
  - 失败熔断：连续 max_fail_streak 章失败 → 停，避免坏配置空烧 token
  - 挂起看门狗：单章超过 max_chapter_seconds → 停（标记 stalled）。
    Python 无法安全杀死阻塞线程，宁可停批也不让孤儿线程和下一章抢真相文件。

任务状态存内存 dict，前端轮询 /api/books/<id>/batch/<task_id> 拿进度。
服务进程存活期间任务有效；刷新页面不丢（任务在服务端线程里跑）。
"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

from . import pipeline


class BatchRunner:
    def __init__(self, book_id, start, count, cfg,
                 auto_revise=1, auto_accept=True, do_summary=True,
                 max_chapter_seconds=1800, max_fail_streak=3):
        self.book_id = book_id
        self.start = int(start)
        self.count = int(count)
        self.cfg = cfg
        self.auto_revise = int(auto_revise)
        self.auto_accept = bool(auto_accept)
        self.do_summary = bool(do_summary)
        self.max_chapter_seconds = int(max_chapter_seconds or 1800)
        self.max_fail_streak = int(max_fail_streak or 3)

        self.status = "queued"      # queued | running | done | stopped | stalled
        self.current = self.start
        self.results = []
        self.started_at = None
        self.finished_at = None

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._thread = None

    # ---- 对外控制 ----
    def start_run(self):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="batch-%s" % self.book_id)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ---- 快照（供前端轮询） ----
    def snapshot(self):
        with self._lock:
            return {
                "status": self.status,
                "book_id": self.book_id,
                "start": self.start,
                "count": self.count,
                "current": self.current,
                "auto_accept": self.auto_accept,
                "results": list(self.results),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    # ---- 工作线程 ----
    def _run(self):
        self.started_at = time.time()
        self.status = "running"
        fail_streak = 0
        for i in range(self.count):
            if self._stop.is_set():
                self._finish("stopped")
                return
            ch = self.start + i
            self.current = ch
            rec = {"chapter": ch, "ok": False, "accepted": False,
                   "elapsed": 0, "score": None, "error": None}
            try:
                fut = self._pool.submit(pipeline.full_chapter,
                                        self.book_id, ch, self.cfg,
                                        self.auto_revise, True, self.do_summary)
                r = fut.result(timeout=self.max_chapter_seconds)
            except FutTimeout:
                # 单章挂起超时：停批，不再提交新章。孤儿线程继续在后台跑，
                # 但因为不再有下一章，不会和它并发写真相文件。
                rec["error"] = "超时 > %ds（疑似模型挂起/排队），已停止" % self.max_chapter_seconds
                self._append(rec)
                self._finish("stalled")
                return
            except Exception as e:
                rec["error"] = str(e)[:200]
                self._append(rec)
                fail_streak += 1
                if fail_streak >= self.max_fail_streak:
                    self._finish("stopped")
                    return
                continue
            fail_streak = 0
            rec["ok"] = bool(r.get("passed"))
            rec["elapsed"] = round(r.get("elapsed", 0), 1)
            rec["score"] = r.get("score")
            if self.auto_accept and r.get("text"):
                try:
                    a = pipeline.accept_chapter(self.book_id, ch, "", r["text"])
                    rec["accepted"] = bool(a.get("ok"))
                except Exception as e:
                    rec["error"] = (rec["error"] or "") + "采纳失败:" + str(e)[:80]
            self._append(rec)
        self._finish("done")

    def _append(self, rec):
        with self._lock:
            self.results.append(rec)

    def _finish(self, status):
        with self._lock:
            self.status = status
            self.finished_at = time.time()


# ---- 全局任务表（进程内） ----
TASKS = {}
LATEST = {}          # book_id -> 最近一次批量 task_id（供页面刷新后重连）
_TASKS_LOCK = threading.Lock()


def start_batch(book_id, start, count, cfg, **kw) -> str:
    task_id = uuid.uuid4().hex[:12]
    runner = BatchRunner(book_id, start, count, cfg, **kw)
    with _TASKS_LOCK:
        TASKS[task_id] = runner
        LATEST[book_id] = task_id
    runner.start_run()
    return task_id


def get_task(task_id):
    with _TASKS_LOCK:
        return TASKS.get(task_id)


def get_latest(book_id):
    """返回 (runner, task_id)：该书最近一次批量任务，不存在返回 (None, None)。"""
    with _TASKS_LOCK:
        tid = LATEST.get(book_id)
        runner = TASKS.get(tid) if tid else None
        return runner, (tid if runner else None)
