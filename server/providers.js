'use strict';
// Multi-provider streaming: Anthropic, OpenAI (+any OpenAI-compatible), Ollama (offline), and a built-in offline brain.
const sleep = ms => new Promise(r => setTimeout(r, ms));
const offline = require('./offline');
const sidecar = require('./olmavax-agent');
async function* lines(res) {
  const reader = res.body.getReader(), dec = new TextDecoder(); let buf = '';
  for (;;) {
    const { done, value } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true }); let i;
    while ((i = buf.indexOf('\n')) >= 0) { const l = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (l) yield l; }
  }
  if (buf.trim()) yield buf.trim();
}
const toA = m => m.images && m.images.length ? { role: m.role, content: [...m.images.map(i => ({ type: 'image', source: { type: 'base64', media_type: i.mime, data: i.data } })), { type: 'text', text: m.content }] } : { role: m.role, content: m.content };
const toO = m => m.images && m.images.length ? { role: m.role, content: [{ type: 'text', text: m.content }, ...m.images.map(i => ({ type: 'image_url', image_url: { url: `data:${i.mime};base64,${i.data}` } }))] } : { role: m.role, content: m.content };
const toL = m => m.images && m.images.length ? { role: m.role, content: m.content, images: m.images.map(i => i.data) } : { role: m.role, content: m.content };
async function fail(name, res) { throw new Error(`${name} error ${res.status}: ${(await res.text()).slice(0, 300)}`); }

async function* anthropic(p, { messages, system, model }) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST', headers: { 'content-type': 'application/json', 'x-api-key': p.apiKey, 'anthropic-version': '2023-06-01' },
    body: JSON.stringify({ model: model || process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-20250514', max_tokens: 4096, stream: true, system, messages: messages.map(toA) }),
  });
  if (!res.ok) await fail('Anthropic', res);
  for await (const l of lines(res)) {
    if (!l.startsWith('data:')) continue;
    try { const j = JSON.parse(l.slice(5)); if (j.type === 'content_block_delta' && j.delta && j.delta.text) yield j.delta.text; } catch {}
  }
}
async function* openai(p, { messages, system, model }) {
  const res = await fetch((p.base || 'https://api.openai.com/v1').replace(/\/$/, '') + '/chat/completions', {
    method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + p.apiKey },
    body: JSON.stringify({ model: model || process.env.OPENAI_MODEL || 'gpt-4o-mini', stream: true, messages: [{ role: 'system', content: system }, ...messages.map(toO)] }),
  });
  if (!res.ok) await fail('OpenAI-compatible', res);
  for await (const l of lines(res)) {
    if (!l.startsWith('data:') || l.includes('[DONE]')) continue;
    try { const t = JSON.parse(l.slice(5)).choices[0].delta.content; if (t) yield t; } catch {}
  }
}
async function* ollama(p, { messages, system, model }) {
  const res = await fetch(p.base.replace(/\/$/, '') + '/api/chat', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ model: model || process.env.OLLAMA_MODEL || 'llama3.2', stream: true, messages: [{ role: 'system', content: system }, ...messages.map(toL)] }),
  });
  if (!res.ok) await fail('Ollama', res);
  for await (const l of lines(res)) { try { const j = JSON.parse(l); if (j.message && j.message.content) yield j.message.content; } catch {} }
}
const EMPTY_MEM = { list: () => [], add: () => null, remove: () => false, save() {}, facts: [] };
async function* mock(p, { messages, agent, mem }) {
  const lm = messages[messages.length - 1] || {}, last = lm.content || '', ni = (lm.images || []).length;
  const text = ni
    ? `**${agent.icon} ${agent.name}** - *offline brain*\n\n${ni} image${ni > 1 ? 's' : ''} mila. Abhi main image **nahi dekh sakta** (offline brain text-only hai).\n\nVision ke liye Settings mein Anthropic ya OpenAI key daalein - phir main image samajh kar jawab dunga.`
    : offline.reply(last, mem || EMPTY_MEM);
  for (const w of text.split(/(\s+)/)) { yield w; await sleep(2); }
}
const IMPL = { anthropic, openai, ollama, mock, sidecar };
async function ollamaUp(base) { try { const r = await fetch(base.replace(/\/$/, '') + '/api/tags', { signal: AbortSignal.timeout(700) }); return r.ok; } catch { return false; } }

async function pickProvider(name = 'auto', keys = {}) {
  const k = {
    anthropic: keys.anthropic || process.env.ANTHROPIC_API_KEY, openai: keys.openai || process.env.OPENAI_API_KEY,
    openaiBase: keys.openaiBase || process.env.OPENAI_BASE_URL, ollama: keys.ollama || process.env.OLLAMA_URL || 'http://localhost:11434',
  };
  if (name === 'sidecar') {
    if (!(await sidecar.probe())) throw new Error('Olmavax Agent is not running. Start it with:  python advanced/olmavax-agent/olmavax_agent.py ui');
    return { name: 'sidecar', base: sidecar.DEFAULT_BASE };
  }
  if (name === 'anthropic') { if (!k.anthropic) throw new Error('No Anthropic API key. Add it in Settings.'); return { name, apiKey: k.anthropic }; }
  if (name === 'openai') { if (!k.openai) throw new Error('No OpenAI/compatible API key. Add it in Settings.'); return { name, apiKey: k.openai, base: k.openaiBase }; }
  if (name === 'ollama') return { name, base: k.ollama };
  if (name === 'mock') return { name };
  if (k.anthropic) return { name: 'anthropic', apiKey: k.anthropic };
  if (k.openai) return { name: 'openai', apiKey: k.openai, base: k.openaiBase };
  if (await ollamaUp(k.ollama)) return { name: 'ollama', base: k.ollama };
  if (await sidecar.probe()) return { name: 'sidecar', base: sidecar.DEFAULT_BASE };
  return { name: 'mock' };
}
function streamChat(provider, opts) { return (IMPL[provider.name] || IMPL.mock)(provider, opts); }
async function collect(provider, opts) { let s = ''; for await (const d of streamChat(provider, opts)) s += d; return s; }
async function providerStatus(keys = {}) {
  const base = keys.ollama || process.env.OLLAMA_URL || 'http://localhost:11434';
  return {
    anthropic: !!(keys.anthropic || process.env.ANTHROPIC_API_KEY),
    openai: !!(keys.openai || process.env.OPENAI_API_KEY),
    ollama: await ollamaUp(base),
    sidecar: await sidecar.probe(),
  };
}
module.exports = { pickProvider, streamChat, collect, providerStatus };
