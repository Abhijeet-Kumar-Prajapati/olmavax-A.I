/* ══════════════════════════════════════════════════════════
   Olmavax A.I — frontend
   ══════════════════════════════════════════════════════════ */
(() => {
'use strict';

/* ────────────────── tiny helpers ────────────────── */
const $  = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const DEFAULTS = {
  chats: [], cur: null, lang: 'en', agent: 'auto', provider: 'auto', model: 'auto',
  keys: {}, theme: 'dark', name: '', projects: [], project: null,
  enterToSend: true, talkRate: 1, fontScale: 1, splashSeen: false, space: 'chat', rail: false, sideSize: 'md',
};
let S;
try { S = Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem('olmavax') || '{}')); }
catch { S = Object.assign({}, DEFAULTS); }

const T = (k, v) => {
  let s = (I18N[S.lang] || I18N.en)[k] ?? I18N.en[k] ?? k;
  for (const x in v || {}) s = s.replace('{' + x + '}', v[x]);
  return s;
};
const save = () => { try { localStorage.setItem('olmavax', JSON.stringify(S)); } catch {} };
const esc  = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const uid  = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const safeUrl = u => /^https?:\/\//i.test(u) ? u : '#';
const chat = () => S.chats.find(c => c.id === S.cur);
const isRTL = () => S.lang === 'ar';
const HL = window.Highlighter || { highlight: s => esc(s), detect: () => 'text', languages: [] };

/* ─────────── icons ─────────── */
const IC = {
  copy:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2.4"/><path d="M5 15V5a2 2 0 012-2h10"/></svg>',
  speak:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h3.5L12 19V5L7.5 9z"/><path d="M16 8.5a4.5 4.5 0 010 7M18.5 6a8 8 0 010 12"/></svg>',
  redo:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 10-2.6 6"/><path d="M20 5v6h-6"/></svg>',
  save:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h11l3 3v13H5z"/><path d="M8 4v6h7V4M8 20v-6h8v6"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9.5 7V5h5v2M6.5 7l1 13h9l1-13"/></svg>',
  pin:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6l-1 6 3.5 3.5H6.5L10 9z"/><path d="M12 12.5V21"/></svg>',
  dl:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12M7.5 11.5L12 16l4.5-4.5"/><path d="M5 20h14"/></svg>',
  up:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  down:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12l7 7 7-7"/></svg>',
  play:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5l12 7.5-12 7.5z"/></svg>',
  clock:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>',
  plug:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3v4M15 3v4"/><path d="M6 7h12v4a6 6 0 01-6 6 6 6 0 01-6-6z"/><path d="M12 17v4"/></svg>',
  book:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 5.5A2.5 2.5 0 016.5 3H20v15H6.5A2.5 2.5 0 000 20.5z"/><path d="M4 5.5v15"/></svg>',
  img:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M4 17l5-5 4 4 2.5-2.5L20 17"/></svg>',
  code:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 8L5 12l3.5 4M15.5 8l3.5 4-3.5 4"/></svg>',
  gear:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2V21a2 2 0 11-4 0v-.1A1.7 1.7 0 004 19.4l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.7 1.7 0 001 15H1a2 2 0 110-4h.1A1.7 1.7 0 002.6 8.6l-.1-.1a2 2 0 112.8-2.8l.1.1A1.7 1.7 0 009 5.6V5a2 2 0 114 0v.1a1.7 1.7 0 002.9 1.2l.1-.1a2 2 0 112.8 2.8l-.1.1A1.7 1.7 0 0021 15h.1a2 2 0 110 4H21z" stroke-linejoin="round"/></svg>',
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5" stroke-linecap="round"/></svg>',
  folder:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 7a2 2 0 012-2h4l2 2.5h8a2 2 0 012 2V17a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>',
  memory:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M4.2 7.5l2.6 1.5M17.2 15l2.6 1.5M19.8 7.5l-2.6 1.5M6.8 15l-2.6 1.5"/></svg>',
  build:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 5.5l4 4L8 20H4v-4z"/><path d="M12 8l4 4"/></svg>',
  check:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>',
  warn:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.5l8.5 15h-17z"/><path d="M12 10v4M12 16.5v.2"/></svg>',
  info:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.8v.2"/></svg>',
  plus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  x:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  edit:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9a2.1 2.1 0 00-3-3L5 17z"/></svg>',
  export:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 014 19V8a1.5 1.5 0 011.5-1.5H10"/></svg>',
};
const GO_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
const GO_STOP = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/></svg>';

/* ─────────────────── runtime state ─────────────────── */
let busy = false, ctrl = null, agents = [], models = [], providers = {}, sidecar = { available: false };
let mode = null, think = !!S.think, atts = [], liveEngine = 'mock', greetPick = Math.random(), stickBottom = true;

/* ──────────── toasts ──────────── */
function toast(msg, kind = 'info', ms = 2600) {
  const d = document.createElement('div');
  d.className = 'toast ' + kind;
  d.innerHTML = (kind === 'ok' ? IC.check : kind === 'err' ? IC.warn : IC.info) + '<span>' + esc(msg) + '</span>';
  $('#toasts').appendChild(d);
  setTimeout(() => { d.classList.add('out'); setTimeout(() => d.remove(), 240); }, ms);
}

/* ---------- trusted inline SVG (QR codes from our own encoder) ----------
   Everything else is escaped. This allowlist rejects anything scriptable, so
   even if a model hallucinated a fenced svg block it could not execute. */
function safeSvg(s) {
  const t = String(s).trim();
  if (!/^<svg[\s>]/i.test(t) || !/<\/svg>\s*$/i.test(t)) return null;
  if (/<script|javascript:|on\w+\s*=|xlink:href|<foreignObject|<image\b|<use\b/i.test(t)) return null;
  if (!/viewBox\s*=/i.test(t)) return null;
  return t;
}

/* ─────────────────────────────────────── markdown with syntax highlighting ─────────────────────────────────────── */
function md(src) {
  const blocks = [];
  // Split on fenced blocks FIRST so code keeps its raw characters; everything
  // outside the fences is escaped, and the highlighter escapes its own text.
  const parts = String(src == null ? "" : src).split(/```(\w*)\n?([\s\S]*?)```/g);
  let out = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 3 === 0) { out += inlineMd(parts[i]); continue; }
    if (i % 3 === 2) continue;   // the body for the pair above
    const lang = parts[i], body = parts[i + 1].replace(/\n$/, "");
    const raw = lang.toLowerCase() === "svg" ? safeSvg(body) : null;
    if (raw) {
      blocks.push('<div class="qr-out">' + raw + "</div>");
    } else {
      const l = lang || HL.detect(body);
      blocks.push('<div class="code" data-lang="' + esc(l) + '">' +
        '<div class="code-bar"><span class="code-lang">' + esc(l) + "</span>" +
        '<button data-cp="' + (blocks.length) + '" title="Copy">' + IC.copy + "</button>" +
        '<button data-dl="' + (blocks.length) + '" title="Download">' + IC.dl + "</button></div>" +
        '<pre><code>' + HL.highlight(body, lang) + "</code></pre></div>");
    }
    out += "\u0000B" + (blocks.length - 1) + "\u0000";
  }
  return out.replace(/\u0000B(\d+)\u0000/g, (_, i) => blocks[+i]);
}

/* ──────────────────────────────────────────────────── inline markdown only no code fences reach this ──────────────────────────────────────────────────── */
function inlineMd(text) {
  return esc(text)
    .replace(/\\([*_`\\])/g, "$1")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/^###\s+(.+)$/gm, '<b style="font-size:1.06em">$1</b>')
    .replace(/^##\s+(.+)$/gm, '<b style="font-size:1.14em">$1</b>')
    .replace(/^#\s+(.+)$/gm, '<b style="font-size:1.24em">$1</b>')
    .replace(/\*\*(.+?)\*\*/gs, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=$|[\s.,!?)])/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/^[-*]\s+(.+)$/gm, "•&nbsp; $1")
    .replace(/\n{2,}/g, "<br><br>")
    .replace(/\n/g, "<br>");
}
const codeBlocks = () => {
  const raw = [];
  $$('#msgs .code pre').forEach(p => { raw[p.closest('.code').dataset.lang] = p.textContent; });
  return raw;
};

/* ──────────────── api helper ──────────────── */
async function api(path, opts = {}) {
  const r = await fetch(path, Object.assign({ headers: { 'content-type': 'application/json' } }, opts));
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'HTTP ' + r.status);
  return j;
}

/* ═══════ SHELL ═══════ */
function applyI18n() {
  $$('[data-i]').forEach(e => e.textContent = T(e.dataset.i));
  $$('[data-ph]').forEach(e => e.placeholder = T(e.dataset.ph));
  $('#input').placeholder = T('placeholder');
  document.documentElement.lang = S.lang;
  document.documentElement.dir = isRTL() ? 'rtl' : 'ltr';
  document.documentElement.dataset.theme = S.theme;
  document.documentElement.style.fontSize = (15 * (S.fontScale || 1)) + 'px';
  $('#langPill').textContent = (S.lang || 'en').toUpperCase();
  const agent = agents.find(a => a.id === S.agent);
  $('#agentPill').textContent = S.agent === 'auto' ? T('auto') : (agent ? agent.icon + ' ' + agent.name.split(' ')[0] : S.agent);
  paintEngine(); greet(); updateChip(); updateGo(); renderTitle(); renderChats(); paintMode();
  $('#think').classList.toggle('on', think);
  $('#think').setAttribute('aria-pressed', String(think));
}
function greet() { $('#greet').textContent = (S.name && greetPick < 0.5) ? T('goodToSee', { name: S.name }) : T('onMind'); }
function renderTitle() {
  const c = chat();
  $('#chatTitle').textContent = (c && c.msgs.length) ? c.title : 'Olmavax A.I';
}
function paintMode() {
  $$('.seg [data-mode]').forEach(b => {
    const on = b.dataset.mode === S.space;
    b.classList.toggle('on', on);
    b.setAttribute('aria-selected', String(on));
  });
  document.body.classList.toggle('work-mode', S.space === 'work');
  document.body.classList.toggle('side-rail', !!S.rail);
  document.body.classList.toggle('side-sm', !S.rail && S.sideSize === 'sm');
  document.body.classList.toggle('side-wide', sideW() >= SIDE_W.lg);
  const sc = $('#sideCollapse'); if (sc) sc.setAttribute('aria-expanded', String(!S.rail));
  $('#talkBtn') && $('#talkBtn').classList.toggle('on', live.on);
  $('#voiceBtn') && $('#voiceBtn').classList.toggle('on', live.on);
}

/* ── sidebar width ───────────────────────────────────────────────────
   Four presets. "rail" is the icon-only strip; the other three keep every
   label visible, and the widest one gives the panel nav room to go back to
   a single column. */
const SIDE_SIZES = [
  { id: 'rail', px: 68,  rail: true },
  { id: 'sm',   px: 208, rail: false },
  { id: 'md',   px: 268, rail: false },
  { id: 'lg',   px: 344, rail: false },
];
const SIDE_W = { rail: 68, sm: 208, md: 268, lg: 344 };

function sideSize() {
  return SIDE_SIZES.find(s => s.id === S.sideSize) || SIDE_SIZES[2];
}
function sideW() { return S.rail ? SIDE_W.rail : sideSize().px; }

/* The sidebar can never leave the chat area at zero width, so the chosen
   width is written onto the element rather than left to a stale CSS var. */
function applySideW() {
  const side = $('#side');
  if (side) side.style.setProperty('--side-w', sideW() + 'px');
}

function setSideSize(id, quiet) {
  const found = SIDE_SIZES.find(s => s.id === id);
  if (!found) return;
  S.sideSize = found.id;
  S.rail = found.rail;        // picking "rail" collapses, picking a width expands
  save(); applySideW(); paintMode();
  if (!quiet) toast(T('sidebarSize') + ': ' + T('size_' + found.id), 'info', 1600);
}

function toggleRail() {
  S.rail = !S.rail; save(); applySideW(); paintMode();
  toast(S.rail ? T('sidebarCollapsed') : T('sidebarExpanded'), 'info', 1500);
}
function setSpace(m) {
  S.space = m; save(); paintMode();
  if (m === 'work') { toast(T('workHint'), 'info', 3400); openPanel('codex'); }
}
function updateChip() {
  const c = $('#chip'); c.hidden = !mode; if (!mode) return;
  const MAP = { image: 'Create an image', search: 'Web search', research: 'Deep research', write: 'Write or edit' };
  c.innerHTML = esc(T(MAP[mode] || 'mode')) + ' <button aria-label="Remove">' + IC.x + '</button>';
  c.querySelector('button').onclick = () => setMode(null);
}
function setMode(m) { mode = m; updateChip(); $('#input').focus(); }
function updateGo() {
  const has = $('#input').value.trim() || atts.length;
  const b = $('#go');
  b.hidden = !busy && !has;
  b.innerHTML = busy ? GO_STOP : GO_SEND;
  b.classList.toggle('stop', busy);
}
function paintEngine() {
  const e = $('#engine'); if (!e) return;
  const L = {
    anthropic: { t: 'Claude · online', ok: 1 }, openai: { t: 'OpenAI · online', ok: 1 },
    ollama: { t: 'Ollama · offline', ok: 1 }, sidecar: { t: 'Olmavax Agent', ok: 1 },
    mock: { t: T('offlineBrain'), ok: 0 },
  }[liveEngine] || { t: T('offlineBrain'), ok: 0 };
  e.className = 'eng ' + (L.ok ? 'live' : 'warn');
  $('#engTxt').textContent = L.t;
  $('#engFix').hidden = !!L.ok;
}
async function checkEngine() {
  try {
    const j = await api('/api/status', { method: 'POST', body: JSON.stringify({ keys: S.keys }) });
    providers = j.providers || {}; sidecar = j.sidecar || { available: false };
    liveEngine = j.live || 'mock';
    paintEngine(); updateModelBtn(); updatePlugins();
  } catch { /* offline */ }
}
function updateModelBtn() {
  const m = models.find(x => x.id === S.model && x.provider === (S.provider || 'auto'))
          || models.find(x => x.id === S.model) || models[0];
  $('#modelBtnLabel').textContent = m ? m.label : 'Auto';
  $('#modelBtnIcon').style.background = m && m.free
    ? 'linear-gradient(135deg,#35d07f,#4f8cff)' : 'linear-gradient(135deg,#4f8cff,#8b5cf6)';
}

/* ═══════════ CHAT LIST ═══════════ */
function bucketOf(ts) {
  const d = new Date(ts), now = new Date(), day = 864e5;
  const t0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (ts >= t0) return 'today';
  if (ts >= t0 - day) return 'yesterday';
  if (ts >= t0 - day * 7) return 'prev7';
  if (ts >= t0 - day * 30) return 'prev30';
  return 'older';
}
function renderChats() {
  const box = $('#chats'); if (!box) return;
  const q = ($('#csearch').value || '').toLowerCase().trim();
  box.innerHTML = '';
  const list = S.chats.filter(c => !q || (c.title || '').toLowerCase().includes(q))
    .sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || (b.at || 0) - (a.at || 0));
  $('#chatsEmpty').hidden = list.length > 0;
  if (!list.length) return;
  const groups = new Map();
  for (const c of list) {
    const k = c.pinned ? 'pin' : bucketOf(c.at || Date.now());
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(c);
  }
  const labels = { pin: T('pinned'), today: T('today'), yesterday: T('yesterday'),
                   prev7: T('prev7'), prev30: T('prev30'), older: T('older') };
  for (const k of ['pin', 'today', 'yesterday', 'prev7', 'prev30', 'older']) {
    const arr = groups.get(k); if (!arr) continue;
    const g = document.createElement('div'); g.className = 'grp';
    g.innerHTML = '<div class="grp-h">' + esc(labels[k]) + '</div>';
    for (const c of arr) {
      const d = document.createElement('div');
      d.className = 'chat' + (c.id === S.cur ? ' on' : '') + (c.pinned ? ' pin' : '');
      d.innerHTML = '<span class="chat-txt">' + esc(c.title || T('newChat')) + '</span>' +
        '<button class="chat-x" title="' + esc(T('deleteChat')) + '">' + IC.trash + '</button>';
      d.onclick = e => { if (e.target.closest('.chat-x')) return; S.cur = c.id; save(); render(); closeSide(); };
      d.oncontextmenu = e => { e.preventDefault(); chatMenu(c, e.clientX, e.clientY); };
      d.querySelector('.chat-x').onclick = e => { e.stopPropagation(); delChat(c.id); };
      g.appendChild(d);
    }
    box.appendChild(g);
  }
}
function delChat(id) {
  S.chats = S.chats.filter(c => c.id !== id);
  if (S.cur === id) S.cur = (S.chats[0] || {}).id || null;
  save(); render(); toast(T('chatDeleted'), 'ok');
}
function chatMenu(c, x, y) {
  closeMenus();
  const m = document.createElement('div');
  m.className = 'pal-card';
  Object.assign(m.style, { position: 'fixed', left: Math.min(x, innerWidth - 240) + 'px',
                           top: Math.min(y, innerHeight - 210) + 'px', width: '228px', zIndex: 500 });
  const item = (label, icon, fn) => {
    const b = document.createElement('button');
    b.className = 'pal-item'; b.innerHTML = icon + '<span>' + esc(label) + '</span>';
    b.onclick = () => { m.remove(); fn(); };
    return b;
  };
  m.append(
    item(T('renameChat'), IC.edit, () => renameChat(c.id)),
    item(c.pinned ? T('unpinChat') : T('pinChat'), IC.pin, () => { c.pinned = !c.pinned; save(); renderChats(); }),
    item(T('exportChat'), IC.export, () => exportChat(c.id)),
    item(T('exportPdf'), IC.dl, () => exportPDF(c.id)),
    item(T('deleteChat'), IC.trash, () => delChat(c.id)),
  );
  document.body.appendChild(m);
  const kill = e => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('click', kill); } };
  setTimeout(() => document.addEventListener('click', kill), 0);
}
function renameChat(id) {
  const c = S.chats.find(x => x.id === id); if (!c) return;
  const v = prompt(T('renameChat'), c.title || '');
  if (v && v.trim()) { c.title = v.trim().slice(0, 80); save(); renderTitle(); renderChats(); toast(T('chatRenamed'), 'ok'); }
}
function exportChat(id) {
  const c = S.chats.find(x => x.id === id); if (!c) return;
  const md2 = ['# ' + c.title, '', '_Exported from Olmavax A.I · ' + new Date().toLocaleString() + '_', '']
    .concat(c.msgs.map(m => '**' + (m.role === 'user' ? 'You' : 'Olmavax') + '**\n\n' + (m.content || '[image or attachment]') + '\n')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([md2], { type: 'text/markdown' }));
  a.download = (c.title || 'olmavax-chat').replace(/[^\p{L}\p{M}\p{N}\s'’-]/gu, '_').slice(0, 60) + '.md';
  a.click(); URL.revokeObjectURL(a.href);
  toast(T('chatExported'), 'ok');
}
async function exportPDF(id) {
  const c = S.chats.find(x => x.id === (id || S.cur));
  if (!c || !c.msgs.length) return toast(T('noSuggestions'), 'err');
  try {
    const r = await fetch('/api/export/pdf', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title: c.title, messages: c.msgs.map(m => ({ role: m.role, content: m.content || '' })) }) });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (c.title || 'olmavax-chat').replace(/[^\p{L}\p{M}\p{N}\s'’-]/gu, '_').slice(0, 60) + '.pdf';
    a.click(); URL.revokeObjectURL(a.href);
    toast(T('pdfExported'), 'ok');
  } catch (e) { toast(T('runFailed') + ': ' + e.message, 'err', 4000); }
}

/* ═════════════════ LAYOUT / RENDER ═════════════════ */
function layout() {
  const c = chat();
  const empty = !c || !c.msgs.length;
  $('#home').hidden = !empty; $('#msgs').hidden = empty;
  (empty ? $('#homeComposer') : $('#dock')).appendChild($('#comp'));
}
function newChat() {
  if (chat() && !chat().msgs.length) { layout(); $('#input').focus(); return; }
  const c = { id: uid(), title: T('newChat'), msgs: [], at: Date.now() };
  S.chats.unshift(c); S.cur = c.id; greetPick = Math.random(); save(); render(); $('#input').focus(); closeSide();
}

/* Wipe the chat history. Confirm first, and never leave the app with no chat. */
function clearChats() {
  if (!S.chats.length) { toast(T('noChats'), 'info', 2000); return; }
  if (!confirm(T('confirmClearAll'))) return;
  const n = S.chats.length;
  S.chats = []; save(); newChat(); render();
  toast(n + ' ' + T('chatsCleared'), 'ok', 2600);
}
function bubble(m) {
  const d = document.createElement('div');
  d.className = 'm ' + m.role;
  fill(d, m);
  d.querySelectorAll('[data-a]').forEach(b => b.onclick = () => {
    const k = b.dataset.a;
    if (k === 'copy') {
      navigator.clipboard?.writeText(m.content || '').then(() => {
        b.innerHTML = IC.check; b.classList.add('done');
        setTimeout(() => { b.innerHTML = IC.copy; b.classList.remove('done'); }, 1400);
      }).catch(() => toast(T('copy'), 'err'));
    }
    else if (k === 'speak') speak(m.content || '');
    else if (k === 'redo') redo();
    else if (k === 'save') saveToLibrary(m);
  });
  return d;
}
function fill(d, m) {
  const raw = m.content || '';
  let h = '';
  if (m.role === 'assistant') {
    h += '<div class="av"><img src="logo-mark.svg" alt="">' +
         '<span>' + esc(m.agentName || 'Olmavax') + '</span>' +
         (m.streaming ? '<span class="spin"></span>' : '') +
         (m.tag && !m.streaming ? '<small>' + esc(m.tag) + '</small>' : '') + '</div>';
    h += '<div class="body">' + (md(raw) || '<span class="thinking-dots"><i></i><i></i><i></i></span>') + '</div>';
  } else {
    h += '<div class="bub">' + esc(raw) + '</div>';
  }
  if (m.image) {
    const u = 'data:' + m.image.mime + ';base64,' + m.image.data;
    const ext = m.image.mime.includes('svg') ? 'svg' : 'png';
    h += '<img class="gen" src="' + u + '" alt="">' +
         '<a class="dl" download="olmavax-image.' + ext + '" href="' + u + '">' + IC.dl + ' Download</a>';
  }
  if (m.sources && m.sources.length) {
    h += '<div class="src">' + m.sources.map((s, i) =>
      '<a target="_blank" rel="noopener" href="' + esc(safeUrl(s.url)) + '">[' + (i + 1) + '] ' + esc(s.title) + '</a>').join('') + '</div>';
  }
  if (m.audio) h += '<div><audio controls src="' + m.audio + '"></audio> <a class="dl" href="' + m.audio + '" download="recording.webm">' + IC.dl + ' Download</a></div>';
  if (m.role === 'assistant' && raw && !m.streaming) {
    h += '<div class="acts"><button data-a="copy" title="' + esc(T('copy')) + '">' + IC.copy + '</button>' +
         '<button data-a="speak" title="Speak">' + IC.speak + '</button>' +
         '<button data-a="save" title="' + esc(T('saveToLibrary')) + '">' + IC.save + '</button>' +
         '<button data-a="redo" title="' + esc(T('rebuild')) + '">' + IC.redo + '</button></div>';
  }
  d.innerHTML = h;
  d.querySelectorAll('.code [data-cp]').forEach(b => b.onclick = () => {
    const code = b.closest('.code').querySelector('pre').textContent;
    navigator.clipboard?.writeText(code).then(() => { b.innerHTML = IC.check; setTimeout(() => b.innerHTML = IC.copy, 1300); });
  });
  d.querySelectorAll('.code [data-dl]').forEach(b => b.onclick = () => {
    const el = b.closest('.code');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([el.querySelector('pre').textContent], { type: 'text/plain' }));
    a.download = 'snippet-' + (el.dataset.lang || 'txt') + '.txt';
    a.click(); URL.revokeObjectURL(a.href);
  });
}
function render() {
  if (!chat()) {
    if (!S.chats.length) { S.cur = null; newChat(); return; }
    S.cur = S.chats[0].id;
  }
  renderChats(); layout(); renderTitle();
  const box = $('#msgs'); box.innerHTML = '';
  chat().msgs.forEach(m => box.appendChild(bubble(m)));
  scrollEnd(true);
}
function scrollEnd(force) { const st = $('#stage'); if (force || stickBottom) st.scrollTop = st.scrollHeight; }

async function saveToLibrary(m) {
  try {
    await api('/api/library', { method: 'POST', body: JSON.stringify({
      kind: 'reply', title: (m.content || '').slice(0, 70) || 'Saved reply',
      body: m.content || '', chatId: S.cur,
    }) });
    toast(T('savedToLibrary'), 'ok');
    refreshCounts();
  } catch (e) { toast(T('runFailed') + ': ' + e.message, 'err'); }
}

/* ══════ SEND ══════ */
async function send(text, opt = {}) {
  text = (text || '').trim();
  if (!text || busy) return;
  if (!chat()) newChat();
  const c = chat();
  if (!c.msgs.length) c.title = text.slice(0, 42);

  const files = atts.filter(a => !a.image);
  const images = atts.filter(a => a.image);
  const full = text + files.map(f => '\n\n[File: ' + f.name + ']\n' + f.text).join('');
  const shown = text + atts.map(a => '\n📎 ' + a.name).join('');

  c.msgs.push({ role: 'user', content: shown, raw: text, at: Date.now() });
  const am = { role: 'assistant', content: '', tag: T('thinking'), streaming: true, at: Date.now() };
  c.msgs.push(am); c.at = Date.now();

  const sendMode = mode, sendThink = think;
  const imgs = images.map(a => ({ mime: a.mime, data: a.image }));
  const model = S.model, provider = S.provider, agent = S.agent;

  $('#input').value = ''; autosize();
  atts = []; renderAtts();
  if (mode !== 'write') setMode(null);
  busy = true; updateGo(); render();

  const el = $('#msgs').lastChild;
  ctrl = new AbortController();
  const proj = S.projects.find(p => p.id === S.project);
  try {
    const hist = c.msgs.slice(0, -1).filter(m => m.content).map((m, i, a) => ({
      role: m.role, content: i === a.length - 1 ? full : (m.raw || m.content),
    }));
    if (imgs.length && hist.length) hist[hist.length - 1].images = imgs;

    const r = await fetch('/api/chat', {
      method: 'POST', headers: { 'content-type': 'application/json' }, signal: ctrl.signal,
      body: JSON.stringify({
        messages: hist, agent: sendMode === 'write' ? 'writer' : agent,
        provider, model, keys: S.keys, lang: S.lang,
        mode: sendMode, think: sendThink, voice: !!opt.voice,
        instructions: proj ? proj.instr : '',
      }),
    });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).error) || ('HTTP ' + r.status));

    const rd = r.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 2);
        if (!line.startsWith('data:')) continue;
        let j; try { j = JSON.parse(line.slice(5)); } catch { continue; }
        if (j.agent) { const a = agents.find(x => x.id === j.agent); am.agentName = a ? a.name : 'Olmavax'; }
        if (j.provider) am.tag = j.provider;
        if (j.delta) am.content += j.delta;
        if (j.error) am.content += '\n\n⚠️ **' + esc(j.error) + '**';
        if (j.image) { am.image = j.image; refreshCounts(); }
        if (j.sources) am.sources = j.sources;
        fill(el, am);
        if (stickBottom) $('#stage').scrollTop = $('#stage').scrollHeight;
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') am.content += '\n\n⚠️ ' + esc(e.message) + ' — ' + T('offlineNote');
  }
  busy = false; ctrl = null; am.streaming = false;
  if (!am.agentName) am.agentName = 'Olmavax';
  fill(el, am); updateGo(); renderChats(); renderTitle(); save();

  if (opt.speak) {
    if (live.on) { vstate('speaking', T('speaking')); await speak(am.content); if (live.on) vstate('listening', T('listening')); }
    else await speak(am.content);
  }
  return am.content;
}
function redo() {
  const c = chat(); if (busy || !c) return;
  const i = c.msgs.map(m => m.role).lastIndexOf('user'); if (i < 0) return;
  const t = c.msgs[i].raw || c.msgs[i].content;
  c.msgs.splice(i); save(); render(); send(t);
}

/* ════════ SPEECH ════════ */
const plain = t => String(t).replace(/```[\s\S]*?```/g, ' ').replace(/[*`#_>|-]/g, '').replace(/\s+/g, ' ').trim();
function speak(text) {
  return new Promise(ok => {
    if (!('speechSynthesis' in window) || !text) return ok();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(plain(text).slice(0, 900));
    u.lang = T('lang'); u.rate = S.talkRate || 1;
    u.onend = u.onerror = ok;
    try { speechSynthesis.speak(u); } catch { ok(); }
  });
}
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const live = { on: false, rec: null };
function listen(fillBox) {
  return new Promise(ok => {
    if (!SR) { toast('Speech recognition needs Chrome, Edge or Safari', 'err', 4000); return ok({ text: '', fatal: true }); }
    let r; try { r = new SR(); } catch { return ok({ text: '', fatal: true }); }
    r.lang = T('lang'); r.interimResults = true; r.continuous = false;
    let final = '', fatal = false;
    live.rec = r;
    r.onresult = e => {
      let t = ''; for (const x of e.results) t += x[0].transcript;
      if (fillBox) { $('#input').value = t; updateGo(); autosize(); }
      if (e.results[e.results.length - 1].isFinal) final = t;
    };
    r.onerror = e => { if (['not-allowed', 'service-not-allowed', 'audio-capture'].includes(e.error)) fatal = true; };
    r.onend = () => ok({ text: final, fatal });
    try { r.start(); } catch { ok({ text: final, fatal: true }); }
  });
}
function vstate(s, txt) {
  const v = $('#voiceDock'); if (!v) return;
  v.className = s || ''; v.classList.add('show'); v.hidden = false;
  document.body.classList.add('voicing');
  $('#vstat').textContent = txt || '';
  drawWave(s);
  const talking = s === 'speaking' || s === 'thinking';
  const vb = $('#vstop'); if (vb) vb.hidden = !talking;
  if (live.on) drawWave(s);
}

function drawWave(state) {
  const cv = $('#orbWave'); if (!cv) return;
  const x = cv.getContext('2d'), w = cv.width, h = cv.height;
  x.clearRect(0, 0, w, h);
  const n = 30, gap = w / n;
  const amp = state === 'speaking' ? h * .42 : state === 'thinking' ? h * .28 : h * .2;
  for (let i = 0; i < n; i++) {
    const t = i / n, env = Math.sin(t * Math.PI);
    const wob = state === 'listening' ? Math.sin(t * 14 + performance.now() / 260) : Math.sin(t * 9 + performance.now() / 200);
    const bh = Math.max(3, Math.abs(wob) * amp * env);
    x.fillStyle = state === 'speaking' ? '#8fb4ff' : state === 'thinking' ? '#b490ff' : '#4f8cff';
    x.globalAlpha = .35 + env * .55;
    const px = i * gap + gap / 2;
    x.beginPath();
    if (x.roundRect) { x.roundRect(px - 2.5, h / 2 - bh / 2, 5, bh, 3); x.fill(); }
    else x.fillRect(px - 2.5, h / 2 - bh / 2, 5, bh);
  }
  x.globalAlpha = 1;
}

let waveTimer = null;
async function voiceLoop() {
  while (live.on) {
    vstate('listening', T('listening'));
    const { text, fatal } = await listen(false);
    if (fatal) { closeVoice(); return; }
    if (!live.on) return;
    if (!text) { $('#vtext').textContent = ''; continue; }
    // what was spoken is written out automatically and kept in the voice log
    $('#vtext').textContent = text;
    logVoice('you', text);
    vstate('thinking', T('thinking'));
    const answer = await send(text, { speak: true, voice: true });
    if (answer) logVoice('ai', answer);
  }
}

/* ---- voice log: spoken turns kept separate from typed chat ---- */
const voiceLog = [];
function logVoice(who, text) {
  const t = String(text || '').trim();
  if (!t) return;
  voiceLog.push({ who, text: t, at: Date.now() });
  if (voiceLog.length > 200) voiceLog.shift();
  paintVoiceLog();
}
function paintVoiceLog() {
  const box = $('#vlBody'); if (!box) return;
  box.innerHTML = voiceLog.length
    ? voiceLog.map(r => '<div class="vl-row ' + r.who + '"><span class="who">' +
        (r.who === 'you' ? T('you') : T('olmavax')) + '</span><span class="txt">' + esc(r.text) + '</span></div>').join('')
    : '<div class="vl-empty">' + esc(T('voiceLogEmpty')) + '</div>';
  box.scrollTop = box.scrollHeight;
}
function showVoiceLog(on) {
  const el = $('#voiceLog'); if (!el) return;
  if (!on) { el.classList.remove('show'); setTimeout(() => { el.hidden = true; }, 260); return; }
  el.hidden = false; requestAnimationFrame(() => el.classList.add('show'));
  paintVoiceLog();
}
function openVoice() {
  if (live.on) return;
  // no speech engine: say so instead of flashing the dock open and shut
  if (!SR && !('speechSynthesis' in window)) {
    toast(T('noVoiceSupport'), 'err', 4200); return;
  }
  if (!SR) { toast(T('voiceTypingOnly'), 'info', 4200); }
  live.on = true;
  const v = $('#voiceDock'); v.hidden = false;
  requestAnimationFrame(() => v.classList.add('show'));
  vstate('listening', T('listening'));
  waveTimer = setInterval(() => drawWave($('#voiceDock').classList), 90);
  paintMode();
  showVoiceLog(true);
  logVoice('ai', T('voiceReady'));
  toast(T('voiceHint'), 'info', 3400);
  voiceLoop();
}
function closeVoice() {
  live.on = false; clearInterval(waveTimer);
  document.body.classList.remove('voicing');
  showVoiceLog(false);
  paintMode();
  try { live.rec && live.rec.stop(); } catch {}
  speechSynthesis.cancel();
  const v = $('#voiceDock');
  v.classList.remove('show');
  setTimeout(() => { v.hidden = true; v.className = ''; $('#vtext').textContent = ''; }, 360);
}

/* ═════════════════════════ RECORDING / ATTACHMENTS ═════════════════════════ */
let mr = null, chunks = [];
async function toggleRec() {
  if (mr && mr.state === 'recording') { mr.stop(); return; }
  try {
    const st = await navigator.mediaDevices.getUserMedia({ audio: true });
    mr = new MediaRecorder(st); chunks = [];
    mr.ondataavailable = e => chunks.push(e.data);
    mr.onstop = () => {
      st.getTracks().forEach(t => t.stop());
      $('#mic').classList.remove('rec');
      if (!chunks.length) return;
      const url = URL.createObjectURL(new Blob(chunks, { type: mr.mimeType || 'audio/webm' }));
      if (!chat()) newChat();
      chat().msgs.push({ role: 'assistant', content: '🔊', audio: url, at: Date.now() });
      render();
    };
    mr.start(); $('#mic').classList.add('rec');
  } catch (e) { toast('Microphone unavailable: ' + e.message, 'err', 4000); }
}
const addAtt = a => { atts.push(a); renderAtts(); };
function renderAtts() {
  const box = $('#atts'); box.innerHTML = '';
  atts.forEach((a, i) => {
    const d = document.createElement('div'); d.className = 'att';
    d.innerHTML = (a.image ? '<img src="data:' + a.mime + ';base64,' + a.image + '" alt="">' : '🖼️') +
      '<span>' + esc(a.name) + '</span><button aria-label="Remove">' + IC.x + '</button>';
    d.querySelector('button').onclick = () => { atts.splice(i, 1); renderAtts(); };
    box.appendChild(d);
  });
  updateGo();
}
function shrink(dataUrl, max = 1600) {
  return new Promise(ok => {
    const im = new Image();
    im.onload = () => {
      const k = Math.min(1, max / Math.max(im.width, im.height));
      const c = document.createElement('canvas');
      c.width = Math.round(im.width * k); c.height = Math.round(im.height * k);
      c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
      try { ok(c.toDataURL('image/jpeg', .85)); } catch { ok(dataUrl); }
    };
    im.onerror = () => ok(dataUrl); im.src = dataUrl;
  });
}
async function onFiles(files) {
  for (const f of files) {
    if (f.type.startsWith('image/')) {
      const url = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(f); });
      const sm = f.type === 'image/gif' ? url : await shrink(url);
      addAtt({ name: f.name, mime: sm.slice(5, sm.indexOf(';')), image: sm.split(',')[1] });
    } else if (f.size < 400000) {
      try { addAtt({ name: f.name, text: (await f.text()).slice(0, 60000) }); }
      catch { toast('Could not read ' + f.name, 'err'); }
    } else toast(f.name + ' — too large (max 400 KB for text files)', 'err', 4000);
  }
}
const autosize = () => {
  const el = $('#input'); el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 220) + 'px';
};

/* ════════ MODALS ════════ */
const modal = (html, after) => { $('#mbody').innerHTML = html; $('#modal').hidden = false; after && after(); };
const closeModal = () => { $('#modal').hidden = true; $('#mbody').innerHTML = ''; };

/* ════════ PANELS ════════ */
const openPanel = k => {
  ({ images: imagesPanel, scheduled: scheduledPanel, library: libraryPanel,
     plugins: pluginsPanel, codex: codexPanel, explore: explorePanel,
     projects: projectPanel, memory: memPanel, build: buildPanel, agents: agentPanel,
     talk: () => { if (live.on) closeVoice(); else openVoice(); } }[k] || (() => {}))();
  closeSide();
};

/* ---------- IMAGES ---------- */
function imagesPanel() {
  const all = [];
  for (const c of S.chats) for (const m of c.msgs) {
    if (m.image) all.push({ img: m.image, chat: c.id, title: c.title, at: m.at || c.at || 0 });
    for (const a of (m.attachments || [])) if (a.image) all.push({ img: { mime: a.mime, data: a.image }, chat: c.id, title: c.title, at: m.at || 0 });
  }
  all.sort((a, b) => b.at - a.at);
  modal('<h3>' + IC.img + ' ' + esc(T('images')) + '</h3>' +
    '<p class="muted">' + esc(T('imagesHint')) + '</p>' +
    (all.length ? '<div class="gallery">' + all.map((it, i) =>
        '<button class="g-item" data-i="' + i + '" title="' + esc(it.title || '') + '">' +
        '<img src="data:' + it.img.mime + ';base64,' + it.img.data + '" alt=""></button>').join('') + '</div>'
      : '<p class="muted">' + esc(T('noImages')) + '</p>'), () => {
    $('#mbody').querySelectorAll('.g-item').forEach(b => b.onclick = () => {
      const it = all[+b.dataset.i];
      const a = document.createElement('a');
      a.href = 'data:' + it.img.mime + ';base64,' + it.img.data;
      a.download = 'olmavax-image.' + (it.img.mime.includes('svg') ? 'svg' : 'png');
      a.click();
    });
  });
}

/* ---------- SCHEDULED ---------- */
const WHEN = [
  ['inMinutes', 10, '10m'], ['inMinutes', 60, '1h'], ['nextHour', 0, '1h2'],
  ['tomorrow', 0, 'tomorrow'],
];
async function scheduledPanel() {
  let items = [];
  try { items = (await api('/api/schedule')).items; } catch {}
  const draw = () => {
    $('#mbody').innerHTML =
      '<h3>' + IC.clock + ' ' + esc(T('scheduled')) + '</h3>' +
      '<p class="muted">' + esc(T('scheduleHint')) + '</p>' +
      (items.length ? '<div class="flist">' + items.map(s => {
        const due = s.at || 0;
        const past = due < Date.now();
        return '<div class="fitem"><span>' + (s.enabled === false ? '⏸ ' : '') +
          esc(String(s.prompt || '').slice(0, 70)) + '<small class="muted"> · ' +
          (past ? T('scheduledNow') : new Date(due).toLocaleString()) +
          (s.runs ? ' · ' + s.runs + '×' : '') + '</small></span>' +
          '<button data-run="' + esc(s.id) + '" title="' + esc(T('runNow')) + '">' + IC.play + '</button>' +
          '<button data-del="' + esc(s.id) + '" title="' + esc(T('delete')) + '">' + IC.trash + '</button></div>';
      }).join('') + '</div>' : '<p class="muted">' + esc(T('noScheduled')) + '</p>') +
      '<label>' + esc(T('schedulePrompt')) + '<textarea id="sp" rows="2" placeholder="' + esc(T('schedulePrompt')) + '"></textarea></label>' +
      '<label>' + esc(T('scheduleWhen')) + '<select id="sw">' +
        '<option value="10">' + esc(T('inMinutes', { name: 10 })) + '</option>' +
        '<option value="60">' + esc(T('inMinutes', { name: 60 })) + '</option>' +
        '<option value="3600">' + esc(T('nextHour')) + '</option>' +
        '<option value="86400">' + esc(T('tomorrow')) + '</option>' +
      '</select></label>' +
      '<button class="b primary" id="sadd">' + esc(T('newTask')) + '</button>';
    $('#mbody').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      await api('/api/schedule?id=' + encodeURIComponent(b.dataset.del), { method: 'DELETE' });
      items = items.filter(x => x.id !== b.dataset.del); draw(); refreshCounts();
    });
    $('#mbody').querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
      const s = items.find(x => x.id === b.dataset.run); if (!s) return;
      toast(T('scheduledNow'), 'info');
      $('#input').value = s.prompt; closeModal(); send(s.prompt);
    });
    $('#sadd').onclick = async () => {
      const prompt = $('#sp').value.trim(); if (!prompt) return;
      try {
        items.unshift(await api('/api/schedule', { method: 'POST',
          body: JSON.stringify({ prompt, at: Date.now() + (+$('#sw').value) * 1000, agent: S.agent, provider: S.provider, model: S.model }) }));
        $('#sp').value = ''; draw(); refreshCounts(); toast(T('scheduledOk'), 'ok');
      } catch (e) { toast(e.message, 'err'); }
    };
  };
  $('#modal').hidden = false; draw();
}

/* ---------- LIBRARY ---------- */
async function libraryPanel() {
  let items = [];
  try { items = (await api('/api/library')).items; } catch {}
  const draw = () => {
    $('#mbody').innerHTML =
      '<h3>' + IC.book + ' ' + esc(T('library')) + '</h3>' +
      '<p class="muted">' + esc(T('libraryHint')) + '</p>' +
      (items.length ? '<div class="flist">' + items.map(it =>
          '<div class="fitem"><span>' + esc(String(it.title || 'Untitled').slice(0, 60)) +
          '<small class="muted"> · ' + esc(it.kind || 'note') + ' · ' + new Date(it.at || Date.now()).toLocaleDateString() + '</small></span>' +
          '<button data-open="' + esc(it.id) + '" title="' + esc(T('copy')) + '">' + IC.copy + '</button>' +
          '<button data-del="' + esc(it.id) + '" title="' + esc(T('delete')) + '">' + IC.trash + '</button></div>').join('') + '</div>'
        : '<p class="muted">' + esc(T('noLibrary')) + '</p>');
    $('#mbody').querySelectorAll('[data-open]').forEach(b => b.onclick = async () => {
      const it = items.find(x => x.id === b.dataset.open);
      if (!it) return;
      if (it.body) await navigator.clipboard?.writeText(it.body).catch(() => {});
      toast(T('codeCopied'), 'ok');
    });
    $('#mbody').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      await api('/api/library?id=' + encodeURIComponent(b.dataset.del), { method: 'DELETE' });
      items = items.filter(x => x.id !== b.dataset.del); draw(); refreshCounts();
    });
  };
  $('#modal').hidden = false; draw();
}

/* ---------- PLUGINS ---------- */
let PLUGINS = [];
async function updatePlugins() {
  try {
    PLUGINS = (await api('/api/plugins')).plugins;
    $('#plugPill').textContent = PLUGINS.filter(p => p.enabled).length + '/' + PLUGINS.length;
  } catch {}
}
async function pluginsPanel() {
  if (!PLUGINS.length) await updatePlugins();   // may be opened before boot finishes
  const draw = (filter = '') => {
    const list = PLUGINS.filter(p => !filter || (p.name + p.desc + p.cat).toLowerCase().includes(filter.toLowerCase()));
    $('#mbody').innerHTML =
      '<h3>' + IC.plug + ' ' + esc(T('plugins')) + '</h3>' +
      '<input id="psearch" placeholder="' + esc(T('searchChats')) + '" value="' + esc(filter) + '">' +
      (list.length ? '<div class="plist">' + list.map(p =>
        '<div class="pcard' + (p.enabled ? ' on' : '') + '">' +
          '<button class="pswitch" data-tog="' + p.id + '" role="switch" aria-checked="' + p.enabled + '"><span></span></button>' +
          '<div class="pbody"><b>' + p.icon + ' ' + esc(p.name) + '</b>' +
          '<small>' + esc(p.desc) + '</small>' +
          '<code>/' + esc(p.id) + ' ' + esc(p.args) + '</code></div>' +
          '<button class="b primary small" data-run="' + p.id + '"' + (p.enabled ? '' : ' disabled') + '>' + esc(T('run')) + '</button>' +
        '</div>').join('') + '</div>'
        : '<p class="muted">' + esc(T('nothingFound')) + '</p>');
    const q = $('#psearch');
    q.oninput = e => draw(e.target.value);
    q.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); openPluginRun(list.find(p => p.id === q.dataset.id)); } };
    $('#mbody').querySelectorAll('[data-tog]').forEach(b => b.onclick = async () => {
      const p = PLUGINS.find(x => x.id === b.dataset.tog);
      const next = !p.enabled;
      try {
        await api('/api/plugins', { method: 'POST', body: JSON.stringify({ id: p.id, enabled: next }) });
        p.enabled = next; draw(q.value); updatePlugins();
        toast(p.name + ' · ' + (next ? T('enabled') : T('disabled')), 'ok');
      } catch (e) { toast(e.message, 'err'); }
    });
    $('#mbody').querySelectorAll('[data-run]').forEach(b => b.onclick = () => openPluginRun(PLUGINS.find(p => p.id === b.dataset.run)));
  };
  $('#modal').hidden = false; draw();
}
function openPluginRun(p) {
  if (!p) return;
  if (!p.enabled) return toast(T('enableFirst'), 'err');
  modal('<h3>' + p.icon + ' ' + esc(p.name) + '</h3>' +
    '<p class="muted">' + esc(p.desc) + '</p>' +
    '<label>' + esc(T('pluginInput')) + '<textarea id="pinput" rows="3" placeholder="' + esc(p.args) + '"></textarea></label>' +
    '<button class="b primary" id="prun">' + esc(T('run')) + '</button>' +
    '<div id="pout" class="pout"></div>', () => {
    $('#prun').onclick = async () => {
      const input = $('#pinput').value;
      $('#pout').textContent = T('thinking') + '…';
      try {
        const r = await api('/api/plugins/' + p.id + '/run', { method: 'POST', body: JSON.stringify({ input }) });
        $('#pout').innerHTML = md(r.result);
      } catch (e) { $('#pout').innerHTML = '<p class="err">' + esc(T('runFailed')) + ': ' + esc(e.message) + '</p>'; }
    };
    $('#pinput').focus();
  });
}

/* ---------- CODEX ---------- */
async function codexPanel() {
  let items = [];
  try { items = (await api('/api/workspace')).items; } catch {}
  const LANGUAGES = HL.languages;
  const draw = () => {
    $('#mbody').innerHTML =
      '<h3>' + IC.code + ' ' + esc(T('codex')) + '</h3>' +
      '<p class="muted">' + esc(T('codeHint')) + '</p>' +
      (items.length ? '<div class="flist">' + items.map(f =>
          '<div class="fitem"><span>' + IC.code + ' ' + esc(f.name || 'untitled') +
          '<small class="muted"> · ' + esc(f.lang || 'text') + '</small></span>' +
          '<button data-open="' + esc(f.id) + '" title="' + esc(T('edit')) + '">' + IC.edit + '</button>' +
          '<button data-run="' + esc(f.id) + '" title="' + esc(T('runSnippet')) + '">' + IC.play + '</button>' +
          '<button data-del="' + esc(f.id) + '" title="' + esc(T('delete')) + '">' + IC.trash + '</button></div>').join('') + '</div>'
        : '<p class="muted">' + esc(T('noCode')) + '</p>') +
      '<label>' + esc(T('snippetName')) + '<input id="cxName" placeholder="hello.py"></label>' +
      '<label>' + esc(T('snippetLang')) + '<select id="cxLang">' +
        '<option value="">' + esc(T('detectedLang')) + '</option>' +
        LANGUAGES.map(l => '<option value="' + l + '">' + l + '</option>').join('') + '</select></label>' +
      '<label>' + esc(T('snippetCode')) + '<textarea id="cxCode" rows="8" class="mono" spellcheck="false" placeholder="print(\'hello\')"></textarea></label>' +
      '<div class="row2"><button class="b" id="cxDet">' + esc(T('detectedLang')) + '</button>' +
      '<button class="b primary" id="cxSave">' + esc(T('saveSnippet')) + '</button></div>' +
      '<div id="cxPrev" class="pout"></div>';

    $('#cxDet').onclick = () => {
      const guess = HL.detect($('#cxCode').value);
      $('#cxLang').value = LANGUAGES.includes(guess) ? guess : '';
      toast(T('detectedLang') + ': ' + guess, 'info');
    };
    $('#cxSave').onclick = async () => {
      const content = $('#cxCode').value;
      if (!content.trim()) return toast(T('noCode'), 'err');
      const lang = $('#cxLang').value || HL.detect(content);
      try {
        items.unshift(await api('/api/workspace', { method: 'POST',
          body: JSON.stringify({ name: $('#cxName').value.trim() || 'snippet.' + (lang === 'text' ? 'txt' : lang), lang, content }) }));
        $('#cxCode').value = ''; $('#cxName').value = ''; draw(); toast(T('savedSnip'), 'ok');
      } catch (e) { toast(e.message, 'err'); }
    };
    $('#mbody').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      await api('/api/workspace?id=' + encodeURIComponent(b.dataset.del), { method: 'DELETE' });
      items = items.filter(x => x.id !== b.dataset.del); draw();
    });
    $('#mbody').querySelectorAll('[data-open]').forEach(b => b.onclick = () => {
      const f = items.find(x => x.id === b.dataset.open); if (!f) return;
      $('#cxName').value = f.name || ''; $('#cxLang').value = f.lang || ''; $('#cxCode').value = f.content || '';
      $('#cxCode').focus();
    });
    $('#mbody').querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
      const f = items.find(x => x.id === b.dataset.run); if (!f) return;
      $('#cxPrev').innerHTML = '<h4>' + esc(f.name) + '</h4><div class="code" data-lang="' + esc(f.lang) + '">' +
        '<pre><code>' + HL.highlight(f.content, f.lang) + '</code></pre></div>';
    });
  };
  $('#modal').hidden = false; draw();
}

/* ---------- EXPLORE ---------- */
async function explorePanel() {
  let data = { prompts: [], categories: [], agents: [] };
  try { data = await api('/api/explore'); } catch {}
  const draw = (cat = 'all') => {
    const list = cat === 'all' ? data.prompts : data.prompts.filter(p => p.cat === cat);
    $('#mbody').innerHTML =
      '<h3>🧭 ' + esc(T('explore')) + '</h3>' +
      '<p class="muted">' + esc(T('exploreHint')) + '</p>' +
      '<div class="chips">' +
        ['all'].concat(data.categories).map(c =>
          '<button class="chip' + (c === cat ? ' on' : '') + '" data-cat="' + esc(c) + '">' +
          esc(c === 'all' ? T('allCats') : c) + '</button>').join('') + '</div>' +
      '<div class="exgrid">' + list.map(p =>
        '<button class="excard" data-id="' + p.id + '">' +
          '<span class="ae">' + p.icon + '</span>' +
          '<b>' + esc(p.title) + '</b>' +
          '<small>' + esc(p.cat) + '</small></button>').join('') + '</div>';
    $('#mbody').querySelectorAll('[data-cat]').forEach(b => b.onclick = () => draw(b.dataset.cat));
    $('#mbody').querySelectorAll('[data-id]').forEach(b => b.onclick = () => {
      const p = data.prompts.find(x => x.id === b.dataset.id); if (!p) return;
      const a = agents.find(x => x.id === p.agent);
      if (p.agent && p.agent !== 'auto') { S.agent = p.agent; save(); applyI18n(); }
      if (p.mode) setMode(p.mode);
      closeModal();
      $('#input').value = p.body; autosize(); updateGo(); $('#input').focus();
      toast((a ? a.icon + ' ' + a.name : '') + ' · ' + p.title, 'info');
    });
  };
  $('#modal').hidden = false; draw();
}

/* ═══════════════════ SETTINGS / MODELS ═══════════════════ */
function settingsPanel() {
  const langOpts = ['en', 'hi', 'es', 'fr', 'ar']
    .map(l => '<option value="' + l + '"' + (S.lang === l ? ' selected' : '') + '>' +
      ({ en: 'English', hi: 'हिन्दी', es: 'Español', fr: 'Français', ar: 'العربية' })[l] + '</option>').join('');
  const readyCount = ['anthropic', 'openai', 'ollama', 'sidecar'].filter(p => providers[p]).length;

  modal(
    '<h3>' + IC.gear + ' ' + esc(T('settings')) + '</h3>' +
    '<h4>' + esc(T('personalization')) + '</h4>' +
    '<label>' + esc(T('yourName')) + '<input id="k0" value="' + esc(S.name || '') + '" placeholder="' + esc(T('yourName')) + '"></label>' +
    '<h4>' + esc(T('engine')) + '</h4>' +
    '<label>' + esc(T('agent')) + '<select id="kAgent"><option value="auto"' + (S.agent === 'auto' ? ' selected' : '') + '>🤖 ' + esc(T('auto')) + '</option>' +
      agents.map(a => '<option value="' + a.id + '"' + (S.agent === a.id ? ' selected' : '') + '>' + a.icon + ' ' + esc(a.name) + '</option>').join('') + '</select></label>' +
    '<button class="b" id="kModel">' + esc(T('chooseModel')) + ' ✎</button>' +
    '<p class="muted">' + readyCount + ' ' + esc(T('enginesReady')) + '</p>' +
    '<h4>' + esc(T('keys')) + '</h4>' +
    '<label>Anthropic API key<input id="k1" type="password" placeholder="sk-ant-…" value="' + esc(S.keys.anthropic || '') + '"></label>' +
    '<div class="grid2"><label>OpenAI / compatible<input id="k2" type="password" placeholder="sk-…" value="' + esc(S.keys.openai || '') + '"></label>' +
      '<label>Base URL (optional)<input id="k3" placeholder="https://api.groq.com/openai/v1" value="' + esc(S.keys.openaiBase || '') + '"></label></div>' +
    '<label>Ollama URL<input id="k4" placeholder="http://localhost:11434" value="' + esc(S.keys.ollama || '') + '"></label>' +
    '<h4>' + esc(T('appearance')) + '</h4>' +
    '<div class="sizepick"><span class="szlabel">' + esc(T('sidebarSize')) + '</span>' +
      SIDE_SIZES.map(s =>
        '<button class="szopt' + ((S.rail ? 'rail' : S.sideSize) === s.id ? ' on' : '') +
        '" data-sz="' + s.id + '" role="radio" aria-checked="' + ((S.rail ? 'rail' : S.sideSize) === s.id) +
        '" title="' + esc(T('size_' + s.id)) + '">' +
        '<span class="szbar' + (s.rail ? ' r' : '') + '" style="--w:' + (s.px / 344 * 100).toFixed(0) + '%"></span>' +
        '<b>' + esc(T('size_' + s.id)) + '</b></button>').join('') +
    '</div>' +
    '<label>' + esc(T('theme')) + '<select id="kTheme"><option value="dark"' + (S.theme === 'dark' ? ' selected' : '') + '>🌙 Dark</option>' +
      '<option value="light"' + (S.theme === 'light' ? ' selected' : '') + '>☀️ Light</option></select></label>' +
    '<label>' + esc(T('language')) + '<select id="kLang">' + langOpts + '</select></label>' +
    '<label>' + esc(T('fontSize')) + '<input id="kFs" type="range" min="0.85" max="1.25" step="0.05" value="' + (S.fontScale || 1) + '"></label>' +
    '<label>' + esc(T('talkSpeed')) + '<input id="kRate" type="range" min="0.5" max="2" step="0.1" value="' + (S.talkRate || 1) + '"></label>' +
    '<div class="frow"><span>' + esc(T('sendOnEnter')) + '</span><button class="b" id="kEnter" role="switch" aria-checked="' + (S.enterToSend !== false) + '">' + (S.enterToSend !== false ? 'On' : 'Off') + '</button></div>' +
    '<h4>' + esc(T('advanced')) + ' — Olmavax Agent</h4>' +
    '<p class="muted">' + esc(T('sidecarHint')) + '</p>' +
    '<code class="codeblock">python advanced/olmavax-agent/olmavax_agent.py ui</code>' +
    '<p class="muted">' + (sidecar.available ? '✅ ' + esc(T('enginesReady')) : '⚠️ ' + esc(T('sidecarOff'))) + '</p>' +
    '<h4>' + esc(T('dataControls')) + '</h4><p class="muted">' + esc(T('dataNote')) + '</p>' +
    '<div class="grid2"><button class="b" id="kExport">' + esc(T('exportData')) + '</button>' +
    '<button class="b" id="kImport">' + esc(T('importData')) + '</button></div>' +
    '<button class="b danger" id="kClear">' + esc(T('clearAll')) + '</button>' +
    '<h4>' + esc(T('about')) + '</h4><p class="muted">Olmavax A.I · v<span id="ver">3.0.0</span> · local-first</p>' +
    '<a class="b web-link" id="kSite" href="https://abhijeet-kumar-prajapati.github.io/olmavax-A.I/docs/" target="_blank" rel="noopener">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 2.5 15 0 18M12 3c-2.5 2.7-2.5 15 0 18"/></svg>' +
      esc(T('visitWebsite')) + '</a>' +
    '<button class="b primary" id="kSave">' + esc(T('save')) + '</button>', () => {
    $('#kSave').onclick = async () => {
      S.name = $('#k0').value.trim(); S.agent = $('#kAgent').value;
      S.keys = { anthropic: $('#k1').value.trim(), openai: $('#k2').value.trim(),
                 openaiBase: $('#k3').value.trim(), ollama: $('#k4').value.trim() };
      S.theme = $('#kTheme').value; S.lang = $('#kLang').value;
      S.fontScale = +$('#kFs').value; S.talkRate = +$('#kRate').value;
      save(); closeModal(); applyI18n(); render(); await checkEngine(); toast(T('save'), 'ok');
    };
    $('#kModel').onclick = () => modelPanel(() => settingsPanel());
    // the size picker applies live so you can see it without saving
    $$('#mbody .szopt').forEach(b => {
      b.onclick = () => {
        setSideSize(b.dataset.sz);
        $$('#mbody .szopt').forEach(x => {
          const on = x.dataset.sz === b.dataset.sz;
          x.classList.toggle('on', on);
          x.setAttribute('aria-checked', String(on));
        });
      };
    });
    $('#kEnter').onclick = () => {
      S.enterToSend = !(S.enterToSend !== false); save();
      $('#kEnter').textContent = S.enterToSend ? 'On' : 'Off';
      $('#kEnter').setAttribute('aria-checked', String(S.enterToSend));
    };
    $('#kFs').oninput = e => { document.documentElement.style.fontSize = (15 * +e.target.value) + 'px'; };
    $('#kExport').onclick = () => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(S, null, 2)], { type: 'application/json' }));
      a.download = 'olmavax-data.json'; a.click(); URL.revokeObjectURL(a.href);
    };
    $('#kImport').onclick = () => {
      const i = document.createElement('input'); i.type = 'file'; i.accept = '.json,application/json';
      i.onchange = async () => {
        try { S = Object.assign({}, DEFAULTS, JSON.parse(await i.files[0].text()));
              save(); closeModal(); applyI18n(); render(); toast(T('importData'), 'ok'); }
        catch { toast('Invalid file', 'err'); }
      };
      i.click();
    };
    $('#kClear').onclick = () => {
      if (!confirm(T('confirmClear'))) return;
      localStorage.removeItem('olmavax'); S = Object.assign({}, DEFAULTS); save();
      closeModal(); render(); applyI18n(); toast(T('clearAll'), 'ok');
    };
  });
}

function modelPanel(back) {
  const byProv = {};
  for (const m of models) (byProv[m.provider] = byProv[m.provider] || []).push(m);
  const NAME = { auto: T('auto'), mock: T('offlineBrain'), anthropic: 'Anthropic',
                 openai: 'OpenAI / compatible', ollama: 'Ollama', sidecar: 'Olmavax Agent' };
  let h = '<h3>' + esc(T('chooseModel')) + '</h3>';
  for (const p of ['auto', 'anthropic', 'openai', 'ollama', 'sidecar']) {
    const arr = byProv[p]; if (!arr) continue;
    const ready = p === 'auto' || p === 'mock' || providers[p];
    h += '<div class="pal-h">' + esc(NAME[p] || p) + (ready ? '' : ' · ' + esc(T('needsKey'))) + '</div><div class="mlist">';
    for (const m of arr) {
      const on = S.model === m.id && (S.provider || 'auto') === p;
      h += '<button class="mitem' + (on ? ' on' : '') + '" data-m="' + esc(m.id) + '" data-p="' + p + '">' +
        '<span class="mi"></span><span class="mt"><b>' + esc(m.label) + '</b><small>' + esc(m.note) + '</small></span>' +
        (m.free ? '<span class="badge">' + esc(T('free')) + '</span>' : '') +
        (on ? '<span class="ok">' + IC.check + '</span>' : '') + '</button>';
    }
    h += '</div>';
  }
  modal(h, () => {
    $('#mbody').querySelectorAll('[data-m]').forEach(b => b.onclick = () => {
      S.model = b.dataset.m; S.provider = b.dataset.p; save();
      updateModelBtn(); closeModal(); toast(T('modelSet') + ' · ' + b.querySelector('b').textContent, 'ok');
      if (back) back();
    });
  });
}

function agentPanel() {
  const BLURB = {
    general: 'Everyday questions, quick answers and general help.',
    coder: 'Writes, reviews and debugs code in any language.',
    app: 'Designs apps and websites, with structure and build steps.',
    research: 'Goes deep, compares sources, flags uncertainty.',
    writer: 'Articles, emails, stories, scripts and résumés.',
    presenter: 'Slide decks with titles, bullets and speaker notes.',
    portfolio: 'Portfolios, CVs, LinkedIn and interview prep.',
    tutor: 'Explains step by step, then quizzes you.',
    planner: 'Turns goals into milestones, schedules and checklists.',
  };
  modal('<h3>' + esc(T('chooseAgent')) + '</h3><p class="muted">' + esc(T('agentsHint')) + '</p><div class="agrid">' +
    '<button class="acard' + (S.agent === 'auto' ? ' on' : '') + '" data-a="auto"><span class="ae">🤖</span><b>' + esc(T('auto')) + '</b><small>' + esc(T('agentsHint')) + '</small></button>' +
    agents.map(a => '<button class="acard' + (S.agent === a.id ? ' on' : '') + '" data-a="' + a.id + '">' +
      '<span class="ae">' + a.icon + '</span><b>' + esc(a.name) + '</b><small>' + esc(BLURB[a.id] || '') + '</small></button>').join('') +
    '</div>', () => {
      $('#mbody').querySelectorAll('[data-a]').forEach(b => b.onclick = () => {
        S.agent = b.dataset.a; save(); closeModal(); applyI18n(); toast(T('agentSet'), 'ok');
      });
    });
}

async function memPanel() {
  let facts = [];
  try { facts = (await api('/api/memory')).facts || []; } catch {}
  const paint = () => {
    $('#mbody').innerHTML =
      '<h3>' + IC.memory + ' ' + esc(T('memory')) + '</h3>' +
      '<p class="muted">Facts are injected into every conversation.</p>' +
      (facts.length ? '<div class="flist">' + facts.map(f =>
          '<div class="fitem"><span>' + esc(f.text) + '</span><button data-id="' + esc(f.id) + '" title="' + esc(T('delete')) + '">' + IC.trash + '</button></div>').join('') + '</div>'
        : '<p class="muted">' + esc(T('nothing')) + '</p>') +
      '<label>' + esc(T('addFact')) + '<input id="nf" placeholder="' + esc(T('addFact')) + '"></label>' +
      '<button class="b primary" id="af">' + esc(T('create')) + '</button>';
    $('#mbody').querySelectorAll('[data-id]').forEach(b => b.onclick = async () => {
      await api('/api/memory?id=' + encodeURIComponent(b.dataset.id), { method: 'DELETE' });
      facts = facts.filter(f => f.id !== b.dataset.id); paint(); refreshCounts();
    });
    $('#af').onclick = async () => {
      const t = $('#nf').value.trim(); if (!t) return;
      try { facts.unshift(await api('/api/memory', { method: 'POST', body: JSON.stringify({ text: t }) }));
            $('#nf').value = ''; paint(); refreshCounts(); }
      catch (e) { toast(e.message, 'err'); }
    };
  };
  $('#modal').hidden = false; paint();
}

async function buildPanel() {
  const types = ['website', 'app', 'presentation', 'portfolio', 'article'];
  modal('<h3>' + IC.build + ' ' + esc(T('buildSomething')) + '</h3>' +
    '<select id="bt">' + types.map(t => '<option>' + t + '</option>').join('') + '</select>' +
    '<textarea id="bp" rows="4" placeholder="' + esc(T('whatBuild')) + '"></textarea>' +
    '<button class="b primary" id="bg">' + esc(T('generate')) + '</button><div id="bo"></div>', () => {
    $('#bg').onclick = async () => {
      const prompt = $('#bp').value.trim();
      if (!prompt) return toast(T('whatBuild'), 'err');
      $('#bo').textContent = T('thinking') + '…'; $('#bg').disabled = true;
      try {
        const j = await api('/api/build', { method: 'POST', body: JSON.stringify({ type: $('#bt').value, prompt, provider: S.provider, model: S.model, keys: S.keys }) });
        const html = j.files.find(f => f.name.endsWith('.html'));
        $('#bo').innerHTML = '<p class="muted">' + j.files.map(f => esc(f.name)).join(' · ') + ' — ' + esc(j.mode) + '/' + esc(j.provider) + '</p>' +
          (html ? '<iframe sandbox="allow-scripts"></iframe>' : '') +
          '<a class="dl" href="/api/download/' + esc(j.id) + '">' + IC.dl + ' ' + esc(T('download')) + '</a>';
        if (html) $('#bo iframe').srcdoc = html.content;
        toast(T('generate') + ' 🚀', 'ok');
      } catch (e) { $('#bo').textContent = '⚠️ ' + e.message; toast(e.message, 'err', 4000); }
      finally { $('#bg').disabled = false; }
    };
  });
}

function projectPanel() {
  const draw = () => {
    $('#mbody').innerHTML =
      '<h3>' + IC.folder + ' ' + esc(T('projects')) + '</h3>' +
      '<p class="muted">Project instructions are prepended to every message in that project.</p>' +
      '<div class="flist"><div class="fitem"><span>' + esc(T('noProject')) + '</span>' +
        '<button data-p=""' + (!S.project ? ' class="on"' : '') + '>' + (S.project ? 'Use' : IC.check) + '</button></div>' +
        (S.projects.map(p => '<div class="fitem"><span>📁 ' + esc(p.name) + '</span><span style="display:flex;gap:4px">' +
          '<button data-p="' + esc(p.id) + '"' + (S.project === p.id ? ' class="on"' : '') + '>' + (S.project === p.id ? IC.check : 'Use') + '</button>' +
          '<button data-d="' + esc(p.id) + '">' + IC.trash + '</button></span></div>').join('') || '') + '</div>' +
      '<label>' + esc(T('projectName')) + '<input id="pn" placeholder="' + esc(T('projectName')) + '"></label>' +
      '<label>' + esc(T('projectInstr')) + '<textarea id="pi" rows="3" placeholder="' + esc(T('projectInstr')) + '"></textarea></label>' +
      '<button class="b primary" id="pc">' + esc(T('addProject')) + '</button>';
    $('#mbody').querySelectorAll('[data-p]').forEach(b => b.onclick = () => { S.project = b.dataset.p || null; save(); applyI18n(); draw(); });
    $('#mbody').querySelectorAll('[data-d]').forEach(b => b.onclick = () => {
      S.projects = S.projects.filter(p => p.id !== b.dataset.d);
      if (S.project === b.dataset.d) S.project = null; save(); applyI18n(); draw();
    });
    $('#pc').onclick = () => {
      const n = $('#pn').value.trim(); if (!n) return;
      S.projects.push({ id: uid(), name: n, instr: $('#pi').value.trim() });
      S.project = S.projects[S.projects.length - 1].id; save(); applyI18n(); draw();
    };
  };
  $('#modal').hidden = false; draw();
}

function sketchPanel() {
  modal('<h3>✏️ ' + esc(T('sketch')) + '</h3>' +
    '<canvas class="pad" id="cv" width="800" height="500"></canvas>' +
    '<div class="grid2"><button class="b" id="cc">' + esc(T('clear')) + '</button>' +
    '<button class="b primary" id="ca">' + esc(T('attach')) + '</button></div>', () => {
    const cv = $('#cv'), x = cv.getContext('2d');
    x.fillStyle = '#fff'; x.fillRect(0, 0, 800, 500);
    x.lineWidth = 4; x.lineCap = 'round'; x.lineJoin = 'round'; x.strokeStyle = '#111';
    let down = false;
    const pos = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * 800 / r.width, (e.clientY - r.top) * 500 / r.height]; };
    cv.onpointerdown = e => { down = true; const [a, b] = pos(e); x.beginPath(); x.moveTo(a, b); cv.setPointerCapture(e.pointerId); };
    cv.onpointermove = e => { if (!down) return; const [a, b] = pos(e); x.lineTo(a, b); x.stroke(); };
    cv.onpointerup = cv.onpointercancel = () => { down = false; };
    $('#cc').onclick = () => { x.fillStyle = '#fff'; x.fillRect(0, 0, 800, 500); };
    $('#ca').onclick = () => {
      addAtt({ name: 'sketch.png', mime: 'image/png', image: cv.toDataURL('image/png').split(',')[1] });
      closeModal(); toast(T('attach') + ' 🚀', 'ok');
    };
  });
}

/* ═════════════════ COMMAND PALETTE ═════════════════ */
const CMDS = () => [
  { ic: IC.plus, t: T('newChat'), k: 'Ctrl K', fn: newChat },
  { ic: IC.search, t: T('searchHistory'), k: 'Ctrl ⇧F', fn: () => { openSide(); $('#csearch').focus(); } },
  { ic: IC.gear, t: T('settings'), k: 'Ctrl ,', fn: settingsPanel },
  { ic: IC.img, t: T('images'), fn: () => openPanel('images') },
  { ic: IC.clock, t: T('scheduled'), fn: () => openPanel('scheduled') },
  { ic: IC.book, t: T('library'), fn: () => openPanel('library') },
  { ic: IC.plug, t: T('plugins'), fn: () => openPanel('plugins') },
  { ic: IC.code, t: T('codex'), fn: () => openPanel('codex') },
  { ic: IC.search, t: T('explore'), fn: () => openPanel('explore') },
  { ic: IC.memory, t: T('memory'), fn: () => openPanel('memory') },
  { ic: IC.folder, t: T('projects'), fn: () => openPanel('projects') },
  { ic: IC.build, t: T('buildSomething'), fn: () => openPanel('build') },
  { ic: IC.dl, t: T('chooseModel'), fn: () => modelPanel() },
  { ic: IC.export, t: T('exportPdf'), k: 'Ctrl E', fn: () => exportPDF() },
  { ic: IC.export, t: T('exportChat'), fn: () => chat() && exportChat(S.cur) },
  { ic: IC.mic, t: T('voiceMode'), k: 'Ctrl M', fn: openVoice },
  { ic: IC.trash, t: T('clearChat'), fn: () => { const c = chat(); if (c) { c.msgs = []; save(); render(); } } },
];
function openPalette() {
  $('#palette').hidden = false; $('#palQ').value = ''; paintPalette(''); $('#palQ').focus();
}
function closePalette() { $('#palette').hidden = true; }
let palSel = 0, palItems = [];
function paintPalette(q) {
  const s = (q || '').toLowerCase();
  const items = CMDS().filter(c => !s || c.t.toLowerCase().includes(s)).map(c => ({ ...c, group: T('commands') }));
  for (const c of S.chats) if (!s || (c.title || '').toLowerCase().includes(s)) {
    items.push({ ic: IC.search, t: c.title, group: T('today'), fn: () => { S.cur = c.id; save(); render(); closeSide(); } });
  }
  palItems = items; palSel = 0;
  const list = $('#palList');
  if (!items.length) { list.innerHTML = '<div class="pal-item">' + IC.search + '<span>' + esc(T('noResults')) + '</span></div>'; return; }
  let html = '', last = null;
  items.forEach((it, i) => {
    if (it.group !== last) { html += '<div class="pal-h">' + esc(it.group) + '</div>'; last = it.group; }
    html += '<button class="pal-item' + (i === 0 ? ' sel' : '') + '" data-i="' + i + '">' + it.ic + '<span>' + esc(it.t) + '</span>' +
      (it.k ? '<kbd>' + esc(it.k) + '</kbd>' : '') + '</button>';
  });
  list.innerHTML = html;
  list.querySelectorAll('[data-i]').forEach(b => b.onclick = () => { const it = palItems[+b.dataset.i]; closePalette(); it.fn(); });
}
function movePal(d) {
  const btns = $$('#palList [data-i]'); if (!btns.length) return;
  palSel = Math.max(0, Math.min(btns.length - 1, palSel + d));
  btns.forEach((b, i) => b.classList.toggle('sel', i === palSel));
  btns[palSel].scrollIntoView({ block: 'nearest' });
}

/* ══════════════════ SIDEBAR / COUNTS ══════════════════ */
function openSide() { if (innerWidth <= 860) { $('#side').classList.add('open'); $('#scrim').hidden = false; } }
function closeSide() { $('#side').classList.remove('open'); $('#scrim').hidden = true; }
function closeMenus() { $('#menu2').hidden = true; $('#plus').classList.remove('on'); }

async function refreshCounts() {
  const imgs = S.chats.reduce((n, c) => n + c.msgs.filter(m => m.image).length, 0);
  $('#imgPill').textContent = imgs;
  try {
    const [mem, lib, sch] = await Promise.all([api('/api/memory'), api('/api/library'), api('/api/schedule')]);
    $('#memPill').textContent = (mem.facts || []).length;
    $('#libPill').textContent = (lib.items || []).length;
    $('#schPill').textContent = (sch.items || []).length;
  } catch {}
}

/* ════════ WIRING ════════ */
const ACTS = {
  files: () => $('#file').click(),
  image: () => setMode('image'),
  search: () => setMode('search'),
  research: () => setMode('research'),
  sketch: sketchPanel,
  codex: () => openPanel('codex'),
  library: () => openPanel('library'),
  schedule: () => scheduledPanel(chat() && chat().msgs.length ? chat().msgs.slice(-1)[0].content : $('#input').value),
  project: () => openPanel('projects'),
  build: () => openPanel('build'),
  record: toggleRec,
};

function wire() {
  $('#plus').onclick = e => {
    e.stopPropagation();
    const open = $('#menu2').hidden;
    closePalette(); $('#menu2').hidden = !open; $('#plus').classList.toggle('on', open);
  };
  $('#menu2').querySelectorAll('[data-act]').forEach(b => b.onclick = () => { closeMenus(); ACTS[b.dataset.act](); });
  document.addEventListener('click', e => { if (!$('#comp').contains(e.target)) closeMenus(); });

  $('#think').onclick = () => { think = !think; S.think = think; save(); $('#think').classList.toggle('on', think); $('#think').setAttribute('aria-pressed', String(think)); };
  $$('#sugg button').forEach(b => b.onclick = () => setMode(b.dataset.mode));
  $$('.seg [data-mode]').forEach(b => b.onclick = () => setSpace(b.dataset.mode));

  $('#go').onclick = () => {
    if (busy) { ctrl && ctrl.abort(); return; }
    const t = $('#input').value.trim();
    if (t) send(t); else if (atts.length) $('#input').focus();
  };
  $('#input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (S.enterToSend === false && !e.ctrlKey) return;
      send($('#input').value);
    }
    if (e.key === 'Escape' && $('#input').value) { $('#input').value = ''; autosize(); updateGo(); }
  });
  $('#input').addEventListener('input', () => { autosize(); updateGo(); });
  $('#mic').onclick = async () => { const { text } = await listen(true); if (text) send(text); };
  $('#vstart').onclick = () => { if (!live.on) openVoice(); };
  $('#voiceBtn').onclick = () => { if (live.on) closeVoice(); else openVoice(); };
  $('#orb').onclick = () => closeVoice();
  $('#vclose').onclick = () => closeVoice();
  $('#vlToggle').onclick = () => $('#voiceLog').classList.toggle('collapsed');
  $('#vlClear').onclick = () => { voiceLog.length = 0; paintVoiceLog(); };

  $('#vstop').onclick = () => { speechSynthesis.cancel(); logVoice('ai', T('stoppedSpeaking')); vstate('listening', T('listening')); };
  $('#voiceDock').onclick = e => { if (e.target === $('#voiceDock')) closeVoice(); };

  $('#newChat').onclick = newChat;
  $$('#botnav [data-bn]').forEach(b => b.onclick = () => {
    const k = b.dataset.bn;
    if (k === 'new') newChat();
    else if (k === 'talk') { if (live.on) closeVoice(); else openVoice(); }
    else if (k === 'menu') { $('#side').classList.contains('open') ? closeSide() : openSide(); }
    else openPanel(k);
    $$('#botnav [data-bn]').forEach(x => x.classList.toggle('on', x.dataset.bn === k));
  });
  $('#menu').onclick = () => { $('#side').classList.contains('open') ? closeSide() : openSide(); };
  $('#sideClose').onclick = closeSide;
  $('#scrim').onclick = closeSide;
  $('#sideCollapse').onclick = toggleRail;
  $('#histClear').onclick = clearChats;
  $('#talkBtn').onclick = () => { if (live.on) closeVoice(); else openVoice(); };
  $('#menu').onclick = () => {
    if (innerWidth <= 860) { $('#side').classList.contains('open') ? closeSide() : openSide(); }
    else toggleRail();
  };
  $('#csearchX').onclick = () => { $('#csearch').value = ''; renderChats(); $('#csearch').focus(); };
  $('#csearch').oninput = renderChats;
  $('#titleEdit').onclick = () => chat() && renameChat(S.cur);
  $('#modelBtn').onclick = () => modelPanel();
  $('#pdfBtn').onclick = () => exportPDF();
  $('#bSet').onclick = settingsPanel;
  $('#engFix').onclick = settingsPanel;
  $('#bTheme').onclick = () => {
    S.theme = S.theme === 'dark' ? 'light' : 'dark'; save(); applyI18n();
    toast(T('themeSet') + ' · ' + (S.theme === 'dark' ? '🌙 Dark' : '☀️ Light'), 'ok');
  };
  $('#bLang').onclick = () => {
    const order = ['en', 'hi', 'es', 'fr', 'ar'];
    S.lang = order[(order.indexOf(S.lang) + 1) % order.length];
    save(); applyI18n(); render(); toast(T('langSet') + ' · ' + $('#langPill').textContent, 'ok');
  };
  $$('.side-nav [data-nav]').forEach(b => b.onclick = () => openPanel(b.dataset.nav));

  $('#mclose').onclick = closeModal;
  $('#modal').onclick = e => { if (e.target === $('#modal')) closeModal(); };
  $('#palette').onclick = e => { if (e.target === $('#palette')) closePalette(); };
  $('#palQ').addEventListener('input', e => paintPalette(e.target.value));
  $('#palQ').addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); movePal(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); movePal(-1); }
    else if (e.key === 'Enter') { e.preventDefault(); const it = palItems[palSel]; if (it) { closePalette(); it.fn(); } }
  });

  $('#file').onchange = e => { onFiles([...e.target.files]); e.target.value = ''; };
  $('#input').addEventListener('paste', e => {
    const f = [...((e.clipboardData || {}).files || [])];
    if (f.length) { e.preventDefault(); onFiles(f); }
  });
  $('#input').addEventListener('dragover', e => { e.preventDefault(); });
  $('#input').addEventListener('drop', e => {
    e.preventDefault();
    const f = [...(e.dataTransfer.files || [])]; if (f.length) onFiles(f);
  });

  $('#stage').addEventListener('scroll', () => {
    const st = $('#stage');
    stickBottom = st.scrollHeight - st.scrollTop - st.clientHeight < 90;
    document.querySelector('main').classList.toggle('scrolled', st.scrollTop > 6);
    $('#scrollEnd')?.remove();
    if (!stickBottom && chat() && chat().msgs.length) {
      const b = document.createElement('div');
      b.className = 'scroll-end'; b.id = 'scrollEnd';
      b.innerHTML = '<button>' + IC.down + ' Latest</button>';
      b.querySelector('button').onclick = () => { stickBottom = true; scrollEnd(); b.remove(); };
      $('#msgs').appendChild(b);
    }
  });

  addEventListener('online', () => { $('#net').classList.remove('off'); checkEngine(); });
  addEventListener('offline', () => $('#net').classList.add('off'));
  if (!navigator.onLine) $('#net').classList.add('off');

  addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
    if (e.key === 'Escape') {
      if (!$('#palette').hidden) return closePalette();
      if (!$('#modal').hidden) return closeModal();
      if (!$('#menu2').hidden) return closeMenus();
      if (live.on) return closeVoice();
      if ($('#side').classList.contains('open')) return closeSide();
    }
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'k') { e.preventDefault(); return openPalette(); }
    if ((e.ctrlKey || e.metaKey) && k === 'b') { e.preventDefault(); return innerWidth <= 860 ? $('#menu').click() : toggleRail(); }
    if ((e.ctrlKey || e.metaKey) && k === 'm') { e.preventDefault(); return $('#vstart').click(); }
    if ((e.ctrlKey || e.metaKey) && k === 'e') { e.preventDefault(); return exportPDF(); }
    if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); return settingsPanel(); }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && k === 'f') { e.preventDefault(); return $('#csearch').focus(); }
    if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (e.key === '/') { e.preventDefault(); $('#input').focus(); }
      else if (k === 'n') { e.preventDefault(); newChat(); }
      else if (k === 'i') { e.preventDefault(); openPanel('images'); }
      else if (k === 'l') { e.preventDefault(); openPanel('library'); }
      else if (k === 'p') { e.preventDefault(); openPanel('plugins'); }
      else if (k === 'v' || k === 't') { e.preventDefault(); if (live.on) closeVoice(); else openVoice(); }
    }
  });

  // NB: no beforeunload save — every mutation already calls save(), and an
  // unload write would resurrect data the user just cleared.
}

/* ══════ BOOT ══════ */
(async () => {
  wire();
  try {
    const j = await api('/api/status');
    agents = j.agents || []; models = j.models || []; providers = j.providers || {};
    sidecar = j.sidecar || { available: false };
    const v = $('#ver'); if (v) v.textContent = j.version || '3.0.0';
  } catch {}
  if (!S.chats.length) newChat(); else render();
  applyI18n(); updateModelBtn(); refreshCounts(); updatePlugins(); applySideW();
  checkEngine(); $('#input').focus();

  const sp = $('#splash');
  if (S.splashSeen) { sp.classList.add('hide'); setTimeout(() => sp.remove(), 700); }
  else {
    setTimeout(() => {
      sp.classList.add('hide'); S.splashSeen = true; save();
      setTimeout(() => sp.remove(), 700);
    }, 2000);
  }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  setInterval(checkEngine, 30000);
})();
})();
