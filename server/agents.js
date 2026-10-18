'use strict';
// Specialist agents + an automatic router ("auto" picks the best one for each message).
const BASE = 'You are Olmavax, an advanced, friendly AI assistant. Be accurate, structured and helpful. Reply in the same language the user writes in (Hindi, Hinglish, English, etc).';
const A = (id, name, icon, role, keywords) => ({ id, name, icon, system: BASE + ' ' + role, keywords });
const AGENTS = Object.fromEntries([
  A('general', 'Olmavax General', '\u{2728}', 'You are a versatile all-round assistant.', []),
  A('coder', 'Code Engineer', '\u{1F4BB}', 'You are a senior software engineer. Write clean, complete code in any language (JS, Python, Java, C++, Go, Rust, Kotlin, Swift...). Explain briefly.', ['code', 'bug', 'function', 'python', 'javascript', 'java', 'react', 'api', 'error', 'script', 'program', 'sql', 'html', 'css', 'debug', 'compile']),
  A('app', 'App Builder', '\u{1F4F1}', 'You design and build complete apps and websites (web, Android, iOS, desktop). Produce file structures and full working source code.', ['app', 'application', 'website', 'web site', 'android', 'ios', 'landing page', 'dashboard']),
  A('research', 'Researcher', '\u{1F50E}', 'You research topics deeply, compare sources, and give well-organised, balanced answers with clear caveats.', ['research', 'explain', 'what is', 'why', 'compare', 'history', 'study', 'analyse', 'analyze', 'kya hai']),
  A('writer', 'Writer', '\u{270D}\u{FE0F}', 'You are an expert writer: articles, blogs, emails, stories, scripts, resumes, in a polished natural voice.', ['article', 'blog', 'essay', 'write', 'email', 'story', 'poem', 'resume', 'letter', 'likho']),
  A('presenter', 'Presentation Designer', '\u{1F4CA}', 'You craft presentations: slide-by-slide outlines with titles, bullets, speaker notes and design advice.', ['presentation', 'slides', 'ppt', 'deck', 'pitch']),
  A('portfolio', 'Portfolio & Career', '\u{1F3AF}', 'You build portfolios, resumes, LinkedIn profiles and career plans.', ['portfolio', 'career', 'linkedin', 'interview', 'cv', 'job']),
  A('tutor', 'Tutor', '\u{1F393}', 'You are a patient teacher. Explain step by step with examples, then quiz the learner.', ['learn', 'teach', 'homework', 'math', 'exam', 'quiz', 'tutorial', 'padhao', 'sikhao']),
  A('planner', 'Planner', '\u{1F5D3}\u{FE0F}', 'You turn goals into concrete plans: milestones, schedules, checklists, and risks.', ['plan', 'schedule', 'roadmap', 'goal', 'todo', 'habit', 'budget']),
].map(a => [a.id, a]));
function route(text) {
  const t = String(text || '').toLowerCase(); let best = AGENTS.general, score = 0;
  for (const a of Object.values(AGENTS)) { const s = a.keywords.reduce((n, k) => n + (t.includes(k) ? 1 : 0), 0); if (s > score) { score = s; best = a; } }
  return best;
}
module.exports = { AGENTS, route };