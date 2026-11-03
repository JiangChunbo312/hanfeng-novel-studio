"""临时验证：写作台顶部状态条布局（工具栏 + 状态条同一粘性容器）。"""
import re
import urllib.request

BASE = "http://127.0.0.1:8787"


def get(p):
    return urllib.request.urlopen(BASE + p, timeout=5).read().decode("utf-8")


h, a, c = get("/"), get("/static/app.js"), get("/static/style.css")
ok = bad = 0


def chk(name, cond):
    global ok, bad
    print(("  [OK]   " if cond else "  [FAIL] ") + name)
    if cond:
        ok += 1
    else:
        bad += 1


i_sticky = h.find('class="write-sticky"')
i_tab = h.find('class="toolbar"')
i_out = h.find('id="write-out"')
i_grid = h.find('class="write-grid"')
i_audit = h.find('id="pane-audit"')
i_side = h.find('class="card side"')

print("[index.html]")
chk("#write-out 只有 1 处", h.count('id="write-out"') == 1)
chk("顺序 粘性容器→工具栏→状态条→编辑区", i_sticky < i_tab < i_out < i_grid)
chk("工具栏与状态条同在一个粘性容器内", i_tab > i_sticky and i_out > i_sticky and i_out < i_grid)
seg = h[h.rfind("<div", 0, i_sticky):h.rfind("<div", 0, i_grid)]   # 整个粘性容器块
chk("粘性容器块 div 开闭配平", seg.count("<div") == seg.count("</div>"))
chk("粘性容器块内含工具栏+状态条且无其他 pane",
    'class="toolbar"' in seg and 'id="write-out"' in seg and 'class="pane' not in seg)
chk("状态条位于正文编辑区之外（pane-audit 在其后）", i_audit > i_out)
chk("状态条位于右侧状态卡之外（card.side 在其后）", i_side > i_out)
chk("状态条带 data-out-base", 'data-out-base="statusbar"' in h)
chk("inspire-out 未被改动", 'id="inspire-out" class="out"' in h)
chk("7 个工序按钮齐全", all(x in h for x in
    ['id="w-plan"', 'id="w-write"', 'id="w-audit"', 'id="w-revise"',
     'id="w-extract"', 'id="w-summary"', 'id="w-accept"']))
chk("HTML div 标签配平", h.count("<div") == h.count("</div>"))

print("[style.css]")
chk(".write-sticky 定义为 sticky", bool(re.search(r"\.write-sticky\{position:sticky", c)))
chk("容器内 toolbar 取消 sticky（防两块 sticky 互相压盖）",
    bool(re.search(r"\.write-sticky \.toolbar\{position:static", c)))
chk(".statusbar 自身不再 sticky",
    ".statusbar{" in c and ".statusbar{position:sticky" not in c)
chk(".statusbar 有实底背景（滚动时能盖住下层文字）", "background:var(--accent-soft)" in c)
chk(".statusbar.ok / .err 变体齐全", ".statusbar.ok{" in c and ".statusbar.err{" in c)
chk(".statusbar 规则写在 .out 之后（保证能覆盖 .out 的样式）",
    c.find(".statusbar{") > c.find(".out.ok{"))

print("[app.js]")
chk("out() 保留 data-out-base 样式类", "el.dataset.outBase" in a)
chk("空态提示常量与函数各一处", "WRITE_READY" in a and a.count("function statusReady") == 1)
chk("切到写作台时补空态提示", "dataset.view === 'write') statusReady()" in a)
chk("首次加载即关自动填充并显示空态",
    "updateMeta();\n  noAutofill();\n  statusReady();" in a)
chk("noAutofill 至少两处调用（渲染后 + 初始化）", a.count("noAutofill();") >= 2)
PWD = 'type="password"'
chk("DOM 中不再有任何 password 字段（根治登录页误判）", PWD not in a and PWD not in h)
chk("API Key 字段改为 text 型 + 关闭自动填充",
    'class="f-key" type="text"' in a and 'spellcheck="false"' in a)
chk("CSS 有 Key 掩码兜底", "-webkit-text-security:disc" in c)
chk("7 道工序全部仍写 #write-out", a.count("out('#write-out'") >= 20)
for op, cl in [("{", "}"), ("(", ")"), ("[", "]")]:
    chk("括号配平 %s%s" % (op, cl), a.count(op) == a.count(cl))

print("\n通过 %d 项，失败 %d 项" % (ok, bad))
