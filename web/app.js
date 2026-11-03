/* 寒峰小说工作台 · 前端（零构建，原生 JS） */
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const MASK = '***KEEP***';

const S = { config: null, presets: {}, books: [], book: null, chapter: 1 };

/* 写作台顶部状态条的空态提示：有真实进度时不覆盖，只在空着时填上 */
const WRITE_READY = '就绪 · 选好项目与章号，点上方工序开始（进度显示在这里）';
function statusReady() {
  const el = $('#write-out');
  if (el && !el.textContent.trim()) out('#write-out', WRITE_READY, '');
}

/* 全站关掉自动填充：本页不是登录页，别让浏览器往章号/模型名里塞"已保存的登录信息" */
function noAutofill() {
  document.querySelectorAll('input, select, textarea').forEach(el => { el.autocomplete = 'off'; });
}

/* ---------------- 基础 ---------------- */
async function api(path, method, body) {
  const opt = { method: method || 'GET' };
  if (body !== undefined) {
    opt.headers = { 'Content-Type': 'application/json' };
    opt.body = JSON.stringify(body);
  }
  const r = await fetch('/api' + path, opt);
  return r.json();
}

function out(sel, msg, kind) {
  const el = $(sel);
  if (!el) return;
  el.textContent = msg || '';
  // data-out-base 里的样式类要保留（比如顶部状态条的 statusbar），只切换 ok/err
  const base = el.dataset.outBase || '';
  el.className = (base ? base + ' ' : '') + 'out' + (kind ? ' ' + kind : '');
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* 极简 Markdown → HTML：只覆盖世界状态投影用到的 标题 / 列表 / 加粗 / 行内代码 */
function md(src) {
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  let html = '', list = false;
  const close = () => { if (list) { html += '</ul>'; list = false; } };
  for (const raw of String(src).split('\n')) {
    const line = raw.trim();
    const isItem = /^-\s/.test(line);
    if (!line || !isItem) close();          // 空行 / 非列表行 → 结束当前列表
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

// 对象转中文友好字符串（抽事实 delta 里的关系/情感等可能是对象）
function json_cn(o) {
  try { return JSON.stringify(o, null, 0); } catch (e) { return String(o); }
}

/* SSE over POST */
async function ssePost(path, body, onEvent) {
  const res = await fetch('/api' + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const reader = res.body.getReader();
  const dec = new TextDecoder('utf-8');
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const chunks = buf.split('\n\n');
    buf = chunks.pop();
    for (const c of chunks) {
      let ev = 'message', data = '';
      for (const line of c.split('\n')) {
        if (line.startsWith('event: ')) ev = line.slice(7).trim();
        else if (line.startsWith('data: ')) data += line.slice(6);
      }
      if (!data) continue;
      try { onEvent(ev, JSON.parse(data)); } catch (e) { /* 忽略坏帧 */ }
    }
  }
}

/* ---------------- 视图切换 ---------------- */
$$('.navitem').forEach(t => t.onclick = () => {
  $$('.navitem').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  $$('.view').forEach(v => v.classList.remove('active'));
  $('#view-' + t.dataset.view).classList.add('active');
  if (t.dataset.view === 'write') statusReady();
});
$$('.tmini[data-pane]').forEach(t => t.onclick = () => { switchPane(t.dataset.pane); });
$$('.tmini[data-side]').forEach(t => t.onclick = () => {
  const g = t.dataset.side;
  $$('.tmini[data-side]').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  ['state', 'hooks', 'cost', 'chapters'].forEach(k => $('#side-' + k).classList.toggle('active', k === g));
});

/* ---------------- 模型配置 ---------------- */
async function loadConfig() {
  const c = await api('/config');
  S.config = c;
  renderProviders();
  renderRoutes();
  renderPrices();
  const sto = $('#step-timeout');
  if (sto) sto.value = (c.defaults && c.defaults.step_timeout) || 180;
  renderTestStatus();   // 用已存的 model_status 重建「可用 / 不可用」分组
}

function modelOptions() {
  const opts = ['<option value="">（回落 default）</option>'];
  (S.config.providers || []).forEach(p => {
    const models = String(p.model || '').split(',').map(s => s.trim()).filter(Boolean);
    if (!models.length) models.push('');
    models.forEach(m => {
      const v = m ? p.id + ':' + m : p.id + ':';
      opts.push(`<option value="${v}">${esc(p.label)} · ${esc(m || '(未填模型)')}</option>`);
    });
  });
  return opts.join('');
}

function renderProviders() {
  const box = $('#providers');
  if (!(S.config.providers || []).length) {
    box.innerHTML = '<div class="empty">还没有服务商，先选一个预设新增。</div>';
    return;
  }
  box.innerHTML = S.config.providers.map((p, i) => `
    <div class="pitem" data-i="${i}">
      <div class="prow">
        <span class="fld w120"><b>名称</b><input class="f-label" value="${esc(p.label)}"></span>
        <span class="fld w90"><b>ID</b><input class="f-id" value="${esc(p.id)}"></span>
        <span class="tag dim mono keytag" title="当前已保存的 Key">${esc(p.api_key || '(未保存 Key)')}</span>
        <button class="btn mini f-test">测试连接</button>
        <button class="btn mini f-del">删除</button>
      </div>
      <span class="fld"><b>Base URL <i>(服务商接口地址，以 /v1 结尾)</i></b>
        <input class="f-base mono" value="${esc(p.base_url)}" placeholder="例如 https://ark.cn-beijing.volces.com/api/v3"></span>
      <div class="prow" style="margin-top:6px">
        <span class="fld grow"><b>模型名 <i>(每个用逗号隔开，火山豆包填 ep-xxx 或模型 ID)</i></b>
          <input class="f-model mono" value="${esc(p.model)}" placeholder="例如 doubao-seed-1-6-250615"></span>
        <span class="fld grow"><b>API Key <i>(留空=保持不变；本地模型可留空)</i></b>
          <input class="f-key" type="text" inputmode="text" autocomplete="off" spellcheck="false"
            value="" placeholder="粘贴你的 Key，保存后不再明文显示"></span>
        <span class="fld w80"><b>超时(秒)</b>
          <input class="f-timeout" type="number" value="${p.timeout || 180}"></span>
      </div>
    </div>`).join('');

  box.querySelectorAll('.pitem').forEach(el => {
    const i = +el.dataset.i;
    el.querySelector('.f-test').onclick = async () => {
      const cfg = collectConfig();
      out('#test-out', '测试中…');
      const r = await api('/models/test', 'POST', { provider: cfg.providers[i], model: cfg.providers[i].model });
      out('#test-out', (r.ok ? '✅ ' : '❌ ') + r.message, r.ok ? 'ok' : 'err');
    };
    el.querySelector('.f-del').onclick = () => {
      S.config.providers.splice(i, 1);
      renderProviders(); renderRoutes(); renderPrices();
    };
  });
}

// 一键测试全部模型的结果（供删除后局部重渲染）
let currentTestResults = [];

async function testAllModels() {
  const btn = $('#test-all-btn');
  if (!btn) return;
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '测试中…';
  out('#test-out', '正在逐个测试库里所有模型（并发请求，请稍候）…');
  try {
    const r = await api('/models/test-all', 'POST', {});
    if (!r.ok) { out('#test-out', '❌ ' + (r.error || '测试失败'), 'err'); return; }
    currentTestResults = r.results || [];
    // 把 ok/bad 写进内存配置，故障转移会立即只轮换可用模型
    S.config.model_status = {};
    currentTestResults.forEach(x => { S.config.model_status[x.key] = x.ok ? 'ok' : 'bad'; });
    renderTestAll(r);
    out('#test-out', `✅ 测试完成：可用 ${r.ok_count} / 不可用 ${r.bad_count}。不可用的点「删除」移除，任务就不会轮换到它。`, 'ok');
  } catch (e) {
    out('#test-out', '❌ ' + e, 'err');
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function renderTestAll(data) {
  const results = data.results || [];
  const ok = results.filter(x => x.ok);
  const bad = results.filter(x => !x.ok);
  const box = $('#test-all-result');
  if (!box) return;
  if (!results.length) {
    box.innerHTML = '<div class="empty">还没测过。点上方「一键测试全部模型」即可逐个测连通与额度。</div>';
    return;
  }
  const card = (title, cls, arr) => `
    <div class="tgroup ${cls}">
      <div class="tgroup-h">${title}（${arr.length}）</div>
      ${arr.length ? arr.map(x => `
        <div class="titem">
          <div class="tinfo"><b>${esc(x.provider)} · ${esc(x.model || '(未填模型)')}</b>
            <span class="tmsg">${esc(x.message || '')}${x.latency_ms ? (' · ' + x.latency_ms + 'ms') : ''}</span></div>
          ${cls === 'bad' ? `<button class="btn mini t-del" data-key="${esc(x.key)}">删除</button>` : ''}
        </div>`).join('') : '<div class="empty">无</div>'}
    </div>`;
  box.innerHTML = card('✅ 可用', 'good', ok) + card('❌ 不可用（点删除，移除后任务不再轮换到）', 'bad', bad);
  box.querySelectorAll('.t-del').forEach(b => b.onclick = async () => {
    const key = b.dataset.key;
    const i = key.lastIndexOf(':');
    const pid = key.slice(0, i);
    const m = key.slice(i + 1);
    b.disabled = true; b.textContent = '删除中…';
    const rr = await api('/models/remove', 'POST', { provider_id: pid, model: m });
    if (rr.ok) {
      S.config = rr.config;
      renderProviders(); renderRoutes(); renderPrices();
      const newResults = currentTestResults.filter(x => x.key !== key);
      currentTestResults = newResults;
      renderTestAll({ results: newResults });
      out('#test-out', '✅ 已删除 ' + key, 'ok');
    } else {
      b.disabled = false; b.textContent = '删除';
      out('#test-out', '❌ ' + (rr.error || '删除失败'), 'err');
    }
  });
}

function renderTestStatus() {
  // 刷新页面 / 载入配置后，用已存的 model_status 重建「可用 / 不可用」分组（不重新发请求）
  const cfg = S.config || {};
  const status = cfg.model_status || {};
  const items = [];
  (cfg.providers || []).forEach(p => {
    const models = String(p.model || '').split(',').map(s => s.trim()).filter(Boolean);
    const list = models.length ? models : [''];
    list.forEach(m => {
      const key = p.id + ':' + m;
      const st = status[key];
      if (st) items.push({ key, provider: p.label, model: m, ok: st === 'ok', message: st === 'ok' ? '上次测试可用' : '上次测试不可用' });
    });
  });
  currentTestResults = items;
  renderTestAll({ results: items });
}

function renderRoutes() {
  const routes = S.config.routes || {};
  const models = (S.config.providers || []).flatMap(p =>
    String(p.model || '').split(',').map(s => s.trim()).filter(Boolean).map(m => p.id + ':' + m)
  );
  const rows = ROLE_LABELS.map(r => {
    const cur = routes[r.key] || '';
    return `<tr><td>${r.label}</td><td>
      <input type="text" class="route-input" data-role="${r.key}" value="${esc(cur)}"
        placeholder="（回落 default）" spellcheck="false" autocomplete="off" style="width:100%">
      <div class="route-hint">可选模型链（按顺序尝试，超时自动切下一个）：
        ${models.slice(0, 5).map(m => `<code class="rcode" data-copy="${esc(m)}">${esc(m)}</code>`).join(' ')}${models.length > 5 ? ' …' : ''}
      </div>
    </td></tr>`;
  }).join('');
  $('#routes').innerHTML = `<table><tr><th style="width:180px">角色</th><th>模型链（英文逗号分隔，前面的优先）</th></tr>${rows}</table>`;
  // 点可选模型 → 追加到对应行输入框
  document.querySelectorAll('.rcode').forEach(c => c.onclick = () => {
    const inp = c.closest('td').querySelector('.route-input');
    if (!inp) return;
    const v = c.dataset.copy;
    const cur = inp.value.trim();
    inp.value = cur ? cur + ',' + v : v;
  });
}
const ROLE_LABELS = [
  { key: 'default', label: '默认（回落）' },
  { key: 'planner', label: '规划师 · 本章意图' },
  { key: 'writer', label: '写手 · 正文' },
  { key: 'observer', label: '观察者 · 事实抽取' },
  { key: 'auditor', label: '审计员 · 一致性检查' },
  { key: 'reviser', label: '修订者 · 定点改写' },
  { key: 'summary', label: '摘要 · 章节梗概' },
];

function renderPrices() {
  const prices = S.config.prices || {};
  const rows = [];
  (S.config.providers || []).forEach(p => {
    String(p.model || '').split(',').map(s => s.trim()).filter(Boolean).forEach(m => {
      const k = p.id + ':' + m;
      const v = prices[k] || { in: 0, out: 0 };
      rows.push(`<tr><td class="mono">${esc(p.label)} · ${esc(m)}</td>
        <td><input type="number" step="0.1" data-price="${esc(k)}" data-f="in" value="${v.in || 0}" style="width:90px"></td>
        <td><input type="number" step="0.1" data-price="${esc(k)}" data-f="out" value="${v.out || 0}" style="width:90px"></td></tr>`);
    });
  });
  $('#prices').innerHTML = rows.length
    ? `<table><tr><th>模型</th><th>输入 元/百万</th><th>输出 元/百万</th></tr>${rows.join('')}</table>`
    : '<div class="empty">先配置服务商和模型名。</div>';
  noAutofill();   // renderProviders → renderRoutes → renderPrices 是一起跑的，收尾统一关掉自动填充
}

function collectConfig() {
  const providers = Array.from(document.querySelectorAll('#providers .pitem')).map(el => {
    const key = el.querySelector('.f-key').value.trim();
    return {
      id: el.querySelector('.f-id').value.trim(),
      label: el.querySelector('.f-label').value.trim(),
      base_url: el.querySelector('.f-base').value.trim(),
      api_key: key || MASK,
      model: el.querySelector('.f-model').value.trim(),
      timeout: +el.querySelector('.f-timeout').value || 180,
    };
  });
  const routes = {};
  document.querySelectorAll('#routes .route-input').forEach(inp => { routes[inp.dataset.role] = inp.value.trim(); });
  const prices = {};
  document.querySelectorAll('[data-price]').forEach(inp => {
    const k = inp.dataset.price;
    prices[k] = prices[k] || { in: 0, out: 0 };
    prices[k][inp.dataset.f] = +inp.value || 0;
  });
  const defaults = Object.assign({}, S.config.defaults || {});
  const sto = $('#step-timeout');
  if (sto) defaults.step_timeout = +sto.value || 180;
  // 保留一键测试写出的 model_status，否则点保存会把「可用/不可用」标记清掉
  const model_status = S.config.model_status || {};
  return { providers, routes, prices, defaults, model_status };
}

/* ---------------- 项目 ---------------- */
async function loadBooks() {
  const r = await api('/books');
  S.books = r.books || [];
  $('#book-list').innerHTML = S.books.length ? S.books.map(b => `
    <div class="chitem"><span><b>${esc(b.title)}</b>
      <span class="tag dim">${b.chapter_count} 章</span>
      <span class="tag dim">${b.words} 字</span></span>
      <button class="btn mini" data-open="${esc(b.id)}">打开</button></div>`).join('')
    : '<div class="empty">还没有项目，右边创建一个。</div>';
  $('#book-list').querySelectorAll('[data-open]').forEach(btn => {
    btn.onclick = () => openBook(btn.dataset.open);
  });

  const sel = $('#w-book');
  const cur = sel.value;
  sel.innerHTML = S.books.map(b => `<option value="${esc(b.id)}">${esc(b.title)}</option>`).join('');
  if (cur && S.books.some(b => b.id === cur)) sel.value = cur;
}

async function openBook(id) {
  const d = await api('/books/' + encodeURIComponent(id));
  S.book = d;
  $('#detail-body').innerHTML = `
    <div class="export-bar">
      <span class="export-label">⬇ 一键导出全部章节</span>
      <button class="btn mini" id="exp-txt">下载 TXT</button>
      <button class="btn mini" id="exp-md">下载 MD</button>
      <span class="hint export-hint">把本书所有正式章节（按章号排序拼接）导出成文档，正文自动补章标题</span>
    </div>
    <div class="form">
      <label>书名<input id="b-title" value="${esc(d.book.title)}"></label>
      <label>题材<input id="b-genre" value="${esc(d.book.genre)}"></label>
      <label>单章字数<input id="b-words" type="number" value="${d.book.chapter_words || 2000}"></label>
      <label>章节目录<input id="b-dir" value="${esc(d.book.chapters_dir || '')}" placeholder="留空=默认"></label>
      <label>核心设定<textarea id="b-premise" rows="3">${esc(d.book.premise)}</textarea></label>
      <label>文风要求<textarea id="b-style" rows="2">${esc(d.book.style)}</textarea></label>
      <label>硬性禁忌<textarea id="b-taboo" rows="2">${esc(d.book.taboos)}</textarea></label>
      <label>卷纲/大纲<textarea id="b-outline" rows="5">${esc(d.book.outline)}</textarea></label>
    </div>
    <div class="row"><button class="btn primary" id="b-save">保存设定</button></div>
    <div id="b-out" class="out"></div>
    <h2 class="mt">章节（${d.chapters.length}）</h2>
    <div style="max-height:260px;overflow:auto">
      ${d.chapters.length ? d.chapters.map(c => `<div class="chitem"><span>第${c.num}章 · ${esc(c.title)} · ${c.words}字 ${c.has_summary ? '<span class="tag ok">摘要</span>' : ''}</span></div>`).join('') : '<div class="empty">暂无章节</div>'}
    </div>
    <h2 class="mt">成本</h2>
    ${costHtml(d.cost)}
    <h2 class="mt">快照（${(d.snapshots || []).length}）</h2>
    <div>${(d.snapshots || []).slice(0, 8).map(s => `<div class="chitem"><span class="mono">${esc(s)}</span><button class="btn mini" data-roll="${esc(s)}">回滚</button></div>`).join('') || '<div class="empty">暂无快照</div>'}</div>
  `;
  $('#b-save').onclick = async () => {
    const r = await fetch('/api/books/' + encodeURIComponent(id), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: $('#b-title').value, genre: $('#b-genre').value,
        chapter_words: +$('#b-words').value, chapters_dir: $('#b-dir').value,
        premise: $('#b-premise').value, style: $('#b-style').value,
        taboos: $('#b-taboo').value, outline: $('#b-outline').value
      })
    }).then(x => x.json());
    out('#b-out', r.ok ? '✅ 已保存' : '❌ 保存失败', r.ok ? 'ok' : 'err');
    loadBooks();
  };
  document.querySelectorAll('[data-roll]').forEach(btn => btn.onclick = async () => {
    const r = await api('/books/' + encodeURIComponent(id) + '/rollback', 'POST', { snapshot: btn.dataset.roll });
    out('#b-out', r.ok ? '✅ 已回滚状态文件（正文不变）' : '❌ 回滚失败', r.ok ? 'ok' : 'err');
    openBook(id);
  });
  const expTxt = $('#exp-txt'), expMd = $('#exp-md');
  if (expTxt) expTxt.onclick = () => exportBook(id, 'txt');
  if (expMd) expMd.onclick = () => exportBook(id, 'md');
}

// 一键导出整本书：后端按章号拼好正文并返回文件下载，前端只负责触发浏览器下载。
function exportBook(id, fmt) {
  const a = document.createElement('a');
  a.href = '/api/books/' + encodeURIComponent(id) + '/export?fmt=' + fmt;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function money(x) {
  return (x && parseFloat(x)) ? '¥' + x : '免费';
}
function costHtml(c) {
  if (!c || !c.calls) return '<div class="empty">暂无调用记录。</div>';
  const row = (k, v) => `<div class="kv"><span>${esc(k)}</span><span class="mono">${v.calls} 次 · ${v.total_tokens} tok · ${money(v.cost)}</span></div>`;
  return `<div class="kv"><span><b>合计</b></span><span class="mono"><b>${c.calls} 次 · ${c.total_tokens} tok · ${money(c.total_cost)}</b></span></div>
    ${Object.entries(c.by_role || {}).map(([k, v]) => row(k, v)).join('')}
    ${c.estimated_calls ? `<div class="hint">其中 ${c.estimated_calls} 次为流式估算值（服务商未返回 usage）。</div>` : ''}`;
}

/* ---------------- 写作台 ---------------- */
function updateDraftCount() {
  const c = $('#draft-cnt');
  if (c) c.textContent = ($('#pane-draft').value || '').replace(/\s/g, '').length;
}

async function loadChapter() {
  const id = $('#w-book').value;
  const n = +$('#w-chapter').value || 1;
  if (!id) { out('#write-out', '先创建一个项目', 'err'); return null; }
  const d = await api(`/books/${encodeURIComponent(id)}/chapter/${n}`);
  $('#pane-plan').value = d.plan || '';
  if (!$('#pane-draft').value.trim()) $('#pane-draft').value = d.text || d.draft || '';
  const ti = $('#chapter-title');
  if (ti) ti.value = d.title && d.title !== ('第' + String(n).padStart(3, '0') + '章') ? d.title : '';
  updateDraftCount();
  renderAudit(d.audit);
  renderRevise(d.revise);
  renderExtract(d.extraction);
  if (d.summary) renderSummary(d.summary);
  renderFlowFromChapter(d);   // 读取旧章即重建「流程结果」时间线，一眼看清本章怎么生成的
  renderStepProgress(d);   // 打开章节即刷新卡点条，一眼看清跑到哪、卡在哪
  updateMeta();            // 标题/字数与正文同步（避免首屏“第1章 0字”但内容有字的错位）
  return d;
}

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

function renderRevise(reviseTxt) {
  const box = $('#pane-revise');
  if (!box) return;
  if (!reviseTxt) {
    box.innerHTML = '<div class="empty">还没有改写报告。点「④ 改写」后，这里会列出每条审计问题是怎么改的。</div>';
    return;
  }
  let r;
  try { r = JSON.parse(reviseTxt); } catch (e) { box.innerHTML = '<pre>' + esc(reviseTxt) + '</pre>'; return; }
  // 新格式：对象带 rounds_detail —— 轮次感知改写报告
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

// 第⑤步 抽事实 —— 把模型抽取的事实 delta 渲染成可读清单
function renderExtract(delta) {
  const box = $('#pane-extract');
  if (!box) return;
  const d = delta || {};
  const chars = d.characters || {};
  const charKeys = Object.keys(chars);
  const facts = d.facts || [];
  const items = d.items || {};
  const itemKeys = Object.keys(items);
  const newHooks = d.new_hooks || [];
  const resolvedHooks = d.resolved_hooks || [];
  const relations = d.relations || [];
  const emotions = d.emotions || [];
  const time = d.time_advance || '';
  const has = charKeys.length || facts.length || itemKeys.length || newHooks.length ||
              resolvedHooks.length || relations.length || emotions.length || time;
  if (!has) {
    box.innerHTML = '<div class="empty">还没有抽取事实。点「⑤ 抽取事实」（或一键跑完的抽事实步骤）后，这里会列出本章抽取到的人物状态、事实、物品、伏笔、关系、情感与时间推进。</div>';
    return;
  }
  const sec = (title, body) => body ? `<div class="ext-sec"><div class="ext-h">${title}</div>${body}</div>` : '';
  const charHtml = charKeys.length ? charKeys.map(n => {
    const p = chars[n] || {};
    const kv = Object.keys(p).map(k => `<span class="ext-kv"><b>${esc(k)}</b>：${esc(p[k])}</span>`).join('');
    return `<div class="ext-row"><b>${esc(n)}</b>${kv ? '<div class="ext-kvs">' + kv + '</div>' : ''}</div>`;
  }).join('') : '';
  const factsHtml = facts.length ? facts.map(f => `<div class="ext-row">· ${esc(typeof f === 'string' ? f : json_cn(f))}</div>`).join('') : '';
  const itemsHtml = itemKeys.length ? itemKeys.map(i => {
    const p = items[i] || {};
    const kv = Object.keys(p).map(k => `<span class="ext-kv"><b>${esc(k)}</b>：${esc(p[k])}</span>`).join('');
    return `<div class="ext-row"><b>${esc(i)}</b>${kv ? '<div class="ext-kvs">' + kv + '</div>' : ''}</div>`;
  }).join('') : '';
  const hooksHtml = newHooks.length ? newHooks.map(h => {
    const t = typeof h === 'string' ? h : (h.text || json_cn(h));
    return `<div class="ext-row">＋ ${esc(t)}${h.due_chapter ? ' <span class="tag dim">预期第' + esc(h.due_chapter) + '章回收</span>' : ''}</div>`;
  }).join('') : '';
  const resolvedHtml = resolvedHooks.length ? resolvedHooks.map(h => {
    const id = (typeof h === 'string') ? '' : (h.id || '');
    const t = (typeof h === 'string') ? h : (h.text || json_cn(h));
    return `<div class="ext-row">✓ ${id ? '<span class="tag ok">' + esc(id) + '</span> ' : ''}${esc(t)}</div>`;
  }).join('') : '';
  const relHtml = relations.length ? relations.map(r => `<div class="ext-row">↔ ${esc(typeof r === 'string' ? r : json_cn(r))}</div>`).join('') : '';
  const emoHtml = emotions.length ? emotions.map(e => `<div class="ext-row">♥ ${esc(typeof e === 'string' ? e : json_cn(e))}</div>`).join('') : '';
  const timeHtml = time ? `<div class="ext-sec"><div class="ext-h">时间推进</div><div class="ext-row">${esc(time)}</div></div>` : '';
  box.innerHTML = sec('人物状态（' + charKeys.length + '）', charHtml)
    + sec('事实（' + facts.length + '）', factsHtml)
    + sec('物品（' + itemKeys.length + '）', itemsHtml)
    + sec('新伏笔（' + newHooks.length + '）', hooksHtml)
    + sec('已回收伏笔（' + resolvedHooks.length + '）', resolvedHtml)
    + sec('关系（' + relations.length + '）', relHtml)
    + sec('情感（' + emotions.length + '）', emoHtml)
    + timeHtml;
}

// 第⑥步 摘要 —— 渲染章节摘要文本
function renderSummary(text) {
  const box = $('#pane-summary');
  if (!box) return;
  if (!text || !text.trim()) {
    box.innerHTML = '<div class="empty">还没有摘要。点「⑥ 摘要」（或一键跑完的摘要步骤）后，这里会显示本章梗概。</div>';
    return;
  }
  box.innerHTML = '<div class="md">' + md(text) + '</div>';
}

async function refreshSide() {
  const id = $('#w-book').value;
  if (!id) return;
  const d = await api('/books/' + encodeURIComponent(id));
  S.book = d;
  const tags = $('#wh-tags');
  if (tags) {
    const words = d.book && d.book.words ? d.book.words : 0;
    tags.innerHTML = `<span class="ht">共 <b>${d.chapters.length}</b> 章</span>`
      + (words ? `<span class="ht">累计 <b>${words}</b> 字</span>` : '');
  }
  const proj = await api('/books/' + encodeURIComponent(id) + '/projection');
  $('#side-state').innerHTML = proj.markdown
    ? md(proj.markdown)
    : '<div class="empty">尚未抽取事实。写完一章后点「⑤ 抽取事实」，这里就会出现世界状态。</div>';
  const hooks = (d.hooks && d.hooks.hooks) || [];
  $('#side-hooks').innerHTML = hooks.length ? hooks.map(h => `
    <div class="chitem"><span>${h.status === 'resolved' ? '✅' : '⏳'} <span class="mono">${esc(h.id)}</span> ${esc(h.text)}
      <span class="tag dim">埋于第${h.planted_ch}章${h.due_chapter ? ' · 预期第' + h.due_chapter + '章' : ''}</span></span></div>`).join('')
    : '<div class="empty">伏笔池为空。写章后点「⑤ 抽取事实」会自动填充。</div>';
  $('#side-cost').innerHTML = costHtml(d.cost);
  $('#side-chapters').innerHTML = (d.chapters || []).slice(-40).reverse().map(c =>
    `<div class="chitem"><span>第${c.num}章 · ${esc(c.title)} · ${c.words}字</span>
     <button class="btn mini" data-go="${c.num}">跳转</button></div>`).join('') || '<div class="empty">暂无章节</div>';
  $('#side-chapters').querySelectorAll('[data-go]').forEach(b => b.onclick = () => {
    $('#w-chapter').value = b.dataset.go;
    $('#pane-draft').value = '';
    loadChapter();
    switchPane('draft');
  });
}

function switchPane(k) {
  $$('.tmini[data-pane]').forEach(x => x.classList.toggle('active', x.dataset.pane === k));
  ['plan', 'draft', 'audit', 'revise', 'flow', 'extract', 'summary'].forEach(x => $('#pane-' + x).classList.toggle('active', x === k));
}

function updateMeta() {
  const sel = $('#w-book');
  const bookTitle = sel.options && sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : '';
  const n = +$('#w-chapter').value || 1;
  const wc = ($('#pane-draft').value || '').replace(/\s/g, '').length;
  const cnt = $('#draft-cnt'); if (cnt) cnt.textContent = wc;
  const meta = $('#wh-meta');
  if (!meta) return;
  const chTitle = ($('#chapter-title') && $('#chapter-title').value || '').trim();
  meta.textContent = (bookTitle ? '《' + bookTitle + '》 · ' : '') + '第 ' + n + ' 章'
    + (chTitle ? ' · 「' + chTitle + '」' : '') + ' · 正文 ' + wc + ' 字';
}

// 写完正文后让服务端起一个章节标题并回填到输入框（失败静默，不影响正文）
async function fillTitle() {
  const id = $('#w-book').value, n = +$('#w-chapter').value;
  const ti = $('#chapter-title');
  if (!id || !ti) return;
  try {
    const r = await api(`/books/${encodeURIComponent(id)}/title`, 'POST',
      { chapter: n, text: $('#pane-draft').value, plan: $('#pane-plan').value });
    if (r.ok && r.title) ti.value = r.title;
  } catch (e) { /* 起名失败不打扰写作 */ }
}

/* ---------------- 流水线进度（卡点可视化） ----------------
   打开任意章节时，依据已落盘的产物（意图/草稿/审计/改写/抽取/摘要/采纳）
   反推「跑到哪一步、卡在哪一步」，并把结论写进常驻的进度卡点条，
   让状态栏与内容栏不再各说各话（解决“状态栏说①完成、内容栏却见③”的困惑）。 */
const STEP_ORDER = ['plan', 'write', 'audit', 'revise', 'observe', 'summary', 'accept'];
const STEP_BTN = { plan: 'w-plan', write: 'w-write', audit: 'w-audit', revise: 'w-revise',
  observe: 'w-extract', summary: 'w-summary', accept: 'w-accept' };
const STEP_NAME = { plan: '① 生成意图', write: '② 写章', audit: '③ 审计', revise: '④ 改写',
  observe: '⑤ 抽事实', summary: '⑥ 摘要', accept: '⑦ 采纳' };

// 抽取事实 delta 是否为“非空”（任一字段有内容即算已抽）
function nonEmptyExtraction(e) {
  if (!e || typeof e !== 'object') return false;
  return ['characters', 'facts', 'items', 'new_hooks', 'resolved_hooks', 'relations', 'emotions', 'time_advance']
    .some(k => {
      const v = e[k];
      if (Array.isArray(v)) return v.length > 0;
      if (v && typeof v === 'object') return Object.keys(v).length > 0;
      return !!(v && String(v).trim());
    });
}

// 从章节数据反推每一步是否已完成
function chapterProgress(d) {
  d = d || {};
  const has = x => !!(x && (typeof x === 'string' ? x.trim() : x));
  return {
    plan: has(d.plan),
    write: has(d.text) || has(d.draft),
    audit: has(d.audit),
    revise: has(d.revise),
    observe: nonEmptyExtraction(d.extraction),
    summary: has(d.summary),
    accept: has(d.text),
  };
}

// 渲染：给 7 个工序按钮上色（完成=绿/卡点=蓝高亮/失败=红），并写卡点条
// opts: { failStep, failError, runningStep }
function renderStepProgress(d, opts) {
  opts = opts || {};
  const prog = chapterProgress(d || {});
  STEP_ORDER.forEach(k => {
    const b = document.getElementById(STEP_BTN[k]);
    if (!b) return;
    b.classList.remove('done', 'frontier', 'fail', 'active');
    if (opts.failStep === k) b.classList.add('fail');
    else if (opts.runningStep === k) b.classList.add('active');
    else if (prog[k]) b.classList.add('done');
  });
  // 卡点 = 第一个未完成的步骤；若某步失败，它本身就是卡点
  let frontier = null;
  for (const k of STEP_ORDER) {
    if (opts.failStep === k) { frontier = k; break; }
    if (!prog[k]) { frontier = k; break; }
  }
  if (frontier && opts.failStep !== frontier && opts.runningStep !== frontier) {
    const fb = document.getElementById(STEP_BTN[frontier]);
    if (fb) fb.classList.add('frontier');
  }
  const strip = $('#progress-strip');
  if (!strip) return;
  const allDone = STEP_ORDER.every(k => prog[k]);
  if (allDone) {
    strip.className = 'progress-strip flag-done';
    const accepted = prog.accept;   // prog.accept 即 has(d.text)，已在 chapterProgress 内算好
    strip.innerHTML = accepted
      ? '✅ 本章七步全部完成（已采纳）· 中间产物（意图/草稿/审计/改写/抽事实/摘要）保留可回看，可直接进入下一章。'
      : '✅ 本章七步全部完成（含已采纳），可直接进入下一章。';
    return;
  }
  // 审计已做且仍有问题 → 在卡点提示里点明，避免以为卡住其实只是没改写
  let auditHint = '';
  if (prog.audit && frontier !== 'plan' && frontier !== 'write') {
    try {
      const ar = typeof d.audit === 'string' ? JSON.parse(d.audit) : d.audit;
      const iss = (ar && ar.issues) || [];
      if (iss.length) auditHint = '（审计发现 ' + iss.length + ' 个问题，建议点④改写）';
    } catch (e) { /* 坏 JSON 忽略 */ }
  }
  const doneNames = STEP_ORDER.filter(k => prog[k]).map(k => STEP_NAME[k]).join('、');
  const fname = frontier ? STEP_NAME[frontier] : '';
  let head, tail = '';
  if (opts.failStep === frontier) {
    head = '🔴 卡在第' + fname + '（上次一键跑完在此报错）';
    tail = opts.failError ? '：' + esc(opts.failError) : '';
    strip.className = 'progress-strip flag-stuck';
  } else if (opts.runningStep) {
    head = '⏳ 后台运行中，已到 ' + STEP_NAME[opts.runningStep];
    strip.className = 'progress-strip';
  } else {
    head = '✅ 已完成 ' + (doneNames || '无') + ' → 🔴 卡在第' + fname;
    tail = '（前序产物已落盘，点该工序单独重跑即可，无需从头开始）' + auditHint;
    strip.className = 'progress-strip flag-stuck';
  }
  strip.innerHTML = head + tail;
}

// 重新拉取当前章数据并刷新卡点条（单步操作或一键跑完后调用）
async function refreshProgress() {
  const id = $('#w-book').value, n = +$('#w-chapter').value || 1;
  if (!id) return;
  try {
    const d = await api(`/books/${encodeURIComponent(id)}/chapter/${n}`);
    renderStepProgress(d);
  } catch (e) { /* 忽略 */ }
}

/* ---------------- 事件绑定 ---------------- */

const FLOW_STEPS = [
  { key: 'plan', label: '① 生成意图' },
  { key: 'write', label: '② 写章' },
  { key: 'audit', label: '③ 审计' },
  { key: 'revise', label: '④ 定点改写' },
  { key: 'observe', label: '⑤ 抽事实' },
  { key: 'summary', label: '⑥ 摘要' },
];
const FLOW_LABEL = { plan: '① 生成意图', write: '② 写章', audit: '③ 审计', revise: '④ 定点改写', observe: '⑤ 抽事实', summary: '⑥ 摘要' };
function flowBadge(state) {
  return state === 'done' ? '<span class="tag ok">✓ 成功</span>'
    : state === 'fail' ? '<span class="tag bad">✗ 失败</span>'
    : '<span class="tag">— 未跑</span>';
}
function flowStatus(log, key) {
  const hits = (log || []).filter(x => x.step === key || x.step.startsWith(key + '#'));
  if (!hits.length) return { state: 'none', detail: '' };
  const fail = hits.find(x => x.ok === false);
  if (fail) return { state: 'fail', detail: (fail.error || '') };
  return { state: 'done', detail: hits[hits.length - 1] };
}
function renderFlow(log, observe, summary, accepted) {
  const box = $('#pane-flow');
  if (!box) return;
  if (!(log || []).length) {
    box.innerHTML = '<div class="empty">还没有流程结果。勾选「一键跑完」点「② 写章」跑完后，这里列出①~⑦每步的完成情况，以及第⑤步抽事实、第⑥步摘要的结果。</div>';
    return;
  }
  let html = '<div class="flow-list">';
  FLOW_STEPS.forEach(s => {
    const fs = flowStatus(log, s.key);
    let detail = '';
    if (s.key === 'observe' && observe) {
      detail = observe.applied
        ? `已写入真相文件：人物 ${observe.characters} · 事实 ${observe.facts} · 物品 ${observe.items} · 新伏笔 ${observe.new_hooks} · 关系 ${observe.relations} · 情感 ${observe.emotions}` + (observe.time_advance ? ' · 时间：' + esc(observe.time_advance) : '')
        : ('未更新：' + esc(observe.reason || '未知原因'));
    } else if (s.key === 'summary' && summary) {
      detail = '<details><summary>查看摘要文本</summary><div class="mono" style="white-space:pre-wrap;color:var(--ink2);margin-top:6px">' + esc(summary) + '</div></details>';
    } else if (fs.state === 'fail') {
      detail = '<span style="color:var(--bad)">' + esc(fs.detail) + '</span>';
    } else if (fs.state === 'done' && s.key === 'audit') {
      const d = fs.detail;
      detail = '<span class="mono">' + (d.score != null ? d.score + ' 分' : '') + (d.critical != null && d.critical ? ' · 致命 ' + d.critical : '') + '</span>';
    } else if (fs.state === 'done' && s.key === 'revise') {
      const d = fs.detail || {};
      const rem = d.remaining, round = d.round || 0;
      detail = rem == null
        ? '已按审计意见定点改写' + (round ? '（' + round + ' 轮）' : '')
        : (rem === 0
            ? '已按审计意见定点改写，全部问题修复（' + round + ' 轮）'
            : '<span style="color:var(--bad)">改写 ' + round + ' 轮，仍有 ' + rem + ' 条问题未修复</span>');
    }
    html += `<div class="flow-row"><span class="flow-label">${s.label}</span><span class="flow-badge">${flowBadge(fs.state)}</span><span class="flow-detail">${detail || '<span style="color:var(--ink3)">—</span>'}</span></div>`;
  });
  const accBadge = accepted ? '<span class="tag ok">✓ 已采纳</span>' : '<span class="tag">待人工</span>';
  const accDetail = accepted
    ? '<span style="color:var(--ok)">已写入正文章节文件，中间产物（意图/草稿/审计/改写/抽事实/摘要）全部保留，可随时回看或回滚</span>'
    : '<span style="color:var(--ink3)">审阅无误后点「⑦ 采纳写入」落盘</span>';
  html += '<div class="flow-row"><span class="flow-label">⑦ 采纳</span><span class="flow-badge">' + accBadge + '</span><span class="flow-detail">' + accDetail + '</span></div>';
  html += '</div>';
  box.innerHTML = html;
}
function renderFlowRunning(steps) {
  const box = $('#pane-flow');
  if (!box) return;
  const order = ['plan', 'write', 'audit', 'revise', 'observe', 'summary'];
  let html = '<div class="flow-list">';
  order.forEach(k => {
    const st = (steps || {})[k] || 'none';
    const b = st === 'done' ? '<span class="tag ok">✓ 成功</span>'
      : st === 'start' ? '<span class="tag" style="color:var(--accent);border-color:var(--accent)">▶ 进行中</span>'
      : st === 'fail' ? '<span class="tag bad">✗ 失败</span>'
      : '<span class="tag">— 未跑</span>';
    html += `<div class="flow-row"><span class="flow-label">${FLOW_LABEL[k]}</span><span class="flow-badge">${b}</span></div>`;
  });
  html += '</div>';
  box.innerHTML = html;
}

// 把抽事实 delta 压成「流程结果」里 ⑤ 步用的计数摘要（与后端 _summarize_observe 同形）
function extractionObserveSummary(e) {
  e = e || {};
  const cnt = k => Array.isArray(e[k]) ? e[k].length
    : (e[k] && typeof e[k] === 'object' ? Object.keys(e[k]).length : (e[k] ? 1 : 0));
  return {
    applied: nonEmptyExtraction(e),
    characters: cnt('characters'), facts: cnt('facts'), items: cnt('items'),
    new_hooks: (e.new_hooks || []).length, resolved_hooks: (e.resolved_hooks || []).length,
    relations: (e.relations || []).length, emotions: (e.emotions || []).length,
    time_advance: e.time_advance || '',
  };
}

// 从已落盘产物重建「流程结果」时间线（点「读取」打开旧章时调用，
// 无需重跑即可在「流程结果」看到本章 ①~⑦ 每一步是怎么生成的）
function renderFlowFromChapter(d) {
  d = d || {};
  const has = x => !!(x && (typeof x === 'string' ? x.trim() : x));
  const log = [];
  if (has(d.plan)) log.push({ step: 'plan', ok: true, meta: { model: '（读取自落盘意图）' } });
  if (has(d.text) || has(d.draft)) {
    const txt = d.text || d.draft || '';
    log.push({ step: 'write', ok: true, words: txt.replace(/\s/g, '').length });
  }
  if (has(d.audit)) {
    let r = null; try { r = JSON.parse(d.audit); } catch (e) { r = null; }
    if (r && typeof r === 'object') log.push({ step: 'audit', ok: !!r.passed, score: r.score, critical: r.critical_count });
    else log.push({ step: 'audit', ok: true });
  }
  if (has(d.revise)) {
    let r = null; try { r = JSON.parse(d.revise); } catch (e) { r = null; }
    const detail = (r && Array.isArray(r.rounds_detail)) ? r.rounds_detail : [];
    const rows = detail.length
      ? detail.flatMap(x => x.issues || [])
      : (r ? (Array.isArray(r) ? r : (r.report || [])) : []);
    const done = rows.filter(x => x.handled).length;
    log.push({ step: 'revise', ok: true, detail: { remaining: rows.length - done, round: detail.length } });
  }
  if (nonEmptyExtraction(d.extraction)) log.push({ step: 'observe', ok: true });
  if (has(d.summary)) log.push({ step: 'summary', ok: true });
  renderFlow(log, extractionObserveSummary(d.extraction), d.summary, has(d.text));
}


window.addEventListener('DOMContentLoaded', async () => {
  const pr = await api('/presets');
  S.presets = pr.presets || {};
  $('#preset-sel').innerHTML = Object.entries(S.presets).map(([k, v]) =>
    `<option value="${k}">${esc(v.label)}</option>`).join('');
  await loadConfig();
  await loadBooks();
  if (S.books.length) { $('#w-book').value = S.books[0].id; refreshSide(); }
  updateMeta();
  noAutofill();
  statusReady();
  if (S.books.length) { await loadChapter(); }   // 进入写作台即载入当前章，进度卡点条立刻有内容

  $('#w-book').addEventListener('change', () => { refreshSide(); updateMeta(); loadChapter(); });
  $('#w-chapter').addEventListener('input', updateMeta);
  $('#pane-draft').addEventListener('input', updateDraftCount);

  $('#add-provider').onclick = () => {
    const k = $('#preset-sel').value;
    const p = S.presets[k] || {};
    const n = (S.config.providers || []).length + 1;
    S.config.providers = S.config.providers || [];
    S.config.providers.push({
      id: 'p' + n, label: p.label || '自定义', base_url: p.base_url || '',
      api_key: '', model: p.model || '', timeout: 180
    });
    renderProviders(); renderRoutes(); renderPrices();
  };

  $('#test-all-btn').onclick = testAllModels;

  $('#save-config').onclick = async () => {
    const cfg = collectConfig();
    const r = await api('/config', 'POST', cfg);
    out('#save-out', r.ok ? '✅ 配置已保存到 config.local.json' : '❌ 保存失败', r.ok ? 'ok' : 'err');
    await loadConfig();
  };

  $('#create-book').onclick = async () => {
    const r = await api('/books', 'POST', {
      title: $('#nb-title').value || '未命名',
      genre: $('#nb-genre').value,
      chapter_words: +$('#nb-words').value || 2000,
      chapters_dir: $('#nb-dir').value,
      premise: $('#nb-premise').value,
      style: $('#nb-style').value,
      taboos: $('#nb-taboo').value,
      outline: $('#nb-outline').value,
    });
    if (r.ok) { await loadBooks(); out('#write-out', '✅ 项目已创建：' + r.book.id); }
  };

  async function inspire() {
    const hint = $('#nb-hint').value.trim();
    const btn = $('#inspire-btn');
    btn.disabled = true; $('#inspire-again').disabled = true;
    out('#inspire-out', 'AI 构思中（推理模型会先思考，可能需 1–2 分钟）…');
    let live = '', thinking = false;
    try {
      await ssePost('/inspire', { hint }, (ev, data) => {
        if (ev === 'think') {
          thinking = true;
          $('#inspire-out').textContent = '🤔 模型思考中…（先构思再落笔，请稍候）';
        } else if (ev === 'delta') {
          live += data.text;
          $('#inspire-out').textContent = (thinking ? '✍️ 生成中… ' : '') + (live.length > 150 ? live.slice(-150) : live);
        } else if (ev === 'result') {
          const b = data.book || {};
          $('#nb-title').value = b.title || '';
          $('#nb-genre').value = b.genre || '';
          $('#nb-premise').value = b.premise || '';
          $('#nb-style').value = b.style || '';
          $('#nb-taboo').value = b.taboos || '';
          $('#nb-outline').value = b.outline || '';
          out('#inspire-out', '✅ 已生成题材与全套设定（书名 / 题材 / 核心设定 / 文风 / 禁忌 / 大纲）。可微调后点「创建项目」。', 'ok');
          $('#inspire-again').style.display = '';
        } else if (ev === 'error') {
          out('#inspire-out', '❌ ' + (data.text || '生成失败'), 'err');
        }
      });
    } catch (e) {
      out('#inspire-out', '❌ ' + e.message, 'err');
    } finally {
      btn.disabled = false; $('#inspire-again').disabled = false;
    }
  }
  $('#inspire-btn').onclick = inspire;
  $('#inspire-again').onclick = inspire;

  $('#w-load').onclick = async () => { $('#pane-draft').value = ''; await loadChapter(); switchPane('flow'); refreshSide(); updateMeta(); };

  $('#w-plan').onclick = async () => {
    // 勾了「一键跑完」时，点「① 生成意图」也直接走全流程（与「② 写章」行为一致），
    // 否则用户预期链式跑下去，实际却在第1步就停。
    if ($('#w-autorun').checked) return runAuto();
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    out('#write-out', '规划中…');
    const r = await api(`/books/${encodeURIComponent(id)}/plan`, 'POST', { chapter: n });
    if (!r.ok) return out('#write-out', '❌ ' + r.error, 'err');
    $('#pane-plan').value = r.plan;
    switchPane('plan');
    out('#write-out', '✅ 意图已生成', 'ok');
    refreshSide();
    refreshProgress();
  };

  $('#w-write').onclick = async () => {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    if ($('#w-autorun').checked) return runAuto();
    const pane = $('#pane-draft');
    const cnt = $('#draft-cnt');
    switchPane('draft');
    pane.value = '';
    let acc = '';
    const t0 = Date.now();
    out('#write-out', '写作中（流式）…');
    try {
      await ssePost(`/books/${encodeURIComponent(id)}/write`,
        { chapter: n, plan: $('#pane-plan').value },
        (ev, data) => {
          if (ev === 'think') { out('#write-out', '🤔 模型思考中…（先构思再落笔，可能需数十秒）'); }
          else if (ev === 'delta') { acc += data.text; pane.value = acc; pane.scrollTop = pane.scrollHeight; if (cnt) cnt.textContent = acc.replace(/\s/g, '').length; }
          else if (ev === 'error') out('#write-out', '❌ ' + data.text, 'err');
          else if (ev === 'done') {
            pane.value = data.text;
            if (cnt) cnt.textContent = data.text.replace(/\s/g, '').length;
            out('#write-out', `✅ 完成 ${data.text.length} 字 · 用时 ${((Date.now() - t0) / 1000).toFixed(1)}s · ${data.meta.model}`, 'ok');
            fillTitle();   // 正文定稿后让服务端起个章标题
          }
        });
    } catch (e) { out('#write-out', '❌ ' + e.message, 'err'); }
    refreshSide();
    refreshProgress();
  };

  $('#w-audit').onclick = async () => {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    out('#write-out', '审计中…');
    const r = await api(`/books/${encodeURIComponent(id)}/audit`, 'POST',
      { chapter: n, text: $('#pane-draft').value, plan: $('#pane-plan').value });
    if (!r.ok) return out('#write-out', '❌ 审计失败', 'err');
    renderAudit(JSON.stringify({ score: r.score, passed: r.passed, issues: r.issues, summary: r.summary, critical_count: r.critical_count }));
    switchPane('audit');
    const cc = r.critical_count || 0;
    out('#write-out', r.passed ? `✅ 审计通过（${r.score} 分）` : `⚠️ ${cc} 个致命问题，建议点「④ 定点改写」` + (r.summary && r.summary.includes('合法 JSON') ? ' · 模型输出异常，请重试' : ''), r.passed ? 'ok' : 'err');
    refreshSide();
    refreshProgress();
  };

  $('#w-revise').onclick = async () => {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    const draft = $('#pane-draft').value;
    try {
      // 定点改写需要审计结论：没有就先跑一次审计（工序可单独重跑）
      out('#write-out', '审计中…（改写前先复核本章，可能需要一两分钟）');
      const r0 = await api(`/books/${encodeURIComponent(id)}/audit`, 'POST',
        { chapter: n, text: draft, plan: $('#pane-plan').value });
      if (!r0.ok) return out('#write-out', '❌ 审计失败：' + (r0.error || '未知错误'), 'err');
      const issues = r0.issues || [];
      out('#write-out', '修订中…（按审计意见定点改写）');
      const r = await api(`/books/${encodeURIComponent(id)}/revise`, 'POST',
        { chapter: n, text: draft, issues });
      if (r.changed) {
        $('#pane-draft').value = r.text;
        updateDraftCount();
        renderRevise(JSON.stringify(r.revise_obj || r.report || []));
        switchPane('revise');
      } else if (r.revise_obj) {
        // 无可改问题 / 改写未生效：也把「因审计无问题」说明渲染出来
        renderRevise(JSON.stringify(r.revise_obj));
        switchPane('revise');
      }
      const rn = (r.report || []).length;
      out('#write-out', r.changed
        ? `✅ 已按审计意见定点改写，共处理 ${rn} 条问题（见「改写报告」）`
        : '没有需要改的问题', r.changed ? 'ok' : '');
    } catch (e) {
      out('#write-out', '❌ 改写失败：' + (e && e.message ? e.message : e), 'err');
    }
    refreshSide();
    refreshProgress();
  };

  $('#save-draft').onclick = async () => {
    const id = $('#w-book').value;
    if (!id) return out('#write-out', '❌ 请先选择项目', 'err');
    const n = +$('#w-chapter').value || 1;
    const text = $('#pane-draft').value;
    try {
      const r = await api(`/books/${encodeURIComponent(id)}/draft`, 'POST', { chapter: n, text });
      if (!r.ok) return out('#write-out', '❌ 保存草稿失败：' + (r.error || ''), 'err');
      out('#write-out', `✅ 草稿已保存（第${n}章 · ${r.words} 字）`, 'ok');
    } catch (e) {
      out('#write-out', '❌ 保存草稿失败：' + (e && e.message ? e.message : e), 'err');
    }
  };

  $('#w-extract').onclick = async () => {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    out('#write-out', '抽取事实中…');
    const r = await api(`/books/${encodeURIComponent(id)}/extract`, 'POST',
      { chapter: n, text: $('#pane-draft').value });
    renderExtract(r.delta);
    switchPane('extract');
    out('#write-out', r.applied ? '✅ 真相文件已更新（state/ledger/hooks）' : '⚠️ 未更新：' + (r.reason || ''), r.applied ? 'ok' : 'err');
    refreshSide();
    refreshProgress();
  };

  $('#w-summary').onclick = async () => {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    out('#write-out', '生成摘要中…');
    const r = await api(`/books/${encodeURIComponent(id)}/summary`, 'POST',
      { chapter: n, text: $('#pane-draft').value });
    if (r.summary) renderSummary(r.summary);
    switchPane('summary');
    out('#write-out', r.summary ? '✅ 摘要已写入 summaries/ch%03d.md'.replace('%03d', String(n).padStart(3, '0')) : '❌ 失败', r.summary ? 'ok' : 'err');
    refreshSide();
    refreshProgress();
  };

  $('#w-accept').onclick = async () => {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    const title = ($('#chapter-title') && $('#chapter-title').value || '').trim();
    const r = await api(`/books/${encodeURIComponent(id)}/accept`, 'POST',
      { chapter: n, text: $('#pane-draft').value, title });
    out('#write-out', r.ok ? `✅ 已写入 ${r.file}（${r.words} 字${r.title ? ' · 标题「' + r.title + '」' : ''}），快照 ${r.snapshot} · 中间产物（意图/草稿/审计/改写/抽事实/摘要）保留可回看` : '❌ ' + (r.reason || '失败'), r.ok ? 'ok' : 'err');
    refreshProgress();   // 先按当前章（刚采纳）刷新，再前移到下一章
    if (r.ok) { $('#w-chapter').value = n + 1; $('#pane-draft').value = ''; $('#pane-plan').value = ''; if ($('#chapter-title')) $('#chapter-title').value = ''; }
    await loadBooks(); refreshSide(); updateMeta();
  };

  $('#gen-title').onclick = async () => {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    if (!($('#pane-draft').value || '').trim()) return out('#write-out', '先写正文再起名', 'err');
    out('#write-out', '起名中…');
    await fillTitle();
    const t = $('#chapter-title') ? $('#chapter-title').value : '';
    out('#write-out', t ? `✅ 标题：「${t}」` : '⚠️ 起名失败，可手动输入', t ? 'ok' : 'err');
  };

  /* ---- 一键跑完：SSE 流式进度，实时高亮当前步骤 ---- */
  const STEP_IDS = ['w-plan', 'w-write', 'w-audit', 'w-revise', 'w-extract', 'w-summary', 'w-accept'];
  const STEP_LABEL = { plan: '① 生成意图', write: '② 写作', audit: '③ 审计', revise: '④ 定点改写', observe: '⑤ 抽取事实', summary: '⑥ 摘要' };
  const STEP_INDEX = { plan: 1, write: 2, audit: 3, revise: 4, observe: 5, summary: 6 };
  function markSteps(activeIdx, doneUpTo) {
    STEP_IDS.forEach((sid, i) => {
      const b = document.getElementById(sid);
      if (!b) return;
      const n = i + 1;
      b.classList.toggle('active', n === activeIdx);
      b.classList.toggle('done', doneUpTo > 0 && n <= doneUpTo);
    });
  }

  async function restoreRunFlow() {
    const id = $('#w-book').value;
    if (!id) return;
    const n = +$('#w-chapter').value || 1;
    try {
      const r = await api(`/books/${encodeURIComponent(id)}/run/last?chapter=${n}`, 'GET');
      if (!r || r.status === 'none') return;
      // 拉当前章数据，用于给工序按钮上色 + 写卡点条（即使上一键跑完异常退出，落盘产物仍是真相来源）
      let d = null;
      try { d = await api(`/books/${encodeURIComponent(id)}/chapter/${n}`); } catch (e) { /* 忽略 */ }
      if (r.status === 'running') {
        renderFlowRunning(r.steps);
        const cur = ['plan', 'write', 'audit', 'revise', 'observe', 'summary'].find(k => (r.steps || {})[k] === 'start')
          || ['plan', 'write', 'audit', 'revise', 'observe', 'summary'].filter(k => (r.steps || {})[k] === 'done').pop();
        out('#write-out', '⏳ 上一键跑完仍在后台进行，已到「' + (cur ? FLOW_LABEL[cur] : '…') + '」——可在「流程结果」查看进度。', '');
        if (d) renderStepProgress(d, { runningStep: cur });
      } else if (r.status === 'done' && r.result) {
        renderFlow(r.result.log, r.result.observe, r.result.summary, !!(d && d.text));
        if (d) {
          renderStepProgress(d);
          if ($('#chapter-title') && d.title && d.title !== ('第' + String(n).padStart(3, '0') + '章'))
            $('#chapter-title').value = d.title;
          else if ($('#chapter-title') && r.result.title) $('#chapter-title').value = r.result.title;
        }
      } else if (r.status === 'error') {
        renderFlowRunning(r.steps);
        const failStep = ['plan', 'write', 'audit', 'revise', 'observe', 'summary'].find(k => (r.steps || {})[k] === 'fail');
        out('#write-out', '❌ 上一键跑完出错：' + (r.error || '未知'), 'err');
        if (d) renderStepProgress(d, { failStep: failStep, failError: r.error });
      }
    } catch (e) { /* 忽略：无历史状态 */ }
  }
  function applyRunResult(r) {
    if (!r || !r.ok) { out('#write-out', '❌ ' + ((r && r.error) || '未知错误'), 'err'); return; }
    $('#pane-plan').value = '';
    $('#pane-draft').value = r.text;
    updateDraftCount();
    if ($('#chapter-title')) $('#chapter-title').value = r.title || '';
    fillTitle();   // 若模型未带标题则即时补一个
    renderAudit(JSON.stringify(r.report));
    renderFlow(r.log, r.observe, r.summary);
    renderExtract(r.observe_delta);
    if (r.summary) renderSummary(r.summary);
    switchPane('flow');
    const failed = (r.log || []).find(x => x.ok === false);
    const planReused = (r.log || []).find(x => x.step === 'plan' && x.reused);
    if (failed) {
      // revise 循环里「修订后仍有问题未清零」的 log 条目只有 remaining、没有 error 字段，
      // 此前被误显示成「未知错误」；这里按真实原因给出可读提示。
      const why = failed.error
        || (failed.remaining != null
          ? `修订后仍有 ${failed.remaining} 个问题未清零（见右侧审计报告）`
          : '未知错误');
      out('#write-out', `⚠️ 第${r.log.indexOf(failed) + 1}步「${failed.step}」：${why}。前面的步骤已完成，可单独点对应工序重跑。`, 'err');
    } else {
      out('#write-out', `${r.passed ? '✅' : '⚠️'} 完成：${r.score} 分 · 用时 ${r.elapsed}s · 步骤 ${r.log.map(x => x.step).join(' → ')}（见「流程结果」）。${planReused ? '①已复用既有意图，未重复生成。' : ''}请人工过一遍再点「⑦ 采纳写入」。`, r.passed ? 'ok' : 'err');
    }
    markSteps(0, 7);
    refreshProgress();   // 跑完后按落盘产物刷新卡点条（全绿或标出残留缺口）
  }

  async function runAuto() {
    const id = $('#w-book').value, n = +$('#w-chapter').value;
    switchPane('draft');
    markSteps(1, 0);
    out('#write-out', '一键跑全流程中（规划→写作→审计→修订→抽取→摘要），请稍候…');
    let gotResult = false;
    try {
      await ssePost(`/books/${encodeURIComponent(id)}/run`,
        { chapter: n, auto_revise: 3, apply: true, summary: true,
          reuse_plan: $('#w-reuse-plan').checked },
        (ev, data) => {
          if (ev === 'progress') {
            const st = data.step, status = data.status;
            const idx = STEP_INDEX[st] || 0;
            const label = STEP_LABEL[st] || st;
            if (status === 'start') {
              markSteps(idx, idx - 1);
              out('#write-out', `${label}中…`);
            } else if (status === 'done') {
              markSteps(0, idx);
              if (st === 'plan' && data.detail && data.detail.reused) {
                out('#write-out', '① 复用已生成意图（不再重新生成，省资源）');
              }
            } else if (status === 'fail') {
              out('#write-out', `⚠️ ${label}失败：` + (((data.detail || {}).error) || '未知错误'), 'err');
            }
          } else if (ev === 'result') {
            gotResult = true;
            applyRunResult(data);
          } else if (ev === 'error') {
            gotResult = true;
            out('#write-out', '❌ ' + ((data && data.error) || '未知错误'), 'err');
          }
        });
    } catch (e) {
      out('#write-out', '❌ 一键跑完失败：' + (e && e.message ? e.message : e), 'err');
    }
    if (!gotResult) markSteps(0, 7);
    refreshSide();
  }

  /* ---------------- 夜间批量流水线 ---------------- */
  let batchTimer = null;
  const batchState = { running: false, taskId: null };
  const BATCH_LABEL = { queued: '排队中', running: '运行中', done: '已完成', stopped: '已停止', stalled: '已熔断' };

  function syncBatchStart() {
    if (batchState.running) return;
    $('#b-start').value = $('#w-chapter').value || 1;
  }
  $('#w-chapter').addEventListener('input', syncBatchStart);
  $('#w-book').addEventListener('change', () => { syncBatchStart(); recoverBatch(); restoreRunFlow(); });

  // 页面加载/切书时，若该书有正在跑的批量，自动重连并恢复进度显示
  async function recoverBatch() {
    const id = $('#w-book').value;
    if (!id) return;
    try {
      const r = await api(`/books/${encodeURIComponent(id)}/batch/latest`, 'GET');
      if (!r.active || !r.task_id) return;
      batchState.running = true;
      batchState.taskId = r.task_id;
      renderBatch(r);
      clearInterval(batchTimer);
      batchTimer = setInterval(() => pollBatch(id, r.task_id), 3000);
      out('#write-out', `🌙 检测到正在运行的批量（第${r.current}章，已完成 ${r.results.length}/${r.count}），已恢复进度显示。`, 'ok');
    } catch (e) { /* 静默：无任务或接口异常 */ }
  }

  function fmtBatchTime(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  }

  function renderBatch(s) {
    const statusEl = $('#batch-status'), bar = $('#b-bar'), res = $('#b-results');
    const pct = s.count ? Math.round((s.results.length / s.count) * 100) : 0;
    if (bar) bar.style.width = pct + '%';
    const terminal = s.status === 'done' || s.status === 'stopped' || s.status === 'stalled';
    const active = s.status === 'running' || s.status === 'queued';
    // 按钮态以服务端状态为准：运行中禁用「开始」、启用「停止」；终态反之
    const startBtn = $('#b-start-btn'), stopBtn = $('#b-stop-btn');
    if (startBtn) startBtn.disabled = active;
    if (stopBtn) stopBtn.disabled = !active;
    if (statusEl) {
      const kind = s.status === 'done' ? 'ok' : terminal ? 'err' : '';
      statusEl.className = 'batch-status' + (kind ? ' ' + kind : '');
      statusEl.textContent = `${BATCH_LABEL[s.status] || s.status} · 第${s.current || s.start}章 · ${s.results.length}/${s.count}`;
    }
    if (res) {
      let emptyMsg = '尚未开始，点「开始批量」。';
      if (active) emptyMsg = `运行中 · 正在写第 ${s.current || s.start} 章…（首章通常要几分钟，完成后结果逐条显示）`;
      else if (s.status === 'stalled') emptyMsg = '已熔断（单章超时）：请查看上面状态，调大「单章超时」或检查模型后重试。';
      res.innerHTML = s.results.length
        ? s.results.map(r => {
            const acc = r.accepted ? ' · 已采纳' : '';
            const err = r.error ? ` · <span class="err">${esc(r.error)}</span>` : '';
            return `<div class="brow"><span class="bnum">第${r.chapter}章</span><span class="bmark">${r.ok ? '✅' : '❌'}</span><span class="binfo">${r.score != null ? r.score + '分' : ''} · ${r.elapsed}s${acc}${err}</span></div>`;
          }).join('')
        : `<div class="hint">${esc(emptyMsg)}</div>`;
      res.scrollTop = res.scrollHeight;
    }
  }

  async function pollBatch(id, taskId) {
    const s = await api(`/books/${encodeURIComponent(id)}/batch/${taskId}`, 'GET');
    renderBatch(s);
    if (s.status === 'done' || s.status === 'stopped' || s.status === 'stalled') {
      clearInterval(batchTimer); batchTimer = null;
      batchState.running = false;
      const ok = s.results.filter(r => r.ok).length;
      const fail = s.results.length - ok;
      if (s.status === 'done') { $('#w-chapter').value = s.start + s.count; syncBatchStart(); }
      const msg = `🌙 批量${BATCH_LABEL[s.status]}：${ok}/${s.results.length} 章通过${fail ? `，${fail} 章失败` : ''}。${s.status === 'done' ? '已自动前移到第 ' + (s.start + s.count) + ' 章。' : ''}`;
      out('#write-out', msg, fail ? 'err' : 'ok');
      refreshSide();
    }
  }

  $('#b-start-btn').onclick = async () => {
    const id = $('#w-book').value;
    if (!id) return out('#write-out', '❌ 请先选择项目', 'err');
    const start = +$('#b-start').value || 1;
    const count = +$('#b-count').value || 1;
    const auto_accept = $('#b-accept').checked;
    const max_chapter_seconds = (+$('#b-timeout').value || 30) * 60;
    if (count > 99) return out('#write-out', '❌ 单次最多 99 章，超出请分批', 'err');
    out('#write-out', `🌙 批量启动：第${start}章起连写 ${count} 章${auto_accept ? '（自动采纳）' : ''}，后台运行，进度见下方卡片…`);
    const r = await api(`/books/${encodeURIComponent(id)}/batch`, 'POST',
      { start, count, auto_accept, max_chapter_seconds, auto_revise: 1, do_summary: true });
    if (!r.ok) return out('#write-out', '❌ ' + r.error, 'err');
    batchState.running = true;
    batchState.taskId = r.task_id;
    $('#b-start-btn').disabled = true;
    $('#b-stop-btn').disabled = false;
    $('#b-results').innerHTML = '';
    $('#b-bar').style.width = '0%';
    const s0 = await api(`/books/${encodeURIComponent(id)}/batch/${r.task_id}`, 'GET');
    renderBatch(s0);
    clearInterval(batchTimer);
    batchTimer = setInterval(() => pollBatch(id, r.task_id), 3000);
  };

  $('#b-stop-btn').onclick = async () => {
    const id = $('#w-book').value;
    if (!batchState.taskId) return;
    await api(`/books/${encodeURIComponent(id)}/batch_stop`, 'POST', { task_id: batchState.taskId });
    out('#write-out', '⏹ 已请求停止：当前章跑完即停，已完成的保留。', 'err');
    $('#b-stop-btn').disabled = true;
  };

  // 初始加载时当前书（默认第一本）若有正在跑的批量，自动重连恢复进度显示
  recoverBatch();
  // 初始加载时恢复最近一次「一键跑完」的流程结果（刷新后仍能看到第5、6步及进行到哪）
  restoreRunFlow();
});
