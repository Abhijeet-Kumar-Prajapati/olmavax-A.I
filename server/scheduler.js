'use strict';
/**
 * Runs prompts that the user scheduled in the "Scheduled" panel.
 *
 * A tick fires every 30s, picks up anything whose time has come and that is
 * still enabled, streams it through the configured provider, and files the
 * result into the Library as a `schedule` item so it is never lost.
 */
const { pickProvider, collect } = require('./providers');
const { AGENTS } = require('./agents');

const TICK_MS = Number(process.env.SCHEDULER_TICK || 30_000);

function start({ store, agentsList = () => AGENTS, onRun } = {}) {
  const timer = setInterval(() => { tick().catch(() => {}); }, TICK_MS);
  if (timer.unref) timer.unref();           // never hold the process open
  timer._olmavax = true;
  return timer;
}

async function tick({ store, agentsList = () => AGENTS, onRun } = {}) {
  if (!store) return [];
  const now = Date.now();
  const due = store.all('schedule').filter(s => s.enabled !== false && Number(s.at) <= now);
  const ran = [];
  for (const job of due) {
    try {
      const provider = await pickProvider(job.provider || 'auto', job.keys || {});
      const agent = AGENTS[job.agent] || AGENTS.general;
      const answer = await collect(provider, {
        messages: [{ role: 'user', content: job.prompt }],
        system: agent.system, model: job.model,
      });
      const rec = store.add('library', {
        kind: 'schedule',
        title: job.prompt.slice(0, 80),
        body: answer,
        lang: '',
      });
      const runs = (job.runs || 0) + 1;
      // one-shot jobs retire after firing unless an interval was set
      if (job.every && runs < (job.repeat || 0)) {
        const every = Math.max(60_000, Number(job.every) * 60_000);
        store.update('schedule', job.id, { at: now + every, runs, lastRun: now });
      } else {
        store.remove('schedule', job.id);
      }
      ran.push({ job: job.id, result: rec });
      onRun && onRun({ job, answer });
    } catch (e) {
      // keep the job but remember why it failed, so the UI can show it
      store.update('schedule', job.id, { lastRun: now, error: String(e.message).slice(0, 300) });
    }
  }
  return ran;
}

module.exports = { start, tick, TICK_MS };
