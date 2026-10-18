'use strict';
/**
 * Olmavax Agent bridge.
 *
 * Olmavax Agent is the advanced Python agent that ships in `advanced/olmavax-agent`.
 * It runs as its own local HTTP service (default http://127.0.0.1:8765) so the
 * Node server never needs Python itself. Everything here degrades gracefully:
 * if Python is not installed or the sidecar is not running, `probe()` simply
 * reports `false` and the rest of the app behaves exactly as before.
 */
const DEFAULT_BASE = process.env.OLMAVAX_AGENT_URL || 'http://127.0.0.1:8765';
const TIMEOUT = Number(process.env.OLMAVAX_AGENT_TIMEOUT || 1500);

let cache = { ok: false, at: 0, info: null };
const isUp = async (base, ms) => {
  try {
    const r = await fetch(base.replace(/\/$/, '') + '/api/status', { signal: AbortSignal.timeout(ms) });
    return r.ok;
  } catch { return false; }
};

/** Cheap liveness check, memoised briefly so status polling stays snappy. */
async function probe(base = DEFAULT_BASE, { force = false } = {}) {
  if (!force && Date.now() - cache.at < 5000) return cache.ok;
  cache = { ok: await isUp(base, TIMEOUT), at: Date.now(), info: null };
  return cache.ok;
}

/** Full status payload from the sidecar (null when unreachable). */
async function status(base = DEFAULT_BASE) {
  try {
    const r = await fetch(base.replace(/\/$/, '') + '/api/status', { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

/** Turn a single reply into the same delta stream shape the browser expects. */
async function* streamChat(base, { messages, system, model }) {
  if (!(await probe(base))) throw new Error('Olmavax Agent is not running. Start it with: python sidecar.py ui');
  const last = (messages || []).filter(m => m && m.content).slice(-1)[0] || {};
  const res = await fetch(base.replace(/\/$/, '') + '/api/chat', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message: last.content || '', history: (messages || []).slice(0, -1), system, model }),
    signal: AbortSignal.timeout(120000),
  });
  if (!res.ok) throw new Error(`Olmavax Agent error ${res.status}: ${(await res.text()).slice(0, 300)}`);

  const ctype = res.headers.get('content-type') || '';
  if (!ctype.includes('text/event-stream')) {
    const j = await res.json().catch(() => ({}));
    const text = j.reply || j.response || j.answer || j.message || j.text || JSON.stringify(j);
    for (const w of String(text).split(/(\s+)/)) yield w;
    return;
  }

  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i).trim();
      buf = buf.slice(i + 2);
      for (const raw of chunk.split('\n')) {
        if (!raw.startsWith('data:')) continue;
        const body = raw.slice(5).trim();
        if (!body || body === '[DONE]') continue;
        try {
          const j = JSON.parse(body);
          const d = j.delta || j.token || j.text || (j.reply !== undefined ? j.reply : '');
          if (d) yield String(d);
        } catch { /* non-JSON keep-alive comment */ }
      }
    }
  }
}

/** Forward a tool call to the sidecar's tool runner. */
async function runTool(base, name, args) {
  const r = await fetch(base.replace(/\/$/, '') + '/api/tool', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, args }),
    signal: AbortSignal.timeout(30000),
  });
  if (!r.ok) throw new Error(`Olmavax Agent tool error ${r.status}`);
  return r.json();
}

module.exports = { DEFAULT_BASE, probe, status, streamChat, runTool };
