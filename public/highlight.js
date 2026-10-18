/* ═══════════════════════════════════════════════════════════
   Olmavax A.I — dependency-free syntax highlighter
   20+ languages. One left-to-right pass: every pattern is
   wrapped in exactly one capturing group (all inner groups are
   non-capturing), so group N maps to token class N.
   ═══════════════════════════════════════════════════════════ */
(() => {
'use strict';
if (typeof window === 'undefined') return;

const KW = {
  javascript: 'await async break case catch class const continue debugger default delete do else export extends finally for from function get if import in instanceof let new of return set static super switch this throw try typeof var void while with yield',
  typescript: 'abstract any as async await boolean break case catch class const constructor continue declare default delete do else enum export extends finally for from function get if implements import in instanceof interface is keyof let namespace never new number of private protected public readonly return set static string super switch symbol this throw try type typeof undefined unique unknown var void while yield',
  python: 'and as assert async await break class continue def del elif else except finally for from global if import in is lambda match nonlocal not or pass raise return try while with yield',
  java: 'abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while var record sealed permits yield',
  c: 'auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while',
  cpp: 'alignas alignof auto bool break case catch char class const constexpr continue decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept nullptr operator private protected public register reinterpret_cast return short signed sizeof static static_assert struct switch template this throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while',
  csharp: 'abstract as base bool break byte case catch char checked class const continue decimal default delegate do double dynamic else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using var virtual void volatile while async await record',
  go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var',
  rust: 'as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while macro_rules union',
  ruby: 'alias and begin break case class def defined do else elsif end ensure for if in module next nil not or redo rescue retry return self super then true false undef unless until when while yield require require_relative attr_accessor attr_reader attr_writer puts lambda proc',
  php: 'abstract and array as break callable case catch class clone const continue declare default do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile extends final finally fn for foreach function global goto if implements include include_once instanceof insteadof interface isset list match namespace new or print private protected public readonly require require_once return static switch throw trait try unset use var while xor yield enum',
  swift: 'associatedtype class deinit enum extension fileprivate func import init inout internal let open operator private protocol public rethrows static struct subscript typealias var break case continue default defer do else fallthrough for guard if in repeat return switch where while as Any catch is nil super self Self throw throws true try',
  kotlin: 'abstract actual annotation as break by catch class companion const constructor continue crossinline data delegate do dynamic else enum expect external false final finally for fun get if import in infix init inline inner interface internal is lateinit noinline null object open operator out override package private protected public reified return sealed set super suspend tailrec this throw true try typealias typeof val var vararg when while',
  sql: 'select from where insert into values update set delete create table alter drop index view join inner left right outer on group by order having limit offset union all distinct as and or not null primary key foreign references default begin commit rollback transaction explain analyze with recursive intersect except returning cascade',
  bash: 'if then else elif fi for while do done case esac function return local export readonly declare source alias set unset echo printf cd ls rm cp mv mkdir pwd cat grep sed awk find curl wget chmod chown sudo apt npm pip git python node docker kubectl systemctl service exit trap test source',
  powershell: 'if else elseif foreach for while do switch return function filter param begin process end try catch finally throw new class using import set write out read get invoke where select continue break exit',
  json: 'true false null',
  yaml: 'true false null yes no on off',
  dockerfile: 'FROM RUN CMD LABEL EXPOSE ENV ADD COPY ENTRYPOINT VOLUME USER WORKDIR ARG ONBUILD STOPSIGNAL HEALTHCHECK SHELL AS',
  lua: 'and break do else elseif end false for function goto if in local nil not or repeat return then true until while',
  r: 'if else repeat while function for next break continue Inf NaN NA',
  matlab: 'function end if elseif else for while switch case otherwise return break continue try catch global persistent',
};
const LIT = {
  javascript: 'true false null undefined NaN Infinity', typescript: 'true false null undefined NaN Infinity',
  python: 'True False None', java: 'true false null', cpp: 'true false nullptr NULL', c: 'NULL',
  csharp: 'true false null', go: 'true false nil iota', rust: 'true false None Some Ok Err',
  ruby: 'true false nil', php: 'true false null', swift: 'true false nil', kotlin: 'true false null',
  sql: 'true false null', bash: 'true false', lua: 'true false nil', r: 'TRUE FALSE NULL',
  json: 'true false null', yaml: 'true false null',
};

const ALIAS = {
  js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript', node: 'javascript',
  ts: 'typescript', tsx: 'typescript',
  py: 'python', python3: 'python',
  'c++': 'cpp', cxx: 'cpp', cc: 'cpp', h: 'c', hpp: 'cpp', hxx: 'cpp',
  cs: 'csharp', 'c#': 'csharp',
  golang: 'go', rs: 'rust', rb: 'ruby', kt: 'kotlin', swiftui: 'swift',
  sh: 'bash', shell: 'bash', zsh: 'bash', ps1: 'powershell', pwsh: 'powershell',
  yml: 'yaml', jsonc: 'json', json5: 'json', docker: 'dockerfile', hcl: 'json', tfvars: 'json',
  md: 'markdown', plaintext: 'text', text: 'text', txt: 'text',
  xml: 'html', svg: 'html', vue: 'html', svelte: 'html', scss: 'css', less: 'css',
  psql: 'sql', mysql: 'sql', sqlite: 'sql',
};
const canonical = l => {
  const k = String(l || '').toLowerCase().trim();
  return ALIAS[k] || k;
};

const SLASHY = new Set(['javascript','typescript','java','c','cpp','csharp','go','rust','swift','kotlin','php','dart']);
const HASHY  = new Set(['python','ruby','r','perl','yaml','dockerfile','matlab','lua','bash','powershell','shell']);

const escH = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const tok  = (cls, txt) => '<span class="tk-' + cls + '">' + escH(txt) + '</span>';

/** Build the ordered token table for a language. */
function table(L) {
  const t = [];
  if (HASHY.has(L)) t.push(['comment', '#[^\\n]*']);
  if (SLASHY.has(L)) t.push(['comment', '\\/\\/[^\\n]*'], ['comment', '\\/\\*[\\s\\S]*?\\*\\/']);
  if (L === 'python') t.push(['string', '[rbfu]{0,2}"""[\\s\\S]*?"""'], ['string', "[rbfu]{0,2}'''[\\s\\S]*?'''"]);
  if (L === 'php') t.push(['string', "<<<['\"]?\\w+['\"]?[\\s\\S]*?;"]);
  t.push(
    ['string', '`(?:\\\\[\\s\\S]|[^\\\\`])*`'],
    ['string', '"(?:\\\\[\\s\\S]|[^\\\\"])*"'],
    ['string', "'(?:\\\\[\\s\\S]|[^\\\\'])*'"],
    ['number', '(?:\\b0[xXbBoO][0-9a-fA-F_]+\\b|\\b\\d[\\d_]*(?:\\.\\d[\\d_]*)?(?:[eE][+-]?\\d+)?[a-zA-Z%]*)'],
    ['fn', '[A-Za-z_$][\\w$]*(?=\\s*\\()'],
    ['cls', '\\b[A-Z][\\w$]*\\b'],
    ['prop', '(?<=\\.)[A-Za-z_$][\\w$]*'],
    ['op', '[+\\-*/%=<>!&|^~?:]+'],
    ['meta', '[{}()\\[\\];,.]'],
    ['ident', '[A-Za-z_$][\\w$]*'],
    ['ws', '\\s+'],
    ['any', '[\\s\\S]'],
  );
  return t;
}

const cache = new Map();
function compile(L) {
  if (cache.has(L)) return cache.get(L);
  const t = table(L);
  const src = t.map(([, s]) => '(' + s + ')').join('|');
  let re;
  try { re = new RegExp(src, 'g'); } catch { re = /([\s\S])/g; t.length = 0; t.push(['any', '[\\s\\S]']); }
  const compiled = { re, names: t.map(x => x[0]), kw: new Set((KW[L] || '').split(/\s+/).filter(Boolean)),
                     lit: new Set((LIT[L] || '').split(/\s+/).filter(Boolean)) };
  cache.set(L, compiled);
  return compiled;
}

function highlight(code, lang) {
  const src = String(code == null ? '' : code);
  const L = canonical(lang);
  // unknown languages are rendered as escaped plain text, never tokenised
  if (!L || L === 'text' || L === 'markdown' || !KW[L]) return escH(src);
  const { re, names, kw, lit } = compile(L);
  re.lastIndex = 0;
  let out = '', m, guard = 0;
  while ((m = re.exec(src)) !== null && guard++ < 200000) {
    if (m[0] === '') { re.lastIndex++; continue; }
    let k = 'plain';
    for (let i = 1; i <= names.length; i++) {
      if (m[i] !== undefined) { k = names[i - 1]; break; }
    }
    const w = m[0];
    // keywords and literals win over the capitalised-identifier rule, so
    // Python's True/False/None do not render as class names.
    if (kw.has(w)) k = 'kw';
    else if (lit.has(w)) k = 'lit';
    else if (k === 'ident' || k === 'cls') k = 'plain';
    out += (k === 'plain' || k === 'ws') ? escH(w) : tok(k, w);
  }
  return out;
}

/** Best-effort language guess from the code itself. */
function detect(code) {
  const c = String(code || '');
  const tests = [
    [/^\s*(?:FROM|RUN|CMD|COPY|LABEL|ENTRYPOINT)\s+\S+/im, 'dockerfile'],
    [/^\s*def\s+\w+\s*\(|\bfrom\s+\w+\s+import\b|\bprint\s*\(/m, 'python'],
    [/\bfunction\s+\w+\s*\(|\bconst\s+\w+\s*=|\bconsole\.log\b|\brequire\s*\(/, 'javascript'],
    [/<!DOCTYPE\s+html|<html[\s>]|\bdiv\b[\s\S]{0,40}className=/i, 'html'],
    [/^\s*[.#@][\w-]+\s*\{|^\s*[\w-]+\s*\{[\s\S]*?[\w-]+\s*:\s*[^;]+;/m, 'css'],
    [/^\s*#!\/|\b(?:sudo|chmod|apt-get|npm|pip)\b|\becho\s+["$]/m, 'bash'],
    [/^\s*[\w.-]+\s*:\s*(?:\n\s+\S|["'\d]|$)/m, 'yaml'],
    [/\b(SELECT|INSERT INTO|UPDATE|CREATE TABLE|DELETE FROM)\b/i, 'sql'],
    [/^\s*\{[\s\S]*?\}\s*$/m, 'json'],
    [/\bfunc\s+\w+|\bpackage\s+main\b|\bchan\s+\w/, 'go'],
    [/\bfn\s+\w+|\blet\s+mut\b|\bimpl\s+\w+\s+for\b/, 'rust'],
    [/\b(?:public|private)\s+(?:static\s+)?(?:void|class|int)\b/, 'java'],
    [/\bstd::|\btemplate\s*<|\bnamespace\s+\w+\s*\{/, 'cpp'],
    [/using\s+System\b|\bpublic\s+class\s+\w+\s*[:{]/, 'csharp'],
    [/\bfunc\s+\w+\s*(?:->|\()|\blet\s+\w+\s*:\s*String/, 'swift'],
    [/\bfun\s+\w+\s*\(|\bval\s+\w+\s*:|@Composable/, 'kotlin'],
    [/\bdef\s+self\.|\bself\.\w+\s*=/, 'python'],
  ];
  for (const [re, lang] of tests) if (re.test(c)) return lang;
  return 'text';
}

window.Highlighter = { highlight, detect, canonical, languages: Object.keys(KW).sort() };
})();
