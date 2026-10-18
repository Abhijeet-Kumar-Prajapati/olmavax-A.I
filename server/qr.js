'use strict';
/**
 * Minimal but correct QR Code encoder (byte mode, EC level M).
 * Implements Reed–Solomon over GF(256), version selection, mask scoring and
 * the format/version information blocks. No dependencies.
 *
 * Reference: ISO/IEC 18004. Supports versions 1–20 (up to ~1273 bytes),
 * which is far more than the plugin needs.
 */

// ── GF(256) arithmetic, primitive polynomial 0x11d ─────────────
const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
(function initTables() {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x; LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
})();
const mul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]];

/** Reed–Solomon generator polynomial for `degree` error-correction words. */
function rsPoly(degree) {
  let p = [1];
  for (let i = 0; i < degree; i++) {
    const next = new Array(p.length + 1).fill(0);
    for (let j = 0; j < p.length; j++) {
      next[j] ^= mul(p[j], EXP[i]);
      next[j + 1] ^= p[j];
    }
    p = next;
  }
  return p;
}

/** Divide `data` by the generator poly, returning `degree` ECC bytes. */
function rsEncode(data, degree) {
  const gen = rsPoly(degree);
  const rem = new Uint8Array(degree);
  for (const b of data) {
    const factor = b ^ rem[0];
    rem.copyWithin(0, 1);
    rem[degree - 1] = 0;
    if (factor !== 0) for (let i = 0; i < degree; i++) rem[i] ^= mul(gen[i + 1], factor);
  }
  return rem;
}

// ── block layout tables, EC level M ─────────────────────────────
// Per version: [ecCodewordsPerBlock, group1Blocks, group1DataCw, group2Blocks, group2DataCw]
const LAYOUT_M = {
  1:  [10, 1, 16, 0, 0],     2:  [16, 1, 28, 0, 0],     3:  [26, 1, 44, 0, 0],
  4:  [18, 2, 32, 0, 0],     5:  [24, 2, 43, 0, 0],     6:  [16, 4, 27, 0, 0],
  7:  [18, 4, 31, 0, 0],     8:  [22, 2, 38, 2, 39],   9:  [22, 3, 36, 2, 37],
  10: [26, 4, 43, 1, 44],   11: [30, 1, 50, 4, 51],   12: [22, 6, 36, 2, 37],
  13: [22, 8, 37, 1, 38],   14: [24, 4, 40, 5, 41],   15: [24, 5, 41, 5, 42],
  16: [28, 7, 45, 3, 46],   17: [28, 10, 46, 1, 47],  18: [26, 9, 43, 4, 44],
  19: [26, 3, 44, 11, 45],  20: [26, 3, 41, 13, 42],
};
const ALIGN = {
  1: [], 2: [6,18], 3: [6,22], 4: [6,26], 5: [6,30], 6: [6,34], 7: [6,22,38],
  8: [6,24,42], 9: [6,26,46], 10: [6,28,50], 11: [6,30,54], 12: [6,32,58],
  13: [6,34,62], 14: [6,26,46,66], 15: [6,26,48,70], 16: [6,26,50,74], 17: [6,30,54,78],
  18: [6,30,56,82], 19: [6,30,58,86], 20: [6,34,62,90],
};
const size = v => v * 4 + 17;

/** Build the interleaved codeword stream for a byte-mode message. */
function buildCodewords(bytes, version) {
  const [eccPerBlock, g1, g1Data, g2, g2Data] = LAYOUT_M[version];
  const totalData = g1 * g1Data + g2 * g2Data;

  const bits = [];
  const push = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1); };
  push(0b0100, 4);                                   // byte mode
  push(bytes.length, version < 10 ? 8 : 16);         // char count
  for (const b of bytes) push(b, 8);

  const capacityBits = totalData * 8;
  push(0, Math.min(4, capacityBits - bits.length));  // terminator
  while (bits.length % 8) bits.push(0);              // byte align

  const data = new Uint8Array(totalData);
  for (let i = 0; i < bits.length; i += 8) {
    let v = 0; for (let j = 0; j < 8; j++) v = (v << 1) | bits[i + j];
    data[i >> 3] = v;
  }
  // pad with the two alternating pad bytes
  const PADS = [0xEC, 0x11];
  for (let i = bits.length / 8, k = 0; i < totalData; i++, k++) data[i] = PADS[k % 2];

  // split into blocks, compute ECC, then interleave
  const blocks = [];
  let off = 0;
  for (let i = 0; i < g1; i++) { const d = data.slice(off, off + g1Data); off += g1Data; blocks.push({ d, e: rsEncode(d, eccPerBlock) }); }
  for (let i = 0; i < g2; i++) { const d = data.slice(off, off + g2Data); off += g2Data; blocks.push({ d, e: rsEncode(d, eccPerBlock) }); }

  const out = [];
  const maxD = Math.max(g1Data, g2Data);
  for (let i = 0; i < maxD; i++) for (const b of blocks) if (i < b.d.length) out.push(b.d[i]);
  for (let i = 0; i < eccPerBlock; i++) for (const b of blocks) out.push(b.e[i]);
  return out;
}

/** Module grid helpers ------------------------------------------------ */
function makeMatrix(version) {
  const n = size(version);
  const m = Array.from({ length: n }, () => new Int8Array(n).fill(-1)); // -1 = free
  const reserved = Array.from({ length: n }, () => new Uint8Array(n));

  const setFinder = (r, c) => {
    for (let i = -1; i <= 7; i++) for (let j = -1; j <= 7; j++) {
      const rr = r + i, cc = c + j;
      if (rr < 0 || rr >= n || cc < 0 || cc >= n) continue;
      const inner = i >= 0 && i <= 6 && j >= 0 && j <= 6;
      const edge = i === 0 || i === 6 || j === 0 || j === 6;
      const core = i >= 2 && i <= 4 && j >= 2 && j <= 4;
      m[rr][cc] = (inner && (edge || core)) ? 1 : 0;
      reserved[rr][cc] = 1;
    }
  };
  setFinder(0, 0); setFinder(0, n - 7); setFinder(n - 7, 0);

  // timing patterns
  for (let i = 8; i < n - 8; i++) {
    const v = i % 2 === 0 ? 1 : 0;
    m[6][i] = v; reserved[6][i] = 1;
    m[i][6] = v; reserved[i][6] = 1;
  }

  // alignment patterns
  const spots = ALIGN[version] || [];
  for (const r of spots) for (const c of spots) {
    if ((r === 6 && c === 6) || (r === 6 && c === n - 7) || (r === n - 7 && c === 6)) continue;
    for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) {
      const ring = Math.max(Math.abs(i), Math.abs(j));
      m[r + i][c + j] = ring === 1 ? 0 : 1;
      reserved[r + i][c + j] = 1;
    }
  }

  // reserve format areas (values written later)
  for (let i = 0; i < 9; i++) {
    if (m[8][i] === -1) { m[8][i] = 0; reserved[8][i] = 1; }
    if (m[i][8] === -1) { m[i][8] = 0; reserved[i][8] = 1; }
  }
  for (let i = 0; i < 8; i++) {
    if (m[8][n - 1 - i] === -1) { m[8][n - 1 - i] = 0; reserved[8][n - 1 - i] = 1; }
    if (m[n - 1 - i][8] === -1) { m[n - 1 - i][8] = 0; reserved[n - 1 - i][8] = 1; }
  }
  // the always-dark module
  m[n - 8][8] = 1; reserved[n - 8][8] = 1;

  // version information (version >= 7)
  if (version >= 7) {
    let rem = version;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
    const bitsV = (version << 12) | (rem & 0xFFF);
    for (let i = 0; i < 18; i++) {
      const bit = (bitsV >> i) & 1, r = Math.floor(i / 3), c = i % 3;
      m[r][n - 11 + c] = bit; reserved[r][n - 11 + c] = 1;
      m[n - 11 + c][r] = bit; reserved[n - 11 + c][r] = 1;
    }
  }
  return { m, reserved, n };
}

const MASKS = [
  (r, c) => (r + c) % 2 === 0,
  (r, c) => r % 2 === 0,
  (r, c) => c % 3 === 0,
  (r, c) => (r + c) % 3 === 0,
  (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
  (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
  (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
  (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
];

function placeData(grid, codewords) {
  const { m, reserved, n } = grid;
  let bitIdx = 0;
  const totalBits = codewords.length * 8;
  const bitAt = i => (codewords[i >> 3] >> (7 - (i & 7))) & 1;
  let upward = true;
  for (let col = n - 1; col > 0; col -= 2) {
    if (col === 6) col--;                       // skip vertical timing column
    for (let k = 0; k < n; k++) {
      const row = upward ? n - 1 - k : k;
      for (const c of [col, col - 1]) {
        if (reserved[row][c]) continue;
        m[row][c] = bitIdx < totalBits ? bitAt(bitIdx) : 0;
        bitIdx++;
      }
    }
    upward = !upward;
  }
}

/** Bit length of an integer. */
function bitLen(x) { let n = 0; while (x) { n++; x >>>= 1; } return n; }

/**
 * BCH(15,5) format information for EC level M (0b00) and a given mask.
 * The generator 0b537 has degree 10, so the remainder must be reduced until
 * its degree drops below 10 — a single descending pass is not enough because
 * the XOR can set a higher bit again.
 */
function formatBits(mask) {
  const data = (0b00 << 3) | mask;               // EC level M = 0b00
  const G = 0b10100110111;                       // 0x537
  let rem = data << 10;
  while (bitLen(rem) - 1 >= 10) rem ^= G << (bitLen(rem) - 1 - 10);
  return ((data << 10) | rem) ^ 0b101010000010010;
}

function applyFormat(grid, mask) {
  const { m, n } = grid;
  const f = formatBits(mask);
  for (let i = 0; i < 15; i++) {
    const bit = (f >> i) & 1;
    // copy 1 — around the top-left finder
    if (i < 6) m[8][i] = bit;
    else if (i < 8) m[8][i + 1] = bit;
    else if (i === 8) m[7][8] = bit;
    else m[14 - i][8] = bit;
    // copy 2
    if (i < 8) m[n - 1 - i][8] = bit;
    else m[8][n - 15 + i] = bit;
  }
  m[n - 8][8] = 1;
}

/** Penalty score used to choose the least-noisy mask. */
function penalty(m, n) {
  let p = 0;
  const line = (get, len) => {
    let run = 1;
    for (let i = 1; i < len; i++) {
      if (get(i) === get(i - 1)) run++;
      else { if (run >= 5) p += 3 + (run - 5); run = 1; }
    }
    if (run >= 5) p += 3 + (run - 5);
  };
  for (let i = 0; i < n; i++) {
    line(j => m[i][j], n);
    line(j => m[j][i], n);
  }
  // 2x2 blocks
  for (let i = 0; i < n - 1; i++) for (let j = 0; j < n - 1; j++) {
    const v = m[i][j];
    if (v === m[i][j + 1] && v === m[i + 1][j] && v === m[i + 1][j + 1]) p += 3;
  }
  // finder-like patterns
  const pat1 = [1,0,1,1,1,0,1,0,0,0,0], pat2 = [0,0,0,0,1,0,1,1,1,0,1];
  for (let i = 0; i < n; i++) for (let j = 0; j + 11 <= n; j++) {
    let a = 1, b = 1;
    for (let k = 0; k < 11; k++) {
      if (m[i][j + k] !== pat1[k]) a = 0;
      if (m[i][j + k] !== pat2[k]) b = 0;
      if (m[j + k][i] !== pat1[k]) a = 0;
      if (m[j + k][i] !== pat2[k]) b = 0;
    }
    p += (a ? 40 : 0) + (b ? 40 : 0);
  }
  // dark/light balance
  let dark = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) dark += m[i][j];
  const ratio = Math.abs((dark * 100) / (n * n) - 50);
  p += Math.floor(ratio / 5) * 10;
  return p;
}

function toMatrix(text) {
  const bytes = Array.from(Buffer.from(String(text), 'utf8'));

  let version = 0;
  for (let v = 1; v <= 20; v++) {
    const [e, g1, d1, g2, d2] = LAYOUT_M[v];
    const capacity = g1 * d1 + g2 * d2;
    const needBits = 4 + (v < 10 ? 8 : 16) + bytes.length * 8;
    if (needBits <= capacity * 8) { version = v; break; }
  }
  if (!version) return null;

  const codewords = buildCodewords(bytes, version);
  const base = makeMatrix(version);

  let best = null;
  for (let mask = 0; mask < 8; mask++) {
    const g = makeMatrix(version);
    placeData(g, codewords);
    for (let r = 0; r < g.n; r++) for (let c = 0; c < g.n; c++) {
      if (!g.reserved[r][c]) g.m[r][c] ^= MASKS[mask](r, c) ? 1 : 0;
    }
    applyFormat(g, mask);
    const score = penalty(g.m, g.n);
    if (!best || score < best.score) best = { score, m: g.m, n: g.n, reserved: g.reserved };
  }
  return { version, size: base.n, modules: best.m, reserved: best.reserved };
}

/**
 * Encode text as a standalone SVG QR code.
 * @returns {string|null} SVG markup, or null when the payload is too large.
 */
function encode(text) {
  const r = toMatrix(text);
  if (!r) return null;
  const { size: n, modules: m, version } = r;
  const quiet = 4, total = n + quiet * 2;
  let d = '';
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      if (m[y][x]) d += 'M' + (x + quiet) + ' ' + (y + quiet) + 'h1v1h-1z';
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${total}" width="220" height="220" data-v="${version}" role="img" aria-label="QR code">
<rect width="${total}" height="${total}" fill="#fff"/>
<path d="${d}" fill="#000"/>
</svg>`;
}

module.exports = { encode, toMatrix, size };
