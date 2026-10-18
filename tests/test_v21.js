'use strict';
/**
 * Tests for v2.1: OpenCharvis bridge, model catalogue, redesigned front-end.
 */
const test = require('node:test'), assert = require('node:assert');
const fs = require('fs'), os = require('os'), path = require('path');
const { createServer } = require('../server/server');
const charvis = require('../server/charvis');
const { MODELS, PROVIDER_NAME } = require('../server/models');
const I18N = require('../public/i18n');

const PUB = path.join(__dirname, '../public');
const read = f => fs.readFileSync(path.join(PUB, f), 'utf8');
const CLOSED = 'http://127.0.0.1:9'; // nothing listens here

let srv, base;
test.before(async () => {
  srv = createServer({ dataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'olma21-')) });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  base = 'http://127.0.0.1:' + srv.address().port;
});
test.after(() => srv.close());

/* ── OpenCharvis bridge ───────────────────────────────────────── */

test('charvis: probe and status degrade quietly when the sidecar is down', async () => {
  assert.equal(await charvis.probe(CLOSED), false);
  assert.equal(await charvis.status(CLOSED), null);
});

test('charvis: selecting it without a sidecar gives an actionable error', async () => {
  const r = await fetch(base + '/api/chat', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ messages: [{ role: 'user', content: 'hi' }], provider: 'charvis' }),
  });
  const t = await r.text();
  assert.ok(t.includes('OpenCharvis is not running'), 'missing guidance');
  assert.ok(t.includes('"done":true'), 'stream was not terminated cleanly');
});

/* ── model catalogue ──────────────────────────────────────────── */

test('models: entries are well formed and uniquely addressable', () => {
  assert.ok(MODELS.length >= 10, 'catalogue too small');
  const seen = new Set();
  for (const m of MODELS) {
    assert.ok(m.id && m.label && m.note, 'incomplete entry ' + JSON.stringify(m));
    assert.ok(PROVIDER_NAME[m.provider], 'unknown provider ' + m.provider);
    const key = m.provider + '::' + m.id;
    assert.ok(!seen.has(key), 'duplicate ' + key);
    seen.add(key);
  }
});

test('models: every zero-config path is represented', () => {
  assert.ok(MODELS.some(m => m.free && m.provider === 'mock'), 'no offline brain');
  assert.ok(MODELS.some(m => m.free && m.provider === 'ollama'), 'no local model');
  assert.ok(MODELS.some(m => m.provider === 'charvis'), 'no OpenCharvis entry');
});

test('status advertises the catalogue, versions and charvis bridge', async () => {
  const j = await (await fetch(base + '/api/status')).json();
  assert.equal(j.version, '3.0.0');
  assert.ok(Array.isArray(j.models) && j.models.length === MODELS.length, 'models missing');
  assert.ok(j.providerNames && j.providerNames.anthropic, 'provider names missing');
  assert.ok(j.providers && 'charvis' in j.providers, 'charvis not in providers');
  assert.ok(j.charvis && j.charvis.url, 'charvis info missing');
});

/* ── front-end ────────────────────────────────────────────────── */

test('i18n: history group labels exist in every language', () => {
  for (const l of Object.keys(I18N)) {
    for (const k of ['today', 'yesterday', 'prev7', 'prev30', 'older', 'pinned']) {
      assert.ok(I18N[l][k], l + ' missing ' + k);
    }
  }
});

test('i18n: every data-i hook used in the shell resolves', () => {
  const used = [...read('index.html').matchAll(/data-i="(\w+)"/g)].map(m => m[1]);
  assert.ok(used.length > 15, 'expected many i18n hooks, got ' + used.length);
  for (const k of used) assert.ok(I18N.en[k], 'missing i18n key: ' + k);
});

test('markdown: fences, bold, italic and escaping are all handled', () => {
  const js = read('app.js');
  assert.ok(js.includes('blocks.push('), 'fenced-code extraction missing');
  assert.ok(js.includes('<pre><code'), 'code block rendering missing');
  for (const [n, w] of [['<strong>', 'bold'], ['<em>', 'italic'], ['rel="noopener"', 'safe links']]) {
    assert.ok(js.includes(n), w + ' not handled');
  }
  for (const e of ['&amp;', '&lt;', '&gt;', '&quot;']) {
    assert.ok(js.includes(e), 'escape ' + e + ' missing');
  }
});

test('markdown: fenced code is captured raw and escaped exactly once', () => {
  const js = read('app.js');
  assert.ok(js.includes('function inlineMd('), 'inlineMd helper missing');
  assert.ok(/i % 3 === 2/.test(js), 'split loop does not skip the captured body');
  assert.ok(js.includes('function safeSvg('), 'safeSvg guard missing');
  assert.ok(read('highlight.js').includes('escH'), 'highlighter must escape');
});

test('markdown: svg pass-through is allowlisted, never raw', () => {
  const js = read('app.js');
  for (const bad of ['<script', 'javascript:', 'on\\w+', '<foreignObject', '<image\\b']) {
    assert.ok(js.includes(bad), 'guard does not reject: ' + bad);
  }
  assert.ok(js.includes('viewBox'), 'guard does not require a viewBox');
});

test('css: dead selectors from the previous design are gone', () => {
  const css = read('style.css');
  for (const dead of ['.vchip', '#vtoast', '.orb{']) {
    assert.ok(!css.includes(dead), 'stale selector still present: ' + dead);
  }
});

test('composer: send button stays hidden until there is something to send', () => {
  assert.ok(read('app.js').includes('b.hidden = !busy && !has'), 'send visibility rule missing');
});

test('dom: every id app.js reaches for exists in the shell', () => {
  const js = read('app.js'), html = read('index.html');
  const used = new Set([...js.matchAll(/\$\('#([\w-]+)'\)/g)].map(m => m[1]));
  const have = new Set([...html.matchAll(/id="([\w-]+)"/g)].map(m => m[1]));
  // ids created at runtime inside modal templates
  const dyn = new Set(['k0','k1','k2','k3','k4','k5','ks','kSave','kAgent','kTheme','kLang','kFs','kRate',
    'kModel','kEnter','kExport','kImport','kClear','ver','scrollEnd','nf','af','bt','bp','bg','bo',
    'pn','pi','pc','cv','cc','ca','engTxt','engFix',
    'psearch','prun','pinput','pout','cxCode','cxLang','cxName','cxPrev','cxSave','cxDet','sadd','sp','sw']);
  assert.deepEqual([...used].filter(x => !have.has(x) && !dyn.has(x)), []);
});

test('settings: shows how to launch the OpenCharvis sidecar', () => {
  assert.ok(read('app.js').includes('charvis.py ui'), 'launch hint missing');
  assert.ok(I18N.en.charvisHint, 'charvisHint missing');
});

/* ── packaging ────────────────────────────────────────────────── */

test('packaging: env example documents the charvis sidecar', () => {
  const env = fs.readFileSync(path.join(__dirname, '..', '.env.example'), 'utf8');
  assert.ok(env.includes('CHARVIS_URL'), 'CHARVIS_URL missing');
  assert.ok(env.includes('8787'), 'PORT missing');
});

test('packaging: launcher script ships', () => {
  assert.ok(fs.existsSync(path.join(__dirname, '..', 'start-olmavax.bat')));
});

test('packaging: service worker cache is current and precaches the new assets', () => {
  const sw = read('sw.js');
  assert.ok(sw.includes('olmavax-v3'), 'stale cache name');
  for (const a of ['/highlight.js', '/logo.svg', '/logo-mark.svg']) {
    assert.ok(sw.includes(a), 'not precached: ' + a);
  }
});

/* ═══════════ v3.1 — voice visibility, sidebar states, bottom nav ═══════════ */

test('voice: reachable from several visible places, not just a shortcut', () => {
  const html = read('index.html'), js = read('app.js');
  assert.ok(html.includes('id="talkBtn"'), 'no visible Talk button in the sidebar');
  assert.ok(html.includes('data-bn="talk"'), 'no Talk entry in the bottom nav');
  assert.ok(html.includes('id="vstart"'), 'no voice button in the composer');
  assert.ok(html.includes('id="mic"'), 'no dictation button in the composer');
  for (const [label, re] of [['Ctrl+M', /k === 'm'/], ['T/V key', /k === 'v' \|\| k === 't'/]]) {
    assert.ok(re.test(js), 'keyboard route missing: ' + label);
  }
});

test('voice: dock does not take over the screen, chat stays usable', () => {
  const css = read('style.css');
  assert.ok(!/#voice\s*\{[^}]*inset:0/.test(css), '#voice is still a full-screen takeover');
  assert.ok(css.includes('#voiceDock'), 'no #voiceDock rules');
  // anchored to the composer, which moves into both the home and chat views
  assert.ok(/#voiceDock\s*\{[^}]*position:\s*absolute/.test(css), 'dock is not anchored to #comp');
  assert.ok(!/body\.voicing #comp \{[^}]*translateY/.test(css), 'composer still shifts while voicing');
  // the input must stay reachable while voice runs
  assert.ok(!/body\.voicing #input\s*\{[^}]*display:\s*none/.test(css), 'input hidden while voicing');
});

test('voice: refuses gracefully when the browser has no speech engine', () => {
  const js = read('app.js');
  assert.ok(js.includes('noVoiceSupport'), 'no unsupported-browser message');
  const open = js.slice(js.indexOf('function openVoice()'));
  const head = open.slice(0, open.indexOf('live.on = true;'));
  assert.ok(head.includes('if (!SR'), 'openVoice does not check SR before opening the dock');
});

test('sidebar: three states — hidden, icon rail, full drawer', () => {
  const css = read('style.css'), js = read('app.js');
  assert.ok(/body\.side-rail #side \{ width: var\(--rail-w\); \}/.test(css), 'no rail width');
  assert.ok(css.includes('@media (max-width: 860px)') && css.includes('#side.open'), 'no off-canvas drawer');
  assert.ok(js.includes('function toggleRail()'), 'no rail toggle');
  assert.ok(/rail: false/.test(js), 'rail state not persisted in defaults');
  assert.ok(js.includes("toggle('side-rail'"), 'rail class never applied');
});

test('sidebar: search box is always visible, and tooltips explain the rail', () => {
  const html = read('index.html');
  assert.ok(!/id="sideSearchBox" hidden/.test(html), 'search box starts hidden');
  assert.ok(html.includes('id="sideSearchBox"'), 'no search box');
  const tips = [...html.matchAll(/data-nav="\w+" data-tip="(\w+)"/g)].map(m => m[1]);
  assert.ok(tips.length >= 10, 'only ' + tips.length + ' nav items have tooltips');
  assert.ok(read('style.css').includes('data-tip'), 'no tooltip styling');
});

test('layout: mobile bottom nav exists and is wired to the panels', () => {
  const html = read('index.html'), js = read('app.js'), css = read('style.css');
  assert.ok(html.includes('id="botnav"'), 'no bottom nav');
  assert.ok((html.match(/data-bn="/g) || []).length >= 5, 'bottom nav has too few items');
  assert.ok(js.includes('#botnav [data-bn]'), 'bottom nav not wired');
  assert.ok(css.includes('#botnav'), 'no bottom nav styling');
  assert.ok(/@media \(max-width: 860px\)/.test(css) && css.includes('#botnav { display: flex;'), 'bottom nav never shows');
});

test('layout: index.html has no duplicate ids and is tag-balanced', () => {
  const html = read('index.html');
  const ids = [...html.matchAll(/id="([\w-]+)"/g)].map(m => m[1]);
  const dupes = [...new Set(ids.filter((x, i) => ids.indexOf(x) !== i))];
  assert.deepEqual(dupes, [], 'duplicate ids: ' + dupes.join(', '));
  for (const tag of ['div', 'aside', 'main', 'nav', 'section', 'button']) {
    const open = (html.match(new RegExp('<' + tag + '(\\s|>)', 'g')) || []).length;
    const close = (html.match(new RegExp('</' + tag + '>', 'g')) || []).length;
    assert.equal(open, close, tag + ' tags unbalanced: ' + open + ' vs ' + close);
  }
});

test('layout: element accessors are not mixed up ($ vs $$)', () => {
  const js = read('app.js');
  const D = '$';
  // $$(...) is an array — it must never be chained into a node method
  const nodeMethods = ['querySelectorAll', 'querySelector', 'getBoundingClientRect', 'addEventListener',
                       'setAttribute', 'getAttribute', 'appendChild', 'closest', 'getContext'];
  for (const meth of nodeMethods) {
    const bad = new RegExp('\\$\\$(\\([^\\n]*?\\))\\.' + meth + '\\b');
    assert.ok(!bad.test(js), '$$(' + ')' + ').' + meth + ' — querySelectorAll returns one node');
  }
  assert.ok(!/\$\$\$\(/.test(js), 'found an accidental $$$(');
});

/* ═══════════ v3.2 — compact voice dock, Stop/Exit flanks, separate voice log ═══════════ */

test('voice: dock is compact with Stop on the left and Exit on the right', () => {
  const html = read('index.html'), css = read('style.css');
  assert.ok(/class="v-btn v-stop"/.test(html), 'no left-hand Stop button');
  assert.ok(/class="v-btn v-exit"/.test(html), 'no right-hand Exit button');
  assert.ok(html.includes('id="vstop"') && html.includes('id="vclose"'), 'missing stop/exit ids');
  // the orb sits between them
  const dock = html.slice(html.indexOf('<div class="v-dock"'), html.indexOf('<div id="voiceLog"'));
  const iStop = dock.indexOf('id="vstop"');
  const iOrb = dock.indexOf('id="orb"');
  const iClose = dock.indexOf('id="vclose"');
  assert.ok(iStop > 0 && iOrb > 0 && iClose > 0, 'dock is missing stop / orb / exit');
  assert.ok(iStop < iOrb, 'Stop is not to the left of the orb');
  assert.ok(iOrb < iClose, 'Exit is not to the right of the orb');
  // compact: not a full-width card
  assert.ok(/\.v-dock \{[^}]*width:\s*max-content/.test(css), 'dock is not sized to its content');
  assert.ok(/\.v-dock \{[^}]*border-radius:\s*999px/.test(css), 'dock is not a compact pill');
  assert.ok(/\.v-orb \{[^}]*width:\s*46px/.test(css), 'orb is not the smaller 46px size');
});

test('voice: Stop interrupts speech, it does not just hide the dock', () => {
  const js = read('app.js');
  const i = js.indexOf("$('#vstop').onclick");
  assert.ok(i > 0, 'Stop has no handler');
  const handler = js.slice(i, js.indexOf('\n', i));
  assert.ok(handler.includes('speechSynthesis.cancel'), 'Stop does not cancel speech');
  assert.ok(!/closeVoice/.test(handler), 'Stop closes voice instead of interrupting speech');
});

test('voice: spoken turns are written into the chat automatically', () => {
  const js = read('app.js');
  const loop = js.slice(js.indexOf('async function voiceLoop()'), js.indexOf('function openVoice()'));
  assert.ok(loop.includes("logVoice('you', text)"), 'the spoken line is not recorded');
  assert.ok(/await send\(text, \{ speak: true, voice: true \}\)/.test(loop), 'speech is not sent as a normal message');
  assert.ok(loop.includes("logVoice('ai'"), 'the reply is not recorded in the log');
  // send() must hand back the reply so the log can capture it
  assert.ok(/return am\.content;/.test(js.slice(js.lastIndexOf('if (opt.speak)'))), 'send() does not return the reply');
});

test('voice: a separate log box keeps spoken turns apart from typed chat', () => {
  const html = read('index.html'), js = read('app.js'), css = read('style.css');
  assert.ok(html.includes('id="voiceLog"') && html.includes('id="vlBody"'), 'no voice log box');
  assert.ok(html.includes('id="vlClear"') && html.includes('id="vlToggle"'), 'log is not clearable/collapsible');
  assert.ok(js.includes('function logVoice(who, text)'), 'no logVoice()');
  assert.ok(js.includes('function paintVoiceLog()'), 'log is never painted');
  assert.ok(js.includes('function showVoiceLog(on)'), 'log is never shown/hidden');
  // it opens with voice and closes with it
  const open = js.slice(js.indexOf('function openVoice()'), js.indexOf('function closeVoice()'));
  const close = js.slice(js.indexOf('function closeVoice()'), js.indexOf('function closeVoice()') + 400);
  assert.ok(open.includes('showVoiceLog(true)'), 'log does not open with voice');
  assert.ok(close.includes('showVoiceLog(false)'), 'log does not close with voice');
  // distinct look from the dock
  assert.ok(/#voiceLog \{[^}]*width: min\(520px/.test(css), 'log is not its own narrower panel');
  assert.ok(css.includes('#voiceLog.collapsed'), 'log cannot be collapsed');
});

test('voice: the log speaker labels must not wrap', () => {
  const css = read('style.css');
  assert.ok(/\.vl-row \.who \{[^}]*white-space: nowrap/.test(css), 'speaker label can wrap');
  assert.ok(/\.vl-row \.who \{[^}]*width: 58px/.test(css), 'speaker column too narrow for "Olmavax"');
});

test('voice: a dedicated on/off button sits in the top bar', () => {
  const html = read('index.html'), js = read('app.js'), css = read('style.css');
  assert.ok(html.includes('id="voiceBtn"'), 'no top-bar voice button');
  assert.ok(/class="icon-btn voice-btn"/.test(html), 'voice button has no dedicated styling hook');
  assert.ok(js.includes("$('#voiceBtn').onclick"), 'top-bar voice button is not wired');
  assert.ok(js.includes("classList.toggle('on', live.on)"), 'top-bar button never reflects state');
  assert.ok(css.includes('.voice-btn.on'), 'no active styling for the voice button');
});

test('voice: Exit label stays short in every language', () => {
  const i18n = new Function(read('i18n.js') + '; return I18N;')();
  for (const lang of Object.keys(i18n)) {
    assert.ok(i18n[lang].exit, lang + ' has no exit label');
    assert.ok(i18n[lang].exit.length <= 8, lang + ' exit label is too long: ' + i18n[lang].exit);
  }
});

/* ═══════════ sidebar vertical budget ═══════════ */

/* Ten panel rows plus header, search, talk and footer overflowed a laptop
   window, and .side-scroll - the chat history - was the flex item that got
   squeezed to zero height. The history became unreachable, so pin the fix. */
test('sidebar: the history list can never collapse to zero height', () => {
  const css = read('style.css');
  const m = css.match(/\.side-scroll \{([^}]*)\}/);
  assert.ok(m, 'no .side-scroll rule');
  const rule = m[1];
  assert.ok(/min-height:\s*\d+px/.test(rule), 'history has no min-height floor: ' + rule.trim());
  assert.ok(/max-height:/.test(rule), 'history can grow without limit');
  assert.ok(/overflow-y:\s*auto/.test(rule), 'a long history will not scroll');
  const floor = parseInt(rule.match(/min-height:\s*(\d+)px/)[1], 10);
  assert.ok(floor >= 80, 'min-height floor too small: ' + floor);
});

test('sidebar: nothing else is allowed to shrink away', () => {
  const css = read('style.css');
  assert.ok(/#side > \* \{ flex-shrink: 0; \}/.test(css),
            'sidebar children can shrink, which is what pushed history off screen');
  assert.ok(/#side \{[^}]*overflow-y: auto/.test(css) ||
            /#side \{[\s\S]{0,400}?overflow-y: auto/.test(css),
            'the sidebar has no scroll fallback for very short windows');
});

test('sidebar: the panel nav is a two-column grid so it stops crowding out history', () => {
  const css = read('style.css');
  const m = css.match(/\.side-nav \{([^}]*)\}/g);
  assert.ok(m && m.length, 'no .side-nav rule');
  assert.ok(m.some(r => /grid-template-columns:\s*1fr 1fr/.test(r)), 'nav is not a 2-column grid');
  // the rail keeps two icon columns too: one column of ten is tall enough to
  // push the history off a short screen again
  assert.ok(/body\.side-rail \.side-nav \{[^}]*grid-template-columns:\s*1fr 1fr/.test(css),
            'the collapsed rail falls back to one tall column');
});

test('sidebar: nav icons cannot stretch and squeeze their labels', () => {
  const css = read('style.css');
  assert.ok(/\.side-nav \.nv \.nav-ic \{[^}]*flex:\s*0 0 \d+px/.test(css),
            'the icon wrapper has no flex-basis, so .nv span { flex: 1 } grows it');
  assert.ok(/\.side-nav \.nv > span:not\(\.nav-ic\) \{ flex: 1 1 auto/.test(css),
            'the label does not get the remaining width');
});

test('history: it is labelled, and can be cleared', () => {
  const html = read('index.html'), js = read('app.js');
  assert.ok(html.includes('class="hist-head"'), 'no History heading in the sidebar');
  assert.ok(/data-i="history"/.test(html), 'the heading is not translatable');
  assert.ok(html.includes('id="histClear"'), 'no clear-all button');
  assert.ok(js.includes("$('#histClear').onclick = clearChats"), 'the clear button is not wired');
  assert.ok(js.includes('function clearChats()'), 'clearChats() is missing');
  // it must not leave the app with no chat at all
  const fn = js.slice(js.indexOf('function clearChats()'));
  assert.ok(/S\.chats = \[\]; save\(\); newChat\(\)/.test(fn.slice(0, 400)),
            'clearing the history does not start a fresh chat');
  assert.ok(/confirm\(/.test(fn.slice(0, 400)), 'clearing the history asks no confirmation');
});

test('history: the new strings exist in every language', () => {
  const i18n = new Function(read('i18n.js') + '; return I18N;')();
  for (const lang of Object.keys(i18n)) {
    for (const k of ['history', 'clear', 'confirmClearAll', 'chatsCleared', 'noChats']) {
      assert.ok(i18n[lang][k], lang + ' is missing the i18n key "' + k + '"');
    }
  }
});

/* ═══════════ sidebar size presets ═══════════ */

test('sidebar: four size presets, each with a distinct width', () => {
  const js = read('app.js');
  const m = js.match(/const SIDE_SIZES = \[([\s\S]*?)\];/);
  assert.ok(m, 'no SIDE_SIZES table');
  const ids = [...m[1].matchAll(/id:\s*'(\w+)'/g)].map(x => x[1]);
  assert.deepEqual(ids, ['rail', 'sm', 'md', 'lg'], 'unexpected presets: ' + ids.join(','));
  const pxs = [...m[1].matchAll(/px:\s*(\d+)/g)].map(x => +x[1]);
  assert.equal(pxs.length, 4, 'each preset needs a width');
  for (let i = 1; i < pxs.length; i++) {
    assert.ok(pxs[i] > pxs[i - 1], 'widths must increase: ' + pxs.join(','));
  }
  assert.ok(pxs[0] >= 56 && pxs[0] <= 80, 'the icon rail should be about 68px, got ' + pxs[0]);
  assert.ok(pxs[3] >= 320, 'the widest preset should be at least 320px, got ' + pxs[3]);
});

test('sidebar: the chosen size is applied, persisted and survives a reload', () => {
  const js = read('app.js');
  assert.ok(/sideSize: 'md'/.test(js), 'no sideSize default');
  assert.ok(js.includes('function applySideW()'), 'no applySideW()');
  assert.ok(js.includes("setProperty('--side-w'"), 'the width is never written to the element');
  assert.ok(js.includes('function setSideSize(id, quiet)'), 'no setSideSize()');
  const fn = js.slice(js.indexOf('function setSideSize(id, quiet)'));
  assert.ok(/save\(\)/.test(fn.slice(0, 400)), 'setSideSize does not persist');
  assert.ok(/applySideW\(\)/.test(fn.slice(0, 400)), 'setSideSize does not re-apply the width');
  assert.ok(/paintMode\(\)/.test(fn.slice(0, 400)), 'setSideSize does not repaint');
  // picking rail must collapse, picking a width must expand
  assert.ok(/S\.rail = found\.rail/.test(fn.slice(0, 400)), 'rail state is not derived from the preset');
  // applied on boot, or the saved width is ignored until something changes
  assert.ok(/applyI18n\(\);[^\n]*applySideW\(\)/.test(js), 'applySideW is not called during boot');
});

test('sidebar: the header collapse button still toggles the icon rail', () => {
  const js = read('app.js'), html = read('index.html');
  assert.ok(html.includes('id="sideCollapse"'), 'no collapse button in the header');
  assert.ok(js.includes("$('#sideCollapse').onclick = toggleRail"), 'collapse button is not wired');
  const fn = js.slice(js.indexOf('function toggleRail()'));
  assert.ok(/S\.rail = !S\.rail/.test(fn), 'toggleRail does not flip the rail');
  assert.ok(/applySideW\(\)/.test(fn.slice(0, 300)), 'toggleRail does not re-apply the width');
});

test('sidebar: settings has a visible size picker that applies live', () => {
  const html = read('index.html'), js = read('app.js'), css = read('style.css');
  assert.ok(js.includes('class="sizepick"'), 'no size picker in settings');
  assert.ok(js.includes("$$('#mbody .szopt').forEach"), 'the size options are not wired');
  assert.ok(/data-sz="'\s*\+\s*s\.id\s*\+\s*'"/.test(js) || /data-sz="\$\{s\.id\}"/.test(js),
            'each option carries no data-sz');
  assert.ok(js.includes("SIDE_SIZES.map(s =>"), 'the picker is not built from SIDE_SIZES');
  // live means it repaints on click, before the Save button
  const wire = js.slice(js.indexOf("$$('#mbody .szopt').forEach"));
  assert.ok(/setSideSize\(b\.dataset\.sz\)/.test(wire.slice(0, 400)), 'clicking a size does not apply it');
  assert.ok(css.includes('.sizepick'), 'the picker has no styling');
  assert.ok(css.includes('.szopt.on'), 'the selected size is not highlighted');
  assert.ok(html.includes('class="hist-head"'), 'sanity: the history heading is still in the shell');
});

test('sidebar: a narrow or short window still shows the history', () => {
  const css = read('style.css');
  // the nav is the only section allowed to give ground, and only down to a cap.
  // .side-nav has several rules, so find the grid one rather than the first.
  const nav = css.match(/\.side-nav \{[^}]*grid-template-columns:[^}]*\}/);
  assert.ok(nav, 'no grid .side-nav rule');
  assert.ok(/flex:\s*0 1 auto/.test(nav[0]), 'the nav cannot shrink, so it squeezes the history');
  assert.ok(/max-height:\s*\d+vh/.test(nav[0]), 'the nav has no height cap');
  assert.ok(/min-height:\s*0/.test(nav[0]), 'the nav would refuse to shrink');
  // and the rail keeps two icon columns so it stays short too
  assert.ok(/body\.side-rail \.side-nav \{[^}]*grid-template-columns:\s*1fr 1fr/.test(css),
            'the rail falls back to one tall column');
  assert.ok(/body\.side-sm \.side-nav \.nv \{/.test(css), 'the narrow preset has no tighter type');
});

test('sidebar: every size label is translated', () => {
  const i18n = new Function(read('i18n.js') + '; return I18N;')();
  for (const lang of Object.keys(i18n)) {
    for (const k of ['sidebarSize', 'size_rail', 'size_sm', 'size_md', 'size_lg']) {
      assert.ok(i18n[lang][k], lang + ' is missing the i18n key "' + k + '"');
    }
  }
});

/* ═══════════ encoding integrity ═══════════ */

/* A PowerShell Get-Content / Set-Content -Encoding UTF8 round trip silently
   destroys every multi-byte character (U+FFFD). It once wiped 994 of them out
   of app.js, including every icon the UI renders. Nothing about that failure is
   visible in `node --check`, so it gets an explicit guard. */
test('no shipped file contains replacement characters from a bad encoding round trip', () => {
  const BAD = new RegExp('\uFFFD', 'g');
  // only files Olmavax actually serves or ships — not scratch scripts or this guard
  const targets = ['public', 'server', 'advanced',
                   'package.json', 'README.md', '.env.example'];
  const root = path.join(__dirname, '..');
  const files = [];
  for (const t of targets) {
    const p = path.join(root, t);
    if (!fs.existsSync(p)) continue;
    if (fs.statSync(p).isDirectory()) {
      (function walk(dir) {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
          if (e.name === 'node_modules') continue;
          const q = path.join(dir, e.name);
          if (e.isDirectory()) walk(q);
          else if (/\.(js|css|html|json|md|svg|webmanifest|txt|bat|yml|yaml)$/i.test(e.name)) files.push(q);
        }
      })(p);
    } else files.push(p);
  }
  assert.ok(files.length > 15, 'only ' + files.length + ' shipped files found to scan');
  const damaged = [];
  for (const f of files) {
    const n = (fs.readFileSync(f, 'utf8').match(BAD) || []).length;
    if (n) damaged.push(path.relative(root, f) + ' (' + n + ')');
  }
  assert.deepEqual(damaged, [], 'encoding damage in: ' + damaged.join(', '));
});

test('app.js still renders every icon and accented label the UI needs', () => {
  const js = read('app.js');
  const glyphs = {
    'markdown bullet': '•', 'em dash': '—', 'ellipsis': '…',
    'attachment': '📎', 'warning': '⚠️', 'audio': '🔊', 'image': '🖼️',
    'close': '×', 'compass': '🧭', 'auto agent': '🤖', 'edit': '✎',
    'dark theme': '🌙', 'light theme': '☀️', 'ready': '✅',
    'launch': '🚀', 'project folder': '📁', 'sketch': '✏️',
    'shift key': '⇧', 'hindi': 'हिन्दी', 'arabic': 'العربية',
    'spanish': 'Español', 'french': 'Français',
  };
  const missing = Object.entries(glyphs).filter(([, g]) => !js.includes(g)).map(([k]) => k);
  assert.deepEqual(missing, [], 'lost glyphs: ' + missing.join(', '));
});

test('the chat filename sanitiser keeps letters in every script', () => {
  const js = read('app.js');
  const i = js.indexOf(".slice(0, 60) + '.md'");
  assert.ok(i > 0, 'markdown download is gone');
  const expr = js.slice(js.lastIndexOf('a.download', i), i);
  // a literal character range is what got corrupted; a property escape cannot rot
  assert.ok(expr.includes('\\p{L}'), 'sanitiser is not Unicode-aware: ' + expr.trim());
  assert.ok(expr.includes('\\p{N}'), 'sanitiser drops digits: ' + expr.trim());
  assert.ok(expr.includes('\\p{M}'), 'sanitiser strips combining marks: ' + expr.trim());
  // behaviour check
  const clean = (t) => t.replace(/[^\p{L}\p{M}\p{N}\s'-]/gu, '_').slice(0, 60);
  assert.equal(clean('Chai & Samosa — café'), 'Chai _ Samosa _ café');
  assert.equal(clean('हिन्दी chat'), 'हिन्दी chat');
  assert.equal(clean('العربية 123'), 'العربية 123');
  assert.equal(clean('a/b:c*d'), 'a_b_c_d');
});
