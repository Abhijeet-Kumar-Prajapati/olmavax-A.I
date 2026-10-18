'use strict';
/**
 * Minimal PDF writer — no dependencies.
 *
 * Produces a valid PDF 1.4 document from an array of text blocks. Used by the
 * "Save as PDF" action in the top bar. Latin-1 text is written directly;
 * anything outside it is transliterated so the file always opens cleanly
 * rather than throwing at export time.
 */

const PAGE_W = 595.28, PAGE_H = 841.89;   // A4 at 72 dpi
const MARGIN = 56;
const LEADING = 15;
const FONT_SIZE = 11;

/** Replace characters a base-14 PDF font cannot encode. */
function sanitise(s) {
  return String(s == null ? '' : s)
    // curly quotes → straight
    .replace(/[‘’‛]/g, "'")
    .replace(/[“”‟]/g, '"')
    // dashes
    .replace(/[–—]/g, '-')
    .replace(/…/g, '...')
    .replace(/ /g, ' ')
    .replace(/[→⇒]/g, '->')
    .replace(/[←⇐]/g, '<-')
    .replace(/[×✕]/g, 'x')
    .replace(/[•·]/g, '*')
    // emoji and anything else outside Latin-1
    .replace(/[^\x09\x0A\x0D\x20-\x7E\xA0-\xFF]/g, '')
    .replace(/\s+$/, '');
}

function wrap(text, max) {
  const out = [];
  for (const para of String(text).split('\n')) {
    if (!para.trim()) { out.push(''); continue; }
    let line = '';
    for (const word of para.split(/\s+/)) {
      if (!line.length) { line = word; continue; }
      if ((line + ' ' + word).length > max) { out.push(line); line = word; }
      else line += ' ' + word;
    }
    if (line) out.push(line);
  }
  return out;
}

/**
 * @param {{title?:string, blocks:Array<{text:string,bold?:boolean,mono?:boolean,size?:number,gap?:number}>}} doc
 * @returns {Buffer}
 */
function renderPDF(doc = {}) {
  const blocks = (doc.blocks || []).filter(Boolean);
  const maxChars = Math.floor((PAGE_W - MARGIN * 2) / (FONT_SIZE * 0.5));

  // ── lay out every line, assigning it a font
  const lines = [];
  const push = (text, font, size, gapBefore) => {
    for (const l of wrap(sanitise(text), Math.floor((PAGE_W - MARGIN * 2) / (size * 0.5)))) {
      lines.push({ text: l, font, size, gap: lines.length ? gapBefore : 0 });
      gapBefore = 0;
    }
  };

  if (doc.title) push(doc.title, 'F2', 20, 0);
  for (const b of blocks) {
    const size = b.size || (b.mono ? 10 : FONT_SIZE);
    const font = b.mono ? 'F3' : b.bold ? 'F2' : 'F1';
    push(b.text, font, size, b.gap === undefined ? 6 : b.gap);
  }
  if (!lines.length) lines.push({ text: ' ', font: 'F1', size: FONT_SIZE, gap: 0 });

  // ── paginate
  const usable = PAGE_H - MARGIN * 2;
  const pages = [];
  let cur = [], h = 0;
  for (const l of lines) {
    const add = l.size * 1.35 + l.gap;
    if (h + add > usable && cur.length) { pages.push(cur); cur = []; h = 0; }
    h += add;
    cur.push({ ...l, dy: h });
  }
  if (cur.length) pages.push(cur);
  if (!pages.length) pages.push([{ text: ' ', font: 'F1', size: FONT_SIZE, dy: FONT_SIZE, gap: 0 }]);

  // ── serialise
  const objects = [];
  const add = body => { objects.push(body); return objects.length; };

  const fontIds = { F1: add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'),
                    F2: add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'),
                    F3: add('<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>') };
  const fontRes = Object.entries(fontIds).map(([k, v]) => '/' + k + ' ' + v + ' 0 R').join(' ');

  const pageIds = [];
  const contentIds = [];

  for (const page of pages) {
    let stream = '';
    for (const l of page) {
      const esc = l.text.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
      stream += 'BT /' + l.font + ' ' + l.size + ' Tf 1 0 0 1 ' + MARGIN.toFixed(2) +
                ' ' + (PAGE_H - MARGIN - l.dy).toFixed(2) + ' Tm (' + esc + ') Tj ET\n';
    }
    contentIds.push(add('<< /Length ' + Buffer.byteLength(stream, 'latin1') + ' >>\nstream\n' + stream + 'endstream'));
  }

  const pagesId = objects.length + pages.length + 1;   // reserved, patched below
  for (let i = 0; i < pages.length; i++) {
    pageIds.push(add(
      '<< /Type /Page /Parent ' + pagesId + ' 0 R ' +
      '/MediaBox [0 0 ' + PAGE_W.toFixed(2) + ' ' + PAGE_H.toFixed(2) + '] ' +
      '/Resources << /Font << ' + fontRes + ' >> >> ' +
      '/Contents ' + contentIds[i] + ' 0 R >>'));
  }
  const realPagesId = add('<< /Type /Pages /Count ' + pages.length + ' /Kids [' +
                          pageIds.map(i => i + ' 0 R').join(' ') + '] >>');
  const infoId = add('<< /Title (' + sanitise(doc.title || 'Olmavax A.I').replace(/[()\\]/g, '') + ') ' +
                    '/Producer (Olmavax A.I) /Creator (Olmavax A.I) >>');
  const catalogId = add('<< /Type /Catalog /Pages ' + realPagesId + ' 0 R >>');

  let out = '%PDF-1.4\n%\xE2\xE3\xCF\xD3\n';
  const offsets = [0];
  objects.forEach((body, i) => {
    offsets[i + 1] = Buffer.byteLength(out, 'latin1');
    out += (i + 1) + ' 0 obj\n' + body + '\nendobj\n';
  });
  const xrefAt = Buffer.byteLength(out, 'latin1');
  out += 'xref\n0 ' + (objects.length + 1) + '\n0000000000 65535 f \n';
  for (let i = 1; i <= objects.length; i++) out += String(offsets[i]).padStart(10, '0') + ' 00000 n \n';
  out += 'trailer\n<< /Size ' + (objects.length + 1) + ' /Root ' + catalogId +
         ' 0 R /Info ' + infoId + ' 0 R >>\nstartxref\n' + xrefAt + '\n%%EOF\n';

  return Buffer.from(out, 'latin1');
}

module.exports = { renderPDF };
