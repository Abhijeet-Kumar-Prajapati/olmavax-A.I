'use strict';
/*
 * Calculator regression suite.
 *
 * The Calculator plugin describes itself as doing "roots and percentages", but
 * calc() only accepted digits and + - * / ^ % ( ). sqrt(144) and "10% of 850"
 * were both rejected with a 400. These tests pin the behaviour the plugin
 * advertises, and pin that widening it did not widen the injection surface.
 */
const path = require('path');
const { calc } = require(path.join(__dirname, '..', 'server', 'tools.js'));

let pass = 0, fail = 0;
const near = (a, b) => Math.abs(a - b) < 1e-9;

const is = (expr, want) => {
  let got, err = null;
  try { got = calc(expr); } catch (e) { err = e.message; }
  const good = err === null && near(got, want);
  good ? pass++ : fail++;
  console.log((good ? '  ok    ' : '  FAIL  ') + expr.padEnd(22) +
    (err ? 'threw: ' + err : '= ' + got + (near(got, want) ? '' : '   (expected ' + want + ')')));
};

const rejects = (expr) => {
  let threw = false;
  try { calc(expr); } catch { threw = true; }
  threw ? pass++ : fail++;
  console.log((threw ? '  ok    ' : '  FAIL  ') + expr.padEnd(22) +
    (threw ? 'rejected' : '  ACCEPTED but should not have'));
};

console.log('calculator: plain arithmetic');
[['2+2*5', 12], ['12*(3+4)', 84], ['100/4', 25], ['2^10', 1024],
 ['-5+3', -2], ['1.5*4', 6], ['10%3', 1], ['1,000+1', 1001], ['  2 *  3  ', 6]]
  .forEach(([a, b]) => is(a, b));

console.log('calculator: roots (the plugin advertised these)');
[['sqrt(144)', 12], ['sqrt(2)', Math.SQRT2], ['cbrt(27)', 3],
 ['root(27,3)', 3], ['sqr(7)', 49], ['sqrt(16)+abs(-4)', 8]]
  .forEach(([a, b]) => is(a, b));

console.log('calculator: percentages (also advertised, also missing)');
[['10% of 850', 85], ['15 % of 200', 30], ['50%', 0.5],
 ['(20%)', 0.2], ['100 - 10% of 50', 95]]
  .forEach(([a, b]) => is(a, b));

console.log('calculator: multi-argument helpers must not collapse');
[['max(4,9,2)', 9], ['min(4,9,2)', 2], ['max(1000,2000)', 2000], ['min(1,2,3,4)', 1]]
  .forEach(([a, b]) => is(a, b));

console.log('calculator: rounding');
[['abs(-7)', 7], ['round(3.14159)', 3], ['floor(3.9)', 3], ['ceil(3.1)', 4]]
  .forEach(([a, b]) => is(a, b));

console.log('calculator: injection attempts must be rejected');
['alert(1)', 'process.exit(1)', 'require("fs")', 'constructor',
 'this.constructor.constructor("return 1")()', '1;alert(1)', 'Math.constructor',
 'globalThis', 'eval("1")', '1+alert', '__proto__', 'a.b.c', '"x"',
 'fetch("http://evil")', 'sqrt(1);alert(1)', 'sqrt.constructor("return 1")',
 'Math.abs.constructor', 'max(1,alert)', 'sqrt(alert(1))',
 '[].map(x=>x)', '(()=>1)()', '1+'.repeat(200) + '1']
  .forEach(rejects);

console.log('\n' + pass + ' passed, ' + fail + ' failed');
if (fail) { console.log('CALC CHECKS FAILED'); process.exit(1); }
console.log('ALL ' + pass + ' CALC CHECKS PASSED');