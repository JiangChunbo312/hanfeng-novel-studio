"""临时验证：1) /projection 接口返回新格式  2) 前端 md() 渲染逻辑等价实现的结构断言。"""
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
import store  # noqa: E402

BOOK = "我专收死局全城等我翻盘"

# ---- 1) 走真实 HTTP 接口 ----
url = "http://127.0.0.1:8787/api/books/" + urllib.parse.quote(BOOK) + "/projection"
with urllib.request.urlopen(url, timeout=5) as r:
    body = r.read().decode("utf-8")
    status = r.status
mk = __import__("json").loads(body).get("markdown", "")
local = store.markdown_projection(BOOK)

print("[1] HTTP %d  接口 %d 字 / 本地 %d 字  一致=%s"
      % (status, len(mk), len(local), mk == local))
print("    残留 JSON 键(位置/关系/情感原样):", bool(re.search(r'"(a|b|type|change|character|turn)"\s*:', mk)))
print("    章节: ", [l[3:] for l in mk.splitlines() if l.startswith("## ")])

# ---- 2) md() 的 Python 等价实现，用来验结构 ----
ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def esc(s):
    return "".join(ESC.get(c, c) for c in s)


def md(src):
    def inline(s):
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(s))
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        return s
    html, lst = "", False

    def close():
        nonlocal html, lst
        if lst:
            html += "</ul>"
            lst = False

    for raw in src.split("\n"):
        line = raw.strip()
        is_item = bool(re.match(r"^-\s", line))
        if not line or not is_item:
            close()
        if not line:
            continue
        if re.match(r"^#{1,3}\s", line):
            html += '<h3 class="mdh">' + inline(re.sub(r"^#{1,3}\s+", "", line)) + "</h3>"
        elif is_item:
            if not lst:
                html += '<ul class="mdl">'
                lst = True
            html += "<li>" + inline(line[2:]) + "</li>"
        else:
            html += '<div class="mdp">' + inline(line) + "</div>"
    close()
    return html

h = md(mk)
sec = len(re.findall(r"^## ", mk, re.M))
items = len(re.findall(r"^- ", mk, re.M))
opens = h.count('<ul class="mdl">')
closes = h.count("</ul>")
lis = h.count("<li>")
bolds = len(re.findall(r"<b>", h))

print("[2] 期望 h3=%d / li=%d" % (sec, items))
print("    实际 h3=%d / li=%d   <ul>=%d </ul>=%d   <b>=%d" % (len(re.findall(r'<h3', h)), lis, opens, closes, bolds))
print("    结构断言: h3=%s li=%s ul闭合=%s" % (len(re.findall(r'<h3', h)) == sec, lis == items, opens == closes))
print("    行内代码(hook id) 渲染:", h.count("<code>"), "处")
print("    HTML 长度:", len(h))
print()
print("=== 渲染片段（角色段）===")
print(h[h.find('<h3'):h.find("</ul>") + 6][:900])
