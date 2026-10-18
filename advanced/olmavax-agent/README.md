<div align="center">

# Open Olmavax Agent

### A self-evolving personal AI agent that runs entirely on your own machine

`v2.1.0 · OLMAVAX-AGENT-CORE · Windows + Android (PWA)`

**Zero dependencies required.** Standard library only — memory, security, skills,
code execution, image generation and the whole interface work with nothing installed.

</div>

---

## What this is

Open Olmavax Agent is a personal agent kernel: it remembers, learns rules from its own
mistakes, controls your computer, researches the internet, writes and runs code in
several languages, generates images and animation, and protects itself and you while
doing it.

It does that through one loop, run on **every** request:

```
parse → recall → consult lessons → security gate → act → verify → record → reflect
```

The last step is what makes it *self-improving*. The outcome of every task is stored
as an episode, and the reflector distils a rule from it. Next time a similar request
arrives, that rule is already in hand.

> **Honest scope.** This is a real, working agent — not an omniscient one. It cannot
> answer anything, and it will say so instead of guessing. What it *does* do, it does
> for real: the memory persists, the encryption is real, the sandbox really kills
> runaway processes, and the 167 tests pass. Section [Limits](#limits-what-this-is-not)
> is as important as the rest.

---

## Quick start

No installation required. Python 3.10+ is the only prerequisite.

```bat
start.bat          :: Windows menu - chat, voice, 3D interface, doctor
```

or directly:

```bat
py olmavax_agent.py ui --open     :: 3D holographic interface in your browser
py olmavax_agent.py chat          :: text chat
py olmavax_agent.py voice         :: wake-word listening
py olmavax_agent.py doctor        :: diagnose the installation
```

Your data lives in one folder and never leaves your machine:

```
%LOCALAPPDATA%\Olmavax Agent\
├── memory\olmavax_agent_memory.sqlite3   everything it knows
├── mind\mind.json                  everything it has learned
├── vault\secrets.enc               encrypted credentials
├── logs\audit.log                  tamper-evident audit trail
├── curriculum\                     topics it has studied
├── skills\learned\                 skills it wrote for itself
└── exports\                        generated images, code runs, media
```

Point it elsewhere any time with `OLMAVAX_AGENT_HOME`.

---

## The interface

```bat
py olmavax_agent.py ui --open
```

Seven panels over a live **WebGL holographic core** — a pulsing arc-reactor rendered
from raw WebGL, no 3D library, that reacts to how hard the agent is working.

| Panel | What it does |
|---|---|
| **Talk** | Chat, **Think** mode, file attachments, live voice, latency and recall counts |
| **Brain** | Memory stats, full-text search, rules it has taught itself, improvement cycle |
| **Shield** | Posture control, live security report, audit trail, encrypted vault |
| **Studio** | Generate images and animation, browse the gallery |
| **Lab** | Run code in Python/JS/TS, run the test suite, browse all tools |
| **History** | Every past conversation — reopen, delete, export |
| **Settings** | 19 live settings, profile, optional passphrase |

**Live voice.** The mic button opens a full-screen conversation. It listens
continuously, sends your message when you stop talking, answers out loud, then goes
back to listening — a loop, not a push-to-talk. Three details make it usable rather
than a toy:

- The ring is driven by your **actual microphone level**, so it moves when you speak.
- **You can interrupt.** Start talking while it is answering and the speech stops
  immediately, mid-sentence.
- **You can mute**, which stops the listening but leaves the conversation open.

Everything said in live mode is also written into the normal transcript, so the
chat panel keeps the record. `Esc` ends it.

**History and new conversations.** History has its own button in the top bar with a
live count, not just a small rail icon. The `+` button starts a fresh conversation
under its own id, so sessions do not pile into one endless transcript.

**Think mode.** The toggle beside the input turns on visible reasoning. Instead of
just an answer you get the goal, the shape it recognised, every step taken, what was
found at each one, a confidence figure, and — the part that matters — **what it is
unsure about**. It also flags its own failures: an answer that came out empty, one
that is really a limitation notice, or links it cites that it never actually
retrieved. Switch it off and you get only the answer.

**Attachments.** The `+` button uploads a file (max 24 MB, text/code/data/image
extensions) and analyses it before answering — CSV column statistics, Python
structure and risk points, Markdown headings, JSON validity, image dimensions. The
filename is stripped to a safe stem and kept inside `exports/uploads`; a crafted
path like `../../Windows/System32/evil.exe` is flattened and its extension dropped.

Light and dark themes. Works as an Android **PWA** — open the URL in Chrome, then
*Add to Home screen* for a fullscreen, offline-capable app.

---

## What it can actually do

All 73 tools run through one security gate. `py olmavax_agent.py tools` lists them.

### Thinking, coding and files

The layer that makes it work like an assistant rather than a lookup table. Every
part works with or without a language model connected.

| Ask it | What happens |
|---|---|
| `think through why my code is slow` | Classifies the request shape, runs a matching plan, **verifies the result**, reports confidence and doubts |
| `write a program to ...` | Generates code, then **actually runs it** — and tells you plainly if it failed |
| `review this code` | Real static analysis: shell calls, `eval`, bare `except`, unimplemented functions, missing docstrings, branching complexity, with severity levels |
| `explain this code` | Function-by-function walkthrough from the parsed AST |
| `test this function` | Writes a `unittest` file, runs it, reports pass/fail |
| `analyse this file` / attach a file | Structure, columns, types, ranges, averages, gaps, missing data |
| `summarise this csv` | Plain-English description of a dataset |
| `plan how to launch ...` | A shape-aware checklist saved to disk |
| `compare X and Y` | Options weighed against explicit criteria you choose |

Plans are template-driven when no model is connected, because generic filler steps
are worse than an honest default.

### The mind — it actually learns

This is the part that makes it an agent rather than a script. Three small models
train **at runtime, on your machine, from your own usage** — no cloud, no API:

| Model | Algorithm | What it learns |
|---|---|---|
| **Router** | sparse softmax regression, AdaGrad, pure Python | Which command a request means — including phrasings nobody programmed |
| **Bandit** | UCB1 contextual bandit | Which action actually works for this kind of request, and to stop retrying the ones that don't |
| **Calibrator** | exponential moving average per intent | How reliable it is at each thing, so it stops sounding sure about what it keeps getting wrong |

It trains on **every request**. Measured on the built-in benchmark: after a
single epoch it classifies phrasings it has never seen at **86%**, from nothing.

```
$ olmavax_agent mind benchmark

    step   examples   correct  accuracy
  ------------------------------------------
       1         13     4/7     57%  #################
       3         39     5/7     71%  #####################
       6         78     6/7     86%  #########################
       8        104     6/7     86%  #########################
```

**And it listens when you correct it.** Say *"nahi, ye galat hai"* and it marks
that phrasing as wrong — then learns the right intent from whatever you ask for
next. That is the highest-value training signal in the whole system, because it
is you correcting it explicitly.

```
$ olmavax_agent mind

  training examples : 8
  intents known     : 52
  weights stored    : 11,818 (92.4 KB)
  corrections taken : 0

  what it has learned
        23.75  open_app
        21.95  image_generate
        10.15  code_run

  what it is worst at  (so it stays humble there)
       47%  open_app           2 tries, 0 corrections

  action bandit  5 contexts, 5 actions, 7 trials
      100%  media.image                2 tries
```

Everything persists to `mind/mind.json` — learning survives restarts.
`olmavax_agent mind explain "your phrase"` shows exactly what it thinks and why.

**Why a hand-written rule table can't replace this:** rules are frozen at author
time. The mind keeps changing after shipping, from evidence only you can supply.

### Memory and learning
- Hybrid recall — SQLite **FTS5** keyword search blended with **cosine similarity**
  over 256-dimension hashed word vectors. Works with zero dependencies.
- Five stores: memories, episodes, lessons, preferences, conversation window.
- Duplicate detection, importance decay, sleep-cycle consolidation, full export/import.

### Self-improvement
- **Reflection** — after each task it asks what worked, why, and what rule would have
  helped. The rule is stored as a *lesson* and consulted before similar tasks.
- **Skill synthesis** — when the same task shape succeeds 3+ times, it writes a real
  Python skill to `skills/learned/`. Skills ship **disabled** (`guard = "reviewed=False"`)
  until you read the file and flip it. It will not enable its own code.
- **Consolidation** — fades unimportant memories, prunes stale turns, retires rules
  that stopped working, and reassesses the security posture.

### Your computer
Open apps, control volume (via multimedia keys — no pycaw needed), lock, sleep,
shutdown, screenshot, clipboard, notifications, search and read files, manage
processes. Every path is resolved through a jail that refuses `../` escapes and
credential locations. **Deletion goes to the Recycle Bin, never a hard delete.**

### The internet
- Search, fetch and clean page text, Wikipedia summaries
- **Learn a topic** — builds a mini-curriculum from documentation + Wikipedia, stores
  it in memory so it can answer about it later
- **Learn from YouTube** — pulls the caption track without an API key, summarises it
  extractively, and remembers it
- Untrusted page text is passed through the injection scanner and stored as *reference
  data*, never as instructions

### Code
Python, JavaScript, TypeScript, C, Java, batch, PowerShell. Every run is a fresh
process with a wall-clock timeout, output caps and a deliberately minimal environment.
Plus syntax checking, static analysis that flags `eval`/`exec`/`shell=True`, test
running, and project scaffolding.

### Creating things
A **pure standard-library generative renderer** with its own PNG encoder (zlib + CRC32,
no Pillow). Seven styles — `plasma`, `fractal`, `core`, `neon-grid`, `circuit`,
`starfield`, `aurora` — deterministically seeded from the prompt, so the same prompt
always paints the same picture.

Animation writes a PNG sequence **and a self-contained animated SVG** (SMIL, no
JavaScript), and upgrades to MP4/GIF automatically when ffmpeg is installed.

---

## Security

Five layers, all testable:

1. **Intent risk scoring** — every request is scored 0.0–1.0 from the actions it
   implies, using saturating combination so three scary words don't reach critical but
   one genuinely critical action always does.
2. **Capability gates** — each tool declares the capabilities it needs. Asking for an
   undeclared one raises `CapabilityDenied`. This applies to *direct* function calls
   too, so internal code cannot accidentally skip the gate.
3. **Path jail** — filesystem work resolves through `safe_path`, which refuses
   traversal, out-of-root absolute paths, and credential locations (`.ssh`, `SAM`,
   BitLocker, shadow copies) regardless of the roots given.
4. **Secret hygiene** — outputs are scrubbed for OpenAI/Anthropic/Google/GitHub/HF/AWS
   key shapes and `password = …` patterns before reaching a log, the chat history or
   the UI. A credential in chat is *refused*, never stored.
5. **Self-assessment** — the agent reviews its own recent decisions and recommends a
   tighter posture around sensitive work.

```bat
py olmavax_agent.py security scan      :: actually executes each check, does not assume
```

```
  PASS  vault encrypted
  TIP   strong vault key (OLMAVAX_AGENT_MASTER_KEY)
  PASS  path jail active
  PASS  secret scrubber (4/4)
  PASS  audit chain intact
```

**Postures** — how careful it is before acting:

| Posture | Asks above | Use for |
|---|---|---|
| `paranoid` | 10% risk | unfamiliar or high-impact work |
| `balanced` | 35% | daily default |
| `sandbox` | 60% | long unattended runs |
| `open` | 90% | only when nothing risky is happening |

**Hard blocks** — refused even with confirmation, ever: disk format, bulk delete,
recovery sabotage, credential-theft tooling.

**Vault** — `PBKDF2-HMAC-SHA256` ×310k + `HMAC-SHA256` counter-mode keystream with
encrypt-then-MAC authentication. Set `OLMAVAX_AGENT_MASTER_KEY` for a key that is not
machine-bound.

**Audit trail** — every entry stores `sha256(previous_hash + entry)`. Edit or remove a
line and `verify()` reports the break.

---

## Voice

```bat
py olmavax_agent.py voice
```

Say the wake word (**olmavax_agent** / **jarvis**), then your request. **Say `exit`, `bus`,
`bye` or `band karo` and it powers down.**

Understands English, Hindi and Hinglish — `band karo`, `याद रखो`, `exit the loop in
this code` (deliberately *not* treated as an exit; the check is strict on length).

Speech out: `pyttsx3` if installed, else Windows SAPI via PowerShell (text passed as
base64, so nothing can corrupt it), else prints.
Speech in: `speech_recognition` → Vosk (offline) → Whisper (offline) → typed fallback.
`py olmavax_agent.py doctor` tells you which one won.

---

## Connecting a language model

The agent is fully functional **without** one — it falls back to memory, retrieved web
results and local calculation, and clearly labels those answers as offline reasoning.

For full conversation, pick one:

```bat
:: Option 1 — free and fully offline (recommended)
::   1. install Ollama from https://ollama.com/download
::   2. ollama serve
::   3. ollama pull llama3.1:8b

:: Option 2 — cloud key
setx OLMAVAX_AGENT_GROQ_KEY    sk-...     :: free tier, very fast
setx OLMAVAX_AGENT_OPENAI_KEY  sk-...
setx OLMAVAX_AGENT_GEMINI_KEY  AIza...
setx OLMAVAX_AGENT_ANTHROPIC_KEY  sk-ant-...
setx OLMAVAX_AGENT_TOGETHER_KEY   ...
```

`py olmavax_agent.py doctor` shows exactly what is connected and what is missing.

---

## Optional extras

Nothing here is required. Install only what you want:

```bat
pip install SpeechRecognition    :: simplest speech-to-text (needs internet)
pip install pyttsx3              :: faster speech output
pip install Pillow               :: better screenshots
```

`py olmavax_agent.py doctor` prints a full capability table.

---

## Command line

| Command | What it does |
|---|---|
| `olmavax_agent.py chat` | interactive text chat |
| `olmavax_agent.py ask "..."` | one question, print, exit |
| `olmavax_agent.py voice` | wake-word listening loop |
| `olmavax_agent.py ui --open` | 3D interface |
| `olmavax_agent.py remember "..."` / `recall "..."` | memory |
| `olmavax_agent.py memory` | memory dashboard |
| `olmavax_agent.py security scan` | self security scan |
| `olmavax_agent.py audit` | read the audit trail |
| `olmavax_agent.py improve --full` | run a self-improvement cycle now |
| `olmavax_agent.py mind` | what the self-learning core has learned |
| `olmavax_agent.py mind benchmark` | prove it learns, with numbers |
| `olmavax_agent.py mind explain "..."` | see what it thinks of a phrase |
| `olmavax_agent.py mind reset` | wipe everything it learned |
| `olmavax_agent.py skills [list\|reload\|enable\|disable\|new]` | skills |
| `olmavax_agent.py vault set <key>` | encrypted secret |
| `olmavax_agent.py tools --tag media` | list tools |
| `olmavax_agent.py learn "<topic>"` | study and remember a topic |
| `olmavax_agent.py doctor` | diagnose |
| `olmavax_agent.py test` | run the test suite |

---

## Using it as a library

```python
import olmavax_agent

olmavax_agent.boot()
brain = olmavax_agent.get_brain()

print(brain.think("remember that my wifi password is on the fridge").text)
print(brain.think("draw an image of a neon city").text)
print(brain.status()["memory"])
```

---

## Testing

```bat
py olmavax_agent.py test
```

**115 tests**, standard library only, each against a throwaway `OLMAVAX_AGENT_HOME` so your
real memory is never touched. They cover the places where a silent mistake would be
expensive:

- **the mind actually learns** — trained on one set of phrasings, then required to
  classify phrasings it has never seen
- the bandit abandons actions that keep failing; contexts stay independent
- a correction genuinely weakens the wrong label; **a confident rule is never
  overridden by the learned model** (so learning cannot talk it into formatting a disk)
- memory durability, dedup, decay, vector determinism, export/import
- risk scoring, hard blocks, capability containment, path traversal, secret scrubbing
- encryption round trips, **wrong-passphrase rejection**, **tampered-ciphertext rejection**
- sandbox timeout, stderr capture, argument validation
- intent parsing — including that *"explain the exit loop in this code"* does **not**
  shut the agent down
- that **direct tool calls are still gated**
- brain never raises, records an episode, and refuses destructive requests

---

## Architecture

```
cli.py            command line
server.py         loopback HTTP API + serves the interface
voice.py          speech in/out, wake word
brain.py          the kernel: parse → recall → gate → act → verify → learn
reasoning.py      request classification, plan execution, answer verification
mind.py           the self-learning core: AdaGrad router, UCB1 bandit, calibrator
routing.py        one handler per intent
nlu.py            English / Hindi / Hinglish intent parsing
llm.py            provider bridge + offline fallback reasoner
tools/            system · web · dev · media · knowledge · capability
self_improve.py   reflection · skill synthesis · consolidation
skills.py         loads skill files as tools
memory.py         SQLite memory, hybrid keyword + vector recall
security.py       risk · capability gates · path jail · scrubbing · self-assessment
vault.py          encrypted secret storage
user.py           profile · session history · settings
events.py         pub/sub so UI, voice and logs stay decoupled
config.py         every setting, overridable
logger.py         logging + tamper-evident audit trail
utils.py          shared helpers
ui/               WebGL interface, CSS, PWA manifest
tests/            167 tests
```

`config.py`, `events.py`, `logger.py` and `utils.py` were the existing foundation.
Everything else is built on top of them without rewriting them.

---

## Limits — what this is *not*

Stated plainly, because an agent that oversells itself is worse than a limited one.

- **Not omniscient.** It needs a language model for open-ended conversation. Without
  one it answers from memory and calculation and says so.
- **The mind is not a language model.** It learns routing, tool choice and
  self-assessment — not grammar, facts or reasoning. It is a few thousand weights
  trained on your requests, not billions. Expect it to be good at *understanding
  what you want to do* and useless at *writing poetry*.
- **"3D/4D/5D" is a holographic UI, not physics.** The interface is a real WebGL
  renderer. It is not a volumetric display and does not pretend to be.
- **Image generation is generative art, not diffusion.** Seven procedural styles from a
  seeded renderer — no model weights, no photorealism. Connect a diffusion API for that.
- **The sandbox is process-level, not kernel-level.** Timeouts, output caps, a
  minimal environment and a path jail — a determined escape is not impossible, only
  hard. True isolation needs a container or VM.
- **"Learning from the internet" means retrieval.** It reads documentation and
  captions into memory. It is not retraining a model.
- **MP4 output needs ffmpeg.** Without it you still get the PNG sequence and animated
  SVG, and the response says what to install.
- **Think mode shows working, not certainty.** The plan, steps and caveats are real,
  but they come from a classifier plus a small number of templates, not from a
  reasoning model. It will show you a confident-looking chain that reaches a wrong
  conclusion when no language model is connected.
- **`code.write` needs a model.** Without one there is nothing to generate — the tool
  says so rather than emitting a stub. `code.review`, `code.explain` and `file.analyze`
  work fully offline because they analyse code that already exists.
- **Attachments are analysed, not understood.** The agent reads structure and
  statistics out of an uploaded file. It will not answer a question about your
  spreadsheet's *meaning* without a model to reason over it.

---

## Configuration

`config.json` in the agent home, or environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `OLMAVAX_AGENT_HOME` | `%LOCALAPPDATA%\Olmavax Agent` | where everything lives |
| `OLMAVAX_AGENT_MASTER_KEY` | machine-bound | vault passphrase |
| `OLMAVAX_AGENT_POSTURE` | `balanced` | `paranoid`\|`balanced`\|`sandbox`\|`open` |
| `OLMAVAX_AGENT_PROVIDER` | `auto` | `ollama`\|`openai`\|`groq`\|`gemini`\|`anthropic`\|`offline` |
| `OLMAVAX_AGENT_MODEL` | `auto` | model id override |
| `OLMAVAX_AGENT_OWNER` | `Boss` | what it calls you |
| `OLMAVAX_AGENT_DEBUG` | `0` | verbose logging |

---

## Privacy

Everything is local. No telemetry, no phone-home, no accounts. The only outbound
requests are ones you ask for (search, fetch, a model API), and page content fetched
from the internet is never treated as instructions to the agent.