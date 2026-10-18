'use strict';
// Persistent long-term memory ("learning"): facts the assistant keeps across chats.
const fs = require('fs'), path = require('path');
class Memory {
  constructor(dir) { this.dir = dir; this.file = path.join(dir, 'memory.json'); fs.mkdirSync(dir, { recursive: true }); this.facts = []; try { this.facts = JSON.parse(fs.readFileSync(this.file, 'utf8')).facts || []; } catch {} }
  save() { fs.writeFileSync(this.file, JSON.stringify({ facts: this.facts }, null, 2)); }
  list() { return this.facts; }
  add(text) {
    text = String(text || '').trim().slice(0, 300); if (!text) return null;
    const ex = this.facts.find(f => f.text.toLowerCase() === text.toLowerCase()); if (ex) return ex;
    const f = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5), text, ts: Date.now() };
    this.facts.push(f); this.facts = this.facts.slice(-200); this.save(); return f;
  }
  remove(id) { const n = this.facts.length; this.facts = this.facts.filter(f => f.id !== id); this.save(); return n !== this.facts.length; }
  // Auto-learn simple facts from what the user says (English + Hinglish).
  learn(text) {
    const out = [], t = String(text || '');
    const rules = [
      [/\bmy name is ([\p{L} ]{2,30}?)(?:[.,!]|$)/iu, m => `User's name is ${m[1].trim()}`],
      [/\bmera naam ([\p{L} ]{2,30}?) (?:hai|h)\b/iu, m => `User's name is ${m[1].trim()}`],
      [/\bremember that (.{3,200})/i, m => m[1].trim()],
      [/\byaad rakh(?:na|o)? (?:ki )?(.{3,200})/i, m => m[1].trim()],
    ];
    for (const [re, fn] of rules) { const m = t.match(re); if (m) { const f = this.add(fn(m)); if (f) out.push(f.text); } }
    return out;
  }
  prompt() { const f = this.facts.slice(-20).map(x => '- ' + x.text); return f.length ? '\n\nLong-term memory about the user:\n' + f.join('\n') : ''; }
}
module.exports = Memory;