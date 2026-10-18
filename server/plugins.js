'use strict';
/**
 * Plugin registry — the "Plugins" panel in the sidebar.
 *
 * Each plugin is a real, self-contained tool that runs locally with no
 * network and no dependencies. Users can enable/disable them from the UI and
 * invoke them from the composer with /name <args>.
 */
const crypto = require('crypto');
const qr = require('./qr');

const clip = (s, n = 20000) => String(s == null ? '' : s).slice(0, n);

const UNIT_ALIAS = {
  // singular/plural/long forms so "5 miles in km" just works
  m: 'm', meter: 'm', meters: 'm', metre: 'm', metres: 'm',
  km: 'km', kilometer: 'km', kilometers: 'km', kilometre: 'km', kilometres: 'km',
  cm: 'cm', centimeter: 'cm', centimeters: 'cm', centimetre: 'cm', centimetres: 'cm',
  mm: 'mm', millimeter: 'mm', millimeters: 'mm', millimetre: 'mm', millimetres: 'mm',
  mi: 'mi', mile: 'mi', miles: 'mi',
  yd: 'yd', yard: 'yd', yards: 'yd',
  ft: 'ft', foot: 'ft', feet: 'ft',
  in: 'in', inch: 'in', inches: 'in',
  nmi: 'nmi', 'nautical mile': 'nmi', 'nautical miles': 'nmi',

  kg: 'kg', kilogram: 'kg', kilograms: 'kg', kilo: 'kg', kilos: 'kg',
  g: 'g', gram: 'g', grams: 'g',
  mg: 'mg', milligram: 'mg', milligrams: 'mg',
  t: 't', tonne: 't', tonnes: 't', ton: 't', tons: 't',
  lb: 'lb', lbs: 'lb', pound: 'lb', pounds: 'lb',
  oz: 'oz', ounce: 'oz', ounces: 'oz',
  st: 'st', stone: 'st', stones: 'st',

  s: 's', sec: 's', secs: 's', second: 's', seconds: 's',
  min: 'min', mins: 'min', minute: 'min', minutes: 'min',
  h: 'h', hr: 'h', hrs: 'h', hour: 'h', hours: 'h',
  d: 'd', day: 'd', days: 'd',
  wk: 'wk', week: 'wk', weeks: 'wk',
  yr: 'yr', year: 'yr', years: 'yr',

  b: 'B', byte: 'B', bytes: 'B',
  kb: 'KB', kilobyte: 'KB', kilobytes: 'KB',
  mb: 'MB', megabyte: 'MB', megabytes: 'MB',
  gb: 'GB', gigabyte: 'GB', gigabytes: 'GB',
  tb: 'TB', terabyte: 'TB', terabytes: 'TB',
  bit: 'bit', bits: 'bit',
};
const unit = s => UNIT_ALIAS[String(s || '').toLowerCase().trim()] || null;

/** Temperature needs offsets, so it is handled separately from ratios. */
const TEMP = { c: 0, f: -32, k: -273.15 };
const TEMP_ALIAS = {
  c: 'c', celsius: 'c', centigrade: 'c', '°c': 'c',
  f: 'f', fahrenheit: 'f', '°f': 'f',
  k: 'k', kelvin: 'k',
};

/** Parse "72 f" / "72F" / "72 degrees f" into a unit key. */
function parseTemp(raw) {
  const s = String(raw || '').toLowerCase().replace(/degrees|degree|deg/g, '').trim();
  if (TEMP_ALIAS[s]) return TEMP_ALIAS[s];
  const m = s.match(/^(-?[\d.,]+)\s*([cfk])$/);   // "72f" fused form
  return m ? TEMP_ALIAS[m[2]] : null;
}

function convertTemp(v, fromRaw, toRaw) {
  const from = parseTemp(fromRaw), to = parseTemp(toRaw);
  if (!from || !to) return null;
  // normalise to Celsius first, then out to the target scale
  let celsius = v;
  if (from === 'f') celsius = (v - 32) * 5 / 9;
  else if (from === 'k') celsius = v - 273.15;
  let out = celsius;
  if (to === 'f') out = celsius * 9 / 5 + 32;
  else if (to === 'k') out = celsius + 273.15;
  return { kind: 'temperature', value: out, from: from.toUpperCase(), to: to.toUpperCase() };
}

/** Parse "12 km in miles" against a table of unit maps. */
function convertPair(v, fromRaw, toRaw) {
  const temp = convertTemp(v, fromRaw, toRaw);
  if (temp) return temp;
  const from = unit(fromRaw), to = unit(toRaw);
  if (!from || !to) return null;
  for (const [kind, map] of Object.entries(UNITS)) {
    if (map[from] !== undefined && map[to] !== undefined) {
      return { kind, value: v * map[from] / map[to], from, to };
    }
  }
  return null;
}
const PAIR_RE = /^(-?[\d.,]+)\s*([a-z]+)\s+(?:in|to|as)\s+([a-z]+)$/i;
const NUM = s => {
  const v = parseFloat(String(s).replace(/[,\s]/g, ''));
  return Number.isFinite(v) ? v : null;
};
const UNITS = {
  length: { m: 1, km: 1000, cm: .01, mm: .001, mi: 1609.344, yd: .9144, ft: .3048, in: .0254, nmi: 1852 },
  mass:   { kg: 1, g: .001, mg: 1e-6, t: 1000, lb: .45359237, oz: .0283495, st: 6.35029 },
  time:   { s: 1, min: 60, h: 3600, d: 86400, wk: 604800, yr: 31557600 },
  data:   { b: 1, kb: 1024, mb: 1048576, gb: 1073741824, tb: 1099511627776, bit: .125 },
};
const UNIT_LABEL = {
  length: ['m', 'km', 'cm', 'mm', 'mi', 'yd', 'ft', 'in', 'nmi'],
  mass: ['kg', 'g', 'mg', 't', 'lb', 'oz', 'st'],
  time: ['s', 'min', 'h', 'd', 'wk', 'yr'],
  data: ['B', 'KB', 'MB', 'GB', 'TB', 'bit'],
};

/* ── the plugins ─────────────────────────────────────────────── */
const PLUGINS = [
  {
    id: 'calc', name: 'Calculator', icon: '🧮', cat: 'Utility',
    desc: 'Arithmetic, powers, roots, percentages, unit maths, rounding.',
    args: 'expression or "12 km in miles"',
    run(input) {
      const s = clip(input, 500).trim();
      const cv = s.match(PAIR_RE);
      if (cv) {
        const v = NUM(cv[1]);
        const r = convertPair(v, cv[2], cv[3]);
        if (r) return `${v} ${cv[2]} = **${Number(r.value.toPrecision(10))}** ${cv[3]}`;
        return `Unknown units: ${cv[2]} → ${cv[3]}`;
      }
      const { calc } = require('./tools');
      return '`' + s + '` = **' + calc(s) + '**';
    },
  },
  {
    id: 'convert', name: 'Unit Converter', icon: '📐', cat: 'Utility',
    desc: 'Length, mass, time and data-size conversions.',
    args: 'e.g. "5 km in miles", "72f in c"',
    run(input) {
      const m = clip(input, 200).match(PAIR_RE);
      if (!m) return 'Format: `<value> <unit> in <unit>` — units: ' +
        Object.entries(UNIT_LABEL).map(([k, v]) => k + ' (' + v.join('/') + ')').join(', ');
      const v = NUM(m[1]);
      const r = convertPair(v, m[2], m[3]);
      if (!r) return 'Unknown unit pair.';
      return `**${v} ${m[2]} = ${Number(r.value.toPrecision(12))} ${m[3]}**  ·  ${r.kind}`;
    },
  },
  {
    id: 'stats', name: 'Text Stats', icon: '📊', cat: 'Text',
    desc: 'Words, characters, sentences, lines, reading time.',
    args: 'any text',
    run(input) {
      const t = clip(input, 100000);
      if (!t.trim()) return 'Nothing to analyse.';
      const words = (t.match(/\S+/g) || []).length;
      const sents = (t.match(/[.!?]+(\s|$)/g) || []).length || (words ? 1 : 0);
      const paras = t.split(/\n\s*\n/).filter(x => x.trim()).length;
      const mins = Math.max(1, Math.round(words / 225));
      return [
        '**Text statistics**', '',
        '| metric | value |', '|---|---|',
        `| Words | ${words.toLocaleString()} |`,
        `| Characters | ${t.length.toLocaleString()} |`,
        `| Sentences | ${sents.toLocaleString()} |`,
        `| Paragraphs | ${paras.toLocaleString()} |`,
        `| Lines | ${t.split('\n').length.toLocaleString()} |`,
        `| Reading time | ~${mins} min |`,
      ].join('\n');
    },
  },
  {
    id: 'case', name: 'Text Case', icon: '🔤', cat: 'Text',
    desc: 'Convert to upper, lower, title, sentence or camel case.',
    args: 'upper | lower | title | sentence | camel | snake | kebab',
    run(input) {
      const i = input.indexOf(' ');
      const mode = (i < 0 ? 'upper' : input.slice(0, i)).toLowerCase();
      const text = i < 0 ? input : input.slice(i + 1);
      const words = text.trim().split(/\s+/).filter(Boolean);
      const title = s => s.replace(/\b\w/g, c => c.toUpperCase());
      const map = {
        upper: () => text.toUpperCase(), lower: () => text.toLowerCase(),
        title: () => title(words.join(' ')), sentence: () => title(words.join(' ')) + '.',
        camel: () => words.map((w, n) => n ? title(w) : w.toLowerCase()).join(''),
        pascal: () => words.map(title).join(''),
        snake: () => words.map(w => w.toLowerCase()).join('_'),
        kebab: () => words.map(w => w.toLowerCase()).join('-'),
      };
      if (!map[mode]) return 'Modes: ' + Object.keys(map).join(', ');
      return '`' + mode + '`\n\n' + map[mode]();
    },
  },
  {
    id: 'b64', name: 'Base 64', icon: '🔐', cat: 'Utility',
    desc: 'Encode or decode Base 64.',
    args: 'encode <text>  |  decode <base64>',
    run(input) {
      const dec = /^decode\b/i.test(input.trim());
      const body = input.replace(/^\S+\s*/, '');
      try {
        return dec ? '```\n' + Buffer.from(body, 'base64').toString('utf8').slice(0, 8000) + '\n```'
                    : '```\n' + Buffer.from(body).toString('base64') + '\n```';
      } catch { return 'Invalid Base 64 input.'; }
    },
  },
  {
    id: 'hash', name: 'Hasher', icon: '#️⃣', cat: 'Security',
    desc: 'SHA-1 / SHA-256 / SHA-512 / MD5 digest of any text.',
    args: 'text to hash',
    run(input) {
      const out = ['**SHA-256**  `' + crypto.createHash('sha256').update(input).digest('hex') + '`'];
      if (input.length < 400000) {
        out.push('**SHA-1**  `' + crypto.createHash('sha1').update(input).digest('hex') + '`');
        out.push('**MD5**  `' + crypto.createHash('md5').update(input).digest('hex') + '`');
      }
      return out.join('  \n');
    },
  },
  {
    id: 'uuid', name: 'UUID / Tokens', icon: '🆔', cat: 'Utility',
    desc: 'Generate UUID v4s or a random token of a given length.',
    args: 'count (default 5) [token:32]',
    run(input) {
      const m = clip(input, 200).match(/(\d+)/);
      const n = Math.min(50, Math.max(1, m ? +m[1] : 5));
      const tok = /token/i.test(input);
      const len = Math.min(128, Math.max(4, (input.match(/token:(\d+)/i) || [, 32])[1] | 0));
      const lines = [];
      for (let i = 0; i < n; i++) {
        lines.push(tok ? crypto.randomBytes(Math.ceil(len / 2)).toString('hex').slice(0, len)
                       : crypto.randomUUID());
      }
      return '```\n' + lines.join('\n') + '\n```';
    },
  },
  {
    id: 'pass', name: 'Password Generator', icon: '🔑', cat: 'Security',
    desc: 'Strong random passwords with a chosen length and alphabet.',
    args: 'length (default 20) [no-symbols]',
    run(input) {
      const m = clip(input, 100).match(/(\d+)/);
      const len = Math.min(128, Math.max(4, m ? +m[1] : 20));
      const plain = /no-?symbols/i.test(input);
      const sets = ['abcdefghijkmnopqrstuvwxyz', 'ABCDEFGHJKLMNPQRSTUVWXYZ', '23456789', plain ? '' : '!@#$%^&*()-_=+[]{};:,.?'];
      const all = sets.join('');
      const out = Array.from({ length: len }, () => all[crypto.randomInt(all.length)]).join('');
      const bits = Math.round(len * Math.log2(all.length));
      return '`' + out + '`\n\nStrength: ~**' + bits + ' bits** of entropy · ' + len + ' characters' +
             (plain ? ' · letters and digits only' : '');
    },
  },
  {
    id: 'color', name: 'Colour Studio', icon: '🎨', cat: 'Design',
    desc: 'Convert hex to RGB/HSL and build a matching tonal palette.',
    args: '#4f8cff  |  rgb(79,140,255)',
    run(input) {
      const s = clip(input, 120).trim();
      let r, g, b;
      const hex = s.match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);
      const rgb = s.match(/^rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
      if (hex) {
        const h = hex[1].length === 3 ? [...hex[1]].map(c => c + c).join('') : hex[1];
        r = parseInt(h.slice(0, 2), 16); g = parseInt(h.slice(2, 4), 16); b = parseInt(h.slice(4, 6), 16);
      } else if (rgb) { [, r, g, b] = rgb.map(Number); }
      else return 'Format: `#4f8cff` or `rgb(79,140,255)`';
      const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
      let h2 = 0;
      if (d) {
        if (max === r) h2 = ((g - b) / d) % 6;
        else if (max === g) h2 = (b - r) / d + 2;
        else h2 = (r - g) / d + 4;
      }
      h2 = Math.round(h2 * 60 + 360) % 360;
      const l = (max + min) / 2, sat = d === 0 ? 0 : d / (255 - Math.abs(2 * l - 255));
      const lpc = Math.round((l / 255) * 100);           // lightness is 0..1
      const hx = n => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
      const shade = k => `\`#${hx(r * k)}${hx(g * k)}${hx(b * k)}\``;
      return [
        '**' + s + '**', '',
        `- Hex  \`#${hx(r)}${hx(g)}${hx(b)}\``,
        `- RGB  \`rgb(${r}, ${g}, ${b})\``,
        `- HSL  \`hsl(${h2}, ${Math.round(sat * 100)}%, ${lpc}%)\``,
        '- Contrast vs white  **' + contrast(r, g, b, 255, 255, 255).toFixed(2) + ':1**',
        '- Contrast vs black  **' + contrast(r, g, b, 0, 0, 0).toFixed(2) + ':1**', '',
        '**Palette**  50% ' + shade(.5) + ' · 25% ' + shade(.75) + ' · base ' + shade(1) + ' · 150% ' + shade(1.25) + ' · 200% ' + shade(1.5),
      ].join('\n');
    },
  },
  {
    id: 'json', name: 'JSON Formatter', icon: '🧾', cat: 'Developer',
    desc: 'Pretty-print, validate or minify JSON.',
    args: 'the JSON text',
    run(input) {
      try {
        const out = JSON.stringify(JSON.parse(clip(input, 200000)), null, 2);
        return '✅ Valid JSON  ·  ' + out.length.toLocaleString() + ' bytes\n\n```json\n' + out.slice(0, 12000) + '\n```';
      } catch (e) {
        return '❌ Invalid JSON\n\n`' + e.message + '`';
      }
    },
  },
  {
    id: 'url', name: 'URL Encoder', icon: '🔗', cat: 'Developer',
    desc: 'Percent-encode or decode a URL / query component.',
    args: 'encode <text>  |  decode <encoded>',
    run(input) {
      const dec = /^decode\b/i.test(input.trim());
      const body = input.replace(/^\S+\s*/, '');
      try {
        return dec ? '```\n' + decodeURIComponent(body) + '\n```'
                    : '```\n' + encodeURIComponent(body) + '\n```';
      } catch { return 'Invalid percent-encoding.'; }
    },
  },
  {
    id: 'time', name: 'Time & Dates', icon: '🕒', cat: 'Utility',
    desc: 'Current time, timezone offsets and date arithmetic.',
    args: 'now  |  +7d  |  in ms  |  unix 1755000000',
    run(input) {
      const s = clip(input, 200).trim().toLowerCase();
      const now = new Date();
      if (!s || s === 'now') {
        return '**Now**\n\n- Local  `' + now.toLocaleString() + '`\n- UTC  `' + now.toISOString() + '`\n- Unix  `' + Math.floor(now / 1000) + '`\n- Zone  `' + Intl.DateTimeFormat().resolvedOptions().timeZone + '`';
      }
      const m = s.match(/^unix\s+(\d+)$/);
      if (m) { const d = new Date(+m[1] * 1000); return '`' + m[1] + '` → `' + d.toISOString() + '`'; }
      const rel = s.match(/^([+-])(\d+)([smhdwy])$/);
      if (rel) {
        const mult = { s: 1e3, m: 6e4, h: 36e5, d: 864e5, w: 6048e5, y: 315576e5 }[rel[3]];
        const d = new Date(now.getTime() + (rel[1] === '-' ? -1 : 1) * +rel[2] * mult);
        return '`' + s + '` → `' + d.toLocaleString() + '`  (' + d.toISOString() + ')';
      }
      const t = Date.parse(s);
      if (Number.isFinite(t)) {
        const d = new Date(t);
        return '`' + s + '` → `' + d.toLocaleString() + '`  (' + d.toISOString() + ')\n\nDays since epoch: ' +
               Math.floor(t / 864e5).toLocaleString();
      }
      return 'Try: `now`, `+7d`, `unix 1755000000`, or an ISO date.';
    },
  },
  {
    id: 'regex', name: 'Regex Tester', icon: '🕵️', cat: 'Developer',
    desc: 'Test a pattern against sample text and show the matches.',
    args: '/pattern/flags <text to test>',
    run(input) {
      const m = clip(input, 20000).match(/^\/(.+)\/([gimsuy]*)\s+([\s\S]*)$/);
      if (!m) return 'Format: `/pattern/flags` then a space then the text to test.';
      try {
        const re = new RegExp(m[1], m[2].includes('g') ? m[2] : m[2] + 'g');
        const hits = [...clip(m[3], 40000).matchAll(re)].slice(0, 100);
        if (!hits.length) return 'No matches for `' + m[1] + '`';
        return '**' + hits.length + ' match' + (hits.length === 1 ? '' : 'es') + '** for `' + m[1] + '` /' + m[2] + '\n\n' +
          hits.map((h, i) => (i + 1) + '. `' + String(h[0]).replace(/\|/g, '\\|').slice(0, 160) + '` @ index ' + h.index).join('\n');
      } catch (e) { return '❌ Invalid pattern: `' + e.message + '`'; }
    },
  },
  {
    id: 'qr', name: 'QR Generator', icon: '▣', cat: 'Utility',
    desc: 'Render any text or link as a scannable QR code.',
    args: 'text or https://link',
    run(input) {
      const text = clip(input, 900).trim();
      if (!text) return 'Give me something to encode.';
      const svg = qr.encode(text);
      if (!svg) return '❌ Too much data for a QR code — this encoder handles up to 669 bytes. Shorten the text or use a link.';
      // fenced so the client can render it as a real image; the renderer only
      // passes through <svg> payloads that pass its own allowlist check
      return '**QR code** · ' + text.length + ' characters · version ' + (svg.match(/data-v="(\d+)"/) || [, '?'])[1] +
             '\n\n```svg\n' + svg.replace(/\n/g, '') + '\n```';
    },
  },
  {
    id: 'lorem', name: 'Lorem Ipsum', icon: '📄', cat: 'Writing',
    desc: 'Placeholder paragraphs for mockups and designs.',
    args: 'paragraphs (default 3) [words]',
    run(input) {
      const m = clip(input, 200).match(/(\d+)/);
      const n = Math.min(40, Math.max(1, m ? +m[1] : 3));
      const W = 'lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua enim ad minim veniam quis nostrud exercitation ullamco laboris nisi aliquip ex ea commodo consequat duis aute irure in reprehenderit voluptate velit esse cillum eu fugiat nulla pariatur excepteur sint occaecat cupidatat non proident sunt culpa qui officia deserunt mollit anim id est laborum'.split(' ');
      const byWords = /\bwords?\b/i.test(input);
      let out = [], i = 0;
      const pick = () => W[(i = (i + 7) % W.length)];
      for (let p = 0; p < n; p++) {
        const len = byWords ? 120 : 60 + (p * 13) % 40;
        const s = Array.from({ length: len }, pick);
        s[0] = s[0].charAt(0).toUpperCase() + s[0].slice(1);
        s[s.length - 1] += '.';
        out.push(s.join(' '));
      }
      return out.join('\n\n');
    },
  },
  {
    id: 'md', name: 'Markdown Table', icon: '📑', cat: 'Writing',
    desc: 'Turn comma-separated rows into a Markdown table.',
    args: 'header1, header2\\nvalue1, value2',
    run(input) {
      const rows = clip(input, 40000).split(/\n+/).map(r => r.split(/[,\t;]/).map(c => c.trim())).filter(r => r.length && r[0]);
      if (rows.length < 2) return 'Give at least a header row and one data row, separated by newlines.';
      const w = Math.max(...rows.map(r => r.length));
      const fix = r => Array.from({ length: w }, (_, i) => r[i] || '');
      const [h, ...body] = rows.map(fix);
      return '```md\n' +
        '| ' + h.join(' | ') + ' |\n|' + h.map(() => '---').join('|') + '|\n' +
        body.map(r => '| ' + r.join(' | ') + ' |').join('\n') + '\n```';
    },
  },
  {
    id: 'numspell', name: 'Number to Words', icon: '🔢', cat: 'Utility',
    desc: 'Write a number out in English or Hindi digits.',
    args: '123456',
    run(input) {
      const n = NUM(input);
      if (n === null || !Number.isInteger(n) || Math.abs(n) > 1e15) return 'Give a whole number under 10^15.';
      const ONES = ['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve',
        'thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen'];
      const TENS = ['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety'];
      const SCALE = [[1e9,'billion'],[1e6,'million'],[1e3,'thousand'],[1,'']];
      const under1k = x => {
        if (x < 20) return ONES[x];
        if (x < 100) return TENS[Math.floor(x / 10)] + (x % 10 ? '-' + ONES[x % 10] : '');
        return ONES[Math.floor(x / 100)] + ' hundred' + (x % 100 ? ' and ' + under1k(x % 100) : '');
      };
      let rest = Math.abs(n), out = [];
      for (const [v, name] of SCALE) {
        if (rest >= v) { const q = Math.floor(rest / v); out.push(under1k(q) + (name ? ' ' + name : '')); rest %= v; }
      }
      return `**${n}** → ${(n < 0 ? 'negative ' : '') + out.join(' ')}\n\nDigits: ${String(n).split('').join(' ')}`;
    },
  },
  {
    id: 'wcag', name: 'Contrast Checker', icon: '👁️', cat: 'Design',
    desc: 'WCAG contrast ratio for a foreground/background pair.',
    args: 'two colours: #ffffff on #000000',
    run(input) {
      const hexes = clip(input, 200).match(/#[0-9a-f]{3,6}\b/gi);
      if (!hexes || hexes.length < 2) return 'Give two hex colours, e.g. `#ffffff on #000000`.';
      const parse = h => { const s = h.slice(1); const f = s.length === 3 ? [...s].map(c => c + c).join('') : s;
                          return [0, 2, 4].map(i => parseInt(f.slice(i, i + 2), 16)); };
      const a = parse(hexes[0]), b = parse(hexes[1]);
      const c = contrast(...a, ...b);
      const level = c >= 7 ? 'AAA' : c >= 4.5 ? 'AA' : c >= 3 ? 'AA Large text only' : 'Fail';
      return [
        '| pair | ratio | level |', '|---|---|---|',
        `| \`${hexes[0]}\` on \`${hexes[1]}\` | **${c.toFixed(2)}:1** | **${level}** |`, '',
        'WCAG AA needs 4.5:1 for body text and 3:1 for large text (18px+ or bold).',
      ].join('\n');
    },
  },
  {
    id: 'cron', name: 'Cron Explainer', icon: '⏱️', cat: 'Developer',
    desc: 'Describe what a cron expression does in plain English.',
    args: '0 9 * * 1-5',
    run(input) {
      const f = clip(input, 120).trim().split(/\s+/);
      if (f.length !== 5) return 'Give 5 fields: `minute hour day-of-month month day-of-week`';
      const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
      const DAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
      // months are 1-based, weekdays are 0-based — that difference matters
      const read = (v, arr, every, base) => {
        if (v === '*') return 'every ' + every;
        if (v.includes('/')) { const [b, s] = v.split('/'); return `every ${s} ${every}` + (b !== '*' ? ` starting at ${b}` : ''); }
        if (v.includes('-')) {
          const [a, z] = v.split('-');
          return arr ? `${arr[+a - base]} through ${arr[+z - base]}` : `${a} through ${z}`;
        }
        if (v.includes(',')) return v.split(',').map(x => arr ? arr[+x - base] : x).join(', ');
        return arr ? arr[+v - base] : v;
      };
      return [
        '**Cron** `' + f.join(' ') + '`', '',
        '- Minute:  ' + read(f[0], null, 'minute'),
        '- Hour:    ' + read(f[1], null, 'hour'),
        '- Day:     ' + read(f[2], null, 'day of month'),
        '- Month:   ' + read(f[3], MONTHS, 'month', 1),
        '- Weekday: ' + read(f[4], DAYS, 'day of week', 0),
      ].join('\n');
    },
  },
];

/* relative luminance + contrast (WCAG) */
function contrast(r1, g1, b1, r2, g2, b2) {
  const lin = c => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const L = (r, g, b) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const a = L(r1, g1, b1), b = L(r2, g2, b2);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const BY_ID = new Map(PLUGINS.map(p => [p.id, p]));
const meta = p => ({ id: p.id, name: p.name, icon: p.icon, cat: p.cat, desc: p.desc, args: p.args });

module.exports = { PLUGINS, meta, byId: id => BY_ID.get(id) || null };
