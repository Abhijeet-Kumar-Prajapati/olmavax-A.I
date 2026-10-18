"""
Olmavax Agent - Command line
===========================
One entry point for everything::

    olmavax_agent                  interactive text chat
    olmavax_agent ask "..."        one question, print the answer, exit
    olmavax_agent voice            wake-word listening loop
    olmavax_agent ui               3D interface in your browser
    olmavax_agent remember "..."   store a fact
    olmavax_agent recall "..."     search memory
    olmavax_agent memory           memory dashboard
    olmavax_agent skills           list / reload / enable skills
    olmavax_agent security         report, self-scan, posture
    olmavax_agent improve          run a self-improvement cycle now
    olmavax_agent test             run the test suite
    olmavax_agent doctor           diagnose the installation
    olmavax_agent vault            encrypted secrets
    olmavax_agent tools            list every tool
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import __codename__, __version__, boot
from .config import PATHS, capability_report, ensure_dirs, get_config
from .logger import setup_logging
from .utils import human_duration, human_size, pluralize, truncate

# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

_USE_COLOUR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text


def cyan(t: str) -> str:
    return _c(t, "36")


def green(t: str) -> str:
    return _c(t, "32")


def yellow(t: str) -> str:
    return _c(t, "33")


def red(t: str) -> str:
    return _c(t, "31")


def bold(t: str) -> str:
    return _c(t, "1")


def dim(t: str) -> str:
    return _c(t, "2")


def rule(char: str = "-", width: int = 66) -> str:
    return dim(char * width)


def banner() -> None:
    cfg = get_config()
    print()
    print(bold(cyan("  OLMAVAX AGENT")) + dim(f"  v{__version__}  ({__codename__})"))
    print(rule("="))
    print(f"  home     : {PATHS['home']}")
    print(f"  brain    : {cfg.brain.provider} / {cfg.brain.model}")
    print(f"  security : {cfg.security.posture} posture, "
          f"asks above {cfg.security.risk_threshold():.0%} risk")
    print(f"  memory   : {PATHS['memory_db'].name}")
    print(rule("="))
    print(dim("  say 'exit' or 'bus' at any time to close"))
    print()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_boot(args: argparse.Namespace) -> int:
    report = boot()
    banner()
    print(green(f"  {pluralize(report['tools'], 'tool')} ready"))
    if report["skills"]["loaded"]:
        print(green(f"  {pluralize(len(report['skills']['loaded']), 'skill')} loaded: "
                    f"{', '.join(report['skills']['loaded'])}"))
    if report["skills"]["failed"]:
        print(yellow(f"  {len(report['skills']['failed'])} skill(s) failed to load"))
    print(green(f"  memory ready with {report['memory']['active_memories']} active memories"))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from .brain import get_brain

    brain = get_brain()
    reply = brain.think(args.text, source="cli")
    print()
    print(bold(cyan("olmavax_agent>")) + " " + reply.text)
    if reply.offline:
        print(dim(f"  (offline reasoning - no model connected; {reply.elapsed:.2f}s)"))
    elif reply.elapsed:
        print(dim(f"  ({reply.elapsed:.2f}s)"))
    if args.json:
        print(json.dumps(reply.to_dict(), indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    from .brain import get_brain

    brain = get_brain()
    banner()

    # Speaking is on by default - an assistant that never opens its mouth is
    # just a log file with a prompt.
    speaker = None
    if not args.mute:
        try:
            from .voice import get_voice

            speaker = get_voice().speaker
        except Exception as exc:
            print(dim(f"  (voice unavailable: {exc})"))
    print(dim(f"  speaking: {'on' if speaker else 'off'}   "
              f"(press 'exit' to leave)\n"))

    turns = 0
    try:
        while True:
            try:
                text = input(bold(cyan("you> "))).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            reply = brain.think(text, source="cli")
            turns += 1
            print(bold(green("olmavax_agent>")) + " " + reply.text)
            print(dim(f"  [{reply.intent} | {reply.elapsed:.2f}s"
                      + (" | offline reasoning" if reply.offline else "") + "]"))
            print()
            if speaker and reply.text and args.mute is False:
                speaker.speak(reply.text)
            if reply.intent == "shutdown":
                break
    finally:
        print(dim(f"  {pluralize(turns, 'turn')} handled. goodbye."))
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    from .brain import get_brain
    from .voice import get_voice

    voice = get_voice()
    print()
    print(voice.report())
    print()
    if not voice.listener.can_listen and not args.allow_typed:
        print(yellow("  No speech recognition engine is installed."))
        print("  Options:")
        print("    pip install SpeechRecognition        (online, easiest)")
        print("    pip install vosk + a model           (fully offline)")
        print("    pip install openai-whisper          (offline, accurate)")
        print(dim("  Running in typed mode - type commands instead.\n"))
    brain = get_brain()
    voice.loop(brain, max_turns=args.max_turns)
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    import webbrowser

    from .server import serve

    url = f"http://{args.host}:{args.port}"
    print()
    print(bold(cyan("  starting the interface")))
    print(f"  {green(url)}")
    print(dim("  loopback only - not reachable from your network"))
    print(dim("  press Ctrl+C here to stop\n"))
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        serve(args.host, args.port)
    except RuntimeError as exc:
        print(red(f"  {exc}"))
        return 1
    return 0


def cmd_remember(args: argparse.Namespace) -> int:
    from .memory import get_memory

    stored = get_memory().add(
        args.text,
        kind=args.kind,
        tags=[t for t in (args.tags or "").split(",") if t],
        importance=args.importance,
        source="cli",
    )
    if stored:
        print(green(f"  stored memory #{stored.id}: {truncate(stored.text, 100)}"))
        return 0
    print(red("  nothing was stored"))
    return 1


def cmd_recall(args: argparse.Namespace) -> int:
    from .memory import get_memory

    results = get_memory().search(args.text, limit=args.limit)
    if not results:
        print(yellow(f"  nothing stored about '{args.text}'"))
        return 0
    print()
    for result in results:
        memory = result.memory
        print(f"  {green(str(round(result.score * 100)) + '%')}  "
              f"{dim('[' + memory.kind + ']')}  {truncate(memory.text, 110)}")
        print(dim(f"         tags={','.join(memory.tags) or '-'}  "
                  f"importance={memory.importance:.2f}  age={memory.age_days:.0f}d  "
                  f"used={memory.use_count}x"))
    print()
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    from .memory import get_memory

    store = get_memory()
    stats = store.stats()
    print()
    print(rule("="))
    print(bold("  MEMORY"))
    print(rule("="))
    print(f"  database      : {store.path}")
    print(f"  size          : {human_size(stats['db_bytes'])}")
    print(f"  active        : {stats['active_memories']}")
    print(f"  vector dim    : {stats['vector_dim']}   keyword index: "
          f"{'FTS5' if stats['fts'] else 'LIKE fallback'}")
    print()
    print("  by kind:")
    for kind, count in sorted(stats["by_kind"].items(), key=lambda kv: kv[1], reverse=True):
        bar = "#" * min(40, count)
        print(f"    {kind:<14} {count:>5}  {dim(bar)}")
    print()
    episodes = stats["episodes"]
    print("  experience:")
    print(f"    episodes      : {episodes['total']}")
    print(f"    success rate  : {episodes['success_rate']:.1%}")
    print(f"    avg duration  : {episodes['avg_duration']}s")
    print(f"    lessons       : {stats['counts'].get('lessons', 0)}")
    print()
    lessons = store.lessons(limit=8)
    if lessons:
        print("  rules I have learned:")
        for lesson in lessons:
            print(f"    [{lesson.confidence:.0%}] {truncate(lesson.rule, 88)}")
        print()
    print(dim("  use: olmavax_agent remember \"...\"   olmavax_agent recall \"...\""))
    print()
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    from .memory import get_memory

    store = get_memory()
    if args.id:
        store.forget(args.id)
        print(green(f"  memory #{args.id} deleted"))
        return 0
    found = store.find(args.text, limit=10)
    if not found:
        print(yellow("  nothing matched"))
        return 0
    print()
    for memory in found:
        print(f"  #{memory.id}  {truncate(memory.text, 100)}")
    print()
    print(dim("  re-run with --id <number> to delete"))
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    from .skills import get_registry

    registry = get_registry()
    if args.action == "reload":
        report = registry.load(verbose=True)
        print(green(f"  loaded {len(report['loaded'])}, skipped {len(report['skipped'])}, "
                    f"failed {len(report['failed'])}"))
        for failure in report["failed"]:
            print(red(f"    {failure['file']}: {failure['error']}"))
        return 0

    if args.action in {"enable", "disable"}:
        result = getattr(registry, args.action)(args.name)
        print(green(f"  {args.action}d '{args.name}'") if result["ok"]
              else red(f"  failed: {result['error']}"))
        return 0 if result["ok"] else 1

    if args.action == "new":
        path = registry.create(args.name, args.description or f"Skill {args.name}")
        print(green(f"  created {path}"))
        return 0

    listing = registry.listing()
    print()
    print(rule("="))
    print(bold("  SKILLS"))
    print(rule("="))
    if not listing:
        print(yellow("  no skills found"))
        print(dim("  create one:  olmavax_agent skills new my_skill --description \"what it does\""))
        print()
        return 0
    for info in listing:
        mark = green("on ") if info["enabled"] else yellow("off")
        origin = dim(" (auto-learned)") if info["auto_learned"] else ""
        print(f"  [{mark}] {bold(info['name'])}{origin}")
        print(f"        {truncate(info['description'], 76)}")
        print(dim(f"        {info['path']}"))
        if not info["enabled"]:
            print(dim(f"        reason: {info['reason']}"))
        print()
    print(dim("  enable: olmavax_agent skills enable <name>    reload: olmavax_agent skills reload"))
    print()
    return 0


def cmd_security(args: argparse.Namespace) -> int:
    from .security import get_security

    sec = get_security()

    if args.action == "posture" and args.posture:
        if sec.apply_posture(args.posture):
            get_config().security.posture = args.posture
            print(green(f"  posture is now {args.posture}"))
        else:
            print(red("  unknown posture - use paranoid, balanced, sandbox or open"))
        return 0

    if args.action == "scan":
        report = sec.scan_status()
        print()
        print(rule("="))
        print(bold("  SELF SECURITY SCAN"))
        print(rule("="))
        checks = [
            ("vault encrypted", report["vault_protected"], bool),
            ("strong vault key (OLMAVAX_AGENT_MASTER_KEY)", report["strong_key"], None),
            ("path jail active", report["path_jail"], bool),
            (f"secret scrubber ({report['scrubber_tests_passed']}/{report['scrubber_tests']})",
             report["scrubber_tests_passed"] == report["scrubber_tests"], bool),
            ("audit chain intact", report["audit_chain_intact"], bool),
        ]
        for label, passed, required in checks:
            if passed:
                mark = green("PASS")
            elif required is None:
                mark = yellow("TIP ")
            else:
                mark = red("FAIL")
            print(f"  {mark}  {label}")
        print()
        print(f"  assessment: {report['assessment']}")
        print()
        return 0

    status = sec.status()
    decisions = status["decisions"]
    print()
    print(rule("="))
    print(bold("  SECURITY"))
    print(rule("="))
    print(f"  posture          : {status['posture']}  "
          f"(confirm above {status['risk_threshold']:.0%} risk)")
    print(f"  decisions        : {decisions.get('allow', 0)} allowed, "
          f"{decisions.get('ask', 0)} confirmed, {decisions.get('block', 0)} blocked")
    print(f"  sandbox          : {'on' if status['sandbox'] else 'off'}")
    audit = status.get("audit", {})
    print(f"  audit trail      : {audit.get('entries', 0)} entries, "
          f"chain {'intact' if audit.get('chain_intact') else 'BROKEN'} "
          f"({audit.get('checked', 0)} verified)")
    print(f"  my advice        : {status['advice']['why']}")
    print(f"  recommended      : {status['advice']['recommended_posture']}")
    print()
    print(dim(f"  {pluralize(len(status['capabilities']), 'gated capability')}"))
    print(dim("  change posture: olmavax_agent security posture --posture paranoid"))
    print()
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .logger import AuditTrail

    trail = AuditTrail()

    if args.repair:
        report = trail.verify()
        if report.get("valid"):
            print(green("  the chain already verifies - nothing to repair"))
            return 0
        archived = trail.path.with_name(
            f"{trail.path.name}.unverifiable-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        try:
            trail.path.replace(archived)
        except OSError as exc:
            print(red(f"  could not archive the log: {exc}"))
            return 1
        fresh = AuditTrail()
        fresh.record(
            "audit.repair", "allow",
            f"archived an unverifiable audit log to {archived.name} "
            f"(break was at line {report.get('broken_at')}: {report.get('reason')}); "
            "starting a fresh chain",
            0.0,
        )
        print(yellow(f"  old log archived -> {archived.name}"))
        print(green("  fresh chain started; verification now passes"))
        return 0

    entries = trail.entries(limit=args.limit)
    print()
    print(rule("="))
    print(bold("  AUDIT TRAIL") + dim("   (hash chained - edits are detectable)"))
    print(rule("="))
    for entry in entries:
        colour = {"allow": green, "ask": yellow, "block": red}.get(entry.get("decision", ""), str)
        print(f"  {dim(entry.get('time', ''))}  "
              f"{colour(entry.get('decision', '').upper()):<14} "
              f"{entry.get('action', '')}  risk={entry.get('risk', 0)}")
        if entry.get("detail"):
            print(dim(f"        {truncate(entry['detail'], 88)}"))
    verify = trail.verify()
    print()
    if verify.get("valid"):
        print(f"  verification: {green('chain intact')} across "
              f"{verify.get('entries', 0)} entries")
    else:
        print(f"  verification: {red('CHAIN BROKEN')} at line "
              f"{verify.get('broken_at')} - {verify.get('reason')}")
        print(dim("  run 'olmavax_agent audit --repair' to archive it and start a fresh chain"))
    print()
    return 0


def cmd_improve(args: argparse.Namespace) -> int:
    from .self_improve import improve_now

    print()
    print(bold(cyan("  running an improvement cycle")))
    report = improve_now(full=args.full)
    stats = report["stats"]
    print()
    print(f"  {green('archived')}      : {report['archived_memories']} faded memories")
    print(f"  {green('lessons')}       : {report['lessons_reviewed']} reviewed, "
          f"{report['lessons_retired']} retired")
    print(f"  {green('posture')}       : {report['posture']['current_posture']} "
          f"-> {report['posture']['recommended_posture']} ({report['posture']['why']})")
    skills = report["skills"]
    print(f"  {green('skills')}        : {skills['on_disk']} on disk, "
          f"{skills['awaiting_review']} awaiting your review")
    print(f"  {green('episodes')}      : {stats['episodes']['total']} "
          f"({stats['episodes']['success_rate']:.0%} success)")
    print()
    if skills["awaiting_review"]:
        print(yellow("  Skills the agent wrote for itself (review before enabling):"))
        from .skills import get_registry

        for info in get_registry().listing():
            if not info["enabled"]:
                print(f"    {info['name']}  <- {info['path']}")
        print()
    return 0


def cmd_mind(args: argparse.Namespace) -> int:
    """Inspect or benchmark the self-learning core."""
    import olmavax_agent  # noqa: F401  (ensures the package is importable)
    from olmavax_agent.mind import Mind, get_mind

    mind = get_mind()

    if args.action == "reset":
        if not mind.owner:
            print(yellow("  another Olmavax Agent process owns the mind right now."))
            print(dim("  stop it first, then run this again."))
            return 1
        mind.reset()
        print(green("  mind cleared - it starts learning again from nothing"))
        return 0

    if args.action == "explain":
        if not args.text:
            print(red("  give me a phrase: olmavax_agent mind explain \"please open notepad\""))
            return 1
        report = mind.explain(args.text)
        print()
        print(rule("="))
        print(bold("  WHAT THE MIND THINKS"))
        print(rule("="))
        print(f"  phrase : {report.get('text')}")
        print(f"  trained: {report.get('trained_examples')} examples, "
              f"{report.get('features')} features extracted")
        print()
        for row in report.get("ranked", [])[:6]:
            bar = "#" * max(1, int(row["probability"] * 40))
            print(f"  {row['probability']:6.1%}  {row['intent']:<18} {dim(bar)}")
        print()
        return 0

    if args.action == "benchmark":
        return _mind_benchmark(mind)

    # default: status
    st = mind.status()
    print()
    print(rule("="))
    print(bold("  THE MIND") + dim("   (self-learning core)"))
    print(rule("="))
    if st.get("read_only"):
        print(yellow("  another Olmavax Agent process is running and owns the mind."))
        print(dim("  this window is read-only so it cannot overwrite that learning."))
        print(dim("  use the interface of the running agent, or stop it and re-run."))
        print()
    print(f"  training examples : {st['trained_examples']}")
    print(f"  intents known     : {st['classes']}")
    print(f"  weights stored    : {st['weights_stored']:,} ({human_size(st['weight_bytes'])})")
    print(f"  corrections taken : {st['corrections_learned']}")
    print(f"  last trained      : {st['last_train']}")
    print()

    print("  " + bold("what it has learned"))
    for row in st["best_learned"][:8]:
        print(f"    {row['learned_weight']:>9.2f}  {row['intent']}")

    print()
    print("  " + bold("what it is worst at") + dim("  (so it stays humble there)"))
    weak = st["calibration"]
    if weak:
        for row in weak:
            print(f"    {row['success_rate']:>6.0%}  {row['intent']:<18} "
                  f"{row['tries']} tries, {row['corrections']} corrections")
    else:
        print(dim("    not enough data yet"))

    bandit = st["bandit"]
    print()
    print(f"  " + bold("action bandit") + dim(f"  {bandit['contexts']} contexts, "
                                              f"{bandit['arms']} actions, "
                                              f"{bandit['updates']} trials"))
    for row in bandit["best"][:5]:
        print(f"    {row['success_rate']:>6.0%}  {row['arm']:<26} {row['tries']} tries")
    print()
    print(dim(f"  saved at {st['file']}"))
    print(dim("  olmavax_agent mind explain \"...\"    see what it thinks of a phrase"))
    print(dim("  olmavax_agent mind benchmark          prove it learns"))
    print(dim("  olmavax_agent mind reset              wipe everything it learned"))
    print()
    return 0


def _mind_benchmark(mind) -> int:
    """
    Train the mind on a small fixed set and measure it on phrasings it has
    never seen. This is the honest answer to "does it actually learn".
    """
    from olmavax_agent.mind import OnlineSoftmax, vectorize

    teach = [
        ("could you please launch notepad", "open_app"),
        ("launch chrome", "open_app"),
        ("open up paint for me", "open_app"),
        ("make the volume louder", "volume_up"),
        ("turn the volume up", "volume_up"),
        ("volume badhao", "volume_up"),
        ("grab me a screenshot", "screenshot"),
        ("capture the screen now", "screenshot"),
        ("search google for recipes", "web_search"),
        ("run this python snippet", "code_run"),
        ("draw an image of a mountain", "image_generate"),
        ("make a picture of a river", "image_generate"),
        ("set volume to 30", "volume_set"),
    ]
    # Every phrase here is deliberately different from the teaching set.
    holdout = [
        ("start notepad for me right now", "open_app"),
        ("please make it louder", "volume_up"),
        ("take a screenshot of my screen", "screenshot"),
        ("google something interesting", "web_search"),
        ("execute this program", "code_run"),
        ("paint an image of the ocean", "image_generate"),
        ("set the volume to 80", "volume_set"),
    ]
    classes = sorted({label for _, label in teach})
    model = OnlineSoftmax(classes)

    print()
    print(rule("="))
    print(bold("  LEARNING BENCHMARK"))
    print(rule("="))
    print(dim("  training on 13 phrasings, testing on 7 it has never seen"))
    print()
    print(f"  {'step':>6}  {'examples':>9}  {'correct':>8}  accuracy")
    print("  " + dim("-" * 42))

    history = []
    for epoch in range(1, 9):
        for text, label in teach:
            model.update(vectorize(text), label, 1.0)
        correct = sum(1 for t, l in holdout if model.predict(t)[0] == l)
        history.append((epoch, model.trained, correct))
        bar = "#" * int(correct / len(holdout) * 30)
        print(f"  {epoch:>6}  {model.trained:>9}  {correct:>4}/{len(holdout)}   "
              f"{correct / len(holdout):>5.0%}  {dim(bar)}")

    first, last = history[0], history[-1]
    print()
    if last[2] >= first[2] and last[2] >= len(holdout) - 1:
        print(green(f"  it learns: {last[2]}/{len(holdout)} correct on unseen phrasings "
                    f"after {last[1]} updates"))
    else:
        print(yellow(f"  only {last[2]}/{len(holdout)} correct - needs more varied training"))
    print()
    print(dim("  note: this benchmark is disposable. The real model in your mind"))
    print(dim("  folder learns from your own requests, one at a time."))
    print()
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    from .tools import list_tools

    items = list_tools()
    if args.tag:
        items = [i for i in items if args.tag in i["name"] or args.tag in i.get("tags", [])]
    print()
    print(rule("="))
    print(bold(f"  TOOLS  ({len(items)})"))
    print(rule("="))
    current_tag = None
    for item in items:
        tags = item.get("tags") or ["other"]
        primary = tags[0]
        if primary != current_tag:
            current_tag = primary
            print()
            print(f"  {bold(cyan(primary.upper()))}")
        risk = item["risk"]
        colour = red if risk >= 0.6 else yellow if risk >= 0.35 else green
        print(f"    {item['name']:<26} {colour(f'r{risk:.2f}')}  "
              f"{truncate(item['description'], 52)}")
    print()
    return 0


def cmd_vault(args: argparse.Namespace) -> int:
    from .vault import get_vault

    vault = get_vault()
    if args.action == "set":
        value = args.value or input("value> ")
        vault.set(args.name, value, note=args.note or "")
        print(green(f"  stored '{args.name}' encrypted"))
        print(dim(f"  key source: {vault.health()['key_source']}"))
        return 0
    if args.action == "get":
        print(vault.get(args.name, "(not set)"))
        return 0
    if args.action == "delete":
        print(green("  deleted") if vault.delete(args.name) else yellow("  not found"))
        return 0

    health = vault.health()
    print()
    print(rule("="))
    print(bold("  ENCRYPTED VAULT"))
    print(rule("="))
    print(f"  cipher    : {health['cipher']}")
    print(f"  key source: {health['key_source']}")
    if not health["strong_key"]:
        print(yellow("  tip: set OLMAVAX_AGENT_MASTER_KEY for a key that is not machine-bound"))
    print(f"  entries   : {health['entries']}")
    print()
    for item in vault.listing():
        print(f"    {item['key']:<20} {dim(item['note'] or '')} {dim(item['set_at'])}")
    print()
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    from .tools import web_tools

    result = web_tools.learn_topic(args.topic, depth=args.depth)
    if not result.get("ok"):
        print(red(f"  {result.get('error')}"))
        return 1
    print(green(f"  studied '{args.topic}' from {pluralize(result['pages'], 'source')}"))
    for url in result["sources"]:
        print(dim(f"    {url}"))
    print(dim(f"  saved to {result['saved_to']}"))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .llm import get_llm
    from .memory import get_memory
    from .security import get_security
    from .tools import list_tools
    from .voice import get_voice

    print()
    print(rule("="))
    print(bold("  DIAGNOSIS"))
    print(rule("="))

    print(f"\n  {bold('Interpreter')}")
    print(f"    python        : {sys.version.split()[0]} at {sys.executable}")
    print(f"    platform      : {sys.platform}")

    print(f"\n  {bold('Core')}")
    print(f"    home          : {PATHS['home']} "
          f"({'exists' if PATHS['home'].exists() else red('missing')})")
    print(f"    tools         : {green(str(len(list_tools())) + ' registered')}")
    print(f"    memory        : {green('ready')} "
          f"({get_memory().stats()['active_memories']} memories)")
    print(f"    security      : {green('ready')} ({get_security().cfg.posture})")

    print(f"\n  {bold('Language model')}")
    for line in get_llm().doctor():
        print(f"    {line}")

    print(f"\n  {bold('Voice')}")
    print(dim("    " + get_voice().report().replace("\n", "\n    ")))

    print(f"\n  {bold('Optional extras')}")
    print(dim("    " + capability_report().replace("\n", "\n    ")))

    print()
    print(rule("="))
    print(green("  core works with nothing installed - extras only make it better"))
    print(rule("="))
    print()
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    import subprocess

    root = Path(__file__).resolve().parent.parent
    suite = root / "tests" / "test_core.py"
    if not suite.exists():
        print(red(f"  no test suite at {suite}"))
        return 1
    print()
    print(bold(cyan("  running the test suite")))
    print()
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", suite.name],
        cwd=str(suite.parent),
        capture_output=False,
        text=True,
    )
    elapsed = time.perf_counter() - started
    print()
    verdict = green("all tests passed") if completed.returncode == 0 else red("failures")
    print(f"  {verdict} in {human_duration(elapsed)}")
    print()
    return completed.returncode


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="olmavax_agent",
        description=f"Olmavax Agent {__version__} - your personal self-evolving AI agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  olmavax_agent ask \"remember that my wifi password is on the fridge\"\n"
            "  olmavax_agent voice                 speak to the agent\n"
            "  olmavax_agent ui                    open the 3D interface\n"
            "  olmavax_agent security scan         check its own defences\n"
            "  olmavax_agent improve --full        learn + consolidate now\n"
        ),
    )
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--version", action="version", version=f"Olmavax Agent {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("boot", help="prepare everything and report").set_defaults(func=cmd_boot)

    ask = sub.add_parser("ask", help="ask one question and exit")
    ask.add_argument("text")
    ask.add_argument("--json", action="store_true")
    ask.set_defaults(func=cmd_ask)

    chat = sub.add_parser("chat", help="interactive chat (speaks by default)")
    chat.add_argument("--mute", action="store_true", help="do not speak replies aloud")
    chat.set_defaults(func=cmd_chat)

    voice = sub.add_parser("voice", help="wake-word listening loop")
    voice.add_argument("--max-turns", type=int, default=0)
    voice.add_argument("--allow-typed", action="store_true",
                       help="continue with typed input if no mic")
    voice.set_defaults(func=cmd_voice)

    ui = sub.add_parser("ui", help="serve the 3D interface")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--open", action="store_true", help="open a browser")
    ui.set_defaults(func=cmd_ui)

    remember = sub.add_parser("remember", help="store a memory")
    remember.add_argument("text")
    remember.add_argument("--kind", default="fact")
    remember.add_argument("--tags", default="")
    remember.add_argument("--importance", type=float, default=0.6)
    remember.set_defaults(func=cmd_remember)

    recall = sub.add_parser("recall", help="search memory")
    recall.add_argument("text")
    recall.add_argument("--limit", type=int, default=8)
    recall.set_defaults(func=cmd_recall)

    sub.add_parser("memory", help="memory dashboard").set_defaults(func=cmd_memory)

    forget = sub.add_parser("forget", help="delete a memory")
    forget.add_argument("text", nargs="?", default="")
    forget.add_argument("--id", type=int, default=0)
    forget.set_defaults(func=cmd_forget)

    skills = sub.add_parser("skills", help="manage skills")
    skills.add_argument("action", nargs="?", default="list",
                        choices=["list", "reload", "enable", "disable", "new"])
    skills.add_argument("name", nargs="?", default="")
    skills.add_argument("--description", default="")
    skills.set_defaults(func=cmd_skills)

    security = sub.add_parser("security", help="security report and posture")
    security.add_argument("action", nargs="?", default="status",
                          choices=["status", "scan", "posture"])
    security.add_argument("--posture", choices=["paranoid", "balanced", "sandbox", "open"])
    security.set_defaults(func=cmd_security)

    audit = sub.add_parser("audit", help="read the tamper-evident audit trail")
    audit.add_argument("--limit", type=int, default=25)
    audit.add_argument("--repair", action="store_true",
                       help="archive a log that cannot verify and start a fresh chain")
    audit.set_defaults(func=cmd_audit)

    improve = sub.add_parser("improve", help="run a self-improvement cycle")
    improve.add_argument("--full", action="store_true", help="also synthesise new skills")
    improve.set_defaults(func=cmd_improve)

    tools = sub.add_parser("tools", help="list every tool")
    tools.add_argument("--tag", default="")
    tools.set_defaults(func=cmd_tools)

    mind = sub.add_parser("mind", help="the self-learning core")
    mind.add_argument("action", nargs="?", default="status",
                      choices=["status", "explain", "benchmark", "reset"])
    mind.add_argument("text", nargs="?", default="")
    mind.set_defaults(func=cmd_mind)

    vault = sub.add_parser("vault", help="encrypted secrets")
    vault.add_argument("action", nargs="?", default="list",
                       choices=["list", "set", "get", "delete"])
    vault.add_argument("name", nargs="?", default="")
    vault.add_argument("--value", default="")
    vault.add_argument("--note", default="")
    vault.set_defaults(func=cmd_vault)

    learn = sub.add_parser("learn", help="study a topic and remember it")
    learn.add_argument("topic")
    learn.add_argument("--depth", type=int, default=3)
    learn.set_defaults(func=cmd_learn)

    sub.add_parser("doctor", help="diagnose the installation").set_defaults(func=cmd_doctor)
    sub.add_parser("test", help="run the test suite").set_defaults(func=cmd_test)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(debug=getattr(args, "debug", False))
    ensure_dirs()

    if not getattr(args, "func", None):
        args = parser.parse_args(["chat"])

    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n  interrupted")
        return 130
    except Exception as exc:
        print(red(f"\n  error: {type(exc).__name__}: {exc}\n"))
        if getattr(args, "debug", False):
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())