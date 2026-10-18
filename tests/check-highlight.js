'use strict';
/* Quick standalone check of the highlighter's tokenizer. */
const fs = require('fs');
const path = require('path');
const SRC = path.join(__dirname, '..', 'public', 'highlight.js');
const code = fs.readFileSync(SRC, 'utf8');

const win = {};
new Function('window', code)(win);
const H = win.Highlighter;

let fail = 0;
const ok = (cond, msg) => { if (!cond) { fail++; console.log('  FAIL ' + msg); } else console.log('  ok   ' + msg); };

console.log('languages: ' + H.languages.length + ' -> ' + H.languages.join(', '));

const py = H.highlight('def add(a, b):\n    # sum them\n    return a + 2', 'python');
console.log('\n--- python ---\n' + py);
ok(/tk-kw">def<\/span>/.test(py), 'python: keyword');
ok(/tk-comment"># sum them/.test(py), 'python: comment');
ok(/tk-fn">add<\/span>/.test(py), 'python: function name');
ok(/tk-kw">return<\/span>/.test(py), 'python: return keyword');
ok(/tk-number">2<\/span>/.test(py), 'python: number');
ok(/tk-lit">None<\/span>/.test(H.highlight('x = None', 'python')), 'python: literal None');
ok(/tk-lit">True<\/span>/.test(H.highlight('x = True', 'python')), 'python: literal True');

const js = H.highlight('const x = `hi ${name}`;\n// note\nfunction go(a) { return 0xFF; }', 'javascript');
console.log('\n--- javascript ---\n' + js);
ok(/tk-string">`hi/.test(js), 'js: template literal');
ok(/tk-comment">\/\/ note/.test(js), 'js: line comment');
ok(/tk-kw">const<\/span>/.test(js), 'js: keyword');
ok(/tk-kw">function<\/span>/.test(js), 'js: function keyword');
ok(/tk-number">0xFF/.test(js), 'js: hex number');

ok(/tk-comment">\/\* block/.test(H.highlight('/* block */ x', 'javascript')), 'js: block comment');
ok(!/tk-/.test(H.highlight('plain', 'text')), 'text: no tokens');
ok(!/tk-/.test(H.highlight('a < b & c > d', 'unknownlang')), 'unknown lang: falls back to escaped plain');
ok(/&lt;/.test(H.highlight('a < b', 'text')), 'text: html escaped');

// XSS safety: code must never inject live markup
const evil = H.highlight('<img src=x onerror=alert(1)>', 'javascript');
ok(!/<img/.test(evil), 'xss: raw tag neutralised');
ok(!/[<>]/.test(evil.replace(/<span[^>]*>|<\/span>/g, '')), 'xss: no bare angle brackets in code text');

// every language tokenises without throwing and round-trips text content
for (const L of H.languages) {
  const sample = 'x = "s"; // c\n/* b */ 42 fn( ) { return true; }';
  let out;
  try { out = H.highlight(sample, L); } catch (e) { ok(false, L + ': threw ' + e.message); continue; }
  const text = out.replace(/<[^>]+>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  if (text !== sample) ok(false, L + ': text not preserved\n    got: ' + JSON.stringify(text));
}
ok(true, 'all languages preserve source text exactly');

// detection
console.log('\n--- detect ---');
const cases = [
  ['def main():\n    print("hi")', 'python'],
  ['function f(){ return 1; }', 'javascript'],
  ['<!DOCTYPE html><html></html>', 'html'],
  ['SELECT * FROM users WHERE id = 1;', 'sql'],
  ['FROM node:20\nRUN npm i', 'dockerfile'],
];
for (const [src, want] of cases) {
  const got = H.detect(src);
  ok(got === want, 'detect ' + JSON.stringify(src.slice(0, 26)) + ' -> ' + got + ' (want ' + want + ')');
}

// aliases
console.log('\n--- aliases ---');
for (const [a, want] of [['py', 'python'], ['ts', 'typescript'], ['c++', 'cpp'], ['sh', 'bash'], ['yml', 'yaml']]) {
  ok(H.canonical(a) === want, 'canonical(' + a + ') = ' + H.canonical(a));
}

console.log('\n' + (fail ? 'FAILURES: ' + fail : 'ALL CHECKS PASSED'));
process.exit(fail ? 1 : 0);
