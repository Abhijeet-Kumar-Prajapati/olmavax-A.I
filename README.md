# Olmavax A.I

A local-first, multi-agent AI workspace that runs entirely on your own machine.
No account, no cloud, no telemetry — open the app and it works, even with no API key.

![Olmavax A.I](public/logo.svg)

---

## What it is

Olmavax A.I is a single Node.js server with a browser front end. It gives you a
chat workspace, a voice mode you can keep typing through, nine built-in agents,
nineteen local plugins, long-term memory, scheduled tasks, a code workbench,
PDF export, QR generation and syntax highlighting for twenty-two languages.

Everything works offline. A built-in brain answers maths, conversions, text
utilities and web lookups with no network at all. Add a provider key and the
same interface talks to Claude, GPT, Ollama or the OpenCharvis sidecar.

## Highlights

| | |
|---|---|
| **Voice + chat together** | A compact dock floats above the composer. Speak, read the reply aloud, and keep typing — both at once. Spoken turns are written into the chat automatically and also kept in a separate voice log. |
| **19 local plugins** | Calculator with roots and percentages, unit converter, text tools, colour, dates, passwords and more. They run on the server, not through a model. |
| **Nine agents** | Auto-routing plus dedicated ones for code, research, writing, vision and analysis. |
| **Syntax highlighting** | Twenty-two languages, written from scratch, XSS-safe, no CDN. |
| **Memory** | Facts you tell it are stored and recalled across chats. |
| **Scheduled tasks** | Cron-style jobs that run prompts on a timer. |
| **PDF export** | Saves a chat as a real PDF, generated server-side with no dependencies. |
| **QR codes** | A from-scratch QR encoder (versions 1–20, error correction and all). |
| **Five languages** | English, हिन्दी, Español, Français, العربية — including right-to-left Arabic. |
| **Adaptive sidebar** | Icon rail, small, medium or large. The chat history stays reachable at every size. |
| **Zero dependencies** | `npm install` has nothing to install. The whole app is plain Node and vanilla JS. |

## Requirements

- **Node.js 18 or newer** — that is the only hard requirement.
- Optional: [Python 3.10+](https://www.python.org/) for the OpenCharvis sidecar.
- Optional: [Ollama](https://ollama.com) for a fully local model.

## Getting started

```bash
git clone https://github.com/Abhijeet-Kumar-Prajapati/olmavax-A.I.git
cd olmavax-A.I
npm start
```

Then open **http://127.0.0.1:8787**.

On Windows you can double-click `start-olmavax.bat` instead.

### Connecting a model

The app is useful with no configuration at all. When you want a real model, open
**Settings** and paste a key:

| Provider | What to paste |
|---|---|
| Anthropic | `sk-ant-…` |
| OpenAI or compatible | `sk-…`, plus a Base URL for Groq, Together, OpenRouter and friends |
| Ollama | nothing — just make sure Ollama is running locally |

Keys are stored in your browser's `localStorage` and are never written to disk by
the app. For headless or Docker setups, copy `.env.example` to `.env` instead.

### The OpenCharvis sidecar

`advanced/OpenCharvis` is an optional Python agent that adds planning, memory
search, scheduled skills and a voice pipeline.

```bash
python advanced/OpenCharvis/charvis.py ui
```

It listens on `127.0.0.1:8765` and Olmavax bridges to it automatically. If it is
not running, nothing breaks — the rest of the app is unaffected.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl` `B` | Collapse or expand the sidebar |
| `Ctrl` `M` | Start voice mode |
| `T` or `V` | Start voice mode |
| `Ctrl` `K` | Command palette |
| `Ctrl` `Shift` `F` | Search chats |
| `Esc` | Close the current panel or voice mode |

## Project layout

```
olmavax-ai/
├─ server/            Node backend — zero dependencies
│  ├─ server.js         HTTP routes and static file serving
│  ├─ offline.js        the built-in brain
│  ├─ plugins.js        the nineteen plugins
│  ├─ agents.js         agent definitions and routing
│  ├─ qr.js             QR encoder (GF(256), Reed-Solomon, masking)
│  ├─ pdf.js            dependency-free PDF writer
│  ├─ charvis.js        OpenCharvis sidecar bridge
│  ├─ scheduler.js      cron-style scheduled tasks
│  └─ collections.js    library and workspace storage
├─ public/            Browser front end
│  ├─ index.html        the shell
│  ├─ app.js            all front-end logic
│  ├─ style.css         the whole design system
│  ├─ highlight.js      22-language syntax highlighter
│  ├─ i18n.js           222 strings across 5 languages
│  └─ sw.js             offline service worker
├─ advanced/
│  └─ OpenCharvis/      optional Python agent (20 modules)
├─ python/
│  └─ olmavax_cli.py    command-line client
├─ extension/          browser extension shell
└─ tests/              six test suites
```

## Tests

```bash
npm test
```

| Suite | Covers |
|---|---|
| `test.js` + `test_v21.js` | 67 unit and structural checks |
| `check-api.js` | 76 API and plugin checks |
| `check-highlight.js` | the syntax highlighter, including XSS safety |
| `check-qr.js` | 72 QR round-trip checks |
| `check-calc.js` | 50 calculator checks, including injection attempts |
| `check-e2e.js` | 57 end-to-end checks against a live server |

Run one suite on its own with `npm run test:api`, `test:qr`, and so on.

## Docker

```bash
docker build -t olmavax-ai .
docker run -p 8787:8787 olmavax-ai
```

## Browser extension

`extension/` contains a manifest and popup for installing Olmavax as a side
panel. Load the folder as an unpacked extension in your browser.

## Privacy

- Chat history, memory and settings live in your browser and in `data/` on your
  machine. Nothing is sent anywhere.
- There is no analytics, telemetry, tracking or crash reporting.
- The server binds to `127.0.0.1` by default, so it is not reachable from your
  local network unless you deliberately change `HOST`.

## License

No license file is published with this project. All rights reserved by the
author unless you add one.

## Credits

OpenCharvis is vendored under `advanced/OpenCharvis`. See its own README for
details.