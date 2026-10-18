# Olmavax A.I

> A local-first, multi-agent AI workspace. Voice, memory, plugins, scheduled
> tasks, syntax highlighting, PDF export and QR generation — running entirely
> on your own machine. No account, no cloud, no telemetry. It works even with
> no API key.

[![Live website](https://img.shields.io/badge/website-live-4f8cff?style=flat-square)](https://abhijeet-kumar-prajapati.github.io/olmavax-A.I/docs/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square)](package.json)
[![Node](https://img.shields.io/badge/node-18%2B-339933?style=flat-square&logo=node.js)](https://nodejs.org)
[![Tests](https://img.shields.io/badge/tests-320%2B%20green?style=flat-square)](tests/)

![Olmavax A.I](public/logo.svg)

---

## Contents

- [Quick start](#quick-start)
- [What it does](#what-it-does)
- [Languages](#languages)
- [Skills and features](#skills-and-features)
  - [Voice](#1-voice--speak-and-type-at-the-same-time)
  - [The nine agents](#2-the-nine-agents)
  - [Nineteen plugins](#3-the-nineteen-plugins)
  - [Memory](#4-memory)
  - [Scheduled tasks](#5-scheduled-tasks)
  - [Syntax highlighting](#6-syntax-highlighting)
  - [PDF and QR](#7-pdf-export-and-qr-codes)
  - [Code workbench](#8-code-workbench)
  - [Internationalisation](#9-five-interface-languages)
  - [The Olmavax Agent](#10-the-optional-olmavax-agent-python-sidecar)
- [Architecture](#architecture)
- [API](#api)
- [Tests](#tests)
- [Privacy](#privacy)

---

## Quick start

```bash
git clone https://github.com/Abhijeet-Kumar-Prajapati/olmavax-A.I.git
cd olmavax-A.I
npm start
```

Open **http://127.0.0.1:8787**.

There is nothing to install. `npm install` has nothing to fetch — the entire
project runs on Node's standard library alone.

**Requirements:** Node.js 18 or newer. That is the whole list.
Python 3.10+ is optional and only needed for the Olmavax Agent.

---

## What it does

Olmavax A.I is one Node.js server plus a browser front end. You get a chat
workspace with nine agents, a voice mode you can keep typing through,
long-term memory, scheduled prompts, a code workbench, nineteen server-side
plugins, PDF export, QR generation and syntax highlighting for twenty-two
languages.

A built-in offline brain answers maths, conversions, text tools and web
lookups with **no network at all**. Add a provider key and the same interface
talks to Claude, GPT, Ollama or the Olmavax Agent instead.

---

## Languages

### Languages the project is written in

| Language | Lines | Share | Where it lives |
|---|---:|---:|---|
| **Python** | 17,023 | 62.0 % | `advanced/olmavax-agent/` — the optional sidecar |
| **JavaScript** | 6,939 | 25.3 % | `public/` front end and `server/` back end |
| **CSS** | 2,085 | 7.6 % | `public/style.css` — the whole design system |
| **HTML** | 981 | 3.6 % | `public/index.html`, the website in `docs/` |
| **SVG** | 270 | 1.0 % | `logo.svg`, `logo-mark.svg`, `icon.svg` |
| **Batch** | 92 | 0.3 % | `start-olmavax.bat` for Windows |
| **JSON** | 76 | 0.3 % | manifests and configuration |
| *Markdown* | *—* | *—* | *this file and the docs* |

**92 files, 27,466 lines** (this README excluded, so the figure does not move
when you edit it). No transpiler, no bundler, no build step — the browser
loads the same files you read on disk.

### Languages it can highlight

The highlighter is written from scratch, so it needs no CDN and cannot leak
your code to a third party.

**22 grammars:**

`javascript` `typescript` `python` `java` `c` `cpp` `csharp` `go` `rust`
`ruby` `php` `swift` `kotlin` `sql` `bash` `powershell` `json` `yaml`
`dockerfile` `lua` `r` `matlab` — plus generic HTML/XML and CSS handling.

**46 aliases** so the right grammar is picked up from the filename or the
fence tag — `js`, `jsx`, `mjs`, `cjs`, `node`, `ts`, `tsx`, `py`, `python3`,
`cxx`, `cc`, `h`, `hpp`, `hxx`, `cs`, `golang`, `rs`, `rb`, `kt`, `swiftui`,
`sh`, `shell`, `zsh`, `ps1`, `pwsh`, `yml`, `jsonc`, `json5`, `docker`, `hcl`,
`tfvars`, `md`, `plaintext`, `text`, `txt`, `xml`, `svg`, `vue`, `svelte`,
`scss`, `less`, `psql`, `mysql`, `sqlite`.

### Interface languages

Five, each with the full 224-string set and right-to-left support where it
applies: **English · हिन्दी · Español · Français · العربية**

---

## Skills and features

### 1. Voice — speak and type at the same time

The voice mode is a compact dock that floats just above the composer. It does
not take over the screen, so the chat stays readable and the input stays
usable while you talk.

- Stop sits on the left, the orb in the centre, exit on the right
- Whatever you say is written into the chat automatically
- Spoken turns are also kept in a **separate voice log**, apart from anything
  you type
- Replies are read aloud; interrupt with Stop
- If the browser has no speech engine, it says so plainly instead of
  pretending to listen

Reachable from the sidebar, the composer, the top bar, a mobile tab, the
command palette, or `Ctrl`+`M` / `T` / `V`.

### 2. The nine agents

| Agent | Does |
|---|---|
| ✨ Olmavax General | The default; routes to whatever fits |
| 💻 Code Engineer | Writing, reviewing and debugging code |
| 📱 App Builder | Applications and tools |
| 🔎 Researcher | Search, comparison, fact-checking |
| ✍️ Writer | Drafting, editing, tone |
| 📊 Presentation Designer | Decks and slide structure |
| 🎯 Portfolio & Career | CVs, portfolios, interviews |
| 🎓 Tutor | Explaining, step by step |
| 🗓️ Planner | Breaking work into steps |

### 3. The nineteen plugins

They run on your server, not through a model — so they are instant and work
with no API key at all.

| Plugin | Use |
|---|---|
| 🧮 Calculator | Arithmetic, **powers, roots, percentages**, unit maths, rounding, `max`/`min` |
| 📐 Unit Converter | Length, mass, time and data size |
| 📊 Text Stats | Words, characters, sentences, reading time |
| 🔤 Text Case | upper, lower, title, sentence, camel, snake, kebab |
| 🔐 Base 64 | encode / decode |
| #️⃣ Hasher | MD5, SHA-1, SHA-256, SHA-512 |
| 🔑 UUID / Tokens | UUIDs and secure tokens |
| 🔒 Password Generator | Length control, symbol toggle |
| 🎨 Colour Studio | Hex, RGB, HSL, palette, contrast |
| {} JSON Formatter | Pretty-print and validate |
| 🔗 URL Encoder | encode / decode |
| 🕐 Time & Dates | Now, offsets, Unix time, formatting |
| ⁉️ Regex Tester | Pattern and flags against sample text |
| ▦ QR Generator | Real QR codes, versions 1–20 |
| ✒️ Lorem Ipsum | Placeholder paragraphs |
| ▦ Markdown Table | Text to a table |
| 123 Number to Words | Spelled-out numbers |
| ♿ Contrast Checker | WCAG pass or fail for two colours |
| ⏰ Cron Explainer | What a cron expression does |

### 4. Memory

Tell it something once — it is stored and recalled across separate chats.
Tell it to forget, and it goes. All of it lives in `data/` on your machine.

### 5. Scheduled tasks

Cron-style jobs that run a prompt on a timer, so the workspace works while you
are away. Survives a restart.

### 6. Syntax highlighting

Twenty-two languages, written from scratch in `public/highlight.js`. Every
pattern is escaped and wrapped so user content can never become markup — there
is a test that feeds it hostile input to prove it.

### 7. PDF export and QR codes

Both written from scratch:

- `server/pdf.js` — a real PDF writer, no library. Exports any chat.
- `server/qr.js` — a full QR encoder: Reed-Solomon error correction over
  GF(256), all eight mask patterns scored and chosen, BCH format information.
  Versions 1 to 20. There is a round-trip decoder in the test suite that reads
  the generated codes back.

### 8. Code workbench

A panel for running snippets, inspecting the output and saving the result to
the library or a project.

### 9. Five interface languages

Every string in the interface exists in all five languages, including
right-to-left layout for Arabic.

### 10. The optional Olmavax Agent (Python sidecar)

`advanced/olmavax-agent/` is a separate Python agent that adds planning,
memory search, scheduled skills, a voice pipeline and a security layer.

```bash
python advanced/olmavax-agent/olmavax_agent.py ui
```

It listens on `127.0.0.1:8765` and Olmavax bridges to it automatically. If it
is not running, **nothing else breaks**.

**27 modules**, including:

| Module | Job |
|---|---|
| `brain.py` | The main loop |
| `memory.py` | SQLite store with full-text search |
| `mind.py` | Learning and pattern recognition |
| `nlu.py` | Intent and language understanding |
| `reasoning.py` | Multi-step planning |
| `routing.py` | Chooses the right tool |
| `security.py` | Capability control, path jail, secret scrubbing |
| `vault.py` | Encrypted local storage |
| `skills.py` | The skill registry |
| `llm.py` | Provider layer with offline reasoning |
| `voice.py` | Speech in and out |
| `self_improve.py` | Learns from what worked |

Plus a tool pack under `tools/`: `capability_tools.py`, `dev_tools.py`,
`knowledge_tools.py`, `media_tools.py`, `system_tools.py` and
`web_tools.py`.

---

## Architecture

```
olmavax-ai/
├─ server/                     Node backend — zero dependencies
│  ├─ server.js                  routes and static serving
│  ├─ offline.js                 the built-in brain
│  ├─ plugins.js                 the nineteen plugins
│  ├─ agents.js                  agents and routing
│  ├─ models.js                  the model catalogue
│  ├─ providers.js               Anthropic, OpenAI, Ollama, agent
│  ├─ qr.js                      QR encoder — GF(256), Reed-Solomon
│  ├─ pdf.js                     PDF writer
│  ├─ olmavax-agent.js           bridge to the Python sidecar
│  ├─ scheduler.js               cron-style jobs
│  ├─ collections.js             library, schedule, workspace, plugins
│  ├─ explore.js                 idea and topic explorer
│  ├─ builders.js                site / deck / portfolio generation
│  ├─ search.js, tools.js, image.js, memory.js, zip.js
│  └─ offline.js
├─ public/                     Browser front end
│  ├─ index.html                 the shell
│  ├─ app.js                     all front-end logic
│  ├─ style.css                  the design system
│  ├─ highlight.js               22-language highlighter
│  ├─ i18n.js                    224 strings × 5 languages
│  ├─ logo.svg, logo-mark.svg, icon.svg
│  └─ sw.js                      offline service worker
├─ advanced/
│  └─ olmavax-agent/             optional Python agent (27 modules)
├─ docs/                       the website (GitHub Pages)
├─ python/
│  └─ olmavax_cli.py             command-line client
├─ extension/                   browser extension shell
├─ tests/                      six suites
├─ Dockerfile
└─ package.json
```

**18 server modules. 27 Python modules. One browser bundle.**

---

## API

| Route | Purpose |
|---|---|
| `GET /api/status` | Version, agents, models, providers |
| `POST /api/chat` | Streaming chat |
| `GET /api/memory` | Stored facts |
| `POST /api/tool` | Run a slash command |
| `POST /api/build` | Generate a site, deck or portfolio |
| `GET /api/explore` | Explore a topic |
| `GET /api/plugins` | List plugins |
| `POST /api/plugins/:id/run` | Run one |
| `GET /api/library` | Saved items |
| `GET /api/schedule` | Scheduled jobs |
| `GET /api/workspace` | Workspace state |

---

## Tests

```bash
npm test
```

| Suite | Covers |
|---|---|
| `test.js` + `test_v21.js` | 70 unit and structural checks (one stage, two files) |
| `check-api.js` | 76 API and plugin checks |
| `check-highlight.js` | the highlighter, including XSS safety |
| `check-qr.js` | 72 QR round-trip checks |
| `check-calc.js` | 50 calculator checks, 22 of them injection attempts |
| `check-e2e.js` | 57 end-to-end checks against a live server |

Run one on its own: `npm run test:api`, `test:qr`, `test:calc` and so on.

---

## Privacy

- Chat history, memory and settings live in your browser and in `data/` on
  your machine. Nothing is sent anywhere.
- No analytics, no telemetry, no tracking, no crash reporting.
- API keys you type into Settings are stored in your browser's `localStorage`
  and are never written to disk by the app.
- The server binds to `127.0.0.1`, so it is not reachable from your local
  network unless you deliberately change `HOST`.

---

## Website

A project website lives in [`docs/`](docs/index.html) and is published through
GitHub Pages:

**https://abhijeet-kumar-prajapati.github.io/olmavax-A.I/docs/**