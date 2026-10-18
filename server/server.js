'use strict';
const http = require('http'), fs = require('fs'), path = require('path');
const { pickProvider, streamChat, providerStatus } = require('./providers');
const { AGENTS, route } = require('./agents');
const tools = require('./tools');
const Memory = require('./memory');
const { build, types } = require('./builders');
const { webContext } = require('./search');
const { makeImage } = require('./image');
const { zip } = require('./zip');
const charvis = require('./charvis');
const { MODELS, PROVIDER_NAME } = require('./models');
const { Store } = require('./collections');
const plugins = require('./plugins');
const EXPLORE = require('./explore');
const { renderPDF } = require('./pdf');
const scheduler = require('./scheduler');

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpeg': 'image/jpeg', '.jpg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp' };
const LANGNAMES = { en: 'English', hi: 'Hindi', es: 'Spanish', fr: 'French', ar: 'Arabic' };
const APP_NAME = 'Olmavax A.I';
const APP_VERSION = '3.0.0';

/* ===== Security: simple in-memory rate limit (per IP) + security headers ===== */
const RATE = { windowMs: 60_000, max: 90 }; // 90 req / min
const hits = new Map();
function rateLimit(ip) {
  const now = Date.now();
  let e = hits.get(ip);
  if (!e || now - e.t > RATE.windowMs) { e = { t: now, n: 0 }; hits.set(ip, e); }
  e.n++;
  if (hits.size > 5000) { // cleanup
    for (const [k, v] of hits) if (now - v.t > RATE.windowMs) hits.delete(k);
  }
  return e.n > RATE.max;
}
function secHeaders(res) {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'SAMEORIGIN');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.setHeader('Permissions-Policy', 'microphone=(self), camera=(), geolocation=()');
  res.setHeader('X-Olmavax-Security', 'local-first');
}


function createServer({ dataDir } = {}) {
  const DIR = dataDir || process.env.OLMAVAX_DATA || path.join(__dirname, '..', 'data');
  const mem = new Memory(DIR);
  const store = new Store(DIR);
  const builds = new Map();
  const PUB = path.join(__dirname, '..', 'public');
  const json = (res, code, obj) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj)); };
  const readBody = req => new Promise((ok, bad) => {
    let b = ''; req.on('data', c => { b += c; if (b.length > 25e6) { req.destroy(); bad(new Error('Body too large')); } });
    req.on('end', () => { try { ok(b ? JSON.parse(b) : {}); } catch (e) { bad(new Error('Invalid JSON')); } });
  });

  async function chat(req, res) {
    const b = await readBody(req);
    const raw = (b.messages || []).filter(m => m && typeof m.content === 'string' && m.content && ['user', 'assistant'].includes(m.role)).slice(-40);
    const msgs = raw.map((m, i) => { const o = { role: m.role, content: m.content }; if (i === raw.length - 1 && m.role === 'user' && Array.isArray(m.images)) o.images = m.images.filter(x => x && /^image\/(png|jpeg|webp|gif)$/.test(x.mime) && typeof x.data === 'string').slice(0, 4); return o; });
    const last = msgs.length ? msgs[msgs.length - 1].content : '';
    if (!last) return json(res, 400, { error: 'No message' });
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
    let closed = false; res.on('close', () => { closed = true; });
    const send = o => { if (!closed) res.write('data: ' + JSON.stringify(o) + '\n\n'); };
    const learned = mem.learn(last); if (learned.length) send({ learned });
    try {
      if (last.startsWith('/')) { send({ agent: 'tools', provider: 'tools' }); send({ delta: await tools.runSlash(last, mem) }); }
      else {
        const agent = b.agent && b.agent !== 'auto' && AGENTS[b.agent] ? AGENTS[b.agent] : route(last);
        const provider = await pickProvider(b.provider, b.keys || {});
        send({ agent: agent.id, provider: provider.name });
        if (b.mode === 'image') { send({ image: await makeImage(last, provider, b, agent) }); send({ delta: '\u{1F5BC}\u{FE0F} ' }); }
        else {
          let web = '';
          if (b.mode === 'search' || b.mode === 'research') {
            try { const w = await webContext(b.mode, last); send({ sources: w.sources }); web = '\n\nWEB RESULTS (cite sources as [1], [2]...):\n' + w.ctx + (b.mode === 'research' ? '\n\nWrite a thorough, well-structured research report with headings, key findings, caveats and citations.' : ''); }
            catch (e) { send({ delta: `\u{26A0}\u{FE0F} Web search unavailable (${e.message}). Answering from built-in knowledge.\n\n` }); }
          }
          const lang = LANGNAMES[b.lang] ? `\nThe user's interface language is ${LANGNAMES[b.lang]}; prefer it unless they write in another.` : '';
          const proj = b.instructions ? '\n\nProject instructions:\n' + String(b.instructions).slice(0, 2000) : '';
          const think = b.think ? '\nThink step by step carefully and double-check your reasoning before giving a clear final answer.' : '';
          const voice = b.voice ? '\nThis is a spoken voice conversation: answer briefly in natural spoken sentences. No markdown, no lists, no code.' : '';
          for await (const d of streamChat(provider, { messages: msgs, system: agent.system + mem.prompt() + lang + proj + think + voice + web, model: b.model, agent, mem })) { if (closed) break; send({ delta: d }); }
        }
      }
    } catch (e) { send({ error: e.message }); }
    send({ done: true }); res.end();
  }

  const handler = async (req, res) => {
    secHeaders(res);
    const ip = req.socket.remoteAddress || 'local';
    if (rateLimit(ip) && req.url.startsWith('/api/')) {
      res.writeHead(429, { 'content-type': 'application/json', 'retry-after': '60' });
      return res.end(JSON.stringify({ error: 'Too many requests. Please wait a moment.' }));
    }
    const url = new URL(req.url, 'http://x'), p = url.pathname;
    if (p === '/api/status') {
      let keys = {};
      if (req.method === 'POST') { try { keys = (await readBody(req)).keys || {}; } catch {} }
      const prov = await providerStatus(keys);
      prov.charvis = await charvis.probe();
      let live = prov.anthropic ? 'anthropic' : prov.openai ? 'openai' : prov.ollama ? 'ollama' : 'mock';
      return json(res, 200, {
        name: APP_NAME, version: APP_VERSION, providers: prov, live,
        charvis: { available: prov.charvis, url: charvis.DEFAULT_BASE, path: path.join(__dirname, '..', 'advanced', 'OpenCharvis') },
        providerNames: PROVIDER_NAME,
        models: MODELS,
        agents: Object.values(AGENTS).map(({ id, name, icon }) => ({ id, name, icon })),
        buildTypes: types,
      });
    }
    if (p === '/api/chat' && req.method === 'POST') return chat(req, res);
    if (p === '/api/memory') {
      if (req.method === 'GET') return json(res, 200, { facts: mem.list() });
      if (req.method === 'POST') { const f = mem.add((await readBody(req)).text); return f ? json(res, 200, f) : json(res, 400, { error: 'Empty' }); }
      if (req.method === 'DELETE') return json(res, 200, { removed: mem.remove(url.searchParams.get('id')) });
    }
    if (p === '/api/tool' && req.method === 'POST') { const b = await readBody(req); return json(res, 200, { result: await tools.runSlash('/' + b.name + ' ' + (b.args || ''), mem) }); }
    if (p === '/api/build' && req.method === 'POST') {
      const b = await readBody(req);
      const provider = await pickProvider(b.provider, b.keys || {});
      const out = await build(b.type, b.prompt, { provider, agent: AGENTS.app, model: b.model });
      const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      builds.set(id, out.files); if (builds.size > 30) builds.delete(builds.keys().next().value);
      return json(res, 200, { id, mode: out.mode, provider: provider.name, files: out.files });
    }
    const dl = p.match(/^\/api\/download\/([\w-]+)$/);
    if (dl) {
      const files = builds.get(dl[1]); if (!files) return json(res, 404, { error: 'Build expired' });
      res.writeHead(200, { 'content-type': 'application/zip', 'content-disposition': `attachment; filename="olmavax-build-${dl[1]}.zip"` });
      return res.end(zip(files.map(f => ({ name: f.name, data: f.content }))));
    }

    /* ── Explore catalogue ── */
    if (p === '/api/explore') {
      const cat = url.searchParams.get('cat');
      const list = cat && cat !== 'all' ? EXPLORE.PROMPTS.filter(x => x.cat === cat) : EXPLORE.PROMPTS;
      return json(res, 200, { categories: EXPLORE.categories, prompts: list, agents: EXPLORE.AGENTS });
    }

    /* ── Plugin registry ── */
    if (p === '/api/plugins') {
      if (req.method === 'GET') {
        const state = new Map(store.all('plugins').map(x => [x.id, x]));
        return json(res, 200, {
          plugins: plugins.PLUGINS.map(pl => {
            const s = state.get(pl.id);
            return Object.assign(plugins.meta(pl), { enabled: s ? s.enabled !== false : true });
          }),
        });
      }
      if (req.method === 'POST') {
        const b = await readBody(req);
        const pl = plugins.byId(b.id);
        if (!pl) return json(res, 404, { error: 'Unknown plugin' });
        const rec = store.get('plugins', pl.id) || store.add('plugins', { id: pl.id, enabled: true, settings: {} });
        const enabled = b.enabled !== undefined ? !!b.enabled : rec.enabled !== false;
        store.update('plugins', pl.id, { enabled });
        return json(res, 200, { id: pl.id, enabled });
      }
    }
    const plRun = p.match(/^\/api\/plugins\/([\w-]+)\/run$/);
    if (plRun && req.method === 'POST') {
      const pl = plugins.byId(plRun[1]);
      if (!pl) return json(res, 404, { error: 'Unknown plugin' });
      const rec = store.get('plugins', pl.id);
      if (rec && rec.enabled === false) return json(res, 400, { error: pl.name + ' is disabled' });
      try {
        return json(res, 200, { id: pl.id, name: pl.name, result: String(pl.run((await readBody(req)).input || '')) });
      } catch (e) {
        return json(res, 400, { error: pl.name + ' failed: ' + e.message });
      }
    }

    /* ── Generic collections: library / schedule / workspace ── */
    const coll = p.match(/^\/api\/(library|schedule|workspace)$/);
    if (coll) {
      const name = coll[1];
      if (req.method === 'GET') {
        const q = (url.searchParams.get('q') || '').toLowerCase();
        let items = store.all(name);
        if (q) items = items.filter(x => JSON.stringify(x).toLowerCase().includes(q));
        return json(res, 200, { items: items.slice(0, 500) });
      }
      if (req.method === 'POST') {
        const b = await readBody(req);
        if (name === 'schedule') {
          const prompt = String(b.prompt || '').trim();
          if (!prompt) return json(res, 400, { error: 'Prompt is required' });
          const at = Number(b.at);
          if (!Number.isFinite(at) || at < 0) return json(res, 400, { error: 'Invalid time' });
          b.at = at;
        }
        const rec = store.add(name, b);
        return json(res, 200, rec);
      }
      if (req.method === 'PATCH') {
        const b = await readBody(req);
        const rec = store.update(name, b.id, b);
        return rec ? json(res, 200, rec) : json(res, 404, { error: 'Not found' });
      }
      if (req.method === 'DELETE') {
        const id = url.searchParams.get('id');
        if (id === 'all') { store.clear(name); return json(res, 200, { cleared: true }); }
        return json(res, 200, { removed: store.remove(name, id) });
      }
    }

    /* ── Export a conversation as PDF ── */
    if (p === '/api/export/pdf' && req.method === 'POST') {
      const b = await readBody(req);
      const msgs = Array.isArray(b.messages) ? b.messages.slice(0, 400) : [];
      const blocks = [];
      for (const m of msgs) {
        if (!m || typeof m.content !== 'string') continue;
        blocks.push({ text: (m.role === 'user' ? 'You' : 'Olmavax') , bold: true, gap: 14 });
        // strip markdown noise so the PDF reads cleanly
        const body = m.content
          .replace(/```([\w]*)\n?/g, '\n$1\n')
          .replace(/[*_`#>]/g, '')
          .replace(/\n{3,}/g, '\n\n');
        blocks.push({ text: body, mono: /^[\s\S]*\n(js|python|html|css|json|bash|sql|go|rust|java|c|cpp|csharp|php|ruby|swift|kotlin)\n/i.test(body) });
      }
      const pdf = renderPDF({ title: String(b.title || 'Olmavax chat').slice(0, 120), blocks });
      res.writeHead(200, {
        'content-type': 'application/pdf',
        'content-disposition': 'attachment; filename="olmavax-' + Date.now().toString(36) + '.pdf"',
        'content-length': pdf.length,
      });
      return res.end(pdf);
    }

    if (p.startsWith('/api/')) return json(res, 404, { error: 'Not found' });
    let rel = decodeURIComponent(p === '/' ? '/index.html' : p);
    const file = path.normalize(path.join(PUB, rel));
    if (!file.startsWith(PUB)) return json(res, 403, { error: 'Forbidden' });
    fs.readFile(file, (err, data) => {
      if (err) return json(res, 404, { error: 'Not found' });
      res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }); res.end(data);
    });
  };
  return http.createServer((req, res) => {
    res.setHeader('access-control-allow-origin', '*'); res.setHeader('access-control-allow-headers', 'content-type'); res.setHeader('access-control-allow-methods', 'GET,POST,DELETE,OPTIONS');
    if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
    handler(req, res).catch(e => { if (!res.headersSent) json(res, 400, { error: e.message }); else res.end(); });
  });
}
module.exports = { createServer };
if (require.main === module) {
  const port = +process.env.PORT || 8787, host = process.env.HOST || '127.0.0.1';
  const dir = process.env.OLMAVAX_DATA || path.join(__dirname, '..', 'data');
  const srv = createServer();
  srv.scheduled = scheduler.start({ store: new (require('./collections').Store)(dir) });
  srv.listen(port, host, () => console.log(`\n  ${APP_NAME} v${APP_VERSION} running \u2192 http://${host === '0.0.0.0' ? 'localhost' : host}:${port}\n`));
}