'use strict';
/**
 * Small typed JSON collections on disk — the storage behind the sidebar's
 * Library, Scheduled, Plugins and Codex panels.
 *
 * Everything is a plain array persisted as JSON. Writes are atomic (write to a
 * temp file, then rename) so a crash mid-write cannot corrupt the store, and
 * every mutation is clamped so one bad request cannot grow a file without bound.
 */
const fs = require('fs');
const path = require('path');

const SCHEMAS = {
  // things the user saved out of a conversation
  library:  { file: 'library.json',  limit: 2000, fields: ['id', 'kind', 'title', 'body', 'lang', 'chatId', 'at'] },
  // prompts queued to run later
  schedule: { file: 'schedule.json', limit: 500,  fields: ['id', 'prompt', 'agent', 'provider', 'model', 'at', 'every', 'enabled', 'lastRun', 'runs'] },
  // per-plugin enable/disable state and settings
  plugins:  { file: 'plugins.json',  limit: 200,  fields: ['id', 'enabled', 'settings'] },
  // codex workspace: files and snippets saved by the Code panel
  workspace:{ file: 'workspace.json', limit: 3000, fields: ['id', 'name', 'lang', 'content', 'chatId', 'at'] },
};

const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const str = (v, max = 20000) => String(v == null ? '' : v).slice(0, max);

class Store {
  constructor(dir) {
    this.dir = dir;
    this.cache = new Map();
    for (const k of Object.keys(SCHEMAS)) this.#load(k);
  }

  #file(k) { return path.join(this.dir, SCHEMAS[k].file); }

  #load(k) {
    try {
      const raw = fs.readFileSync(this.#file(k), 'utf8');
      const arr = JSON.parse(raw);
      this.cache.set(k, Array.isArray(arr) ? arr : []);
    } catch {
      this.cache.set(k, []);
    }
    return this.cache.get(k);
  }

  #flush(k) {
    const f = this.#file(k), tmp = f + '.tmp';
    try {
      fs.mkdirSync(path.dirname(f), { recursive: true });
      fs.writeFileSync(tmp, JSON.stringify(this.cache.get(k), null, 2));
      fs.renameSync(tmp, f);
      return true;
    } catch {
      try { fs.unlinkSync(tmp); } catch {}
      return false;
    }
  }

  /** Keep only the declared fields, so callers cannot smuggle extra state in. */
  #shape(k, input = {}) {
    const out = {};
    for (const f of SCHEMAS[k].fields) if (input[f] !== undefined) out[f] = input[f];
    return out;
  }

  all(k) { return this.cache.get(k) || []; }
  get(k, id) { return this.all(k).find(x => x.id === id) || null; }

  add(k, input = {}) {
    const rec = Object.assign({ id: uid(), at: Date.now() }, this.#shape(k, input));
    rec.at = Number(rec.at) || Date.now();
    const arr = this.cache.get(k);
    arr.unshift(rec);
    if (arr.length > SCHEMAS[k].limit) arr.length = SCHEMAS[k].limit;
    this.#flush(k);
    return rec;
  }

  update(k, id, patch = {}) {
    const rec = this.get(k, id);
    if (!rec) return null;
    Object.assign(rec, this.#shape(k, patch), { id: rec.id });
    this.#flush(k);
    return rec;
  }

  remove(k, id) {
    const arr = this.cache.get(k);
    const i = arr.findIndex(x => x.id === id);
    if (i < 0) return false;
    arr.splice(i, 1);
    this.#flush(k);
    return true;
  }

  clear(k) { this.cache.set(k, []); this.#flush(k); return true; }

  /** Guarded update used by the scheduler tick. */
  touch(k, id, patch) {
    const rec = this.get(k, id);
    if (!rec) return null;
    Object.assign(rec, patch);
    this.#flush(k);
    return rec;
  }
}

module.exports = { Store, SCHEMAS, uid };
