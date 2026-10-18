'use strict';
// "Create image": OpenAI image API if a key exists, otherwise the AI writes an SVG; demo mode draws a placeholder.
const { collect } = require('./providers');
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const b64 = s => Buffer.from(s).toString('base64');
function placeholder(prompt) {
  const words = String(prompt).slice(0, 90).split(' '); const lines = []; let cur = '';
  for (const w of words) { if ((cur + ' ' + w).length > 22) { lines.push(cur); cur = w; } else cur += ' ' + w; } lines.push(cur);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6c8cff"/><stop offset="1" stop-color="#b06cff"/></linearGradient></defs><rect width="800" height="800" rx="60" fill="url(#g)"/><circle cx="400" cy="300" r="120" fill="#ffffff33"/><path d="M400 200l28 80 80 28-80 28-28 80-28-80-80-28 80-28z" fill="#fff"/>${lines.slice(0, 4).map((l, i) => `<text x="400" y="${540 + i * 46}" font-family="sans-serif" font-size="38" fill="#fff" text-anchor="middle">${esc(l.trim())}</text>`).join('')}<text x="400" y="760" font-family="sans-serif" font-size="22" fill="#ffffffaa" text-anchor="middle">demo image \u2014 add an API key for real images</text></svg>`;
}
async function makeImage(prompt, provider, b, agent) {
  const oKey = (b.keys && b.keys.openai) || process.env.OPENAI_API_KEY;
  const base = ((b.keys && b.keys.openaiBase) || process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1').replace(/\/$/, '');
  if (oKey && /api\.openai\.com/.test(base) && (provider.name === 'openai' || !b.provider || b.provider === 'auto')) {
    const r = await fetch(base + '/images/generations', { method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + oKey }, body: JSON.stringify({ model: 'gpt-image-1', prompt, size: '1024x1024' }) });
    if (!r.ok) throw new Error('Image API error ' + r.status + ': ' + (await r.text()).slice(0, 200));
    const j = await r.json(); const d = j.data && j.data[0]; if (d && d.b64_json) return { mime: 'image/png', data: d.b64_json };
  }
  if (provider.name === 'mock') return { mime: 'image/svg+xml', data: b64(placeholder(prompt)) };
  const out = await collect(provider, { agent, model: b.model, system: 'You are an expert SVG artist. Output ONLY one complete standalone SVG (xmlns, viewBox="0 0 800 800", no scripts, no external links). Make it detailed, colourful and visually polished.', messages: [{ role: 'user', content: prompt }] });
  const m = out.match(/<svg[\s\S]*<\/svg>/i); if (!m) throw new Error('The model did not return an image.');
  return { mime: 'image/svg+xml', data: b64(m[0].replace(/<script[\s\S]*?<\/script>/gi, '').replace(/\son\w+="[^"]*"/gi, '')) };
}
module.exports = { makeImage, placeholder };