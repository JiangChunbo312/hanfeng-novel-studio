/* ============================================================
 * 寒峰小说工作台 · 静态演示引擎（demo.js）
 * 用内置样本数据驱动界面，完整复刻原版功能展示。
 * 无后端、无网络请求、无 API Key。
 * ============================================================ */
'use strict';

/* ---------- 基础工具 ---------- */
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* 极简 Markdown → HTML（复刻原版 md()） */
function md(src) {
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  let html = '', list = false;
  const close = () => { if (list) { html += '</ul>'; list = false; } };
  for (const raw of String(src).split('\n')) {
    const line = raw.trim();
    const isItem = /^-\s/.test(line);
    if (!line || !isItem) close();
    if (!line) continue;
    if (/^#{1,3}\s/.test(line)) {
      html += '<h3 class="mdh">' + inline(line.replace(/^#{1,3}\s+/, '')) + '</h3>';
    } else if (isItem) {
      if (!list) { html += '<ul class="mdl">'; list = true; }
      html += '<li>' + inline(line.slice(2)) + '</li>';
    } else {
      html += '<div class="mdp">' + inline(line) + '</div>';
    }
  }
  close();
  return html;
}

/* 对象转中文友好字符串 */
function json_cn(o) {
  try { return JSON.stringify(o, null, 0); } catch (e) { return String(o); }
}

/* 成本渲染（复刻原版 costHtml()） */
function money(x) { return (x && parseFloat(x)) ? '¥' + x : '免费'; }
function costHtml(c) {
  if (!c || !c.calls) return '<div class="empty">暂无调用记录。</div>';
  const row = (k, v) => `<div class="kv"><span>${esc(k)}</span><span class="mono">${v.calls} 次 · ${v.total_tokens} tok · ${money(v.cost)}</span></div>`;
  return `<div class="kv"><span><b>合计</b></span><span class="mono"><b>${c.calls} 次 · ${c.total_tokens} tok · ${money(c.total_cost)}</b></span></div>`
    + Object.entries(c.by_role || {}).map(([k, v]) => row(k, v)).join('')
    + (c.estimated_calls ? `<div class="hint">其中 ${c.estimated_calls} 次为流式估算值（服务商未返回 usage）。</div>` : '');
}

/* 抽取事实渲染（复刻原版 renderExtract 的分区样式） */
function extractHtml(ext) {
  if (!ext) return '<div class="empty">尚未抽取事实。</div>';
  const sec = (title, body) => body ? `<div class="ext-sec"><div class="ext-h">${title}</div>${body}</div>` : '';
  const row = (arr, icon) => (arr && arr.length) ? arr.map(x => `<div class="ext-row">${icon} ${esc(typeof x === 'string' ? x : json_cn(x))}</div>`).join('') : '';
  const chars = ext.characters || ext.人物 || [];
  const facts = ext.facts || ext.事实 || [];
  const items = ext.items || ext.物品 || [];
  const hooks = ext.new_hooks || ext.新伏笔 || [];
  const resolved = ext.resolved_hooks || ext.已回收伏笔 || [];
  const rels = ext.relations || ext.关系 || [];
  const emos = ext.emotions || ext.情感 || [];
  const time = ext.time || ext.时间推进 || '';
  return sec('人物状态（' + chars.length + '）', row(chars, '👤'))
    + sec('事实（' + facts.length + '）', row(facts, '✓'))
    + sec('物品（' + items.length + '）', row(items, '📦'))
    + sec('新伏笔（' + hooks.length + '）', row(hooks, '🔴'))
    + sec('已回收伏笔（' + resolved.length + '）', row(resolved, '✅'))
    + sec('关系（' + rels.length + '）', row(rels, '↔'))
    + sec('情感（' + emos.length + '）', row(emos, '♥'))
    + (time ? sec('时间推进', `<div class="ext-row">${esc(time)}</div>`) : '');
}

/* ---------- 数据 ---------- */
const D = window.DEMO_DATA || {};
const BOOK = D.book || { title: '样本项目' };
const CHAPTERS = D.chapters || [];
const HOOKS = D.hooks || [];
const LEDGER = D.ledger || {};
const SUMMARIES = D.summaries || {};
const EXTRACTIONS = D.extractions || {};
const DRAFTS = D.drafts || {};
const STATE = D.state || {};
let currentChapter = 1;

/* 示例成本数据（演示用，非真实） */
const DEMO_COST = {
  calls: 42,
  total_tokens: 128640,
  total_cost: 0.0312,
  by_role: {
    '意图': { calls: 6, total_tokens: 18200, cost: 0.0042 },
    '写作': { calls: 6, total_tokens: 61200, cost: 0.0150 },
    '审计': { calls: 6, total_tokens: 18400, cost: 0.0048 },
    '改写': { calls: 3, total_tokens: 9600, cost: 0.0024 },
    '抽取': { calls: 6, total_tokens: 12400, cost: 0.0031 },
    '摘要': { calls: 6, total_tokens: 8840, cost: 0.0017 },
  },
  estimated_calls: 6
};

/* ---------- 写作台 ---------- */
function currentBookChapters() { return CHAPTERS; }

function chapterByIdx(n) {
  return CHAPTERS.find(c => c.num === n) || CHAPTERS[0] || {};
}

function renderWriteMeta() {
  const n = currentChapter;
  const ch = chapterByIdx(n);
  const wc = ($('#pane-draft') && $('#pane-draft').value || '').replace(/\s/g, '').length;
  const meta = $('#wh-meta');
  if (meta) meta.textContent = '《' + BOOK.title + '》 · 第 ' + n + ' 章 · 「' + (ch.title || '') + '」 · 正文 ' + wc + ' 字';
  const tags = $('#wh-tags');
  if (tags) {
    tags.innerHTML = `<span class="ht">共 <b>${CHAPTERS.length}</b> 章</span>`
      + `<span class="ht">累计 <b>${CHAPTERS.reduce((s, c) => s + (c.words || 0), 0)}</b> 字</span>`;
  }
  const cnt = $('#draft-cnt'); if (cnt) cnt.textContent = wc;
}

/* 审计报告渲染（复刻原版：JSON → 评分/问题卡片） */
function renderAudit(auditTxt) {
  const box = $('#pane-audit');
  if (!auditTxt) { box.innerHTML = '<div class="empty">还没有审计报告。点「③ 审计」。</div>'; return; }
  let r;
  try { r = JSON.parse(auditTxt); } catch (e) { box.innerHTML = '<pre>' + esc(auditTxt) + '</pre>'; return; }
  const issues = r.issues || [];
  box.innerHTML = `
    <div class="kv"><span>评分</span><span class="mono"><b>${r.score}</b> / 100 ${r.passed ? '<span class="tag ok">通过</span>' : '<span class="tag bad">有 ' + (r.critical_count || 0) + ' 个致命问题</span>'}</span></div>
    <div class="hint">${esc(r.summary || '')}</div>
    ${issues.length ? issues.map(i => `<div class="issue ${esc(i.level)}">
      <span class="badge ${esc(i.level)}">${esc((i.id || '') + ' ' + (i.level || ''))}</span>${esc(i.desc || '')}
      ${i.evidence ? `<div class="mono" style="color:var(--ink3);margin-top:4px">依据：${esc(i.evidence)}</div>` : ''}
      ${i.fix ? `<div style="margin-top:4px">改法：${esc(i.fix)}</div>` : ''}
    </div>`).join('') : '<div class="empty">没有发现问题。</div>'}`;
}

/* 改写报告渲染（复刻原版：JSON 数组 → 每条问题处理状态） */
function renderRevise(reviseTxt) {
  const box = $('#pane-revise');
  if (!box) return;
  if (!reviseTxt) {
    box.innerHTML = '<div class="empty">还没有改写报告。点「④ 改写」后，这里会列出每条审计问题是怎么改的。</div>';
    return;
  }
  let r;
  try { r = JSON.parse(reviseTxt); } catch (e) { box.innerHTML = '<pre>' + esc(reviseTxt) + '</pre>'; return; }
  // 新格式：对象带 rounds_detail
  if (r && typeof r === 'object' && Array.isArray(r.rounds_detail)) {
    const detail = r.rounds_detail;
    const totalIssues = detail.reduce((a, x) => a + (x.issues || []).length, 0);
    const totalDone = detail.reduce((a, x) => a + (x.issues || []).filter(i => i.handled).length, 0);
    if (!detail.length) {
      box.innerHTML = `<div class="empty">${esc(r.note || '没有进行改写。')}</div>`;
      return;
    }
    box.innerHTML = `
      <div class="kv"><span>改写结果</span><span class="mono"><b>共 ${detail.length} 轮</b> · 累计处理 <b>${totalDone}</b> / ${totalIssues} 条 ${r.note ? '<span class="tag ok">' + esc(r.note) + '</span>' : ''}</span></div>
      ${detail.map((rd, idx) => `
        <div class="round-block">
          <div class="round-head">第 ${esc(rd.round)} 轮</div>
          ${rd.outcome ? `<div class="hint">${esc(rd.outcome)}</div>` : ''}
          ${(rd.issues || []).map(x => `<div class="issue ${esc(x.level || '')}">
            <span class="badge ${x.handled ? 'ok' : 'bad'}">${x.handled ? '✓' : '✗'} ${esc(x.issue_id || '')} ${esc(x.level || '')}</span>${esc(x.desc || '')}
            ${x.evidence ? `<div class="mono" style="color:var(--ink3);margin-top:4px">依据：${esc(x.evidence)}</div>` : ''}
            <div style="margin-top:4px;color:${x.handled ? 'var(--ok)' : 'var(--bad)'}">${x.handled ? '✅ 已改' : '❌ 未改'}：${esc(x.how || '')}</div>
          </div>`).join('')}
        </div>`).join('')}`;
    return;
  }
  // 旧格式：数组 / {report:[...]}
  const rows = Array.isArray(r) ? r : (r.report || []);
  if (!rows.length) { box.innerHTML = `<div class="empty">${esc((r && r.note) || '改写报告为空。')}</div>`; return; }
  const done = rows.filter(x => x.handled).length;
  box.innerHTML = `
    <div class="kv"><span>改写结果</span><span class="mono"><b>${done}</b> / ${rows.length} 条已处理 ${done === rows.length ? '<span class="tag ok">全部处理</span>' : '<span class="tag bad">还有 ' + (rows.length - done) + ' 条未处理</span>'}</span></div>
    ${rows.map(x => `<div class="issue ${esc(x.level || '')}">
      <span class="badge ${x.handled ? 'ok' : 'bad'}">${x.handled ? '✓' : '✗'} ${esc(x.issue_id || '')} ${esc(x.level || '')}</span>${esc(x.desc || '')}
      ${x.evidence ? `<div class="mono" style="color:var(--ink3);margin-top:4px">依据：${esc(x.evidence)}</div>` : ''}
      <div style="margin-top:4px;color:${x.handled ? 'var(--ok)' : 'var(--bad)'}">${x.handled ? '✅ 已改' : '❌ 未改'}：${esc(x.how || '')}</div>
    </div>`).join('')}`;
}

function loadChapter(n) {
  currentChapter = n;
  const ch = chapterByIdx(n);
  $('#w-chapter').value = n;
  $('#chapter-title').value = ch.title || '';
  const plan = (DRAFTS['plan'] || '');
  const draft = (DRAFTS['draft'] || ch.content || '');
  const audit = (DRAFTS['audit'] || '');
  const revise = (DRAFTS['revise'] || '');
  const extract = EXTRACTIONS['ch' + String(n).padStart(3, '0')] || EXTRACTIONS[Object.keys(EXTRACTIONS)[0]] || null;
  const summary = SUMMARIES['ch' + String(n).padStart(3, '0')] || SUMMARIES[Object.keys(SUMMARIES)[0]] || '';
  $('#pane-plan').value = plan;
  $('#pane-draft').value = draft;
  renderAudit(audit);
  renderRevise(revise);
  $('#pane-flow').innerHTML = `<div class="md"><h3 class="mdh">流程结果（示例）</h3><div class="mdp">第 ${n} 章完整流水线已跑通：意图 → 写作 → 审计(通过) → 抽取 → 摘要 → 已采纳。</div></div>`;
  $('#pane-extract').innerHTML = extractHtml(extract);
  $('#pane-summary').innerHTML = summary ? '<div class="md">' + md(summary) + '</div>' : '<div class="empty">暂无摘要。</div>';
  renderWriteMeta();
  switchPane('draft');
  refreshSide();
}

function switchPane(k) {
  $$('.tmini[data-pane]').forEach(x => x.classList.toggle('active', x.dataset.pane === k));
  ['plan', 'draft', 'audit', 'revise', 'flow', 'extract', 'summary'].forEach(x => {
    const el = $('#pane-' + x); if (el) el.classList.toggle('active', x === k);
  });
}

/* ---------- 侧边栏 ---------- */
function renderStateProjection() {
  const box = $('#side-state');
  // 用 state.json 生成可读的世界状态 Markdown
  const chars = STATE.characters || {};
  const world = STATE.world || {};
  const notes = STATE.notes || [];
  let mdText = '## 世界状态\n';
  const charNames = Object.keys(chars).slice(0, 6);
  charNames.forEach(name => {
    const c = chars[name];
    mdText += `### ${name}\n`;
    if (c['位置']) mdText += `- 位置：${c['位置']}\n`;
    if (c['状态']) mdText += `- 状态：${c['状态']}\n`;
    if (c['能力']) mdText += `- 能力：${c['能力']}\n`;
    if (c['持有物']) mdText += `- 持有物：${c['持有物']}\n`;
    if (c['态度']) mdText += `- 态度：${c['态度']}\n`;
  });
  if (Object.keys(world).length) {
    mdText += '### 世界\n';
    Object.entries(world).slice(0, 5).forEach(([k, v]) => {
      mdText += `- ${k}：${typeof v === 'string' ? v : json_cn(v)}\n`;
    });
  }
  box.innerHTML = mdText ? md(mdText) : '<div class="empty">尚未抽取事实。</div>';
}

function renderHooks() {
  const box = $('#side-hooks');
  if (!HOOKS.length) { box.innerHTML = '<div class="empty">伏笔池为空。</div>'; return; }
  const open = HOOKS.filter(h => h.status !== 'resolved');
  const resolved = HOOKS.filter(h => h.status === 'resolved');
  const item = h => `<div class="chitem"><span>${h.status === 'resolved' ? '✅' : '⏳'} <span class="mono">${esc(h.id)}</span> ${esc(h.text)}
    <span class="tag dim">埋于第${h.planted_ch}章${h.due_chapter ? ' · 预期第' + h.due_chapter + '章' : ''}${h.resolved_ch ? ' · 解决于第' + h.resolved_ch + '章' : ''}</span></span></div>`;
  box.innerHTML = `<div class="ext-h">开放伏笔（${open.length}）</div>` + open.slice(0, 12).map(item).join('')
    + `<div class="ext-h" style="margin-top:10px">已回收（${resolved.length}）</div>` + resolved.slice(0, 5).map(item).join('')
    + (HOOKS.length > 17 ? `<div class="hint" style="margin-top:6px">… 共 ${HOOKS.length} 个伏笔</div>` : '');
}

function renderCost() {
  $('#side-cost').innerHTML = costHtml(DEMO_COST);
}

function renderChapterList() {
  const box = $('#side-chapters');
  box.innerHTML = CHAPTERS.slice().reverse().map(c =>
    `<div class="chitem"><span>第${c.num}章 · ${esc(c.title)} · ${c.words}字</span>
     <button class="btn mini" data-go="${c.num}">跳转</button></div>`).join('');
  box.querySelectorAll('[data-go]').forEach(b => b.onclick = () => loadChapter(+b.dataset.go));
}

function refreshSide() {
  renderStateProjection();
  renderHooks();
  renderCost();
  renderChapterList();
}

/* ---------- 项目页 ---------- */
function renderBookList() {
  const box = $('#book-list');
  const books = [BOOK];
  box.innerHTML = books.map(b => `
    <div class="chitem"><span><b>${esc(b.title)}</b>
      <span class="tag dim">${CHAPTERS.length} 章</span>
      <span class="tag dim">${CHAPTERS.reduce((s, c) => s + (c.words || 0), 0)} 字</span></span>
      <button class="btn mini" data-open="${esc(b.id)}">打开</button></div>`).join('');
  box.querySelectorAll('[data-open]').forEach(btn => btn.onclick = () => openBook(btn.dataset.open));
}

function openBook(id) {
  const d = BOOK;
  $('#detail-body').innerHTML = `
    <div class="export-bar">
      <span class="export-label">⬇ 一键导出全部章节</span>
      <button class="btn mini" id="exp-txt">下载 TXT</button>
      <button class="btn mini" id="exp-md">下载 MD</button>
      <span class="hint export-hint">把本书所有正式章节（按章号排序拼接）导出成文档，正文自动补章标题</span>
    </div>
    <div class="form">
      <label>书名<input id="b-title" value="${esc(d.title)}"></label>
      <label>题材<input id="b-genre" value="${esc(d.genre)}"></label>
      <label>单章字数<input id="b-words" type="number" value="${d.chapter_words || 2000}"></label>
      <label>章节目录<input id="b-dir" value="" placeholder="留空=默认"></label>
      <label>核心设定<textarea id="b-premise" rows="3">${esc(d.premise)}</textarea></label>
      <label>文风要求<textarea id="b-style" rows="2">${esc(d.style)}</textarea></label>
      <label>硬性禁忌<textarea id="b-taboo" rows="2">${esc(d.taboos)}</textarea></label>
      <label>卷纲/大纲<textarea id="b-outline" rows="5">${esc(d.outline)}</textarea></label>
    </div>
    <div class="row"><button class="btn primary" id="b-save">保存设定</button></div>
    <div id="b-out" class="out"></div>
    <h2 class="mt">章节（${CHAPTERS.length}）</h2>
    <div style="max-height:260px;overflow:auto">
      ${CHAPTERS.length ? CHAPTERS.map(c => `<div class="chitem"><span>第${c.num}章 · ${esc(c.title)} · ${c.words}字 ${SUMMARIES['ch' + String(c.num).padStart(3, '0')] ? '<span class="tag ok">摘要</span>' : ''}</span></div>`).join('') : '<div class="empty">暂无章节</div>'}
    </div>
    <h2 class="mt">成本</h2>
    ${costHtml(DEMO_COST)}
    <h2 class="mt">快照（3）</h2>
    <div>
      <div class="chitem"><span class="mono">ch001_20261027_162803</span><button class="btn mini" data-roll="ch001_20261027_162803">回滚</button></div>
      <div class="chitem"><span class="mono">ch010_20261028_200332</span><button class="btn mini" data-roll="ch010_20261028_200332">回滚</button></div>
      <div class="chitem"><span class="mono">ch024_20261031_102829</span><button class="btn mini" data-roll="ch024_20261031_102829">回滚</button></div>
    </div>
  `;
  $('#b-save').onclick = () => { out('#b-out', '🔒 演示模式：本地运行时才会保存设定', ''); };
  document.querySelectorAll('[data-roll]').forEach(btn => btn.onclick = () => { out('#b-out', '🔒 演示模式：本地运行时才会回滚快照', ''); });
  const expTxt = $('#exp-txt'), expMd = $('#exp-md');
  if (expTxt) expTxt.onclick = () => demoExport('txt');
  if (expMd) expMd.onclick = () => demoExport('md');
}

/* 演示导出：把样本章节拼成文本下载 */
function demoExport(fmt) {
  let body = '';
  CHAPTERS.forEach(c => {
    const title = c.title || ('第' + c.num + '章');
    body += `第${c.num}章 ${title}\n\n${c.content}\n\n`;
  });
  const ext = fmt === 'md' ? '.md' : '.txt';
  const blob = new Blob([body], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = BOOK.title + ext;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------- 模型配置页（演示占位） ---------- */
function renderConfig() {
  // 服务商已用静态 HTML 占位，这里只需把「保存配置」按钮接上演示提示
  $('#save-config').onclick = () => out('#save-out', '🔒 演示模式：本地运行时保存到 config.local.json', '');
  $('#test-all-btn').onclick = () => {
    const box = $('#test-all-result');
    box.innerHTML = `<div class="tgroup good"><div class="tgroup-h">✅ 可用（6）</div>
      <div class="titem"><div class="tinfo"><b>火山豆包 · doubao-seed-2-0-lite-260428</b><span class="tmsg">连接成功 · 342ms</span></div></div>
      <div class="titem"><div class="tinfo"><b>七牛 Conatus · qiniu/conatus-free</b><span class="tmsg">连接成功 · 287ms</span></div></div>
      <div class="titem"><div class="tinfo"><b>书生(InternLM) · Atria-Dawn</b><span class="tmsg">连接成功 · 401ms</span></div></div>
      <div class="titem"><div class="tinfo"><b>商汤日日新 · sensenova-6.8-flash-lite</b><span class="tmsg">连接成功 · 366ms</span></div></div>
      <div class="titem"><div class="tinfo"><b>魔搭社区 · Qwen/Qwen3.5-27B</b><span class="tmsg">连接成功 · 312ms</span></div></div>
      <div class="titem"><div class="tinfo"><b>Dots · dots3-note-prev</b><span class="tmsg">连接成功 · 298ms</span></div></div>
    </div>
    <div class="tgroup bad"><div class="tgroup-h">❌ 不可用（1）</div>
      <div class="titem"><div class="tinfo"><b>魔搭社区 · ZhipuAI/GLM-4.7-Flash</b><span class="tmsg">401 Unauthorized</span></div>
      <button class="btn mini t-del">删除</button></div>
    </div>`;
    out('#test-out', '✅ 测试完成：可用 6 / 不可用 1。不可用的点「删除」移除。', 'ok');
  };
  $('#add-provider').onclick = () => out('#test-out', '🔒 演示模式：本地运行时才会新增服务商', '');
}

/* ---------- 通用输出 ---------- */
function out(sel, msg, kind) {
  const el = $(sel);
  if (!el) return;
  el.textContent = msg || '';
  const base = el.dataset.outBase || '';
  el.className = (base ? base + ' ' : '') + 'out' + (kind ? ' ' + kind : '');
}

/* ---------- 初始化 ---------- */
function init() {
  // 侧边导航切换
  $$('.navitem').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.navitem').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const v = btn.dataset.view;
      $$('.view').forEach(s => s.classList.remove('active'));
      const target = $('#view-' + v);
      if (target) target.classList.add('active');
    });
  });

  // 支持 ?view=write|books|config 直达指定页面（也便于验证）
  const viewParam = new URLSearchParams(location.search).get('view');
  if (viewParam && ['write', 'books', 'config'].includes(viewParam)) {
    const btn = document.querySelector('.navitem[data-view="' + viewParam + '"]');
    if (btn) btn.click();
  }

  // 写作台项目下拉
  const sel = $('#w-book');
  if (sel) {
    sel.innerHTML = `<option value="${esc(BOOK.id)}">${esc(BOOK.title)}</option>`;
  }
  // 写作台页签
  $$('.tmini[data-pane]').forEach(btn => btn.onclick = () => switchPane(btn.dataset.pane));
  $$('.tmini[data-side]').forEach(btn => {
    btn.onclick = () => {
      $$('.tmini[data-side]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      ['state', 'hooks', 'cost', 'chapters'].forEach(k => {
        const el = $('#side-' + k); if (el) el.classList.toggle('active', k === btn.dataset.side);
      });
    };
  });
  // 写作台按钮
  $('#w-load').onclick = () => loadChapter(+$('#w-chapter').value || 1);
  $('#w-plan').onclick = () => { switchPane('plan'); out('#write-out', '已展示「写作意图」样本（来自样本项目 ch001）', 'ok'); };
  $('#w-write').onclick = () => { switchPane('draft'); out('#write-out', '已展示「正文」样本（流式输出在本地运行时可见）', 'ok'); };
  $('#w-audit').onclick = () => { switchPane('audit'); out('#write-out', '已展示「审计报告」样本', 'ok'); };
  $('#w-revise').onclick = () => { switchPane('revise'); out('#write-out', '已展示「改写报告」样本', 'ok'); };
  $('#w-extract').onclick = () => { switchPane('extract'); out('#write-out', '已展示「抽取事实」样本', 'ok'); };
  $('#w-summary').onclick = () => { switchPane('summary'); out('#write-out', '已展示「摘要」样本', 'ok'); };
  $('#w-accept').onclick = () => out('#write-out', '🔒 演示模式：本地运行时才会写入章节文件', '');
  $('#gen-title').onclick = () => out('#write-out', '🔒 演示模式：本地运行时由模型起名', '');
  $('#save-draft').onclick = () => out('#write-out', '🔒 演示模式：本地运行时保存草稿', '');
  $('#b-start-btn').onclick = () => out('#batch-status', '🔒 演示模式：本地运行时启动批量流水线', '');
  $('#b-stop-btn').onclick = () => out('#batch-status', '🔒 演示模式：本地运行时停止批量流水线', '');

  // 项目页
  renderBookList();
  $('#create-book').onclick = () => out('#inspire-out', '🔒 演示模式：本地运行时创建项目', '');
  $('#inspire-btn').onclick = () => {
    $('#inspire-out').innerHTML = `<div class="md"><h3 class="mdh">✦ AI 推荐题材（示例）</h3>
      <div class="mdp"><b>书名</b>：《我在三国说相声》</div>
      <div class="mdp"><b>题材</b>：架空穿越 / 历史 / 搞笑</div>
      <div class="mdp"><b>核心设定</b>：现代相声演员魂穿东汉，靠「捧逗」技能在乱世收服名将。</div>
      <div class="mdp"><b>文风</b>：轻松诙谐、高密度梗、章末留包袱。</div></div>`;
  };

  // 模型配置
  renderConfig();

  // 载入第一章
  loadChapter(1);
  renderWriteMeta();
  // 默认打开「写作意图」页签更直观
  switchPane('plan');
}

document.addEventListener('DOMContentLoaded', init);