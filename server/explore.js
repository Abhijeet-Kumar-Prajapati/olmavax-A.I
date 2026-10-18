'use strict';
/**
 * Explore — a curated catalogue of ready-made starting points.
 * Each entry pre-fills the composer (and can pin an agent or mode) so the user
 * can go from "I want to build something" to a working prompt in one click.
 */

const AGENTS = require('./agents').AGENTS;

const PROMPTS = [
  { id: 'explain', icon: '🎓', cat: 'Learn', title: 'Explain anything',
    body: 'Explain {topic} to me like I am smart but new to it. Start with a one-line summary, then the key ideas, then a worked example.',
    agent: 'tutor' },
  { id: 'code', icon: '💻', cat: 'Build', title: 'Write and explain code',
    body: 'Write a {language} function called {name} that does {behaviour}. Explain how it works, give a usage example, and list the edge cases to watch for.',
    agent: 'coder' },
  { id: 'debug', icon: '🐛', cat: 'Build', title: 'Debug a bug',
    body: 'Here is my code and the error I get. Find the root cause, explain it in plain words, then show the corrected code.',
    agent: 'coder' },
  { id: 'app', icon: '📱', cat: 'Build', title: 'Design an app',
    body: 'Design a {kind} app called {name}. Give me the core features, the data model, the main screens, and a build plan I can follow step by step.',
    agent: 'app' },
  { id: 'site', icon: '🌐', cat: 'Build', title: 'Plan a website',
    body: 'Plan a website for {topic}. List the pages, what goes on each, the visual style, and the sections to build first.',
    agent: 'app' },
  { id: 'deck', icon: '📊', cat: 'Create', title: 'Build a slide deck',
    body: 'Create a {n}-slide presentation about {topic}. For each slide give a title, 3-4 bullet points, and speaker notes.',
    agent: 'presenter' },
  { id: 'resume', icon: '🎯', cat: 'Create', title: 'Write a resume',
    body: 'Write a one-page resume for a {role}. Highlight skills, projects and measurable impact. Keep it tight and skimmable.',
    agent: 'portfolio' },
  { id: 'linkedin', icon: '💼', cat: 'Create', title: 'LinkedIn profile',
    body: 'Write a LinkedIn headline, About section and 5 experience bullets for a {role}. Professional but not corporate-sounding.',
    agent: 'portfolio' },
  { id: 'interview', icon: '🎤', cat: 'Learn', title: 'Interview prep',
    body: 'Act as a hiring manager for a {role} role. Ask me one interview question at a time, wait for my answer, then critique it.',
    agent: 'portfolio' },
  { id: 'research', icon: '🔬', cat: 'Research', title: 'Deep research',
    body: 'Research {topic}. Cover what it is, why it matters, the main approaches, trade-offs, and where it is heading. Cite sources.',
    agent: 'research', mode: 'research' },
  { id: 'compare', icon: '⚖️', cat: 'Research', title: 'Compare options',
    body: 'Compare {a} and {b} on price, performance, ecosystem and best use case. Give a clear recommendation.',
    agent: 'research' },
  { id: 'summarize', icon: '📝', cat: 'Writing', title: 'Summarise text',
    body: 'Summarise the text I paste below. Give a 3-bullet summary, then the full detail.',
    agent: 'writer' },
  { id: 'email', icon: '✉️', cat: 'Writing', title: 'Write an email',
    body: 'Write a {tone} email to {recipient} about {subject}. Keep it short and professional.',
    agent: 'writer' },
  { id: 'story', icon: '📖', cat: 'Writing', title: 'Write a story',
    body: 'Write a short {genre} story about {theme}. Aim for about {n} words with a real turning point.',
    agent: 'writer' },
  { id: 'blog', icon: '📰', cat: 'Writing', title: 'Write a blog post',
    body: 'Write a {n}-word blog post about {topic}. Use a clear hook, subheadings, and concrete examples.',
    agent: 'writer' },
  { id: 'plan', icon: '🗓️', cat: 'Plan', title: 'Make a plan',
    body: 'Break "{goal}" into milestones over {n} weeks. For each week list the tasks, the time needed, and how I will know it is done.',
    agent: 'planner' },
  { id: 'budget', icon: '💰', cat: 'Plan', title: 'Budget a project',
    body: 'Give me a simple budget breakdown for {project}, with realistic numbers and where people usually forget costs.',
    agent: 'planner' },
  { id: 'habit', icon: '🏃', cat: 'Plan', title: 'Build a habit',
    body: 'Design a 30-day plan to build the habit of {habit}. Make the first week tiny so I cannot fail.',
    agent: 'planner' },
  { id: 'learnlang', icon: '🗣️', cat: 'Learn', title: 'Learn a language',
    body: 'Teach me {language} from zero. Start with the {n} most useful words, with pronunciation and example sentences.',
    agent: 'tutor' },
  { id: 'math', icon: '➗', cat: 'Learn', title: 'Work through maths',
    body: 'Solve this step by step, explaining each step as if teaching me: {problem}',
    agent: 'tutor' },
];

const AGENT_LIST = Object.values(AGENTS).map(a => ({
  id: a.id, name: a.name, icon: a.icon,
  blurb: {
    general: 'Everyday questions, quick answers and general help.',
    coder: 'Writes, reviews and debugs code in any language.',
    app: 'Designs apps and websites, with structure and build steps.',
    research: 'Goes deep, compares sources, flags uncertainty.',
    writer: 'Articles, emails, stories, scripts and résumés.',
    presenter: 'Slide decks with titles, bullets and speaker notes.',
    portfolio: 'Portfolios, CVs, LinkedIn and interview prep.',
    tutor: 'Explains step by step, then quizzes you.',
    planner: 'Turns goals into milestones, schedules and checklists.',
  }[a.id] || '',
}));

module.exports = { PROMPTS, AGENTS: AGENT_LIST, categories: [...new Set(PROMPTS.map(p => p.cat))] };
