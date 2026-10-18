'use strict';
// "Build anything": websites, apps, presentations, portfolios, articles.
// With a real AI provider the model writes the file; without one, high-quality templates are used.
const { collect } = require('./providers');
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const titleOf = p => { const t = String(p).trim().split(/\s+/).slice(0, 6).join(' '); return t ? t[0].toUpperCase() + t.slice(1) : 'My Project'; };
const CSS = `*{box-sizing:border-box}body{margin:0;font:16px/1.6 system-ui,Segoe UI,Roboto,sans-serif;background:#0b1020;color:#e8ecf8}a{color:#8ab4ff}
.wrap{max-width:1000px;margin:auto;padding:0 20px}header{padding:70px 0 50px;text-align:center;background:radial-gradient(circle at 50% 0,#2b3a8a,#0b1020 70%)}
h1{font-size:clamp(2rem,6vw,3.6rem);margin:0 0 12px}.btn{display:inline-block;padding:12px 26px;border-radius:999px;background:#6c8cff;color:#fff;text-decoration:none;border:0;font:inherit;cursor:pointer}
section{padding:44px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px}.card{background:#151c36;border:1px solid #26305a;border-radius:16px;padding:22px}
input,textarea{width:100%;padding:12px;margin:6px 0;border-radius:10px;border:1px solid #26305a;background:#0f1530;color:inherit;font:inherit}footer{padding:30px;text-align:center;color:#8a93b8}`;
const page = (t, body, extra = '') => `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(t)}</title><style>${CSS}${extra}</style></head><body>${body}</body></html>`;

const T = {
  website: p => { const t = titleOf(p); return [{ name: 'index.html', content: page(t, `<header><div class="wrap"><h1>${esc(t)}</h1><p>${esc(p)}</p><a class="btn" href="#contact">Get started</a></div></header>
<section><div class="wrap"><h2>Why choose us</h2><div class="grid"><div class="card"><h3>\u{26A1} Fast</h3><p>Quick, reliable and built for you.</p></div><div class="card"><h3>\u{1F3AF} Focused</h3><p>Everything centred on what you need.</p></div><div class="card"><h3>\u{1F91D} Trusted</h3><p>Friendly support at every step.</p></div></div></div></section>
<section><div class="wrap"><h2>About</h2><p>${esc(p)}</p></div></section>
<section id="contact"><div class="wrap"><h2>Contact</h2><div class="card"><input placeholder="Your name"><input placeholder="Email"><textarea rows="4" placeholder="Message"></textarea><button class="btn" onclick="alert('Thanks! (demo form)')">Send</button></div></div></section><footer>\u00A9 ${new Date().getFullYear()} ${esc(t)}</footer>`) }]; },
  portfolio: p => { const t = titleOf(p); return [{ name: 'index.html', content: page(t + ' \u2014 Portfolio', `<header><div class="wrap"><h1>${esc(t)}</h1><p>Developer \u2022 Designer \u2022 Creator</p><a class="btn" href="#work">View my work</a></div></header>
<section><div class="wrap"><h2>About me</h2><p>${esc(p)}</p></div></section>
<section id="work"><div class="wrap"><h2>Projects</h2><div class="grid">${[1, 2, 3].map(i => `<div class="card"><h3>Project ${i}</h3><p>Short description of what you built and the result.</p></div>`).join('')}</div></div></section>
<section><div class="wrap"><h2>Skills</h2><p>JavaScript \u00B7 Python \u00B7 UI/UX \u00B7 Cloud \u00B7 AI</p></div></section><footer>Contact: you@example.com</footer>`) }]; },
  presentation: p => { const t = titleOf(p); const S = [[t, p], ['Agenda', 'Problem \u2022 Solution \u2022 Plan \u2022 Next steps'], ['The Problem', 'What is broken today and who feels it.'], ['Our Solution', 'How we solve it, simply and better.'], ['Roadmap', 'Q1 Build \u2192 Q2 Launch \u2192 Q3 Grow'], ['Thank you', 'Questions?']];
    return [{ name: 'index.html', content: page(t, S.map(([h, b], i) => `<div class="s" ${i ? '' : 'style="display:flex"'}><div><h1>${esc(h)}</h1><p>${esc(b)}</p></div></div>`).join('') + `<div id="n"></div><script>let i=0;const s=[...document.querySelectorAll('.s')],n=document.getElementById('n');function go(d){i=Math.max(0,Math.min(s.length-1,i+d));s.forEach((e,j)=>e.style.display=j==i?'flex':'none');n.textContent=(i+1)+' / '+s.length}addEventListener('keydown',e=>{if(['ArrowRight',' ','PageDown'].includes(e.key))go(1);if(['ArrowLeft','PageUp'].includes(e.key))go(-1)});addEventListener('click',()=>go(1));go(0)</script>`, `.s{display:none;height:100vh;align-items:center;justify-content:center;text-align:center;padding:40px}#n{position:fixed;right:16px;bottom:12px;color:#8a93b8}h1{font-size:clamp(2rem,7vw,4.5rem)}`) }]; },
  app: p => { const t = titleOf(p); return [{ name: 'index.html', content: page(t, `<div class="wrap" style="padding-top:40px"><h1>${esc(t)}</h1><p>Simple task app (saved in your browser). Request: ${esc(p)}</p><div class="card"><input id="i" placeholder="Add a task and press Enter"><ul id="l"></ul></div></div><script>let d=[];try{d=JSON.parse(localStorage.t||'[]')}catch{}const l=document.getElementById('l'),i=document.getElementById('i');function r(){l.innerHTML='';d.forEach((x,k)=>{const li=document.createElement('li');li.textContent=x.t;li.style.cssText='cursor:pointer;padding:6px;'+(x.d?'text-decoration:line-through;opacity:.5':'');li.onclick=()=>{x.d=!x.d;s()};li.oncontextmenu=e=>{e.preventDefault();d.splice(k,1);s()};l.appendChild(li)})}function s(){try{localStorage.t=JSON.stringify(d)}catch{}r()}i.onkeydown=e=>{if(e.key=='Enter'&&i.value.trim()){d.push({t:i.value.trim(),d:0});i.value='';s()}};r()</script>`) }]; },
  article: p => { const t = titleOf(p); return [{ name: 'article.md', content: `# ${t}\n\n*${p}*\n\n## Introduction\nWhy this topic matters and what you will learn.\n\n## Key ideas\n1. First idea, explained with an example.\n2. Second idea, with practical steps.\n3. Third idea, with common mistakes to avoid.\n\n## Conclusion\nSummary and a clear call to action.\n` }]; },
};
const REAL = {
  website: 'a complete, modern, responsive, accessible website as ONE self-contained index.html (inline CSS and JS)',
  portfolio: 'a complete, modern personal portfolio as ONE self-contained index.html (inline CSS and JS)',
  presentation: 'a complete slide presentation (10+ slides, keyboard navigation) as ONE self-contained index.html (inline CSS and JS)',
  app: 'a complete, working single-page web app as ONE self-contained index.html (inline CSS and JS, data in localStorage)',
  article: 'a complete, well-structured, engaging article in Markdown',
};
function clean(s) { const m = s.match(/```(?:\w+)?\n([\s\S]*?)```/); return (m ? m[1] : s).trim(); }
async function build(type, prompt, { provider, agent, model } = {}) {
  if (!T[type]) throw new Error('Unknown type. Use: ' + Object.keys(T).join(', '));
  prompt = String(prompt || '').trim().slice(0, 2000); if (!prompt) throw new Error('Describe what to build.');
  let files, mode = 'template';
  if (provider && provider.name !== 'mock') {
    const out = await collect(provider, { agent, model, system: `You are an expert creator. Produce ${REAL[type]}. Output ONLY the file content, no commentary.`, messages: [{ role: 'user', content: prompt }] });
    files = [{ name: type === 'article' ? 'article.md' : 'index.html', content: clean(out) }]; mode = 'ai';
  } else files = T[type](prompt);
  files.push({ name: 'README.txt', content: `${titleOf(prompt)}\nBuilt with Olmavax AI (${mode}).\nOpen index.html in any browser (or read article.md).\n` });
  return { files, mode };
}
module.exports = { build, types: Object.keys(T) };