'use strict';
const test = require('node:test'), assert = require('node:assert'), fs = require('fs'), os = require('os'), path = require('path'), { execFileSync, execFile } = require('child_process'), run = (...a) => new Promise((ok, no) => execFile(...a, (e, o) => e ? no(e) : ok(String(o))));
const { createServer } = require('../server/server');
const { calc } = require('../server/tools');
const { route } = require('../server/agents');
const { zip, crc32 } = require('../server/zip');
const I18N = require('../public/i18n');
const { parseDDG } = require('../server/search');
const offline = require('../server/offline');
delete process.env.ANTHROPIC_API_KEY; delete process.env.OPENAI_API_KEY; process.env.OLLAMA_URL = 'http://127.0.0.1:9';
// python may not be installed (Windows without Python) — detect once and skip those checks
const hasPy = (() => { try { execFileSync(process.platform === 'win32' ? 'python' : 'python3', ['-c', 'pass'], { stdio: 'ignore' }); return true; } catch { try { execFileSync('python3', ['-c', 'pass'], { stdio: 'ignore' }); return true; } catch { return false; } } })();
const PY = process.platform === 'win32' ? 'python' : 'python3';
let srv, base;
const chat = async (content, extra = {}) => {
  const r = await fetch(base + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ messages: [{ role: 'user', content }], ...extra }) });
  const t = await r.text(); const ev = t.split('\n\n').filter(x => x.startsWith('data:')).map(x => JSON.parse(x.slice(5)));
  return { ev, text: ev.map(e => e.delta || '').join(''), r };
};
test.before(async () => { srv = createServer({ dataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'olmavax-')) }); await new Promise(r => srv.listen(0, '127.0.0.1', r)); base = 'http://127.0.0.1:' + srv.address().port; });
test.after(() => srv.close());

test('status lists agents and providers', async () => { const j = await (await fetch(base + '/api/status')).json(); assert.ok(j.agents.length >= 8); assert.equal(j.providers.anthropic, false); assert.ok(j.buildTypes.includes('presentation')); });
test('static UI served + PWA files', async () => { for (const f of ['/', '/app.js', '/style.css', '/i18n.js', '/sw.js', '/manifest.webmanifest']) assert.equal((await fetch(base + f)).status, 200, f); assert.equal((await fetch(base + '/..%2fserver/server.js')).status === 200, false); });
test('chat streams (offline brain) and auto-routes agents', async () => {
  const a = await chat('15% of 2500'); assert.match(a.text, /375/); assert.ok(a.ev.at(-1).done);
  const b = await chat('please debug this python code'); assert.ok(b.text.length > 20); assert.equal(b.ev.find(e => e.agent).agent, 'coder'); assert.ok(b.ev.at(-1).done);
  assert.equal(route('make a presentation deck').id, 'presenter'); assert.equal(route('hello').id, 'general');
  assert.equal((await chat('hi', { agent: 'tutor' })).ev.find(e => e.agent).agent, 'tutor');
});
test('offline provider unreachable reports error, not crash', async () => { const a = await chat('hi', { provider: 'ollama' }); assert.ok(a.ev.some(e => e.error)); assert.ok(a.ev.at(-1).done); });
test('missing key gives clear error', async () => { const a = await chat('hi', { provider: 'anthropic' }); assert.match(a.ev.find(e => e.error).error, /API key/); });
test('calculator + slash tools', async () => { assert.equal(calc('2^10'), 1024); assert.throws(() => calc('process.exit()')); assert.match((await chat('/calc 12*(3+4)')).text, /= 84/); assert.match((await chat('/help')).text, /commands/); assert.match((await chat('/time')).text, /20\d\d/); assert.match((await chat('/fetch http://localhost:1')).text, /blocked/); });
test('memory: learn, add, list, delete, injected in prompt', async () => {
  await chat('my name is Rahul.'); await chat('/remember likes Python');
  let f = (await (await fetch(base + '/api/memory')).json()).facts; assert.ok(f.some(x => /Rahul/.test(x.text)) && f.some(x => /Python/.test(x.text)));
  await fetch(base + '/api/memory?id=' + f[0].id, { method: 'DELETE' }); const g = (await (await fetch(base + '/api/memory')).json()).facts; assert.equal(g.length, f.length - 1);
  await chat('mera naam Amit hai'); assert.ok((await (await fetch(base + '/api/memory')).json()).facts.some(x => /Amit/.test(x.text)));
});
test('build every type + valid ZIP download', async () => {
  for (const type of ['website', 'app', 'presentation', 'portfolio', 'article']) {
    const j = await (await fetch(base + '/api/build', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type, prompt: 'a bakery in Patna' }) })).json();
    assert.ok(j.files.length >= 2, type); assert.equal(j.mode, 'template');
    const z = Buffer.from(await (await fetch(base + '/api/download/' + j.id)).arrayBuffer()); assert.equal(z.readUInt32LE(0), 0x04034b50);
    const f = path.join(os.tmpdir(), `t-${type}.zip`); fs.writeFileSync(f, z);
    // verify ZIP central directory in pure JS (no python needed)
    assert.equal(z.readUInt32LE(0), 0x04034b50);
    const eocd = z.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
    assert.ok(eocd > 0, 'EOCD record missing for ' + type);
    assert.equal(z.readUInt16LE(eocd + 10), z.readUInt16LE(eocd + 8), 'entry count mismatch');
    assert.ok(z.readUInt16LE(eocd + 8) >= 2);
    if (hasPy) execFileSync(PY, ['-c', 'import zipfile,sys;z=zipfile.ZipFile(sys.argv[1]);assert z.testzip() is None;assert len(z.namelist())>=2', f]);
  }
  assert.equal((await fetch(base + '/api/build', { method: 'POST', body: JSON.stringify({ type: 'nope', prompt: 'x' }) })).status, 400);
});
test('zip crc32 known value', () => { assert.equal(crc32(Buffer.from('123456789')), 0xCBF43926); assert.ok(zip([{ name: 'a', data: 'b' }]).length > 30); });
test('i18n: every language has every key', () => { const keys = Object.keys(I18N.en); for (const [l, d] of Object.entries(I18N)) assert.deepEqual(Object.keys(d).sort(), keys.slice().sort(), l); });
test('bad JSON handled', async () => { assert.equal((await fetch(base + '/api/chat', { method: 'POST', body: '{bad' })).status, 400); });
test('python CLI works end-to-end', { skip: hasPy ? false : 'python not installed' }, async () => {
  const out = await run(PY, [path.join(__dirname, '../python/olmavax_cli.py'), '--url', base, 'chat', 'hello there']); assert.ok(out.length > 20);
  const z = path.join(os.tmpdir(), 'cli.zip'); await run(PY, [path.join(__dirname, '../python/olmavax_cli.py'), '--url', base, 'build', 'website', 'test site', '-o', z]); assert.ok(fs.statSync(z).size > 200);
});
test('extension manifest valid', () => { const m = JSON.parse(fs.readFileSync(path.join(__dirname, '../extension/manifest.json'))); assert.equal(m.manifest_version, 3); for (const f of ['background.js', 'popup.html', 'popup.js']) assert.ok(fs.existsSync(path.join(__dirname, '../extension', f))); });

test('image mode returns an image (demo SVG)', async () => { const a = await chat('a red fox', { mode: 'image' }); const im = a.ev.find(e => e.image); assert.ok(im && im.image.mime === 'image/svg+xml'); assert.match(Buffer.from(im.image.data, 'base64').toString(), /<svg/); });
test('image attachments reach the provider; invalid ones are dropped', async () => {
  const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  const r = await fetch(base + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ messages: [{ role: 'user', content: 'what is this?', images: [{ mime: 'image/png', data: png }, { mime: 'text/html', data: 'x' }] }] }) });
  const txt = (await r.text()).split('\n\n').filter(x => x.startsWith('data:')).map(x => JSON.parse(x.slice(5)).delta || '').join(''); assert.match(txt, /1 image mila/);
});
test('web search parser + graceful offline fallback', async () => {
  const html = '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=1">Example <b>A</b></a><a class="result__snippet" href="x">Snippet &amp; text</a><a class="result__a" href="https://b.org/">B</a>';
  const r = parseDDG(html); assert.equal(r.length, 2); assert.equal(r[0].url, 'https://example.com/a'); assert.equal(r[0].title, 'Example A'); assert.equal(r[0].snippet, 'Snippet & text');
  const a = await chat('latest news', { mode: 'search' }); assert.ok(a.ev.at(-1).done); assert.ok(a.text.length > 20);
});
test('think / voice / project instructions accepted', async () => { const a = await chat('hi', { think: true, voice: true, instructions: 'Be brief' }); assert.ok(a.ev.at(-1).done && !a.ev.some(e => e.error)); });
test('offline brain: maths, conversions, generators, tools (no API key)', async () => {
  const fakeMem = { facts: [], list() { return this.facts; }, add(t) { const f = { id: 'x', text: t }; this.facts.push(f); return f; }, remove() { return true; }, save() {} };
  const say = q => offline.reply(q, fakeMem);

  // maths
  assert.match(say('15% of 2500'), /375/);
  assert.match(say('sqrt(144)'), /12/);
  assert.match(say('2^10'), /1024/);
  assert.match(say('half of 98'), /49/);
  assert.match(say('12 * (3+4)'), /84/);

  // conversions
  assert.match(say('5 km in miles'), /3\.1|3\.10/);
  assert.match(say('10 kg in pounds'), /22\.0/);
  assert.match(say('72f in celsius'), /22\.2/);
  assert.match(say('100 c in f'), /212/);
  assert.match(say('3 feet to cm'), /91\.44/);

  // time
  assert.match(say('what time is it'), /\d{1,2}:\d{2}/);

  // generators
  assert.match(say('generate password 20'), /20-char/);
  assert.match(say('uuid'), /[0-9a-f]{8}-[0-9a-f]{4}/);
  assert.match(say('random color'), /#[0-9a-f]{6}/);

  // memory + identity + help
  assert.match(say('who are you'), /Olmavax/);
  assert.match(say('what can you do'), /Maths/i);
  assert.match(say('count words in: hello world test'), /Words/);

  // new slash commands through the tools layer
  const tl = require('../server/tools');
  assert.match(await tl.runSlash('/convert 5 km in miles', fakeMem), /mi/);
  assert.match(await tl.runSlash('/password 24', fakeMem), /24-char/);
  assert.match(await tl.runSlash('/uuid', fakeMem), /[0-9a-f]{8}-/);
  assert.match(await tl.runSlash('/stats hello brave world', fakeMem), /Words: 3/);
  assert.match(await tl.runSlash('/help', fakeMem), /\/convert/);
  assert.match(await tl.runSlash('/clear', fakeMem), /cleared/);
});

test('status reports live engine (offline brain when no key)', async () => {
  const r = await fetch(base + '/api/status', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ keys: {} }) });
  const j = await r.json();
  assert.equal(j.name, 'Olmavax A.I');
  assert.ok(['mock', 'ollama'].includes(j.live), 'live engine: ' + j.live);
});

test('frontend: JS parses and every referenced DOM id exists', () => {
  const pub = path.join(__dirname, '../public'); for (const f of ['app.js', 'sw.js', 'i18n.js']) execFileSync(process.execPath, ['--check', path.join(pub, f)]);
  const js = fs.readFileSync(path.join(pub, 'app.js'), 'utf8'), html = fs.readFileSync(path.join(pub, 'index.html'), 'utf8');
  const used = new Set([...js.matchAll(/\$\('#([\w-]+)'\)/g)].map(m => m[1])), have = new Set([...html.matchAll(/id="([\w-]+)"/g)].map(m => m[1]));
  const dyn = new Set(['px', 'cx', 'cv', 'cc', 'ca', 'nf', 'af', 'bt', 'bp', 'bg', 'bo', 'pn', 'pi', 'pc', 'k0', 'k1', 'k2', 'k3', 'k4', 'k5', 'ks', 'engTxt', 'engFix',
    'kSave', 'kAgent', 'kTheme', 'kLang', 'kFs', 'kRate', 'kModel', 'kEnter', 'kExport', 'kImport', 'kClear', 'ver', 'scrollEnd',
    // panels rendered into #mbody at runtime
    'psearch', 'prun', 'pinput', 'pout', 'cxCode', 'cxLang', 'cxName', 'cxPrev', 'cxSave', 'cxDet', 'sadd', 'sp', 'sw']);
  assert.deepEqual([...used].filter(x => !have.has(x) && !dyn.has(x)), []);
});
