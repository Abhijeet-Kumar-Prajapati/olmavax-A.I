'use strict';
/* ============================================================
   Olmavax A.I — Offline Brain
   A genuinely useful zero-API-key assistant.
   Handles greetings, maths, time, conversions, text tools,
   generators, memory commands and app guidance locally.
   ============================================================ */

/* Safe arithmetic evaluator (kept local to avoid a circular import with tools.js) */
function calc(expr) {
  const e = String(expr).replace(/\^/g, '**').replace(/,/g, '');
  if (!/^[0-9+\-*/().%\s]+$/.test(e) || e.length > 200) throw new Error('Only numbers and + - * / ^ % ( ) are allowed.');
  const v = Function('"use strict";return (' + e + ')')();
  if (typeof v !== 'number' || !isFinite(v)) throw new Error('Result is not a finite number.');
  return v;
}

/* ---------- helpers ---------- */
const norm = s => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}\s.+\-*/^%()\[\]]/gu, ' ').replace(/\s+/g, ' ').trim();
const has = (t, ...w) => w.some(x => t.includes(x));

/* ---------- units ---------- */
const TO = {
  mm: 0.001, cm: 0.01, m: 1, km: 1000, in: 0.0254, ft: 0.3048, yd: 0.9144, mi: 1609.344, nmi: 1852, ly: 9.4607e15, lightyear: 9.4607e15,
  mg: 1e-6, g: 0.001, kg: 1, t: 1000, oz: 0.0283495, lb: 0.453592, st: 6.35029,
};
const ALIAS = {
  millimeter: 'mm', millimeters: 'mm', millimetre: 'mm', millimetres: 'mm',
  centimeter: 'cm', centimeters: 'cm', centimetre: 'cm', centimetres: 'cm',
  kilometer: 'km', kilometers: 'km', kilometre: 'km', kilometres: 'km',
  meter: 'm', meters: 'm', metre: 'm', metres: 'm',
  inch: 'in', inches: 'in',
  yard: 'yd', yards: 'yd',
  mile: 'mi', miles: 'mi',
  foot: 'ft', feet: 'ft',
  gram: 'g', grams: 'g', gramme: 'g', grammes: 'g',
  kilogram: 'kg', kilograms: 'kg', kilo: 'kg', kilos: 'kg',
  tonne: 't', tonnes: 't', ton: 't', tons: 't',
  ounce: 'oz', ounces: 'oz',
  pound: 'lb', pounds: 'lb',
  stone: 'st', stones: 'st',
  celsius: 'c', centigrade: 'c', temp: 'c', temperature: 'c',
  fahrenheit: 'f', kelvin: 'k',
};
const unit = w => {
  const k = String(w || '').toLowerCase().trim().replace(/[.,]$/, '');
  return ALIAS[k] || k;
};
const toC = (v, u) => u === 'f' ? (v - 32) * 5 / 9 : u === 'k' ? v - 273.15 : v;
const fromC = (v, u) => u === 'f' ? v * 9 / 5 + 32 : u === 'k' ? v + 273.15 : v;

function fmt(n) {
  if (!isFinite(n)) return String(n);
  return String(Math.round(n * 1e6) / 1e6);
}
const DEG = '\u00B0';

/* ---------- conversion engine ---------- */
const UN_RE = 'mm|cm|km|ft|yd|mi|nmi|lightyear|mg|kg|t|oz|lb|st|inch(?:es)?|in|foot|feet|meter(?:s)?|metre(?:s)?|kilometer(?:s)?|kilometre(?:s)?|gram(?:s)?|gramme(?:s)?|kilogram(?:s)?|kilo(?:s)?|tonne(?:s)?|ton(?:s)?|ounce(?:s)?|pound(?:s)?|stone(?:s)?|mile(?:s)?|yard(?:s)?';

function convert(t) {
  const s = String(t || '').toLowerCase();

  // ---------- temperature
  const tm = s.match(/(-?\d+(?:\.\d+)?)\s*(?:deg(?:rees?)?\s*)?\u00B0?\s*(celsius|centigrade|fahrenheit|kelvin|c(?![a-z])|f(?![a-z])|k(?![a-z]))\b/);
  if (tm) {
    const from = unit(tm[2]);
    const toM = s.slice(tm.index + tm[0].length).match(/\b(?:to|in|into)\s*(celsius|centigrade|fahrenheit|kelvin|c(?![a-z])|f(?![a-z])|k(?![a-z]))\b/);
    const target = toM ? unit(toM[1]) : (from === 'c' ? 'f' : 'c');
    const v = parseFloat(tm[1]);
    if (target === from) return `${fmt(v)}${DEG} ${from.toUpperCase()}`;
    return `${fmt(fromC(toC(v, from), target))}${DEG} ${target.toUpperCase()}`;
  }

  // ---------- length / mass
  const um = s.match(new RegExp('(-?\\d+(?:\\.\\d+)?)\\s*(' + UN_RE + ')\\b'));
  if (um) {
    const v = parseFloat(um[1]);
    const from = unit(um[2]);
    const toM = s.slice(um.index + um[0].length).match(/\b(?:to|in|into)\s+([a-z]+)\b/);
    const target = toM ? unit(toM[1]) : null;
    if (target && TO[target] !== undefined && TO[from] !== undefined) {
      const out = v * TO[from] / TO[target];
      return `${fmt(v)} ${from} = ${fmt(out)} ${target}`;
    }
  }
  return null;
}

/* ---------- percentage / arithmetic in words ---------- */
function arithmetic(t) {
  let m;
  if ((m = t.match(/(-?\d+(?:\.\d+)?)\s*(?:%|percent)\s*of\s*(-?\d+(?:\.\d+)?)/))) {
    const r = parseFloat(m[1]) / 100 * parseFloat(m[2]);
    return `**${m[1]}% of ${m[2]} = ${fmt(r)}**`;
  }
  if ((m = t.match(/(-?\d+(?:\.\d+)?)\s*(?:percent|%)\s*(more|less|greater|smaller)\s*(?:than\s*)?(-?\d+(?:\.\d+)?)/))) {
    const a = parseFloat(m[1]) / 100 * parseFloat(m[3]);
    const less = /less|smaller/.test(m[2]);
    const r = less ? parseFloat(m[3]) - a : parseFloat(m[3]) + a;
    return `**${m[3]} ${m[1]}% ${m[2]} = ${fmt(r)}**`;
  }
  if ((m = t.match(/(?:half|50 ?%)\s*of\s*(-?\d+(?:\.\d+)?)/))) return `**Half of ${m[1]} = ${fmt(parseFloat(m[1]) / 2)}**`;
  if ((m = t.match(/(?:double|twice)\s*(-?\d+(?:\.\d+)?)/))) return `**Double of ${m[1]} = ${fmt(parseFloat(m[1]) * 2)}**`;

  // square / cube root  (handles sqrt(144) and "square root of 144")
  if ((m = t.match(/(?:square root|sqrt)\s*(?:of\s*)?\(*\s*(-?\d+(?:\.\d+)?)\s*\)?/))) {
    const r = Math.sqrt(parseFloat(m[1]));
    return `**\u221A${m[1]} = ${isFinite(r) ? fmt(r) : 'undefined'}**`;
  }
  if ((m = t.match(/cube root\s*(?:of\s*)?\(*\s*(-?\d+(?:\.\d+)?)\s*\)?/))) {
    const r = Math.cbrt(parseFloat(m[1]));
    return `**\u221B${m[1]} = ${isFinite(r) ? fmt(r) : 'undefined'}**`;
  }
  if ((m = t.match(/(-?\d+(?:\.\d+)?)\s*(?:squared|\^2|\*\*2)\b/))) {
    return `**${m[1]}\u00B2 = ${fmt(parseFloat(m[1]) ** 2)}**`;
  }
  if ((m = t.match(/(-?\d+(?:\.\d+)?)\s*(?:cubed|\^3|\*\*3)\b/))) {
    return `**${m[1]}\u00B3 = ${fmt(parseFloat(m[1]) ** 3)}**`;
  }

  // plain expression: match from the first digit/paren, allowing a leading "("
  const anchor = t.search(/\d|\(/);
  if (anchor >= 0) {
    const tail = t.slice(anchor);
    const em = tail.match(/[\d(][\d\s.+\-*/^()%]*/);
    if (em) {
      let e = em[0].replace(/\s+/g, '');
      // need at least one real operator (not just a leading paren)
      if (/[-+*/^%]/.test(e.slice(1))) {
        // cut at the first unbalanced close-paren
        let depth = 0, cut = 0;
        for (let i = 0; i < e.length; i++) {
          if (e[i] === '(') depth++;
          else if (e[i] === ')') { depth--; if (depth < 0) { cut = i; break; } }
        }
        if (cut) e = e.slice(0, cut);
        // drop dangling opening paren / trailing operators
        while (/[-+*/^%.]$/.test(e) || (e[0] === '(' && !e.includes(')'))) e = e.slice(0, -1) && e.slice(0);
        while (/[-+*/^%.]$/.test(e)) e = e.slice(0, -1);
        try { return `**${e} = ${calc(e)}**`; } catch {}
      }
    }
  }
  return null;
}

/* ---------- generators ---------- */
function password(n = 16) {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%&*';
  let out = '';
  const rnd = new Uint32Array(n);
  if (globalThis.crypto && globalThis.crypto.getRandomValues) globalThis.crypto.getRandomValues(rnd);
  else for (let i = 0; i < n; i++) rnd[i] = Math.floor(Math.random() * 4294967295);
  for (let i = 0; i < n; i++) out += chars[rnd[i] % chars.length];
  return out;
}
function uuid() {
  if (globalThis.crypto && globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}
const COLORS = ['#ef4444', '#f97316', '#f59e0b', '#eab308', '#84cc16', '#22c55e', '#10b981', '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899', '#f43f5e'];

/* ---------- word counts ---------- */
function textStats(body) {
  const words = (body.match(/[\p{L}\p{N}'-]+/gu) || []).length;
  const chars = body.length;
  const charsNs = body.replace(/\s/g, '').length;
  const sents = (body.match(/[.!?।]+/g) || []).length || (words ? 1 : 0);
  const paras = body.split(/\n{2,}/).filter(x => x.trim()).length;
  const lines = body.split(/\n/).length;
  const reading = Math.max(1, Math.round(words / 200));
  return { words, chars, charsNs, sents, paras, lines, reading };
}

/* ---------- main ---------- */
function reply(text, mem) {
  const t = norm(text);
  const raw = String(text || '').trim();
  const safeMem = mem || { list: () => [], add: () => null, remove: () => false, save() {}, facts: [] };
  if (!t) return 'Kuch to likhiye \u2014 main hazir hoon.';

  /* ---------- memory ---------- */
  if (/\b(show|list)\s+(my\s+)?memory\b/.test(t) || /^\/?memory\s*$/.test(t) || /kya yaad/.test(t)) {
    const f = safeMem.list();
    return f.length
      ? '**\u{1F9E0} Aapki memory:**\n' + f.map(x => `- \`${x.id}\` ${x.text}`).join('\n')
      : '**\u{1F9E0} Memory khali hai.**\nYaad rakhne ke liye likhein: `mera naam Rahul hai` ya `/remember I like Python`';
  }
  if (/\b(clear|delete|reset)\s+(all\s+)?(memory|yaad)\b/.test(t) || /^\/?clear\s*$/.test(t)) {
    const n = safeMem.list().length;
    try { safeMem.facts = []; safeMem.save(); } catch {}
    return `**\u{1F9E0} Memory clear kar di.** ${n} item hataaye gaye.`;
  }
  const rm = raw.match(/^\/?forget\s+(\S+)/i);
  if (rm) return safeMem.remove(rm[1]) ? '**\u{1F9E0} Forget.** Item hata diya gaya.' : '**\u{1F9E0} Nahi mila.** Sahi id use karein (`/memory` se list dekhein).';
  const lr = raw.match(/^\/?(?:remember|note)\s+(.+)/i);
  if (lr) { const f = safeMem.add(lr[1]); return f ? `**\u{1F9E0} Yaad rakh liya:** "${f.text}"` : 'Kuch to likha hona chahiye.'; }

  /* ---------- identity ---------- */
  if (has(t, 'who are you', 'kaun ho', 'tum kaun', 'your name', 'about you', 'aap kaun')) {
    return '**Main Olmavax A.I hoon** \u2014 aapka multi-agent AI workspace.\n\nAbhi main **offline brain** mode mein hoon (koi API key nahi), isliye maths, time, conversions, text tools aur generators poore kaam karte hain.\n\n**Asli AI (Claude / GPT / Llama) chalu karne ke liye:**\n`Settings \u{2699}\u{FE0F}` mein API key daalein, ya bilkul offline rehne ke liye [Ollama](https://ollama.com) install karke `ollama pull llama3.2` chalayein.\n\nMere paas 9 specialist agents hain: Code, App Builder, Researcher, Writer, Presenter, Portfolio, Tutor, Planner, General.';
  }
  if (has(t, 'what can you do', 'kya kar sakte', 'capabilities', 'features', 'help', 'madad', 'commands', 'options')) {
    return `**\u{1F9E0} Main yeh sab kar sakta hoon (bina key ke):**\n\n**\u{1F4BB} Maths** \u2014 "15% of 2500", "sqrt(144)", "2^10", "half of 98"\n**\u{23F1}\uFE0F Time** \u2014 "what time is it", "today date"\n**\u{1F504} Convert** \u2014 "5 km in miles", "72F in celsius", "10 kg in lb"\n**\u{1F4DD} Text** \u2014 "count words in: ..."\n**\u{1F510} Generate** \u2014 "generate password", "uuid", "random color"\n**\u{1F9E0} Memory** \u2014 "mera naam X hai", "show memory"\n**\u{1F6E0}\uFE0F Build** \u2014 websites, apps, slides, portfolio, article (ZIP)\n**\u{1F310} Search** \u2014 web search & deep research\n**\u{1F399}\u{FE0F} Voice** \u2014 baat karke poochein\n**\u{270F}\uFE0F Sketch** \u2014 draw karke image banayein\n\n**Commands:** \`/help\` \`/calc\` \`/convert\` \`/stats\` \`/password\` \`/uuid\` \`/time\``;
  }

  /* ---------- time & date ---------- */
  if (has(t, 'time', 'samay', 'waqt', 'ghadi', 'clock')) {
    return `**\u{23F1}\uFE0F Abhi:** ${new Date().toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}\n**\u{1F4C5} Aaj:** ${new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}\n**\u{1F30D} Timezone:** ${Intl.DateTimeFormat().resolvedOptions().timeZone}`;
  }
  if (has(t, 'date', 'tareekh', 'aaj', 'today', 'diwas')) {
    return `**\u{1F4C5} Aaj:** ${new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}`;
  }

  /* ---------- converters & maths ---------- */
  if (has(t, 'convert', 'how many', ' in ', ' to ')) {
    const c = convert(t);
    if (c) return `**\u{1F504} ${c}**`;
  }

  /* ---------- generators (before maths: "generate password 20" is not arithmetic) ---------- */
  if (has(t, 'password', 'passphrase')) {
    const digits = raw.match(/\b(\d{2,3})\b/);
    const n = Math.min(64, Math.max(8, digits ? +digits[1] : 16));
    return `**\u{1F510} ${n}-char password:**\n\n\`${password(n)}\`\n\n**Doosra:** \`${password(n)}\`\n\n*Browser mein generate hua \u2014 kahin save nahi hua.*`;
  }
  if (has(t, 'uuid', 'guid')) return `**\u{1F9E0} UUID v4:**\n\n\`${uuid()}\``;
  if (has(t, 'random color', 'random colour', 'random rang')) {
    const hex = COLORS[Math.floor(Math.random() * COLORS.length)];
    const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
    return `**\u{1F3A8} Random colour:** ${hex}\nRGB \`rgb(${r}, ${g}, ${b})\``;
  }

  /* ---------- maths ---------- */
  const ar = arithmetic(t);
  if (ar) return ar;

  /* ---------- generators (word form, after maths) ---------- */
  if (has(t, 'color', 'colour', 'rang')) {
    const hex = COLORS[Math.floor(Math.random() * COLORS.length)];
    const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
    return `**\u{1F3A8} Random colour:** ${hex}\nRGB \`rgb(${r}, ${g}, ${b})\``;
  }

  /* ---------- text stats ---------- */
  if (has(t, 'count words', 'word count', 'words in', 'character count', 'text stats', 'letter count')) {
    const body = raw.replace(/^.*?(?:count words(?: (?:in|of))?|word count(?: (?:in|of))?|characters?(?: count)?(?: (?:in|of))?)\s*[:\u005C-]\s*/is, '');
    if (!body || body.length < 3) return 'Count karna hai to text likhein:\n`count words in: aapka text yahan...`';
    const s = textStats(body);
    return `**\u{1F4DD} Text stats**\n- Words: **${s.words}**\n- Characters: **${s.chars}** (no spaces: ${s.charsNs})\n- Sentences: **${s.sents}**\n- Paragraphs: **${s.paras}**\n- Lines: ${s.lines}\n- Reading time: ~**${s.reading} min**`;
  }

  /* ---------- small talk ---------- */
  if (has(t, 'hello', 'helo', 'hi ', 'hii', 'hey', 'namaste', 'namaskar', 'salam', 'assalam', 'ram')) {
    return '**Namaste! \u{1F44B}** Main Olmavax A.I hoon.\n\nAap seedha sawaal poochh sakte hain, ya mujhe kaam karne dein:\n- `15% of 2500` kya hai?\n- `5 km in miles`\n- `generate password`\n- `mera naam Rahul hai` (main yaad rakh lunga)\n- `\u{1F310}` icon dabayein for web search\n\n**Asli AI** chalu karna hai? `Settings \u{2699}\u{FE0F}` mein API key daalein.';
  }
  if (has(t, 'thanks', 'thank you', 'shukriya', 'dhanyavad', 'thx')) return 'Khushi hui madad kar ke! \u{1F60A}\nKuch aur ho to bataiye.';
  if (has(t, 'bye', 'goodbye', 'alvida', 'see you')) return 'Alvida! Phir milte hain. \u{1F44B}';

  /* ---------- fallback ---------- */
  return `**\u{1F9E0} Offline brain** \u2014 abhi main yeh nahi samajh paya.\n\n**Bina API key ke main yeh kar sakta hoon:**\n- Maths: "15% of 2500", "sqrt(144)", "2^10"\n- Convert: "5 km in miles", "72F in celsius"\n- Time: "what time is it"\n- Tools: "generate password", "uuid", "random color"\n- Memory: "mera naam X hai", "show memory"\n- Count: "count words in: ..."\n\n**Asli AI (Claude / GPT / Llama) ke liye:**\n1. \u{2699}\u{FE0F} Settings kholein\n2. Anthropic ya OpenAI API key daalein \u2014 **Save** dabayein\n3. Ya [Ollama](https://ollama.com) install karein: \`ollama pull llama3.2\`\n\nWeb search ke liye composer mein \u{1F310} icon dabayein.`;
}

module.exports = { reply, password, uuid, convert, arithmetic, textStats };
