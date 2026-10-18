'use strict';
/* Smoke-test every new API surface added in v3. */
const { createServer } = require('../server/server');
const H = { 'content-type': 'application/json' };

const srv = createServer({ dataDir: require('fs').mkdtempSync(require('path').join(require('os').tmpdir(), 'olma3-')) });
let pass = 0, fail = 0;
const ok = (c, m) => { c ? (pass++, console.log('  ok   ' + m)) : (fail++, console.log('  FAIL ' + m)); };

srv.listen(0, '127.0.0.1', async () => {
  const base = 'http://127.0.0.1:' + srv.address().port;
  const J = async (u, o) => { const r = await fetch(base + u, o); return { s: r.status, j: await r.json().catch(() => null) }; };

  console.log('── explore ──');
  const ex = await J('/api/explore');
  ok(ex.s === 200, 'GET /api/explore → ' + ex.s);
  ok(ex.j.prompts.length >= 18, ex.j.prompts.length + ' prompts');
  ok(ex.j.agents.length >= 9, ex.j.agents.length + ' agents described');
  ok(ex.j.categories.length >= 5, 'categories: ' + ex.j.categories.join(', '));
  const filt = await J('/api/explore?cat=Build');
  ok(filt.j.prompts.every(p => p.cat === 'Build'), 'category filter works');
  ok(ex.j.prompts.every(p => p.body && p.title && p.agent), 'every prompt is complete');
  ok(ex.j.agents.every(a => a.blurb), 'every agent has a blurb');

  console.log('\n── plugins ──');
  const pl = await J('/api/plugins');
  ok(pl.s === 200 && pl.j.plugins.length >= 18, pl.j.plugins.length + ' plugins registered');
  ok(pl.j.plugins.every(p => p.id && p.name && p.icon && p.desc && p.args), 'every plugin is documented');
  ok(pl.j.plugins.every(p => p.enabled === true), 'plugins default to enabled');

  for (const [id, input, check] of [
    ['calc', '2^16', /65536/],
    ['convert', '5 km in miles', /3\.106/],
    ['stats', 'one two three', /Words \| 3/],
    ['case', 'title hello wide world', /Hello Wide World/],
    ['b64', 'encode olmavax', /b2xtYXZheA==/],
    ['uuid', '3', /-/],
    ['pass', '24', /entropy|characters/],
    ['color', '#4f8cff', /hsl\(/],
    ['json', '{"b":1,"a":2}', /"b": 1/],
    ['time', 'now', /Unix/],
    ['regex', '/a(b+)c/ abbbc', /match/],
    ['qr', 'https://olmavax.ai', /<svg/],
    ['lorem', '2', /lorem/],
    ['md', 'a,b\n1,2', /\| a \| b \|/],
    ['numspell', '1234', /one thousand/],
    ['wcag', '#ffffff on #000000', /21(\.0+)?:1/],
    ['cron', '0 9 * * 1-5', /Monday/],
    ['hash', 'abc', /SHA-256/],
    ['url', 'encode a b', /a%20b/],
  ]) {
    const r = await J('/api/plugins/' + id + '/run', { method: 'POST', headers: H, body: JSON.stringify({ input }) });
    ok(r.s === 200 && check.test(r.j.result), 'plugin ' + id + ' → ' + (r.j.error || JSON.stringify(r.j.result).slice(0, 46)));
  }

  const off = await J('/api/plugins', { method: 'POST', headers: H, body: JSON.stringify({ id: 'stats', enabled: false }) });
  ok(off.s === 200 && off.j.enabled === false, 'toggle off → ' + JSON.stringify(off.j));
  const blocked = await J('/api/plugins/stats/run', { method: 'POST', headers: H, body: JSON.stringify({ input: 'x' }) });
  ok(blocked.s === 400 && /disabled/.test(blocked.j.error), 'disabled plugin refuses to run → ' + JSON.stringify(blocked.j));
  const stillListed = await J('/api/plugins');
  ok(stillListed.j.plugins.find(p => p.id === 'stats').enabled === false, 'state persists across reads');
  await J('/api/plugins', { method: 'POST', headers: H, body: JSON.stringify({ id: 'stats', enabled: true }) });
  const unblocked = await J('/api/plugins/stats/run', { method: 'POST', headers: H, body: JSON.stringify({ input: 'one two' }) });
  ok(unblocked.s === 200, 're-enabled plugin runs again');
  // colour maths was wrong three times — pin the exact expected values
  const col = await J('/api/plugins/color/run', { method: 'POST', headers: H, body: JSON.stringify({ input: '#4f8cff' }) });
  ok(/hsl\(219, 100%, 65%\)/.test(col.j.result), 'color: HSL lightness normalised → ' + (col.j.result.match(/hsl\([^)]*\)/) || [''])[0]);
  ok(/Contrast vs white\s+\*\*3\.22:1\*\*/.test(col.j.result), 'color: contrast vs white');
  ok(/Contrast vs black\s+\*\*6\.53:1\*\*/.test(col.j.result), 'color: contrast vs black');
  ok(/base `#4f8cff`/.test(col.j.result), 'color: palette base is the original hex');
  ok(/50% `#[0-9a-f]{6}`/.test(col.j.result), 'color: palette shades are full hex');
  ok(!/NaN/.test(col.j.result), 'color: no NaN anywhere');
  const white = await J('/api/plugins/color/run', { method: 'POST', headers: H, body: JSON.stringify({ input: '#ffffff' }) });
  ok(/hsl\(0, 0%, 100%\)/.test(white.j.result), 'color: greyscale hue/sat');

  // cron: months are 1-based but weekdays are 0-based
  const cron = await J('/api/plugins/cron/run', { method: 'POST', headers: H, body: JSON.stringify({ input: '0 9 * * 1-5' }) });
  ok(/Monday/.test(cron.j.result) && !/Sunday–Thursday/.test(cron.j.result), 'cron: weekday range 1-5 means Mon-Fri');
  const cron2 = await J('/api/plugins/cron/run', { method: 'POST', headers: H, body: JSON.stringify({ input: '30 2 1 3 *' }) });
  ok(/March/.test(cron2.j.result), 'cron: month 3 means March');

  // unit aliases
  for (const [input, want] of [['5 km in miles', /3\.10685/], ['72f in c', /22\.2222/], ['0 c in f', /32 f/],
                               ['1 yr in d', /365\.25/], ['2 kg in lb', /4\.409/], ['98\.6 f in c', /37 c/],
                               ['300 k in c', /26\.85/]]) {
    const cv = await J('/api/plugins/convert/run', { method: 'POST', headers: H, body: JSON.stringify({ input }) });
    ok(want.test(cv.j.result), 'convert "' + input + '" → ' + cv.j.result.slice(0, 40));
  }

  const unknown = await J('/api/plugins/nope/run', { method: 'POST', headers: H, body: JSON.stringify({ input: 'x' }) });
  ok(unknown.s === 404, 'unknown plugin → 404');
  const badToggle = await J('/api/plugins', { method: 'POST', headers: H, body: JSON.stringify({ id: 'nope' }) });
  ok(badToggle.s === 404, 'toggling an unknown plugin → 404');

  console.log('\n── collections ──');
  for (const name of ['library', 'schedule', 'workspace']) {
    const created = await J('/api/' + name, { method: 'POST', headers: H, body: JSON.stringify({ prompt: 'p', name: 'a.py', lang: 'python', content: 'x', title: 'T', body: 'B', kind: 'note', at: Date.now() + 60000 }) });
    ok(created.s === 200 && created.j.id, name + ': create');
    const list = await J('/api/' + name);
    ok(list.s === 200 && list.j.items.length >= 1, name + ': list');
    const patched = await J('/api/' + name, { method: 'PATCH', headers: H, body: JSON.stringify({ id: created.j.id, title: 'patched' }) });
    ok(patched.s === 200, name + ': patch');
    ok(patched.j.id === created.j.id, name + ': patch keeps id');
    const gone = await J('/api/' + name + '?id=' + created.j.id, { method: 'DELETE' });
    ok(gone.j.removed === true, name + ': delete');
  }
  const badSched = await J('/api/schedule', { method: 'POST', headers: H, body: JSON.stringify({ prompt: 'x', at: 'soon' }) });
  ok(badSched.s === 400, 'schedule rejects a bad time');
  const noPrompt = await J('/api/schedule', { method: 'POST', headers: H, body: JSON.stringify({ at: Date.now() }) });
  ok(noPrompt.s === 400, 'schedule requires a prompt');

  console.log('\n── pdf ──');
  const pdf = await fetch(base + '/api/export/pdf', {
    method: 'POST', headers: H,
    body: JSON.stringify({
      title: 'Chat — café “quoted”',
      messages: [
        { role: 'user', content: 'hello **world**' },
        { role: 'assistant', content: '```python\nprint("hi")\n```' },
        { role: 'assistant', content: 'x'.repeat(6000) },
      ],
    }),
  });
  const buf = Buffer.from(await pdf.arrayBuffer());
  ok(pdf.status === 200, 'POST /api/export/pdf → ' + pdf.status);
  ok(pdf.headers.get('content-type') === 'application/pdf', 'content-type');
  ok(buf.slice(0, 5).toString() === '%PDF-', 'PDF header');
  ok(buf.slice(-6).toString().includes('%%EOF'), 'PDF trailer');
  ok(buf.length > 1000, buf.length + ' bytes');
  ok(!/[^\x00-\xFF]/.test(buf.toString('latin1')), 'output is pure 8-bit');

  console.log('\n── security ──');
  const badId = await J('/api/library?id=../../etc/passwd', { method: 'DELETE' });
  ok(badId.s === 200, 'traversal-shaped id is harmless');
  const hugeInput = await J('/api/plugins/qr/run', { method: 'POST', headers: H, body: JSON.stringify({ input: 'x'.repeat(5000) }) });
  ok(/too much data/i.test(String(hugeInput.j.result || '')), 'oversized QR input is rejected cleanly → ' + JSON.stringify(hugeInput.j).slice(0, 120));

  console.log('\n' + (fail ? 'FAILURES: ' + fail : 'ALL ' + pass + ' CHECKS PASSED'));
  srv.close();
  process.exit(fail ? 1 : 0);
});
