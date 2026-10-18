'use strict';
/* Final end-to-end sweep of the v3 UI over the real server. */
const { createServer } = require('../server/server');
const fs = require('fs'), os = require('os'), path = require('path');

const srv = createServer({ dataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'olma3e-')) });
let pass = 0, fail = 0;
const ok = (c, m) => { c ? (pass++, console.log('  ok   ' + m)) : (fail++, console.log('  FAIL ' + m)); };

srv.listen(0, '127.0.0.1', async () => {
  const base = 'http://127.0.0.1:' + srv.address().port;
  const H = { 'content-type': 'application/json' };
  const J = async (u, o) => { const r = await fetch(base + u, o); return { s: r.status, j: await r.json().catch(() => null) }; };
  const pub = path.join(__dirname, '..', 'public');

  console.log('── static assets ──');
  for (const f of ['/', '/app.js', '/style.css', '/i18n.js', '/highlight.js', '/sw.js',
                   '/logo.svg', '/logo-mark.svg', '/manifest.webmanifest']) {
    const r = await fetch(base + f);
    ok(r.ok, f + ' → ' + r.status);
  }
  const logo = await (await fetch(base + '/logo.svg')).text();
  ok(logo.startsWith('<svg') && logo.includes('</svg>'), 'logo.svg is well-formed');
  const mark = await (await fetch(base + '/logo-mark.svg')).text();
  ok(mark.startsWith('<svg'), 'logo-mark.svg is well-formed');
  ok(!(await (await fetch(base + '/style.css')).text()).includes('OLMA%20PAGE'), 'no stale jpeg logo references in css');
  const html = await (await fetch(base + '/')).text();
  ok(!html.includes('assets/OLMA'), 'no stale jpeg logo references in html');
  ok(html.includes('logo-mark.svg') && html.includes('highlight.js'), 'new assets wired into the shell');

  console.log('\n── frontend integrity ──');
  const app = fs.readFileSync(path.join(pub, 'app.js'), 'utf8');
  for (const fn of ['md', 'inlineMd', 'safeSvg', 'openPanel',
                    'pluginsPanel', 'codexPanel', 'explorePanel',
                    'libraryPanel', 'scheduledPanel', 'imagesPanel',
                    'agentPanel', 'exportPDF', 'setSpace', 'api']) {
    const decl = new RegExp('(function\\s+' + fn + '\\b|(?:const|let|var)\\s+' + fn + '\\s*=)');
    ok(decl.test(app), 'defined: ' + fn);
  }
  for (const nav of ['images', 'scheduled', 'library', 'plugins', 'codex', 'explore', 'projects', 'memory', 'build', 'agents']) {
    ok(html.includes('data-nav="' + nav + '"'), 'nav entry: ' + nav);
  }
  const i18n = require('../public/i18n');
  const used = [...html.matchAll(/data-i="(\w+)"/g)].map(m => m[1]);
  const unresolved = [...new Set(used)].filter(k => !(k in i18n.en));
  ok(unresolved.length === 0, 'every data-i resolves · ' + Object.keys(i18n.en).length + ' keys');
  for (const l of Object.keys(i18n)) {
    ok(Object.keys(i18n.en).every(k => k in i18n[l]), 'i18n complete: ' + l);
  }

  console.log('\n── new endpoints ──');
  const eps = [['/api/explore', 200], ['/api/plugins', 200], ['/api/library', 200],
               ['/api/schedule', 200], ['/api/workspace', 200]];
  for (const [e, want] of eps) ok((await J(e)).s === want, 'GET ' + e);

  console.log('\n── pdf round trip ──');
  const pdf = await fetch(base + '/api/export/pdf', { method: 'POST', headers: H, body: JSON.stringify({
    title: 'Olmavax — “test”', messages: [
      { role: 'user', content: 'unicode: café — naïve — 你好' },
      { role: 'assistant', content: 'x'.repeat(3000) }] }) });
  const buf = Buffer.from(await pdf.arrayBuffer());
  ok(buf.slice(0, 5).toString() === '%PDF-', 'valid header');
  ok(buf.slice(-6).toString().includes('%%EOF'), 'valid trailer');
  ok(buf.length > 1200, buf.length + ' bytes (multi-page input)');

  console.log('\n── scheduler ──');
  const job = await J('/api/schedule', { method: 'POST', headers: H,
    body: JSON.stringify({ prompt: 'what is 6*7', at: Date.now() - 1000, provider: 'mock' }) });
  ok(job.s === 200, 'back-dated job accepted');
  const sched = require('../server/scheduler');
  const { Store } = require('../server/collections');
  const store = new Store(path.join(os.tmpdir(), 'sched-test-' + Date.now()));
  store.add('schedule', { prompt: 'what is 6*7', at: Date.now() - 1000, provider: 'mock' });
  const ran = await sched.tick({ store });
  ok(ran.length === 1, 'scheduler fired the due job');
  ok(/42/.test(ran[0].result.body), 'answer computed → ' + String(ran[0].result.body).slice(0, 40));
  ok(store.all('schedule').length === 0, 'one-shot job retired');
  ok(store.all('library').some(x => x.kind === 'schedule'), 'result filed into Library');

  console.log('\n' + (fail ? 'FAILURES: ' + fail : 'ALL ' + pass + ' CHECKS PASSED'));
  srv.close();
  process.exit(fail ? 1 : 0);
});
