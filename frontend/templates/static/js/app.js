/* Shared helpers: storage, API, toasts, drawer, mascot, rings, citations. */
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage full or blocked */ } },
};
const USER_RE = /^[A-Za-z0-9_-]{1,64}$/;
function getUser() { const u = LS.get('edumind_user', null); return typeof u === 'string' && USER_RE.test(u) ? u : null; }
function ukey(name) { return `edumind_${name}_${getUser() || 'anon'}`; }

/* ---------- DOM helpers (text is always inserted safely) ---------- */
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  kids.flat(Infinity).forEach(c => { if (c == null || c === false) return; e.append(c.nodeType ? c : document.createTextNode(String(c))); });
  return e;
}
function parseDate(s) {
  if (!s) return null;
  const iso = /Z$|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z';
  const d = new Date(iso);
  return isNaN(d) ? null : d;
}
function fmtDate(s) { const d = parseDate(s); return d ? d.toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}) : ''; }
function fmtSize(b) { return b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB'; }
const pct = v => Math.round((v || 0) * 100);

/* ---------- toasts / banners ---------- */
function toast(msg, type = 'info') {
  const box = document.getElementById('toasts');
  if (!box) return;
  const icon = {ok: '✅', error: '😕', warn: '⚠️', info: '💬'}[type] || '💬';
  const t = h('div', {class: 'toast ' + type, role: 'status'}, h('span', {}, icon), h('span', {}, msg));
  box.append(t);
  setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 300); }, 4500);
}
function banner(msg, type = 'warn', withRetry = false) {
  const b = document.getElementById('banner');
  if (!b) return toast(msg, type);
  b.innerHTML = '';
  const el = h('div', {class: 'banner ' + type}, h('span', {}, msg),
    withRetry ? h('button', {class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => location.reload()}, 'Retry') : null);
  b.append(el);
}

/* ---------- API ---------- */
class ApiError extends Error {
  constructor(code, message, status) { super(message); this.code = code; this.status = status; }
}
async function api(path, opts = {}) {
  const {method = 'GET', body, form} = opts;
  const headers = {'X-User-Id': getUser() || ''};
  const init = {method, headers};
  if (form) init.body = form;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  let res;
  try { res = await fetch('/api' + path, init); }
  catch { throw new ApiError('network', "Can't reach the server. Is the backend running on port 8000?", 0); }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    let code = 'error', msg = 'Something went wrong.';
    if (data && data.error) { code = data.error.code || code; msg = data.error.message || msg; }
    else if (data && Array.isArray(data.detail)) { code = 'validation'; msg = data.detail.map(d => d.msg).join('; '); }
    else if (data && typeof data.detail === 'string') msg = data.detail;
    throw new ApiError(code, msg, res.status);
  }
  return data;
}
function notify(e) {
  if (!(e instanceof ApiError)) { toast('Something went wrong.', 'error'); return; }
  if (e.code === 'ai_not_configured') banner('AI is not set up yet. Add OPENAI_API_KEY to the backend .env and restart.', 'warn');
  else if (e.code === 'rate_limited') toast('Slow down a little, try again in a minute.', 'warn');
  else if (e.code === 'network' || e.code === 'backend_unreachable') banner("Can't reach the server. Is the backend running on port 8000?", 'error', true);
  else toast(e.message, 'error');
}

/* ---------- identity / session ---------- */
function newSession() { const s = 's' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36); LS.set(ukey('session'), s); return s; }
function sessionId() { return LS.get(ukey('session'), null) || newSession(); }
function selectedDocs() { return LS.get(ukey('docs'), []); }

/* ---------- visuals ---------- */
function mascot(mood = 'happy', size = 120) {
  const ink = '#2b2b4b';
  let eyes, extra = '';
  if (mood === 'celebrating') {
    eyes = `<path d="M33 48q9-12 18 0M69 48q9-12 18 0" stroke="${ink}" stroke-width="4.5" fill="none" stroke-linecap="round"/>`;
    extra = '<text x="4" y="22" font-size="18">✨</text><text x="92" y="20" font-size="18">🎉</text>';
  } else {
    const dx = mood === 'thinking' ? 4 : 0, dy = mood === 'thinking' ? -3 : 1;
    eyes = `<circle cx="42" cy="48" r="13" fill="#fff"/><circle cx="78" cy="48" r="13" fill="#fff"/><circle cx="${42 + dx}" cy="${48 + dy}" r="6" fill="${ink}"/><circle cx="${78 + dx}" cy="${48 + dy}" r="6" fill="${ink}"/><circle cx="${44 + dx}" cy="${46 + dy}" r="2" fill="#fff"/><circle cx="${80 + dx}" cy="${46 + dy}" r="2" fill="#fff"/>`;
    if (mood === 'encouraging') {
      eyes += `<path d="M30 30l22 6M90 30l-22 6" stroke="${ink}" stroke-width="3.5" stroke-linecap="round"/>`;
      extra = '<text x="92" y="22" font-size="18">💪</text>';
    }
    if (mood === 'thinking') extra = '<text x="92" y="20" font-size="18">💭</text>';
    if (mood === 'happy') extra = '<text x="92" y="20" font-size="16">⭐</text>';
  }
  return `<svg class="mascot" width="${size}" height="${size}" viewBox="0 0 120 120" role="img" aria-label="Edu the owl">
    <path d="M28 26l10 18-20-2z" fill="#6a4cf0"/><path d="M92 26l-10 18 20-2z" fill="#6a4cf0"/>
    <ellipse cx="60" cy="72" rx="42" ry="40" fill="#7c5cff"/><ellipse cx="60" cy="84" rx="26" ry="26" fill="#ece6ff"/>
    <path d="M34 78q4 8 10 0M50 88q4 8 10 0M66 88q4 8 10 0" stroke="#c9bdff" stroke-width="3" fill="none" stroke-linecap="round"/>
    <circle cx="42" cy="48" r="17" fill="#ffd23f"/><circle cx="78" cy="48" r="17" fill="#ffd23f"/>
    ${eyes}<path d="M54 58h12l-6 12z" fill="#ff8a3d"/>
    <path d="M22 70q-10 14 4 30q4-18-4-30zM98 70q10 14-4 30q-4-18 4-30z" fill="#6a4cf0"/>
    <path d="M44 110h10M66 110h10" stroke="#ff8a3d" stroke-width="5" stroke-linecap="round"/>${extra}</svg>`;
}
function ring(p, {size = 140, color = 'var(--purple)', label = ''} = {}) {
  const v = Math.max(0, Math.min(100, p || 0)), off = 283 - 283 * v / 100;
  return `<div class="ring" style="width:${size}px;height:${size}px"><svg viewBox="0 0 100 100"><circle class="ring-bg" cx="50" cy="50" r="45"/><circle class="ring-fg" cx="50" cy="50" r="45" style="stroke:${color};--off:${off}"/></svg><div class="ring-label"><b>${Math.round(v)}%</b>${label ? `<small>${esc(label)}</small>` : ''}</div></div>`;
}
function celebrate() {
  if (!window.confetti) return;
  confetti({particleCount: 140, spread: 80, origin: {y: 0.6}});
  setTimeout(() => confetti({particleCount: 70, angle: 60, spread: 60, origin: {x: 0}}), 250);
  setTimeout(() => confetti({particleCount: 70, angle: 120, spread: 60, origin: {x: 1}}), 400);
}
function statusBadge(s) {
  const m = {ready: ['mint', '✅ Ready'], processing: ['blue', '⏳ Processing'], awaiting_index: ['yellow', '🕓 Needs indexing'], failed: ['pink', '❌ Failed']}[s] || ['blue', s];
  return h('span', {class: 'badge ' + m[0]}, m[1]);
}
function activityText(a) {
  const d = a.detail || {};
  switch (a.kind) {
    case 'upload': return `📤 Uploaded ${d.filename || 'a file'}`;
    case 'tutor_question': return `🦉 Asked: ${d.question || ''}`;
    case 'quiz_generated': return `🎲 Created a ${d.kind || ''} quiz`;
    case 'quiz_submitted': return `🎯 Finished a quiz (${Math.round(d.percent ?? 0)}%)`;
    default: return a.kind;
  }
}

/* ---------- drawer + citations ---------- */
function openDrawer(title, ...content) {
  document.getElementById('drawerTitle').textContent = title;
  const body = document.getElementById('drawerBody');
  body.innerHTML = '';
  body.append(...content);
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawerBack').classList.add('open');
  document.getElementById('drawer').setAttribute('aria-hidden', 'false');
}
function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawerBack').classList.remove('open');
  document.getElementById('drawer').setAttribute('aria-hidden', 'true');
}
async function openCitation(chunkId) {
  try {
    const d = await api('/documents/chunks/' + encodeURIComponent(chunkId));
    const c = d.citation;
    openDrawer('📎 ' + c.document_name,
      h('div', {class: 'chips'}, h('span', {class: 'chip'}, c.label), h('span', {class: 'chip'}, 'Topic: ' + c.topic), h('span', {class: 'chip'}, c.content_type)),
      d.previous_text ? h('div', {class: 'ctx prev'}, h('small', {}, 'Before'), d.previous_text) : null,
      h('div', {class: 'ctx main-ctx'}, h('small', {}, 'This passage'), d.text),
      d.next_text ? h('div', {class: 'ctx next'}, h('small', {}, 'After'), d.next_text) : null);
  } catch (e) { notify(e); }
}

function answerNodes(text, cites) {
  const map = {};
  (cites || []).forEach(c => { if (c.marker) map[c.marker] = c; });
  const out = [], re = /\[S(\d+)\]/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    out.push(text.slice(last, m.index));
    const c = map['S' + m[1]];
    if (c) out.push(h('button', {class: 'cite-chip', type: 'button', title: c.label, onclick: () => openCitation(c.chunk_id)}, m[1]));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}
function evidenceBadge(status) {
  const m = {supported: ['mint', 'Based on your notes ✅'], partial: ['yellow', 'Partly covered ⚠️'], insufficient: ['orange', 'Not in your notes 🤔']}[status] || ['blue', status];
  return h('span', {class: 'badge ' + m[0]}, m[1]);
}
function assistantCard(data, onSuggest) {
  const card = h('div', {class: 'assistant'});
  card.append(evidenceBadge(data.evidence_status), h('div', {class: 'answer'}, answerNodes(data.answer || '', data.citations)));
  if (data.outside_knowledge_note)
    card.append(h('div', {class: 'outside-box'}, h('b', {}, '🌍 Outside your notes'), h('p', {}, data.outside_knowledge_note)));
  if ((data.citations || []).length) {
    card.append(h('div', {class: 'cites'}, h('small', {class: 'muted'}, 'Sources'),
      data.citations.map(c => h('button', {class: 'source-btn', type: 'button', onclick: () => openCitation(c.chunk_id)},
        `[${(c.marker || '').replace('S', '')}] ${c.label} · ${c.topic}`, c.score != null ? ` · ${Math.round(c.score * 100)}% match` : ''))));
  }
  if (onSuggest && (data.suggestions || []).length)
    card.append(h('div', {class: 'chips sug'}, data.suggestions.map(s => h('button', {class: 'chip chip-btn', type: 'button', onclick: () => onSuggest(s)}, s))));
  return card;
}

/* ---------- bootstrap ---------- */
(function init() {
  const isPublic = document.body.dataset.public === '1';
  if (!isPublic && !getUser()) { location.replace('/'); return; }
  const nu = document.getElementById('navUser');
  if (nu) nu.textContent = getUser();
  const sw = document.getElementById('switchUser');
  if (sw) sw.addEventListener('click', () => { localStorage.removeItem('edumind_user'); location.href = '/'; });
  document.getElementById('drawerClose').addEventListener('click', closeDrawer);
  document.getElementById('drawerBack').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
})();