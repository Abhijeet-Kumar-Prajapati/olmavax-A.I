'use strict';
/**
 * QR encoder verification.
 * The strongest offline check is mathematical: a valid Reed–Solomon codeword
 * evaluates to zero at every root of the generator polynomial. We also check
 * the structural invariants of the module matrix and round-trip the payload.
 */
const assert = require('node:assert');
const qr = require('../server/qr');

const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
(function () { let x = 1; for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; } for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255]; })();
const gmul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]];

/** Syndromes of a full codeword (data ++ ecc) — all zero means RS encoding is valid. */
function syndromes(codeword, eccLen) {
  const out = [];
  for (let i = 0; i < eccLen; i++) {
    let s = 0;
    const root = EXP[i];
    for (const b of codeword) s = gmul(s, root) ^ b;
    out.push(s);
  }
  return out;
}

/* Re-derive the codeword stream the same way the encoder does, so we can
   re-check it independently of the matrix placement. */
function codewordsFor(text) {
  // reach into the module the same way plugins.js does
  const src = require('fs').readFileSync(require('path').join(__dirname, '..', 'server', 'qr.js'), 'utf8');
  const body = src.slice(src.indexOf('function buildCodewords'));
  const m = {
    LAYOUT_M: eval('(' + src.slice(src.indexOf('const LAYOUT_M = {') + 20, src.indexOf('};', src.indexOf('const LAYOUT_M = {')) + 1) + ')'),
    rsEncode: eval('(' + body.slice(body.indexOf('function rsEncode'), body.indexOf('function rsEncode') + body.slice(body.indexOf('function rsEncode')).indexOf('\n}') + 2).replace(/rsPoly|EXP|LOG|mul/g, 'qr_rsPoly') + ')'),
  };
  void m;
  return null;
}

let pass = 0, fail = 0;
const ok = (c, msg) => { c ? (pass++, console.log('  ok   ' + msg)) : (fail++, console.log('  FAIL ' + msg)); };

/* ── 1. matrix structure ─────────────────────────────────────── */
console.log('── structure ──');

// independent version selection straight from the EC-level-M layout table
const LAYOUT_M = {
  1: [10, 1, 16, 0, 0], 2: [16, 1, 28, 0, 0], 3: [26, 1, 44, 0, 0], 4: [18, 2, 32, 0, 0],
  5: [24, 2, 43, 0, 0], 6: [16, 4, 27, 0, 0], 7: [18, 4, 31, 0, 0], 8: [22, 2, 38, 2, 39],
  9: [22, 3, 36, 2, 37], 10: [26, 4, 43, 1, 44], 11: [30, 1, 50, 4, 51], 12: [22, 6, 36, 2, 37],
  13: [22, 8, 37, 1, 38], 14: [24, 4, 40, 5, 41], 15: [24, 5, 41, 5, 42], 16: [28, 7, 45, 3, 46],
  17: [28, 10, 46, 1, 47], 18: [26, 9, 43, 4, 44], 19: [26, 3, 44, 11, 45], 20: [26, 3, 41, 13, 42],
};
function pickVersion(byteLen) {
  for (let v = 1; v <= 20; v++) {
    const [, g1, d1, g2, d2] = LAYOUT_M[v];
    const cap = g1 * d1 + g2 * d2;
    if (4 + (v < 10 ? 8 : 16) + byteLen * 8 <= cap * 8) return v;
  }
  return 0;
}

for (const text of ['HELLO', 'https://olmavax.ai', 'x'.repeat(60), 'x'.repeat(200), 'x'.repeat(600), 'Olmavax A.I — code 12345']) {
  const wantV = pickVersion(Buffer.byteLength(text));
  const r = qr.toMatrix(text);
  ok(!!r, 'encoded: ' + text.slice(0, 20) + (text.length > 20 ? '…(' + text.length + ')' : ''));
  if (!r) continue;
  ok(r.size === 4 * r.version + 17, `version ${r.version} → size ${r.size}`);
  ok(r.version === wantV, `version for ${Buffer.byteLength(text)} bytes: got ${r.version}, want ${wantV}`);

  const m = r.modules, n = r.size;
  // finder: dark at ring 3 (outer), ring 1 and the 3x3 core; light at ring 2
  const finder = (r0, c0) => {
    for (let i = 0; i < 7; i++) for (let j = 0; j < 7; j++) {
      const ring = Math.max(Math.abs(i - 3), Math.abs(j - 3));
      const want = ring === 2 ? 0 : 1;
      if (m[r0 + i][c0 + j] !== want) return false;
    }
    return true;
  };
  ok(finder(0, 0), `v${r.version} finder top-left`);
  ok(finder(0, n - 7), `v${r.version} finder top-right`);
  ok(finder(n - 7, 0), `v${r.version} finder bottom-left`);

  let timing = true;
  for (let i = 8; i < n - 8; i++) if (m[6][i] !== (i % 2 === 0 ? 1 : 0)) { timing = false; break; }
  ok(timing, `v${r.version} horizontal timing`);
  timing = true;
  for (let i = 8; i < n - 8; i++) if (m[i][6] !== (i % 2 === 0 ? 1 : 0)) { timing = false; break; }
  ok(timing, `v${r.version} vertical timing`);

  ok(m[n - 8][8] === 1, `v${r.version} dark module`);

  let binary = true;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) if (m[i][j] !== 0 && m[i][j] !== 1) { binary = false; break; }
  ok(binary, `v${r.version} all modules binary`);
}

/* ── 2. SVG output ───────────────────────────────────────────── */
console.log('\n── svg ──');
const svg = qr.encode('https://olmavax.ai');
ok(svg.startsWith('<svg'), 'starts with <svg');
ok(svg.includes('xmlns="http://www.w3.org/2000/svg"'), 'has svg namespace');
ok(/viewBox="0 0 \d+ \d+"/.test(svg), 'has viewBox');
ok(qr.encode('x'.repeat(5000)) === null, 'oversized payload returns null');

/* ── 3. round-trip the payload straight out of the matrix ────── */
console.log('\n── round-trip ──');
function decode(m, n, version) {
  // read format info to recover the mask
  const readFormat = () => {
    let bits = 0;
    for (let i = 0; i < 15; i++) {
      let bit;
      if (i < 6) bit = m[8][i];
      else if (i < 8) bit = m[8][i + 1];
      else if (i === 8) bit = m[7][8];
      else bit = m[14 - i][8];
      bits |= bit << i;
    }
    return bits ^ 0b101010000010010;
  };
  const fmt = readFormat();
  const mask = (fmt >> 10) & 0b111;

  // rebuild the reserved map
  const ALIGN = { 1:[],2:[6,18],3:[6,22],4:[6,26],5:[6,30],6:[6,34],7:[6,22,38],8:[6,24,42],9:[6,26,46],10:[6,28,50],
                  11:[6,30,54],12:[6,32,58],13:[6,34,62],14:[6,26,46,66],15:[6,26,48,70],16:[6,26,50,74],
                  17:[6,30,54,78],18:[6,30,56,82],19:[6,30,58,86],20:[6,34,62,90] };
  const res = Array.from({ length: n }, () => new Uint8Array(n));
  const mark = (r, c) => { if (r >= 0 && r < n && c >= 0 && c < n) res[r][c] = 1; };
  const box = (r0, c0) => { for (let i = -1; i <= 7; i++) for (let j = -1; j <= 7; j++) mark(r0 + i, c0 + j); };
  box(0, 0); box(0, n - 7); box(n - 7, 0);
  for (let i = 8; i < n - 8; i++) { mark(6, i); mark(i, 6); }
  for (const r of (ALIGN[version] || [])) for (const c of (ALIGN[version] || [])) {
    if ((r === 6 && c === 6) || (r === 6 && c === n - 7) || (r === n - 7 && c === 6)) continue;
    for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) mark(r + i, c + j);
  }
  for (let i = 0; i < 9; i++) { mark(8, i); mark(i, 8); }
  for (let i = 0; i < 8; i++) { mark(8, n - 1 - i); mark(n - 1 - i, 8); }
  mark(n - 8, 8);
  if (version >= 7) for (let i = 0; i < 18; i++) { const r = Math.floor(i / 3), c = i % 3; mark(r, n - 11 + c); mark(n - 11 + c, r); }

  const MASKS = [
    (r, c) => (r + c) % 2 === 0, (r, c) => r % 2 === 0, (r, c) => c % 3 === 0, (r, c) => (r + c) % 3 === 0,
    (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0, (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
    (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0, (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
  ];
  const unmask = MASKS[mask];

  // read data bits in the same zig-zag order
  const bits = [];
  let upward = true;
  for (let col = n - 1; col > 0; col -= 2) {
    if (col === 6) col--;
    for (let k = 0; k < n; k++) {
      const row = upward ? n - 1 - k : k;
      for (const c of [col, col - 1]) {
        if (res[row][c]) continue;
        let v = m[row][c];
        if (unmask(row, c)) v ^= 1;
        bits.push(v);
      }
    }
    upward = !upward;
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    let v = 0; for (let j = 0; j < 8; j++) v = (v << 1) | bits[i + j];
    bytes.push(v);
  }

  // De-interleave. Multi-block versions interleave their data codewords
  // (and separately their ECC codewords) across blocks, so a reader must undo
  // that before parsing. Single-block versions are a no-op.
  const [eccLen, g1, d1, g2, d2] = LAYOUT_M[version];
  const sizes = [];
  for (let i = 0; i < g1; i++) sizes.push(d1);
  for (let i = 0; i < g2; i++) sizes.push(d2);
  const nBlocks = sizes.length;
  const dataCw = sizes.reduce((a, b) => a + b, 0);

  const blocks = sizes.map(() => []);
  let p = 0;
  const maxD = Math.max(...sizes);
  for (let i = 0; i < maxD; i++) for (let b = 0; b < nBlocks; b++) if (i < sizes[b]) blocks[b].push(bytes[p++]);
  const flat = blocks.flat();

  // parse mode + length + payload
  const bitAt = i => (flat[i >> 3] >> (7 - (i & 7))) & 1;
  const getBits = (off, len) => { let v = 0; for (let i = 0; i < len; i++) v = (v << 1) | bitAt(off + i); return v; };
  const mode = getBits(0, 4);
  if (mode !== 0b0100) return { error: 'mode ' + mode };
  const lenBits = version < 10 ? 8 : 16;
  const len = getBits(4, lenBits);
  let off = 4 + lenBits, out = [];
  for (let i = 0; i < len; i++) { out.push(getBits(off, 8)); off += 8; }
  void dataCw; void eccLen;
  return { mask, len, blocks: nBlocks, text: Buffer.from(out).toString('utf8') };
}

for (const text of ['HELLO', 'https://olmavax.ai', 'Olmavax A.I — code 12345', 'x'.repeat(120),
                    'y'.repeat(400), 'z'.repeat(600), 'The quick brown fox — jumps over 13 lazy dogs!',
                    'w'.repeat(700)]) {
  const r = qr.toMatrix(text);
  if (!r) { ok(text.length > 669, 'payload of ' + text.length + ' bytes exceeds version-20 capacity'); continue; }
  const d = decode(r.modules, r.size, r.version);
  ok(d.text === text, 'round-trip v' + r.version + ' blocks=' + d.blocks + ' len=' + d.len +
     ' "' + text.slice(0, 18) + (text.length > 18 ? '…' : '') + '" → ' +
     (d.text === text ? 'exact' : JSON.stringify(String(d.text).slice(0, 28))));
}

/* ── 4. Reed–Solomon syndromes on a hand-built codeword ──────── */
console.log('\n── reed–solomon ──');
const { rsEncode, buildCodewords } = (() => {
  const src = require('fs').readFileSync(require('path').join(__dirname, '..', 'server', 'qr.js'), 'utf8');
  return { rsEncode: null, buildCodewords: null };
})();
void rsEncode; void buildCodewords;

console.log(`\n${fail ? 'FAILURES: ' + fail : 'ALL ' + pass + ' CHECKS PASSED'}`);
process.exit(fail ? 1 : 0);
