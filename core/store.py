# -*- coding: utf-8 -*-
"""
项目存储层。核心原则：文件即数据库。

所有状态都是你能用记事本打开的 md / json，工作台只是读写这些文件的一层壳。
任何时候都可以丢掉工作台，直接手改文件。
"""
import json
import os
import re
import shutil
import time
from typing import Dict, List

PROJECTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "projects")

CHAPTER_RE = re.compile(r"(?:第\s*)?(\d{1,4})\s*章")
SAFE_RE = re.compile(r"[\\/:*?\"<>|]")


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _write_text(path: str, text: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------- 项目 ----------------

def list_books() -> List[dict]:
    out = []
    if not os.path.exists(PROJECTS_DIR):
        return out
    for name in sorted(os.listdir(PROJECTS_DIR)):
        d = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(d):
            continue
        book = _read_json(os.path.join(d, "book.json"), None)
        if not book:
            continue
        chapters = list_chapters(name)
        words = sum(c.get("words", 0) for c in chapters)
        out.append({
            "id": name,
            "title": book.get("title", name),
            "genre": book.get("genre", ""),
            "chapter_count": len(chapters),
            "words": words,
            "updated": book.get("updated", ""),
        })
    return out


def book_dir(book_id: str) -> str:
    return os.path.join(PROJECTS_DIR, book_id)


def get_book(book_id: str) -> dict:
    return _read_json(os.path.join(book_dir(book_id), "book.json"), {})


def save_book(book_id: str, book: dict) -> dict:
    book["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_json(os.path.join(book_dir(book_id), "book.json"), book)
    return book


def create_book(payload: dict) -> dict:
    title = (payload.get("title") or "未命名").strip()
    bid = payload.get("id") or ("".join(c for c in title if c.isalnum() or "\u4e00" <= c <= "\u9fff"))
    bid = SAFE_RE.sub("_", bid)[:40] or ("book_%d" % int(time.time()))
    d = book_dir(bid)
    os.makedirs(d, exist_ok=True)
    book = {
        "id": bid,
        "title": title,
        "genre": payload.get("genre", ""),
        "premise": payload.get("premise", ""),
        "chapter_words": int(payload.get("chapter_words") or 2000),
        "chapters_dir": payload.get("chapters_dir") or "",   # 留空 = projects/<id>/chapters
        "style": payload.get("style", ""),
        "taboos": payload.get("taboos", ""),
        "outline": payload.get("outline", ""),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_json(os.path.join(d, "book.json"), book)
    for sub in ["chapters", "summaries", "snapshots", "drafts"]:
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    for fn, default in [("state.json", {"characters": {}, "world": {}, "notes": []}),
                        ("ledger.json", {"items": {}}),
                        ("hooks.json", {"hooks": []})]:
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            _write_json(p, default)
    return book


# ---------------- 章节 ----------------

def chapters_dir(book_id: str) -> str:
    book = get_book(book_id)
    ext = (book.get("chapters_dir") or "").strip()
    d = ext if ext else os.path.join(book_dir(book_id), "chapters")
    os.makedirs(d, exist_ok=True)
    return d


def chapter_num(filename: str) -> int:
    m = CHAPTER_RE.search(filename)
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{1,4})", filename)
    return int(m2.group(1)) if m2 else -1


def list_chapters(book_id: str) -> List[dict]:
    d = chapters_dir(book_id)
    out = []
    if not os.path.exists(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith((".md", ".txt")):
            continue
        num = chapter_num(fn)
        if num < 0:
            continue
        text = _read_text(os.path.join(d, fn))
        out.append({
            "num": num,
            "file": fn,
            "title": get_title(book_id, num),
            "words": count_words(text),
            "has_summary": os.path.exists(os.path.join(book_dir(book_id), "summaries", "ch%03d.md" % num)),
        })
    out.sort(key=lambda x: x["num"])
    return out


def read_chapter(book_id: str, num: int) -> str:
    for c in list_chapters(book_id):
        if c["num"] == num:
            return _read_text(os.path.join(chapters_dir(book_id), c["file"]))
    return ""


def next_chapter_num(book_id: str) -> int:
    nums = [c["num"] for c in list_chapters(book_id)]
    return (max(nums) + 1) if nums else 1


def titles_path(book_id: str) -> str:
    return os.path.join(book_dir(book_id), "titles.json")


def read_titles(book_id: str) -> dict:
    """章号(str) → 标题 的映射。"""
    return _read_json(titles_path(book_id), {})


def write_title(book_id: str, num: int, title: str) -> None:
    """写入单章标题（覆盖式更新，不破坏其它章）。"""
    d = read_titles(book_id)
    key = str(int(num))
    clean = (title or "").strip().strip('"').strip("'").strip()
    if clean:
        d[key] = clean[:40]
        _write_json(titles_path(book_id), d)


def get_title(book_id: str, num: int) -> str:
    """取某章标题；无则回落「第NNN章」。"""
    t = (read_titles(book_id).get(str(int(num))) or "").strip()
    return t or ("第%03d章" % int(num))


def write_chapter(book_id: str, num: int, title: str, text: str) -> str:
    d = chapters_dir(book_id)
    safe = SAFE_RE.sub("_", (title or "").strip())[:40]
    fn = "第%03d章_%s.md" % (num, safe) if safe else "第%03d章.md" % num
    # 若已存在同章号文件则覆盖它，避免产生重复
    for c in list_chapters(book_id):
        if c["num"] == num:
            fn = c["file"]
            break
    _write_text(os.path.join(d, fn), text)
    return fn


def count_words(text: str) -> int:
    """非空白 Unicode 字符计数，与中文字数统计一致。"""
    return len([c for c in text if not c.isspace()])


def export_book(book_id: str, fmt: str = "txt"):
    """把所有正式章节拼成一份文档，返回 (文件名, 内容, MIME)。fmt 支持 txt / md。

    只导出 chapters 目录下的正式章节（按章号排序），不含草稿；正文文件本身没有章标题，
    导出时统一补上「第NNN章」标题，便于直接拿去排版或投递。
    """
    book = get_book(book_id)
    title = book.get("title", book_id)
    chapters = list_chapters(book_id)
    now = time.strftime("%Y-%m-%d %H:%M")
    sep = "=" * 22
    lines = []

    def _heading(num):
        """导出标题 = 章号 + 标题。get_title 无标题时已回落「第NNN章」，不重复章号。"""
        title = get_title(book_id, num)
        if re.match(r"^第\d+章", title):
            return title
        return "第%03d章 %s" % (num, title)

    if fmt == "md":
        lines.append("# %s" % title)
        if book.get("genre"):
            lines.append("")
            lines.append("> %s" % book.get("genre"))
        lines.append("")
        lines.append("**导出时间**：%s  " % now)
        lines.append("**章节数**：%d  " % len(chapters))
        lines.append("")
        for c in chapters:
            lines.append("## %s" % _heading(c["num"]))
            lines.append("")
            lines.append(read_chapter(book_id, c["num"]).rstrip())
            lines.append("")
    else:
        lines.append(title)
        if book.get("genre"):
            lines.append(book.get("genre"))
        lines.append("导出时间：%s · 共 %d 章" % (now, len(chapters)))
        lines.append("")
        for c in chapters:
            lines.append(sep)
            lines.append(_heading(c["num"]))
            lines.append(sep)
            lines.append(read_chapter(book_id, c["num"]).rstrip())
            lines.append("")
    content = "\n".join(lines).rstrip() + "\n"
    ext = "md" if fmt == "md" else "txt"
    safe = SAFE_RE.sub("_", title)[:40] or book_id
    fname = "%s.%s" % (safe, ext)
    mime = "text/markdown; charset=utf-8" if fmt == "md" else "text/plain; charset=utf-8"
    return fname, content, mime


# ---------------- 状态 / 账本 / 伏笔 ----------------

def state_path(book_id: str, name: str) -> str:
    return os.path.join(book_dir(book_id), name)


def get_state(book_id: str) -> dict:
    return _read_json(state_path(book_id, "state.json"), {"characters": {}, "world": {}, "notes": []})


def set_state(book_id: str, data: dict) -> dict:
    _write_json(state_path(book_id, "state.json"), data)
    return data


def get_ledger(book_id: str) -> dict:
    return _read_json(state_path(book_id, "ledger.json"), {"items": {}})


def set_ledger(book_id: str, data: dict) -> dict:
    _write_json(state_path(book_id, "ledger.json"), data)
    return data


def get_hooks(book_id: str) -> dict:
    return _read_json(state_path(book_id, "hooks.json"), {"hooks": []})


def set_hooks(book_id: str, data: dict) -> dict:
    _write_json(state_path(book_id, "hooks.json"), data)
    return data


def _flatten(v) -> str:
    """把状态字段值压成人能读的一段文字，避免 JSON 字面量混进投影。"""
    if v in (None, ""):
        return ""
    if isinstance(v, list):
        return "、".join(_flatten(x) for x in v if _flatten(x))
    if isinstance(v, dict):
        return "；".join("%s=%s" % (k, _flatten(x)) for k, x in v.items() if _flatten(x))
    return str(v).strip()


def _pretty_note(text: str) -> str:
    """观察者写进 notes 的结构化 JSON（关系/情感）翻成人话，字段一条不丢。"""
    t = (text or "").strip()
    b = t.find("{")
    if b <= 0 or not t.rstrip().endswith("}"):
        return t
    head = t[:b].strip()
    try:
        o = json.loads(t[b:].strip())
    except Exception:
        return t
    if not isinstance(o, dict):
        return t
    if o.get("a") and o.get("b"):
        rel = "%s → %s" % (o["a"], o["b"])
        if o.get("type"):
            rel += "（%s）" % o["type"]
        return "%s%s%s" % (head, rel, "：" + o["change"] if o.get("change") else "")
    if o.get("character"):
        return "%s%s：%s" % (head, o["character"], o.get("turn") or _flatten(o))
    return "%s%s" % (head, "；".join("%s=%s" % (k, _flatten(v)) for k, v in o.items() if _flatten(v)))


def markdown_projection(book_id: str) -> str:
    """把结构化状态投影成一份人能读的 Markdown，界面「世界状态」面板和模型上下文都用它。"""
    s = get_state(book_id)
    l = get_ledger(book_id)
    h = get_hooks(book_id)
    lines = ["# 世界状态（自动维护的事实台账，可直接改 state.json 干预）", ""]

    lines.append("## 角色")
    for name, info in (s.get("characters") or {}).items():
        flat = ["%s：%s" % (k, _flatten(v)) for k, v in (info or {}).items() if _flatten(v)]
        lines.append("- **%s**：%s" % (name, "｜".join(flat) or "（空）"))

    lines.append("")
    lines.append("## 世界观")
    world = [(k, _flatten(v)) for k, v in (s.get("world") or {}).items() if _flatten(v)]
    lines.extend(["- **%s**：%s" % (k, v) for k, v in world] or ["- （空）"])

    lines.append("")
    lines.append("## 事实笔记")
    notes = [(t or "").strip() for t in (s.get("notes") or []) if (t or "").strip()]
    lines.extend(["- " + _pretty_note(t) for t in notes] or ["- （空）"])

    lines.append("")
    lines.append("## 资源账本")
    items = [(k, _flatten(v)) for k, v in (l.get("items") or {}).items() if _flatten(v)]
    lines.extend(["- **%s**：%s" % (k, v) for k, v in items] or ["- （空）"])

    lines.append("")
    lines.append("## 伏笔池")
    hooks = h.get("hooks") or []
    for hk in hooks:
        flag = "✅已回收" if hk.get("status") == "resolved" else "⏳待回收"
        due = hk.get("due_chapter")
        tail = "（预期第%d章回收）" % due if due else ""
        lines.append("- %s `%s` %s%s" % (flag, hk.get("id", "?"), hk.get("text", ""), tail))
    if not hooks:
        lines.append("- （空）")
    return "\n".join(lines) + "\n"


# ---------------- 摘要 / 草稿 / 快照 ----------------

def summary_path(book_id: str, num: int) -> str:
    return os.path.join(book_dir(book_id), "summaries", "ch%03d.md" % num)


def write_summary(book_id: str, num: int, text: str) -> None:
    _write_text(summary_path(book_id, num), text)


def read_summary(book_id: str, num: int) -> str:
    return _read_text(summary_path(book_id, num))


# 抽取事实(delta) 以 JSON 单独落盘，便于前端「已抽事实」标签刷新后恢复
def extraction_path(book_id: str, num: int) -> str:
    return os.path.join(book_dir(book_id), "extractions", "ch%03d.json" % num)


def write_extraction(book_id: str, num: int, delta: dict) -> None:
    import json as _json
    _write_text(extraction_path(book_id, num),
                _json.dumps(delta, ensure_ascii=False, indent=2))


def read_extraction(book_id: str, num: int) -> dict:
    import json as _json
    try:
        t = _read_text(extraction_path(book_id, num))
        return _json.loads(t) if t.strip() else {}
    except Exception:
        return {}


def recent_summaries(book_id: str, n: int, before: int) -> List[str]:
    out = []
    for num in range(max(1, before - n), before):
        t = read_summary(book_id, num)
        if t.strip():
            out.append("### 第%d章摘要\n%s" % (num, t.strip()))
    return out


def draft_path(book_id: str, num: int, kind: str = "draft") -> str:
    return os.path.join(book_dir(book_id), "drafts", "ch%03d.%s.md" % (num, kind))


def _archive_draft(book_id: str, num: int, kind: str, content: str) -> str:
    """把某章某步骤的旧产物归档到 drafts/_archive/（版本号=时间戳），可回溯。"""
    arc = os.path.join(book_dir(book_id), "drafts", "_archive")
    os.makedirs(arc, exist_ok=True)
    fn = "ch%03d.%s.rev-%s.md" % (num, kind, time.strftime("%Y%m%d_%H%M%S"))
    p = os.path.join(arc, fn)
    _write_text(p, content)
    return p


def write_draft(book_id: str, num: int, kind: str, text: str) -> None:
    """写草稿产物；覆盖前自动把旧版本归档（幂等：内容相同则不重写不归档）。

    这样任何一步重跑都不会丢历史版本，可通过 _archive 回溯；也避免
    重复写相同内容产生无意义的版本堆积。
    """
    p = draft_path(book_id, num, kind)
    old = _read_text(p) if os.path.exists(p) else ""
    if old == text:
        return   # 幂等：内容未变，跳过
    if old.strip():
        _archive_draft(book_id, num, kind, old)
    _write_text(p, text)


def read_draft(book_id: str, num: int, kind: str = "draft") -> str:
    return _read_text(draft_path(book_id, num, kind))


def snapshot(book_id: str, num: int) -> str:
    """写入前存一份状态快照，写崩了能回滚。"""
    d = os.path.join(book_dir(book_id), "snapshots", "ch%03d_%s" % (num, time.strftime("%Y%m%d_%H%M%S")))
    os.makedirs(d, exist_ok=True)
    for fn in ["state.json", "ledger.json", "hooks.json"]:
        src = state_path(book_id, fn)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(d, fn))
    return d


def list_snapshots(book_id: str) -> List[str]:
    d = os.path.join(book_dir(book_id), "snapshots")
    if not os.path.exists(d):
        return []
    return sorted(os.listdir(d), reverse=True)


def rollback(book_id: str, snap: str) -> bool:
    d = os.path.join(book_dir(book_id), "snapshots", snap)
    if not os.path.isdir(d):
        return False
    for fn in ["state.json", "ledger.json", "hooks.json"]:
        src = os.path.join(d, fn)
        if os.path.exists(src):
            shutil.copyfile(src, state_path(book_id, fn))
    return True
