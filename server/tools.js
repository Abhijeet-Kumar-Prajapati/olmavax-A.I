'use strict';
// Built-in tools, usable via slash commands: /calc /time /fetch /remember /memory /forget /help
// plus extra utilities: /convert /unit /stats /password /uuid /color /date /note
const offline = require('./offline');
/* ---- calculator ------------------------------------------------------
   Helpers that map onto a real Math method. Anything not named here is
   rejected by the whitelist at the bottom, so this list is the whole
   attack surface. */
const FN = 'sqrt|cbrt|abs|round|floor|ceil|min|max';

const HINT = 'Use numbers with + - * / ^ % ( ) - e.g. 2+2*5, sqrt(144), 10% of 850 or max(4,9).';

/* Commas inside a call are parked on U+0001 while the thousands-separator
   rule runs, so max(4,9,2) is not mangled into 492. U+0001 cannot appear in
   valid arithmetic, so admitting it past the whitelist buys no attack
   surface - it is turned back into a comma immediately before evaluation. */
const SEP = '\u0001';
function maskArgs(e) {
  let d = 0, out = '';
  for (const ch of e) {
    if (ch === '(') d++; else if (ch === ')') d--;
    out += (d > 0 && ch === ',') ? SEP : ch;
  }
  return out;
}

/* "10% of 850" -> (10*(850)/100);  a lone trailing "%" means divide by 100. */
function percentise(e) {
  return e
    .replace(/(-?\d[\d\u0001]*(?:\.\d+)?)\s*%\s*(?:of|out\s+of)\s*(-?\d[\d\u0001]*(?:\.\d+)?)/gi,
             (m, pct, base) => '(' + pct + '*(' + base + ')/100)')
    .replace(/\(\s*(-?\d[\d\u0001]*(?:\.\d+)?)\s*%\s*\)/g, (m, p) => '(' + p + '/100)')
    .replace(/(-?\d[\d\u0001]*(?:\.\d+)?)\s*%(?!\s*%)(?!\s*\d)/g, (m, p) => '(' + p + '/100)');
}

/* sqr(7) -> ((7)*(7));  root(27,3) -> Math.pow(27,1/(3));  sqrt(9) -> Math.sqrt(9).
   The root() separator may be a comma or the masked U+0001, because argument
   commas are already parked by the time this runs. */
function expandFns(e) {
  return e
    .replace(/\bsqr\s*\(([^()]*)\)/gi, (m, a) => '((' + a.trim() + ')*(' + a.trim() + '))')
    .replace(/\broot\s*\(([^()]+?)\s*[,\u0001]\s*([^()]+?)\)/gi,
             (m, a, b) => 'Math.pow(' + a.trim() + SEP + '1/(' + b.trim() + '))')
    .replace(new RegExp('\\b(' + FN + ')\\s*\\(', 'gi'),
             (m, name) => 'Math.' + name.toLowerCase() + '(');
}

function calc(expr) {
  let e = maskArgs(String(expr).replace(/\^/g, '**').trim());
  e = e.replace(/(?<=\d),(?=\d{3}(?!\d))/g, '');   // 1,234,567 -> 1234567
  e = expandFns(percentise(e));
  if (e.length > 240) throw new Error(HINT);
  // Strip the whitelisted Math calls; what is left must be plain arithmetic.
  // A stray letter, a semicolon or a property access all fail here.
  if (!/^[0-9+\-*/().%\s\u0001]*$/.test(e.replace(/Math\.[a-z]+/g, ''))) throw new Error(HINT);
  const v = Function('"use strict";return (' + e.split(SEP).join(',') + ')')();
  if (typeof v !== 'number' || !isFinite(v)) throw new Error('Result is not a finite number.');
  return v;
}
/* ---- end calculator -------------------------------------------------- */
function badHost(h) { return /^(localhost|0\.0\.0\.0|127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1)/i.test(h); }
async function fetchPage(url) {
  let u; try { u = new URL(url); } catch { throw new Error('Invalid URL.'); }
  if (!/^https?:$/.test(u.protocol)) throw new Error('Only http/https URLs are allowed.');
  if (badHost(u.hostname)) throw new Error('Local/private addresses are blocked for safety.');
  const r = await fetch(u, { signal: AbortSignal.timeout(10000), headers: { 'user-agent': 'OlmavaxAI/2.0' } });
  const html = await r.text();
  const text = html.replace(/<(script|style)[\s\S]*?<\/\1>/gi, ' ').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
  return text.slice(0, 3000);
}

const HELP = `**Olmavax commands**
- \`/calc 12*(3+4)\` - calculator
- \`/time\` - current date & time
- \`/fetch https://example.com\` - read a web page (online)
- \`/remember I prefer Python\` - save to long-term memory
- \`/memory\` - show memory
- \`/forget <id>\` - delete a memory item
- \`/convert 5 km in miles\` - unit conversion
- \`/stats <text>\` - word / character count
- \`/password [len]\` - strong password
- \`/uuid\` - random UUID
- \`/color\` - random colour
- \`/note <text>\` - quick note to memory
- \`/clear\` - clear all memory
- Use the Build tool for websites, apps, presentations, portfolios and articles`;

async function runSlash(text, mem) {
  const m = text.match(/^\/(\w+)\s*([\s\S]*)$/); if (!m) return 'Unknown command. Try /help';
  const [, cmd, argRaw] = m;
  const arg = argRaw.trim();
  const lc = cmd.toLowerCase();
  try {
    switch (lc) {
      case 'help': case 'h': case '?': return HELP;
      case 'calc': case 'math': return `**${arg} = ${calc(arg)}**`;
      case 'time': return new Date().toString();
      case 'date': return offline.reply('today date', mem);
      case 'fetch': return await fetchPage(arg);
      case 'remember': { const f = mem.add(arg); return f ? `Saved to memory: "${f.text}"` : 'Nothing to remember.'; }
      case 'note': { const f = mem.add(arg); return f ? `**Note saved:** ${f.text}` : 'Nothing to save.'; }
      case 'memory': return mem.list().length ? mem.list().map(f => `- \`${f.id}\` ${f.text}`).join('\n') : 'Memory is empty.';
      case 'forget': return mem.remove(arg) ? 'Forgotten.' : 'No such id.';
      case 'clear': { const n = mem.list().length; mem.facts = []; mem.save(); return `Memory cleared (${n} items removed).`; }
      case 'convert': case 'unit': { const r = offline.convert(arg.toLowerCase()); return r ? `**${r}**` : `Cannot convert "${arg}". Try: 5 km in miles, 72f in celsius, 10 kg in lb.`; }
      case 'stats': { if (!arg) return 'Usage: /stats <your text here>'; const s = offline.textStats(arg); return `**Text stats**\n- Words: ${s.words}\n- Characters: ${s.chars} (no spaces: ${s.charsNs})\n- Sentences: ${s.sents}\n- Paragraphs: ${s.paras}\n- Reading time: ~${s.reading} min`; }
      case 'password': return `**${arg || 16}-char password:**\n\n\`${offline.password(Math.min(64, Math.max(8, +arg || 16)))}\``;
      case 'uuid': case 'guid': return `**UUID v4:**\n\n\`${offline.uuid()}\``;
      case 'color': case 'colour': return offline.reply('random color', mem);
      default: return `Unknown command /${cmd}. Try **/help**`;
    }
  } catch (e) { return 'Error: ' + e.message; }
}
module.exports = { calc, fetchPage, runSlash, HELP };
