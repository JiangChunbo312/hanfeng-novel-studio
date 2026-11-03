# -*- coding: utf-8 -*-
"""
流水线：规划 → 编排(上下文组装) → 写作 → 事实抽取 → 审计 → 修订 → 摘要 → 采纳。

每一道工序都可以单独重跑。审计不过只重跑修订，不推倒整章。
"""
import os
import re
import time
from typing import Iterator

from core import store

from . import base


# ---------------- 编排：上下文组装（纯代码，不烧 Token） ----------------

def build_context(book_id: str, chapter: int, cfg: dict) -> dict:
    book = store.get_book(book_id)
    n = int(cfg.get("defaults", {}).get("recent_summary_count", 5) or 5)

    prev = store.read_chapter(book_id, chapter - 1)
    if not prev:
        chapters = store.list_chapters(book_id)
        lower = [c for c in chapters if c["num"] < chapter]
        if lower:
            prev = store.read_chapter(book_id, lower[-1]["num"])

    hooks_obj = store.get_hooks(book_id)
    active = [h for h in (hooks_obj.get("hooks") or []) if h.get("status") != "resolved"]
    hooks_txt = "\n".join(
        "- [%s] %s（埋于第%s章%s）" % (
            h.get("id", "?"), h.get("text", ""), h.get("planted_ch", "?"),
            "，预期第%s章回收" % h["due_chapter"] if h.get("due_chapter") else "",
        ) for h in active
    ) or "（暂无活跃伏笔）"

    return {
        "chapter": chapter,
        "book_context": "书名：%s\n类型：%s\n核心设定：%s" % (
            book.get("title", ""), book.get("genre", ""), book.get("premise", "")),
        "facts": store.markdown_projection(book_id),
        "hooks": hooks_txt,
        "recent_summaries": "\n\n".join(store.recent_summaries(book_id, n, chapter)) or "（无）",
        "prev_chapter": prev or "（这是第一章，没有前文）",
        "prev_tail": (prev or "")[-800:],
        "outline": book.get("outline", "") or "（未填写卷纲）",
        "style": book.get("style", "") or "（未指定，按题材默认风格）",
        "taboos": book.get("taboos", "") or "（未指定）",
        "chapter_words": max(1500, int(book.get("chapter_words") or cfg.get("defaults", {}).get("chapter_words", 2000))),
        "chapter_words_min": max(1200, int(cfg.get("defaults", {}).get("chapter_words_min", 0) or 0)
                               or int(round(max(1500, int(book.get("chapter_words") or cfg.get("defaults", {}).get("chapter_words", 2000))) * 0.8))),
        "chapter_words_max": int(cfg.get("defaults", {}).get("chapter_words_max", 0) or 0)
                             or int(round(max(1500, int(book.get("chapter_words") or cfg.get("defaults", {}).get("chapter_words", 2000))) * 1.3)),
    }


# ---------------- 加固#2：确定性硬校验层（纯代码，不烧 Token） ----------------

def deterministic_checks(book_id: str, chapter: int, text: str, cfg: dict) -> list:
    """纯代码确定性校验：字数区间 / JSON 污染 / 残留占位符 / 正文非空。

    这些是「可用代码确定的事实」，不依赖模型目测。审计时确定性结论
    优先于模型判定（模型只负责 A1-A11 这类需要判断力的维度）。
    """
    bc = build_context(book_id, chapter, cfg)
    lo, hi = bc["chapter_words_min"], bc["chapter_words_max"]
    target = bc["chapter_words"]
    s = (text or "").strip()
    if not s:
        return [{"id": "A12", "level": "critical", "desc": "正文为空，无内容可审计",
                 "evidence": "", "fix": "重新写章生成正文"}]
    actual = store.count_words(s)
    issues = []
    # JSON 污染：正文被 {text, report} 包裹（模型返回结构未剥离）
    if s.startswith(("{", "[")) or '"text"' in s[:120]:
        issues.append({"id": "A13", "level": "critical",
                       "desc": "正文疑似被 JSON 对象包裹污染（模型返回结构未剥离）",
                       "evidence": s[:60],
                       "fix": "重新落盘纯正文（走 _payload_text 净化）"})
    # 残留未渲染占位符
    ph = re.findall(r"\{\{[^}]+\}\}", s)
    if ph:
        issues.append({"id": "A14", "level": "major",
                       "desc": "正文残留未渲染模板占位符：" + "、".join(sorted(set(ph))[:3]),
                       "evidence": "占位符残留", "fix": "重新渲染或人工清除占位符"})
    # 直角引号：大陆简体规范应用弯引号“”（防 AI 味，书书铁律配套确定性检查）
    if "「" in s or "」" in s:
        first_ln = next((ln.strip() for ln in s.splitlines() if ("「" in ln or "」" in ln)), "")
        issues.append({"id": "A15", "level": "critical",
                       "desc": "正文使用直角引号「」（大陆简体规范应使用弯引号）",
                       "evidence": first_ln[:48],
                       "fix": "将「」按层级改写为外层“”、内嵌‘’后重新落盘"})
    # 字数区间（系统统计，权威）
    if actual < lo or actual > hi:
        ratio = (lo - actual) / lo if actual < lo else (actual - hi) / hi
        issues.append({"id": "A12", "level": "critical" if ratio > 0.10 else "major",
                       "desc": "字数%s：系统统计 %d 字，允许区间 %d-%d 字（目标 %d 字）" % (
                           "不足" if actual < lo else "超标", actual, lo, hi, target),
                       "evidence": "全文系统统计（去空白）",
                       "fix": ("扩充内容到 %d-%d 字" % (lo, hi) if actual < lo
                               else "压缩冗余到 %d-%d 字" % (lo, hi))})
    return issues


def _score_from_issues(issues: list) -> int:
    """由问题清单客观算分：critical 扣 35、major 扣 12、minor 扣 4。"""
    score = 100
    for i in issues:
        lv = str(i.get("level", "")).lower()
        if lv == "critical":
            score -= 35
        elif lv == "major":
            score -= 12
        elif lv == "minor":
            score -= 4
    return max(0, min(100, score))


# ---------------- 加固#3：context 单一来源 ----------------

def role_ctx(book_id: str, chapter: int, role: str, cfg: dict,
             text: str = "", plan: str = "", extra: dict = None) -> dict:
    """统一组装某角色的上下文。

    基础字段一律来自 build_context（单一来源），再按角色叠加专属字段，
    杜绝各工序自行拼 context 导致的字段漏接（如漏注入字数区间）。
    extra 传工序特有数据（如 reviser 的 issues_txt）。
    """
    bc = build_context(book_id, chapter, cfg)
    ctx = dict(bc)
    t = text or ""
    ctx["chapter_text"] = t
    ctx["chapter_actual_words"] = store.count_words(t)
    if role in ("writer", "auditor", "reviser", "title"):
        ctx["plan"] = plan or "（未生成写作意图）"
    if role == "observer":
        ctx["current_state"] = bc["facts"]
    if role == "reviser":
        ctx["issues"] = (extra or {}).get("issues_txt", "")
    if role == "title":
        book = store.get_book(book_id)
        ctx["book_title"] = book.get("title", "")
        ctx["genre"] = book.get("genre", "")
        ctx["chapter_tail"] = t[-800:]
        ctx["chapter_text"] = t[:1600]   # 标题只取开头
    return ctx


# ---------------- 加固#4：幂等 + 版本号 ----------------

def _invalidate_downstream(book_id: str, chapter: int) -> list:
    """重跑写章时，把已存在的下游产物（审计/改写/摘要/抽取）归档到 _archive，
    避免旧版与新正文错配（正文变了，这些判定自然失效）。返回被归档的步骤名。"""
    moved = []
    for kind in ("audit", "revise"):
        p = store.draft_path(book_id, chapter, kind)
        if os.path.exists(p):
            old = store.read_draft(book_id, chapter, kind)
            if old.strip():
                store._archive_draft(book_id, chapter, kind, old)
                os.remove(p)
                moved.append(kind)
    if os.path.exists(store.summary_path(book_id, chapter)):
        old = store.read_summary(book_id, chapter)
        if old.strip():
            store._archive_draft(book_id, chapter, "summary", old)
            os.remove(store.summary_path(book_id, chapter))
            moved.append("summary")
    if os.path.exists(store.extraction_path(book_id, chapter)):
        old = store.read_extraction(book_id, chapter)
        if old:
            store._archive_draft(book_id, chapter, "extraction", json_dump(old))
            os.remove(store.extraction_path(book_id, chapter))
            moved.append("extraction")
    return moved


# ---------------- 各工序 ----------------

def _scan_json_string(s: str, start: int) -> str:
    """从 start（已越过 "text": " 的开头引号）逐字符扫描一个 JSON 字符串。

    容忍正文里的裸英文双引号（未转义）：只有当遇到引号且其后（跳过空白）
    是 , 或 } 时才视为字符串结束，否则当正文引号保留。同时解码常见转义。
    """
    out = []
    i = start
    esc = False
    while i < len(s):
        ch = s[i]
        if esc:
            if ch == 'n': out.append('\n')
            elif ch == 't': out.append('\t')
            elif ch == 'r': out.append('\r')
            elif ch == '"': out.append('"')
            elif ch == '\\': out.append('\\')
            elif ch == '/': out.append('/')
            elif ch == 'b': out.append('\b')
            elif ch == 'f': out.append('\f')
            else: out.append(ch)
            esc = False; i += 1; continue
        if ch == '\\':
            esc = True; i += 1; continue
        if ch == '"':
            j = i + 1
            while j < len(s) and s[j] in ' \t\r\n':
                j += 1
            if j < len(s) and s[j] in ',}':
                return ''.join(out)   # 字符串结束
            out.append(ch); i += 1; continue
        out.append(ch); i += 1
    return ''.join(out)


def _payload_text(raw: str) -> str:
    """模型可能返回 {text, report} 的 JSON 包裹，这里容错提取纯正文。

    纯文本直接原样返回；以 { 或 [ 开头时先尝试标准 JSON 解析取 text 字段；
    若解析失败（如正文含未转义英文引号损坏 JSON），则逐字符扫描容错提取，
    避免把结构当正文写盘。
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith(("{", "[")):
        parsed = base.extract_json(raw)
        if isinstance(parsed, dict) and parsed.get("text"):
            return str(parsed["text"]).strip()
        m = re.search(r'"text"\s*:\s*"', raw)
        if m:
            txt = _scan_json_string(raw, m.end()).strip()
            if txt:
                return txt
    return raw


def plan_chapter(book_id: str, chapter: int, cfg: dict = None) -> dict:
    cfg = cfg or base.load_config()
    ctx = role_ctx(book_id, chapter, "planner", cfg)
    text, meta = base.run("planner", "planner", ctx, store.book_dir(book_id), chapter, cfg=cfg)
    store.write_draft(book_id, chapter, "plan", text)
    return {"plan": text, "meta": meta}


def write_chapter_stream(book_id: str, chapter: int, cfg: dict = None,
                         plan: str = "") -> Iterator[dict]:
    cfg = cfg or base.load_config()
    plan = plan or store.read_draft(book_id, chapter, "plan")
    if not plan:
        plan = plan_chapter(book_id, chapter, cfg)["plan"]
    ctx = role_ctx(book_id, chapter, "writer", cfg, plan=plan)
    temp = cfg.get("defaults", {}).get("temperature_writer")
    for ev in base.stream("writer", "writer", ctx, store.book_dir(book_id), chapter,
                          temperature=temp, cfg=cfg):
        if ev["type"] == "done":
            store.write_draft(book_id, chapter, "draft", _payload_text(ev["text"]))
            _invalidate_downstream(book_id, chapter)
        yield ev


def write_chapter(book_id: str, chapter: int, cfg: dict = None, plan: str = "") -> dict:
    """非流式写章，供脚本 / 批量连写使用。"""
    cfg = cfg or base.load_config()
    plan = plan or store.read_draft(book_id, chapter, "plan")
    if not plan:
        plan = plan_chapter(book_id, chapter, cfg)["plan"]
    ctx = role_ctx(book_id, chapter, "writer", cfg, plan=plan)
    temp = cfg.get("defaults", {}).get("temperature_writer")
    text, meta = base.run("writer", "writer", ctx, store.book_dir(book_id), chapter,
                          temperature=temp, cfg=cfg)
    final = _payload_text(text)
    store.write_draft(book_id, chapter, "draft", final)
    moved = _invalidate_downstream(book_id, chapter)
    return {"text": final, "meta": meta, "plan": plan, "invalidated": moved}


def observe_and_apply(book_id: str, chapter: int, text: str = "", cfg: dict = None) -> dict:
    """抽取本章事实 → 校验 → 不可变更新真相文件。"""
    cfg = cfg or base.load_config()
    text = text or store.read_draft(book_id, chapter, "draft")
    if not text.strip():
        return {"delta": {}, "applied": False, "reason": "没有正文可抽取"}

    ctx = role_ctx(book_id, chapter, "observer", cfg, text=text)
    raw, meta = base.run("observer", "observer", ctx, store.book_dir(book_id), chapter, cfg=cfg)
    delta = base.extract_json(raw)
    if not delta:
        return {"delta": {}, "applied": False, "reason": "模型未返回合法 JSON", "raw": raw[:500], "meta": meta}
    # 截断修复可能只恢复部分字段，补齐空结构防止 KeyError
    delta.setdefault("characters", {})
    delta.setdefault("relations", [])
    delta.setdefault("items", {})
    delta.setdefault("time_advance", "")
    delta.setdefault("facts", [])
    delta.setdefault("new_hooks", [])
    delta.setdefault("resolved_hooks", [])
    delta.setdefault("emotions", [])

    applied = apply_delta(book_id, chapter, delta)
    return {"delta": delta, "applied": applied, "meta": meta}


def apply_delta(book_id: str, chapter: int, delta: dict) -> bool:
    """把 delta 写进真相文件。只做增量更新，不做整体覆盖。"""
    try:
        state = store.get_state(book_id)
        for name, patch in (delta.get("characters") or {}).items():
            if not isinstance(patch, dict):
                continue
            cur = state.setdefault("characters", {}).setdefault(name, {})
            cur.update(patch)
        for f in delta.get("facts") or []:
            notes = state.setdefault("notes", [])
            if isinstance(f, str) and f not in notes:
                notes.append("[第%d章] %s" % (chapter, f))
        for rel in delta.get("relations") or []:
            if isinstance(rel, dict):
                notes = state.setdefault("notes", [])
                line = "[第%d章·关系] %s" % (chapter, json_cn(rel))
                if line not in notes:   # 幂等：重复抽取不重复追加
                    notes.append(line)
        for emo in delta.get("emotions") or []:
            if isinstance(emo, dict):
                notes = state.setdefault("notes", [])
                line = "[第%d章·情感] %s" % (chapter, json_cn(emo))
                if line not in notes:   # 幂等：重复抽取不重复追加
                    notes.append(line)
        if delta.get("time_advance"):
            state.setdefault("world", {})["最近时间线"] = "[第%d章] %s" % (chapter, delta["time_advance"])
        store.set_state(book_id, state)

        ledger = store.get_ledger(book_id)
        for item, info in (delta.get("items") or {}).items():
            if isinstance(info, dict):
                ledger.setdefault("items", {})[item] = info
        store.set_ledger(book_id, ledger)

        hooks = store.get_hooks(book_id)
        pool = hooks.setdefault("hooks", [])
        maxid = 0
        seen_text = set()
        for h in pool:
            m = (h.get("id") or "").lstrip("H")
            if m.isdigit():
                maxid = max(maxid, int(m))
            seen_text.add(_norm_ev(h.get("text", "")))
        for nh in delta.get("new_hooks") or []:
            if isinstance(nh, dict) and nh.get("text"):
                norm = _norm_ev(nh["text"])
                if norm in seen_text:
                    # 与已有伏笔（无论 open/resolved）高度重复则跳过，
                    # 避免「陆淮舟心动值=0」这种事实被反复记成 H003、H060 多个编号
                    continue
                seen_text.add(norm)
                maxid += 1
                pool.append({
                    "id": "H%03d" % maxid,
                    "text": nh["text"],
                    "planted_ch": chapter,
                    "due_chapter": int(nh.get("due_chapter") or 0),
                    "status": "open",
                    "resolved_ch": None,
                })
        for rh in delta.get("resolved_hooks") or []:
            if not isinstance(rh, dict):
                continue
            key = (rh.get("id") or "").strip()
            txt = (rh.get("text") or "").strip()
            for h in pool:
                if key and h.get("id") == key:
                    h["status"] = "resolved"
                    h["resolved_ch"] = chapter
                    break
                if not key and txt and txt[:12] in (h.get("text") or ""):
                    h["status"] = "resolved"
                    h["resolved_ch"] = chapter
                    break
        store.set_hooks(book_id, hooks)
        return True
    except Exception as e:
        return False


def audit_chapter(book_id: str, chapter: int, text: str = "", plan: str = "",
                  cfg: dict = None) -> dict:
    cfg = cfg or base.load_config()
    text = text or store.read_draft(book_id, chapter, "draft")
    plan = plan or store.read_draft(book_id, chapter, "plan")
    if not text.strip():
        return {"passed": False, "score": 0, "issues": [], "summary": "没有正文可审计"}
    # 加固#2 确定性硬校验：先算"事实"（字数/污染/占位符），模型目测不能覆盖
    det_issues = deterministic_checks(book_id, chapter, text, cfg)
    ctx = role_ctx(book_id, chapter, "auditor", cfg, text=text, plan=plan)
    raw, meta = base.run("auditor", "auditor", ctx, store.book_dir(book_id),
                         chapter, cfg=cfg)
    report = base.extract_json(raw)
    if not report:
        report = {"issues": [], "summary": "模型未返回合法 JSON（已用确定性校验兜底）"}
    model_issues = report.get("issues") or []
    # 加固#5 审计双轨：确定性优先，剔除模型对同 id 的判断，模型补 A1-A11 等
    det_ids = {str(i.get("id", "")) for i in det_issues}
    merged = list(det_issues) + [i for i in model_issues
                                 if str(i.get("id", "")) not in det_ids]
    report["issues"] = merged
    report["critical_count"] = sum(
        1 for i in merged if str(i.get("level", "")).lower() == "critical")
    report["passed"] = report["critical_count"] == 0
    report["score"] = _score_from_issues(merged)
    report["chapter_actual_words"] = store.count_words(text)
    report["det_checks"] = len(det_issues)   # 标记本轮用了确定性校验
    if not report.get("summary"):
        report["summary"] = "（模型未返回合法 JSON，仅确定性校验结论）"
    report["meta"] = meta
    store.write_draft(book_id, chapter, "audit", json_dump(report))
    return report


def _norm_ev(s: str) -> str:
    """归一化字符串用于模糊匹配（去所有空白）。"""
    return re.sub(r"\s+", "", s or "")


def _build_revise_report(todo: list, old_text: str, new_text: str,
                         model_report: list) -> list:
    """生成「改写报告」：每条审计问题 → 是否处理 + 如何改的。

    优先用模型返回的 report（issue_id 对齐）；缺失时用证据对比兜底：
    改后正文里已不再出现该问题的 evidence → 视为已处理。
    """
    mrep = {}
    for it in (model_report or []):
        if isinstance(it, dict):
            iid = str(it.get("issue_id") or it.get("id") or "").strip()
            if iid:
                mrep[iid] = it
    rows = []
    for i in todo:
        iid = str(i.get("id") or "?")
        ev = (i.get("evidence") or "").strip()
        m = mrep.get(iid)
        if m:
            handled = bool(m.get("handled", True))
            how = (m.get("how") or m.get("note") or "").strip() or \
                ("已按审计意见处理" if handled else "未处理")
        elif ev:
            handled = _norm_ev(ev) not in _norm_ev(new_text)
            how = ("该问题的证据已不再出现在正文中" if handled
                   else "正文中仍能检测到该问题的证据，可能未修复")
        else:
            handled = True
            how = "已处理"
        rows.append({
            "issue_id": iid, "level": i.get("level"), "desc": i.get("desc"),
            "evidence": ev, "handled": handled, "how": how,
        })
    return rows


def _build_rounds_report(rounds_detail: list, note: str = "") -> dict:
    """构造「轮次感知」改写报告对象。

    rounds_detail: [{"round": 1, "issues": [...], "outcome": "..."}, ...]
    note: 说明文本（如「因审计无问题，没有进行改写」）。
    """
    return {"rounds": len(rounds_detail), "rounds_detail": rounds_detail, "note": note}


def write_revise_report(book_id: str, chapter: int, rounds_detail: list,
                        note: str = "") -> dict:
    """落盘「轮次感知」改写报告（覆盖旧版），返回对象。"""
    obj = _build_rounds_report(rounds_detail, note)
    store.write_draft(book_id, chapter, "revise", json_dump(obj))
    return obj


def revise_chapter(book_id: str, chapter: int, text: str = "", issues: list = None,
                   cfg: dict = None) -> dict:
    cfg = cfg or base.load_config()
    text = text or store.read_draft(book_id, chapter, "draft")
    issues = issues or []
    # 用户要求：审计提出的所有问题（critical/major/minor）全部修改
    todo = list(issues)
    if not todo:
        # 审计无问题 → 按用户要求写明「因审计无问题，没有进行改写」
        obj = write_revise_report(book_id, chapter, [], "因审计无问题，没有进行改写")
        return {"text": text, "changed": False, "report": [], "revise_obj": obj}
    issues_txt = "\n".join(
        "- [%s|%s] %s（依据：%s）修改方向：%s" % (
            i.get("id", "?"), i.get("level", "?"), i.get("desc", ""),
            (i.get("evidence", "") or "")[:60], i.get("fix", ""),
        ) for i in todo
    )
    ctx = role_ctx(book_id, chapter, "reviser", cfg, text=text,
                   extra={"issues_txt": issues_txt})
    raw, meta = base.run("reviser", "reviser", ctx, store.book_dir(book_id),
                         chapter, cfg=cfg)
    raw = (raw or "").strip()
    # 优先解析结构化返回 {text, report}；纯文本则整体当作正文。
    # 用容错提取：正文含裸英文引号会破坏 JSON，此时逐字符扫描保住正文。
    model_report = None
    if raw.startswith(("{", "[")):
        parsed = base.extract_json(raw)
        if isinstance(parsed, dict) and parsed.get("text"):
            new_text = str(parsed["text"]).strip()
            model_report = parsed.get("report")
        else:
            new_text = _payload_text(raw)
    else:
        new_text = raw
    if not new_text:
        obj = write_revise_report(book_id, chapter, [],
                                  "本轮改写未能产出有效新文本，正文未变更")
        return {"text": text, "changed": False, "meta": meta, "report": [],
                "revise_obj": obj}
    report = _build_revise_report(todo, text, new_text, model_report)
    store.write_draft(book_id, chapter, "draft", new_text)
    # 轮次感知：单轮改写（独立触发 / full_chapter 各轮）先落 rounds=1 的对象；
    # full_chapter 结束后会用累积的 rounds_detail 覆盖写入完整轮次报告。
    handled = sum(1 for x in report if x.get("handled"))
    obj = write_revise_report(book_id, chapter, [{
        "round": 1,
        "issues": report,
        "outcome": "本轮共 %d 条问题，处理 %d 条" % (len(report), handled),
    }])
    return {"text": new_text, "changed": True, "meta": meta, "report": report,
            "revise_obj": obj}


def summarize_chapter(book_id: str, chapter: int, text: str = "", cfg: dict = None) -> dict:
    cfg = cfg or base.load_config()
    text = text or store.read_draft(book_id, chapter, "draft")
    ctx = role_ctx(book_id, chapter, "summary", cfg, text=text)
    s, meta = base.run("summary", "summary", ctx, store.book_dir(book_id), chapter, cfg=cfg)
    store.write_summary(book_id, chapter, s.strip())
    return {"summary": s.strip(), "meta": meta}


def accept_chapter(book_id: str, chapter: int, title: str = "", text: str = "") -> dict:
    """人工闸门：只有点「采纳」才写入正文章节文件。"""
    text = text or store.read_draft(book_id, chapter, "draft")
    if not text.strip():
        return {"ok": False, "reason": "没有可采纳的正文"}
    # 标题持久化：前端传来的标题（人工可改）优先；为空则保留已生成的标题
    if title and title.strip():
        store.write_title(book_id, chapter, title.strip())
    snap = store.snapshot(book_id, chapter)
    fn = store.write_chapter(book_id, chapter, title or "", text)
    return {"ok": True, "file": fn, "words": store.count_words(text), "snapshot": snap,
            "title": store.get_title(book_id, chapter)}


def generate_title(book_id: str, chapter: int, text: str = "", plan: str = "") -> str:
    """根据正文与意图，让模型起一个章节标题，并落盘到 titles.json。

    纯增值步骤：失败也不影响正文，返回空串即可。
    """
    text = text or store.read_draft(book_id, chapter, "draft") or store.read_chapter(book_id, chapter)
    plan = plan or store.read_draft(book_id, chapter, "plan")
    if not (text and text.strip()):
        return ""
    cfg = base.load_config()
    ctx = role_ctx(book_id, chapter, "title", cfg, text=text, plan=plan)
    try:
        raw, _ = base.run("writer", "title", ctx, store.book_dir(book_id), chapter)
    except Exception:
        return ""
    t = (raw or "").strip().strip('"').strip("'").strip()
    t = t.split("\n")[0].strip()
    # 去掉模型可能自作主张加的「第X章」前缀
    t = re.sub(r"^第[0-9零一二三四五六七八九十百千]+章[：: ]*", "", t).strip()
    t = t[:24]
    if not t:
        return ""
    store.write_title(book_id, chapter, t)
    return t


def _summarize_observe(ob) -> dict:
    """把抽取事实的结果压缩成前端可读的摘要（计数 + 关键字段）。"""
    if not ob:
        return None
    d = ob.get("delta") or {}
    return {
        "applied": bool(ob.get("applied")),
        "reason": ob.get("reason", ""),
        "characters": len(d.get("characters") or {}),
        "facts": len(d.get("facts") or []),
        "items": len(d.get("items") or {}),
        "new_hooks": len(d.get("new_hooks") or []),
        "resolved_hooks": len(d.get("resolved_hooks") or []),
        "relations": len(d.get("relations") or []),
        "emotions": len(d.get("emotions") or []),
        "time_advance": d.get("time_advance", ""),
    }


def full_chapter(book_id: str, chapter: int, cfg: dict = None,
                 auto_revise: int = 1, do_apply: bool = True, do_summary: bool = True,
                 progress=None, reuse_plan: bool = True) -> dict:
    """一键跑完整章：规划→写作→抽取→审计→(自动修订N轮)→摘要。不自动采纳。

    progress(step, status, detail) 可选回调，每步 start/done/fail 时触发，
    供前端实时高亮当前步骤（step ∈ plan/write/audit/revise/observe/summary）。
    """
    cfg = cfg or base.load_config()
    log = []
    t0 = time.time()

    def _p(step, status, detail=None):
        if progress:
            try:
                progress(step, status, detail or {})
            except Exception:
                pass

    _p("plan", "start")
    existing_plan = ""
    if reuse_plan:
        try:
            existing_plan = store.read_draft(book_id, chapter, "plan") or ""
        except Exception:
            existing_plan = ""
    if existing_plan:
        # 本章意图早已生成并落盘，直接复用，避免重复消耗模型额度
        p = {"plan": existing_plan, "meta": {"model": "（复用已生成意图）", "reused": True}}
        log.append({"step": "plan", "ok": True, "meta": p["meta"], "reused": True})
        _p("plan", "done", {"reused": True})
    else:
        p = plan_chapter(book_id, chapter, cfg)
        log.append({"step": "plan", "ok": True, "meta": p["meta"]})
        _p("plan", "done")

    _p("write", "start")
    w = write_chapter(book_id, chapter, cfg, plan=p["plan"])
    text = w["text"]
    log.append({"step": "write", "ok": True, "meta": w["meta"], "words": store.count_words(text)})
    _p("write", "done", {"words": store.count_words(text)})

    _p("audit", "start")
    report = audit_chapter(book_id, chapter, text, p["plan"], cfg)
    log.append({"step": "audit", "ok": report.get("passed", False),
                "score": report.get("score", 0), "critical": report.get("critical_count", 0)})
    _p("audit", "done", {"passed": report.get("passed", False),
                         "score": report.get("score", 0)})

    rounds = 0
    rounds_detail = []
    # 用户要求：审计出现的【所有】问题（critical/major/minor）都要在定点改写里修复，
    # 不只要等出现致命问题才改。只要还有 issues 且未超过 auto_revise 轮数就继续改写。
    def _issue_count(rep):
        return len((rep.get("issues") or []))
    first_audit_passed = _issue_count(report) == 0
    while _issue_count(report) > 0 and rounds < int(auto_revise or 0):
        try:
            _p("revise", "start", {"round": rounds + 1,
                                   "issues": _issue_count(report)})
            r = revise_chapter(book_id, chapter, text, report.get("issues", []), cfg)
        except Exception as e:
            log.append({"step": "revise#%d" % (rounds + 1), "ok": False, "error": str(e)[:200]})
            _p("revise", "fail", {"round": rounds + 1, "error": str(e)[:200]})
            break
        if not r.get("changed"):
            # 本轮改写未生效（模型没产出新文本 / 无可改问题）：保留已落盘内容
            _p("revise", "done", {"round": rounds + 1, "changed": False})
            break
        text = r["text"]
        rounds += 1
        report = audit_chapter(book_id, chapter, text, p["plan"], cfg)
        remaining = _issue_count(report)
        # 记录本轮：改了什么（r["report"]）+ 复检结果
        handled = sum(1 for x in (r.get("report") or []) if x.get("handled"))
        total = len(r.get("report") or [])
        if remaining:
            outcome = ("第%d轮：共%d条问题，处理%d条；复检后仍剩%d条（其中%d条致命），"
                        "进入下一轮" % (rounds, total, handled, remaining,
                                        report.get("critical_count", 0)))
        else:
            outcome = ("第%d轮：共%d条问题，全部处理；复检问题清零，改写完成"
                       % (rounds, total))
        rounds_detail.append({"round": rounds, "issues": r.get("report") or [],
                              "outcome": outcome})
        log.append({"step": "revise#%d" % rounds, "ok": remaining == 0,
                    "score": report.get("score", 0), "critical": report.get("critical_count", 0),
                    "remaining": remaining})
        _p("revise", "done", {"round": rounds, "changed": True,
                              "passed": report.get("passed", False),
                              "remaining": remaining})

    # 轮次感知改写报告：整条链路审计最初就无问题 → 「因审计无问题，没有进行改写」；
    # 有累积轮次 → 写完整多轮报告；否则保留 revise_chapter 已落盘的单轮内容。
    if first_audit_passed:
        write_revise_report(book_id, chapter, [], "因审计无问题，没有进行改写")
    elif rounds_detail:
        write_revise_report(book_id, chapter, rounds_detail)

    # 章标题：正文定稿后（改写循环结束）让模型起名，写入 titles.json
    try:
        _title = generate_title(book_id, chapter, text, p.get("plan"))
    except Exception:
        _title = ""

    # 观察者 / 摘要：失败不再整条中断，记录到 log，前端可看到哪步挂了并单独重跑
    observe_res = None
    summary_res = None
    if do_apply:
        try:
            _p("observe", "start")
            observe_res = observe_and_apply(book_id, chapter, text, cfg)
            if observe_res.get("delta"):
                store.write_extraction(book_id, chapter, observe_res["delta"])
            log.append({"step": "observe", "ok": True})
            _p("observe", "done", {"applied": bool(observe_res.get("applied"))})
        except Exception as e:
            log.append({"step": "observe", "ok": False, "error": str(e)[:200]})
            _p("observe", "fail", {"error": str(e)[:200]})
    if do_summary:
        try:
            _p("summary", "start")
            summary_res = summarize_chapter(book_id, chapter, text, cfg)
            log.append({"step": "summary", "ok": True})
            _p("summary", "done")
        except Exception as e:
            log.append({"step": "summary", "ok": False, "error": str(e)[:200]})
            _p("summary", "fail", {"error": str(e)[:200]})

    return {
        "chapter": chapter,
        "passed": report.get("passed", False),
        "score": report.get("score", 0),
        "report": report,
        "text": text,
        "title": _title,
        "log": log,
        "elapsed": round(time.time() - t0, 1),
        "observe": _summarize_observe(observe_res),
        "observe_delta": (observe_res or {}).get("delta") or {},
        "summary": (summary_res or {}).get("summary", ""),
    }


# ---------------- 小工具 ----------------

def json_cn(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def json_dump(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)
