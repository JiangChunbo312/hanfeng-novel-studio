# -*- coding: utf-8 -*-
"""
寒峰小说工作台 · 本地服务。

零第三方依赖：只用 Python 标准库。启动后浏览器打开 http://127.0.0.1:<port>

    python server.py            # 默认 8787
    python server.py --port 9000 --no-browser
"""
import argparse
import concurrent.futures
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from agents import batch as batch_mod            # noqa: E402
from agents import pipeline                      # noqa: E402
from agents.base import load_config, run, extract_json, stream   # noqa: E402
from core import cost as cost_mod                # noqa: E402
from core import store                           # noqa: E402
from core.config import load as cfg_load         # noqa: E402
from core.config import save as cfg_save         # noqa: E402
from core.provider import PRESETS, Provider, estimate_tokens  # noqa: E402
from core.router import describe as routes_describe            # noqa: E402

WEB_DIR = os.path.join(ROOT, "web")
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".ico": "image/x-icon"}

MASK = "***KEEP***"

# ---- 一键跑完运行状态（供页面刷新后恢复：知道跑到哪一步 / 看第5、6步结果）----
RUN_STATE = {}          # (book_id, chapter) -> {"status": running/done/error, "steps": {...}, "result": {...}}
_RUN_LOCK = threading.Lock()


def run_state_save(key: tuple, state: dict) -> None:
    with _RUN_LOCK:
        RUN_STATE[key] = state


def run_state_get(key: tuple):
    with _RUN_LOCK:
        return RUN_STATE.get(key)


def mask_key(k: str) -> str:
    if not k:
        return ""
    return k[:6] + "..." + k[-4:] if len(k) > 12 else "******"


def _as_text(v) -> str:
    """把客户端误传的非字符串字段（dict/list/数字）归一化为字符串。

    背景：/draft 等接口的 text 若被脚本/智能体误传成 JSON 对象，
    落盘时 f.write(dict) 会报 "write() argument must be str, not dict"。
    统一在 API 边界兜底：字符串原样返回，其余序列化成可读文本。
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, indent=2)
    except Exception:
        return str(v)


def public_config(cfg: dict) -> dict:
    out = json.loads(json.dumps(cfg))
    for p in out.get("providers", []):
        p["api_key"] = mask_key(p.get("api_key", ""))
    return out


def _looks_like_mask(k: str) -> bool:
    """判断回传的 key 是否为掩码/占位符，而非真实密钥。"""
    if not k:
        return True
    if k == MASK or k == "******":
        return True
    if "..." in k:          # 形如 ark-8b...f9bb 的展示掩码
        return True
    if len(k) < 16:         # 真实 key 不可能这么短
        return True
    return False


def merge_config(incoming: dict) -> dict:
    """前端回传 MASK 或掩码样式的 key 一律表示「不改这个 key」，从磁盘旧值恢复。

    防污染要点：/api/config 下发给前端的是掩码 key；若浏览器拿着旧页面点保存，
    掩码值会被原样传回。不拦住它就会覆盖真实 key，导致 401。
    """
    old = cfg_load()
    old_keys = {p.get("id"): p.get("api_key", "") for p in old.get("providers", [])}
    for p in incoming.get("providers", []):
        k = p.get("api_key", "")
        if _looks_like_mask(k) and p.get("id") in old_keys:
            p["api_key"] = old_keys[p["id"]]
    return incoming


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---------- 基础 ----------
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8",
              extra: dict = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code: int = 200):
        # allow_nan=False：不输出 NaN/Infinity（非标准 JSON，前端 JSON.parse 会抛错导致“无反应”）
        try:
            payload = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as e:
            payload = json.dumps({"ok": False, "error": "响应序列化失败：" + str(e)},
                                 ensure_ascii=False).encode("utf-8")
            code = 500
        self._send(code, payload)

    def _html_file(self, rel: str):
        path = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not path.startswith(WEB_DIR) or not os.path.exists(path):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, MIME.get(ext, "application/octet-stream"))

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------- SSE ----------
    def _sse_head(self):
        # 不设 Content-Length：靠连接关闭标记流结束，客户端收到 end 事件后主动 close
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, event: str, data):
        try:
            payload = json.dumps(data, ensure_ascii=False)
            self.wfile.write(("event: %s\ndata: %s\n\n" % (event, payload)).encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError):
            raise

    # ---------- 路由 ----------
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        q = urllib.parse.parse_qs(u.query)

        if p in ("/", "/index.html"):
            return self._html_file("index.html")
        if p.startswith("/static/"):
            return self._html_file(p[len("/static/"):])
        if p == "/api/health":
            return self._json({"ok": True, "python": sys.version.split()[0], "root": ROOT})
        if p == "/api/presets":
            return self._json({"presets": PRESETS})
        if p == "/api/config":
            return self._json(public_config(cfg_load()))
        if p == "/api/routes":
            return self._json({"routes": routes_describe(cfg_load())})
        if p == "/api/models":
            pid = (q.get("provider_id") or [""])[0]
            cfg = cfg_load()
            spec = next((x for x in cfg.get("providers", []) if x.get("id") == pid), None)
            if not spec:
                return self._json({"ok": False, "error": "找不到服务商"})
            ok, res = Provider(spec).list_models()
            return self._json({"ok": ok, "models": res if ok else [], "error": "" if ok else str(res)})
        if p == "/api/books":
            return self._json({"books": store.list_books()})

        # /api/books/<id>/...
        if p.startswith("/api/books/"):
            parts = p.split("/")
            if len(parts) >= 4 and parts[3]:
                bid = urllib.parse.unquote(parts[3])
                rest = "/" + "/".join(parts[4:])
                return self._book_get(bid, rest, q)
        return self._json({"error": "未知接口 " + p}, 404)

    def _book_get(self, bid: str, rest: str, q: dict):
        if rest in ("/", ""):
            book = store.get_book(bid)
            return self._json({
                "book": book,
                "chapters": store.list_chapters(bid),
                "state": store.get_state(bid),
                "ledger": store.get_ledger(bid),
                "hooks": store.get_hooks(bid),
                "cost": cost_mod.summary(store.book_dir(bid)),
                "snapshots": store.list_snapshots(bid),
                "next_chapter": store.next_chapter_num(bid),
            })
        if rest == "/cost":
            return self._json(cost_mod.summary(store.book_dir(bid)))
        if rest == "/export":
            # 一键导出本书全部正式章节为 TXT / MD 文件（浏览器直接下载）
            fmt = (q.get("fmt") or ["txt"])[0]
            if fmt not in ("txt", "md"):
                fmt = "txt"
            try:
                fname, content, mime = store.export_book(bid, fmt)
            except Exception as e:
                return self._json({"error": "导出失败：" + str(e)}, 500)
            body = content.encode("utf-8")
            disp = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
                urllib.parse.quote(fname), urllib.parse.quote(fname))
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", disp)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError):
                pass
            return
        if rest == "/projection":
            return self._json({"markdown": store.markdown_projection(bid)})
        if rest == "/run/last":
            # 最近一次一键跑完的状态（供页面刷新后恢复进度/看第5、6步结果）
            try:
                ch = int(q.get("chapter", ["0"])[0] or 0)
            except Exception:
                ch = 0
            st = run_state_get((bid, ch)) if ch else None
            return self._json(st if st else {"status": "none"})
        if rest.startswith("/batch/"):
            # 批量任务状态：/api/books/<id>/batch/<task_id>
            if rest == "/batch/latest":
                runner, tid = batch_mod.get_latest(bid)
                if not runner:
                    return self._json({"ok": True, "active": False})
                snap = runner.snapshot()
                return self._json({"ok": True, "active": snap["status"] in ("queued", "running"),
                                   "task_id": tid, **snap})
            tid = rest.rsplit("/", 1)[-1]
            runner = batch_mod.get_task(tid)
            if not runner:
                return self._json({"error": "任务不存在或已过期"}, 404)
            return self._json({"ok": True, **runner.snapshot()})
        if rest.startswith("/chapter/"):
            try:
                num = int(rest.rsplit("/", 1)[-1])
            except Exception:
                return self._json({"error": "章节号错误"}, 400)
            return self._json({
                "num": num,
                "title": store.get_title(bid, num),
                "text": store.read_chapter(bid, num),
                "draft": store.read_draft(bid, num, "draft"),
                "plan": store.read_draft(bid, num, "plan"),
                "audit": store.read_draft(bid, num, "audit"),
                "revise": store.read_draft(bid, num, "revise"),
                "summary": store.read_summary(bid, num),
                "extraction": store.read_extraction(bid, num),
            })
        return self._json({"error": "未知子接口 " + rest}, 404)

    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/api/books/"):
            parts = u.path.split("/")
            if len(parts) >= 4:
                bid = urllib.parse.unquote(parts[3])
                data = self._body()
                book = store.get_book(bid)
                book.update({k: v for k, v in data.items() if k in
                             ("title", "genre", "premise", "chapter_words", "chapters_dir",
                              "style", "taboos", "outline")})
                store.save_book(bid, book)
                return self._json({"ok": True, "book": book})
        return self._json({"error": "未知接口"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        body = self._body()

        if p == "/api/config":
            cfg = merge_config(body)
            cfg_save(cfg)
            return self._json({"ok": True, "config": public_config(cfg_load())})
        if p == "/api/config/provider":
            cfg = cfg_load()
            spec = body.get("provider") or {}
            if not spec.get("id"):
                spec["id"] = "p%d" % (len(cfg["providers"]) + 1)
            cfg["providers"] = [x for x in cfg["providers"] if x.get("id") != spec["id"]]
            cfg["providers"].append(spec)
            cfg_save(cfg)
            return self._json({"ok": True, "id": spec["id"], "config": public_config(cfg_load())})
        if p == "/api/models/test":
            spec = body.get("provider") or {}
            model = body.get("model") or spec.get("model")
            prov = Provider(spec)
            if model:
                prov.default_model = model
            ok, msg = prov.test()
            return self._json({"ok": ok, "message": msg})

        if p == "/api/models/test-all":
            # 一键测试库里所有模型：每个 provider 的每个模型名单独测（并发执行）。
            # 测完把 ok/bad 写进 model_status，使故障转移只轮换可用模型。
            cfg = cfg_load()
            items = []
            for p_ in cfg.get("providers", []):
                models = [m.strip() for m in str(p_.get("model") or "").split(",") if m.strip()]
                if not models:
                    models = [""]   # 未填模型名的 provider 也测一下，给出明确提示
                for m in models:
                    spec = dict(p_)
                    spec["model"] = m
                    items.append((p_.get("id"), p_.get("label"), m, spec))

            def _one(item):
                pid, label, m, spec = item
                t0 = time.time()
                if not m:
                    return {"key": "%s:%s" % (pid, m), "provider": label, "model": m,
                            "ok": False, "message": "未填模型名，跳过", "latency_ms": 0}
                try:
                    prov = Provider(spec)
                    prov.default_model = m
                    ok, msg = prov.test()
                    return {"key": "%s:%s" % (pid, m), "provider": label, "model": m,
                            "ok": ok, "message": msg, "latency_ms": int((time.time() - t0) * 1000)}
                except Exception as e:
                    return {"key": "%s:%s" % (pid, m), "provider": label, "model": m,
                            "ok": False, "message": str(e), "latency_ms": int((time.time() - t0) * 1000)}

            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                results = list(ex.map(_one, items))
            status = {r["key"]: ("ok" if r["ok"] else "bad") for r in results}
            cfg["model_status"] = status
            cfg_save(cfg)
            available = [r["key"] for r in results if r["ok"]]
            unavailable = [r["key"] for r in results if not r["ok"]]
            return self._json({
                "ok": True, "total": len(results),
                "ok_count": len(available), "bad_count": len(unavailable),
                "results": results, "available": available, "unavailable": unavailable,
            })

        if p == "/api/models/remove":
            # 精准删除某个 provider 下的单个模型（该 provider 模型清空则整删）。
            # 同时清理 model_status，使故障转移不再轮转到已删模型。
            cfg = cfg_load()
            pid_ = body.get("provider_id") or ""
            model = body.get("model") or ""
            dead = "%s:%s" % (pid_, model)
            for p_ in cfg.get("providers", []):
                if p_.get("id") == pid_:
                    models = [m_.strip() for m_ in str(p_.get("model") or "").split(",") if m_.strip()]
                    p_["model"] = ",".join([m_ for m_ in models if m_ != model])
                    break
            cfg["providers"] = [x for x in cfg["providers"] if str(x.get("model") or "").strip()]
            alive = any(x.get("id") == pid_ for x in cfg["providers"])
            if "model_status" in cfg:
                cfg["model_status"] = {k: v for k, v in cfg["model_status"].items()
                                       if k != dead and not (not alive and k.startswith(pid_ + ":"))}
            cfg_save(cfg)
            return self._json({"ok": True, "config": public_config(cfg_load())})
        if p == "/api/books":
            book = store.create_book(body)
            return self._json({"ok": True, "book": book})

        if p == "/api/inspire":
            # AI 一键推荐题材 + 自动生成全套立项设定（SSE 流式）
            # 用流式而非一次性返回：长生成时连接持续活跃，避免被远端网关超时掐断（10054）
            self._sse_head()
            try:
                cfg = cfg_load()
                hint = (body.get("hint") or "").strip()
                got_result = False
                for ev in stream("writer", "inspire", {"hint": hint}, cfg=cfg):
                    if ev["type"] == "delta":
                        self._sse("delta", {"text": ev["text"]})
                    elif ev["type"] == "think":
                        self._sse("think", {"text": ev["text"]})
                    elif ev["type"] == "error":
                        self._sse("error", {"text": ev["text"]})
                    elif ev["type"] == "done":
                        data = extract_json(ev["text"])
                        if not data.get("title"):
                            self._sse("error", {"text": "模型未返回有效结构，请点「换一个」重试"})
                        else:
                            book = {
                                "title": (data.get("title") or "").strip(),
                                "genre": (data.get("genre") or "").strip(),
                                "premise": (data.get("premise") or "").strip(),
                                "style": (data.get("style") or "").strip(),
                                "taboos": (data.get("taboos") or "").strip(),
                                "outline": (data.get("outline") or "").strip(),
                            }
                            self._sse("result", {"book": book, "meta": ev.get("meta")})
                            got_result = True
                if not got_result:
                    self._sse("error", {"text": "未生成有效题材，请重试"})
            except Exception as e:
                self._sse("error", {"text": str(e)})
            self._sse("end", {})
            return

        if p.startswith("/api/books/"):
            parts = p.split("/")
            if len(parts) >= 5:
                bid = urllib.parse.unquote(parts[3])
                action = parts[4]
                return self._book_action(bid, action, body)
        return self._json({"error": "未知接口 " + p}, 404)

    def _book_action(self, bid: str, action: str, body: dict):
        cfg = cfg_load()
        chapter = int(body.get("chapter") or 0)
        # 容错归一化：这些字段任何动作都期望字符串；脚本/智能体误传 JSON 对象时
        # 在此兜底，避免 store._write_text 里 f.write(dict) 崩溃（issues 是列表，合法，不动）
        for _k in ("text", "plan", "title", "kind"):
            if _k in body and not isinstance(body[_k], str):
                body[_k] = str(body[_k]) if _k == "kind" else _as_text(body[_k])

        if action == "plan":
            try:
                r = pipeline.plan_chapter(bid, chapter, cfg)
                return self._json({"ok": True, **r})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        if action == "write":
            # SSE 流式写章
            self._sse_head()
            try:
                plan = body.get("plan") or ""
                for ev in pipeline.write_chapter_stream(bid, chapter, cfg, plan=plan):
                    self._sse("delta" if ev["type"] == "delta" else ev["type"], ev)
            except Exception as e:
                self._sse("error", {"type": "error", "text": str(e)})
            self._sse("end", {"type": "end"})
            return

        if action == "draft":
            # 手动保存草稿（正文框手改后点「保存草稿」）
            try:
                kind = body.get("kind") or "draft"
                text = body.get("text", "")
                store.write_draft(bid, chapter, kind, text)
                return self._json({"ok": True, "kind": kind, "words": store.count_words(text)})
            except Exception as e:
                return self._json({"ok": False, "error": "保存草稿失败：" + str(e)}, 200)

        if action == "extract":
            if chapter < 1:
                return self._json({"ok": False, "error": "抽事实需要正确的章号（>=1），当前为 %s；请先在「章号」框填入章节再点「⑤ 抽事实」，否则伏笔会被记成「埋于第0章」" % chapter}, 200)
            try:
                r = pipeline.observe_and_apply(bid, chapter, body.get("text", ""), cfg)
                if r.get("delta"):
                    store.write_extraction(bid, chapter, r["delta"])
                return self._json({"ok": True, **r})
            except Exception as e:
                return self._json({"ok": True, "delta": {}, "applied": False,
                                   "reason": "抽取失败：" + str(e)}, 200)

        if action == "audit":
            try:
                r = pipeline.audit_chapter(bid, chapter, body.get("text", ""),
                                           body.get("plan", ""), cfg)
                return self._json({"ok": True, **r})
            except Exception as e:
                return self._json({"ok": False, "error": "审计失败：" + str(e)}, 200)

        if action == "revise":
            try:
                r = pipeline.revise_chapter(bid, chapter, body.get("text", ""),
                                            body.get("issues"), cfg)
                return self._json({"ok": True, **r})
            except Exception as e:
                return self._json({"ok": False, "error": "修订失败：" + str(e)}, 200)

        if action == "summary":
            try:
                r = pipeline.summarize_chapter(bid, chapter, body.get("text", ""), cfg)
                return self._json({"ok": True, **r})
            except Exception as e:
                return self._json({"ok": False, "error": "摘要失败：" + str(e)}, 200)

        if action == "title":
            # 为某章即时生成/重生成标题（供写作台写完正文后一键起名、或人工重生成）
            try:
                t = pipeline.generate_title(bid, chapter, body.get("text", ""), body.get("plan", ""))
                return self._json({"ok": True, "title": t, "chapter": chapter})
            except Exception as e:
                return self._json({"ok": False, "title": "", "error": "生成标题失败：" + str(e)}, 200)

        if action == "backfill-titles":
            # 给本书所有已存在章节补标题（历史章节此前没有标题）；逐章调用模型，best-effort
            res = {}
            for c in store.list_chapters(bid):
                try:
                    t = pipeline.generate_title(bid, c["num"])
                    if t:
                        res[c["num"]] = t
                except Exception:
                    pass
            return self._json({"ok": True, "count": len(res), "titles": res})

        if action == "accept":
            r = pipeline.accept_chapter(bid, chapter, body.get("title", ""), body.get("text", ""))
            return self._json(r if r.get("ok") else dict(r, ok=False), 200 if r.get("ok") else 400)

        if action == "run":
            # 一键全流程：SSE 流式上报每步进度（progress: start/done/fail），
            # 前端据此实时高亮当前步骤，避免状态条一直停在第一步。
            # 同时把进度 + 最终结果写进 RUN_STATE，页面刷新后可 /run/last 恢复。
            self._sse_head()
            key = (bid, chapter)
            st = {"status": "running", "steps": {}, "result": None}
            run_state_save(key, st)
            try:
                def _prog(step, status, detail=None):
                    st["steps"][step] = status
                    run_state_save(key, st)
                    self._sse("progress", {"step": step, "status": status, "detail": detail or {}})
                r = pipeline.full_chapter(
                    bid, chapter, cfg,
                    auto_revise=int(body.get("auto_revise", 3)),
                    do_apply=bool(body.get("apply", True)),
                    do_summary=bool(body.get("summary", True)),
                    progress=_prog,
                    reuse_plan=bool(body.get("reuse_plan", True)),
                )
                st["status"] = "done"
                st["result"] = r
                run_state_save(key, st)
                self._sse("result", {"ok": True, **r})
            except Exception as e:
                # 区分两类异常：
                # 1) 流水线业务失败（result 未生成）→ 标 error，前端可看错误重跑
                # 2) SSE 写回时客户端已断开（BrokenPipe/WinError 10053）但 result 已生成
                #    → 业务其实成功，保留 done + result，不因“连不上客户端”误标失败，
                #      否则 /run/last 会把成功跑完的章误判成 error。
                if st.get("result") is not None:
                    st.setdefault("sse_error", str(e)[:200])
                    run_state_save(key, st)
                    return
                st["status"] = "error"
                st["error"] = str(e)
                run_state_save(key, st)
                try:
                    self._sse("error", {"ok": False, "error": str(e)})
                except Exception:
                    pass
            self._sse("end", {})
            return

        if action == "batch":
            # 夜间批量连写：后台线程逐章跑 full_chapter，立即返回 task_id，前端轮询状态
            # 注意 count 显式传 0 也算合法（测试用）；只有缺省才回落 1
            try:
                _c = body.get("count")
                _s = body.get("start")
                task_id = batch_mod.start_batch(
                    bid,
                    int(_s) if _s is not None else 1,
                    int(_c) if _c is not None else 1,
                    cfg,
                    auto_revise=int(body.get("auto_revise", 3)),
                    auto_accept=bool(body.get("auto_accept", True)),
                    do_summary=bool(body.get("do_summary", True)),
                    max_chapter_seconds=int(body.get("max_chapter_seconds") or 1800),
                    max_fail_streak=int(body.get("max_fail_streak") or 3),
                )
                return self._json({"ok": True, "task_id": task_id})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        if action == "batch_stop":
            tid = body.get("task_id") or ""
            runner = batch_mod.get_task(tid)
            if not runner:
                return self._json({"ok": False, "error": "任务不存在"}, 404)
            runner.stop()
            return self._json({"ok": True})

        if action == "rollback":
            snap = body.get("snapshot", "")
            ok = store.rollback(bid, snap)
            return self._json({"ok": ok})

        return self._json({"error": "未知动作 " + action}, 404)


def main():
    ap = argparse.ArgumentParser(description="寒峰小说工作台")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    # 首次运行生成配置文件
    cfg_load()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d/" % (args.host, args.port)
    print("=" * 56)
    print(" 寒峰小说工作台")
    print(" 服务地址 : %s" % url)
    print(" 项目目录 : %s" % os.path.join(ROOT, "projects"))
    print(" 配置目录 : %s" % os.path.join(ROOT, "config.local.json"))
    print(" Ctrl+C 停止")
    print("=" * 56)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.server_close()


if __name__ == "__main__":
    main()
