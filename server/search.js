'use strict';
// Web search (DuckDuckGo HTML, no API key) + "deep research" (search, then read the top pages).
const { fetchPage } = require('./tools');
const strip = s => String(s || '').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+/g, ' ').trim();
function parseDDG(html, max = 6) {
  const out = [];
  for (const part of String(html).split('class="result__a"').slice(1)) {
    const href = (part.match(/href="([^"]+)"/) || [])[1]; if (!href) continue;
    let url = href.replace(/&amp;/g, '&'); const u = url.match(/[?&]uddg=([^&]+)/); if (u) url = decodeURIComponent(u[1]);
    if (url.startsWith('//')) url = 'https:' + url; if (!/^https?:\/\//.test(url)) continue;
    const title = strip((part.match(/>([\s\S]*?)<\/a>/) || [])[1]);
    const sn = part.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/a>/);
    out.push({ title: title || url, url, snippet: strip(sn ? sn[1] : '') }); if (out.length >= max) break;
  }
  return out;
}
async function search(q, max = 6) {
  const r = await fetch('https://html.duckduckgo.com/html/?q=' + encodeURIComponent(q), { signal: AbortSignal.timeout(8000), headers: { 'user-agent': 'Mozilla/5.0 OlmavaxAI/2.0' } });
  const res = parseDDG(await r.text(), max); if (!res.length) throw new Error('No results found');
  return res;
}
async function webContext(mode, q) {
  const results = await search(q, mode === 'research' ? 6 : 5);
  let ctx = results.map((r, i) => `[${i + 1}] ${r.title} (${r.url})\n${r.snippet}`).join('\n\n');
  if (mode === 'research') {
    const pages = await Promise.all(results.slice(0, 3).map(r => fetchPage(r.url).catch(() => '')));
    ctx += '\n\nPAGE EXCERPTS:\n' + pages.map((p, i) => p ? `[${i + 1}] ${p.slice(0, 2500)}` : '').filter(Boolean).join('\n\n');
  }
  return { sources: results.map(({ title, url }) => ({ title, url })), ctx };
}
module.exports = { parseDDG, search, webContext };