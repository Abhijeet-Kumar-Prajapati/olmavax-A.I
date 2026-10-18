"""
Open Charvis - Intent routing
=============================
Maps every parsed intent to the code that carries it out.

Each handler takes an :class:`~opencharvis.nlu.Intent` and returns
``(reply_text, data)``.  The data dict may carry a ``tool`` key so the brain
knows what was actually executed, plus anything else the UI should see.

Handlers deliberately return plain, speakable sentences.  If the owner said
the request out loud, this text is what gets spoken back.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .config import PATHS, capability_report, get_config
from .logger import log_warn
from .nlu import Intent
from .security import get_security
from .tools import (
    capability_tools,
    dev_tools,
    knowledge_tools,
    media_tools,
    run,
    system_tools,
    web_tools,
)
from .vault import get_vault
from .utils import human_size, human_duration, pluralize, truncate

SEC = get_security()
Handler = Callable[[Intent], Tuple[str, Dict[str, Any]]]


def _memory():
    from .memory import get_memory

    return get_memory()


def _bullets(items: List[str], limit: int = 12) -> str:
    lines = [f"- {item}" for item in items[:limit]]
    more = len(items) - limit
    if more > 0:
        lines.append(f"- ...and {more} more")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def h_shutdown(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    return "Shutting down.", {"tool": "core.shutdown"}


def h_help(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    groups = [
        ("Thinking", "toggle 'Think' in the chat bar, or 'think through X' - "
                     "you see every step and what I am unsure about"),
        ("Files", "attach a file with +, or 'analyse this file', 'summarise this csv'"),
        ("Coding", "write a program, 'review this code', 'explain this code', 'test this function'"),
        ("Planning", "'plan how to ...' - you get a checklist saved to disk"),
        ("Deciding", "'compare X and Y', 'should I ...' - options weighed, not guessed"),
        ("Talking", "ask anything, 'who are you', 'status', 'help'"),
        ("Memory", "'remember that ...', 'what do you remember about X', 'forget ...'"),
        ("Your computer", "open notepad, volume up, screenshot, find file, what's my PC"),
        ("Power", "lock, sleep, shutdown - these always ask first"),
        ("Internet", "search X, learn about X, summarise this link, watch this youtube link"),
        ("Making things", "draw an image of X, animate X, make a video of X"),
        ("Safety", "security report, change posture, store password"),
        ("Stopping me", "say 'exit' or 'bus'"),
    ]
    body = "\n".join(f"{label:<14} {examples}" for label, examples in groups)
    return f"Here is everything I can do:\n\n{body}", {"tool": "core.help"}


def h_thanks(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    return "Always.", {"tool": "core.thanks"}


def h_greeting(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    name = _memory().get_pref("owner_name", get_config().owner)
    return (
        f"Hello {name}. I am awake and listening. What shall we do?",
        {"tool": "core.greeting"},
    )


def h_identity(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    cfg = get_config()
    vault = get_vault()
    return (
        f"I am {cfg.name} version {cfg.version}, codename {cfg.codename}.\n"
        f"I live entirely on your machine at {PATHS['home']}. "
        "I remember what you tell me and I learn from my own mistakes. "
        "I can control Windows, search and learn from the internet, run code in several "
        "languages, and generate images, animation and video. "
        f"My encrypted vault currently holds {len(vault.keys())} secret(s). "
        "Nothing is sent anywhere unless you ask me to.",
        {"tool": "core.identity"},
    )


def h_status(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    from .brain import get_brain

    status = get_brain().status()
    memory = status["memory"]
    model = status["model"]
    return (
        "Status report\n"
        "------------\n"
        f"State        : {status['state']}  (up {status['uptime']})\n"
        f"Requests     : {status['totals']['requests']} handled, "
        f"{status['totals']['blocked']} blocked by security\n"
        f"Memory       : {memory['active']} active, {memory['lessons']} lessons learned, "
        f"{human_size(memory['size'])} on disk\n"
        f"Success rate : {memory['success_rate']:.0%} over {memory['episodes']} episodes\n"
        f"Model        : {model['provider']} / {model['model']}"
        f"{' (offline reasoning)' if model['provider'] == 'offline' else ''}\n"
        f"Security     : {status['security']['posture']} posture, "
        f"{status['security']['decisions'].get('allow', 0)} allowed, "
        f"{status['security']['decisions'].get('ask', 0)} confirmed, "
        f"{status['security']['decisions'].get('block', 0)} blocked\n"
        f"Tools        : {status['tools']} registered\n"
        f"Internet     : {'connected' if model['internet'] else 'not available'}",
        {"tool": "core.status", "status": status},
    )


def h_capabilities(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    from .tools import list_tools

    tools = list_tools()
    by_tag: Dict[str, int] = {}
    for item in tools:
        for tag in item.get("tags", []) or ["other"]:
            by_tag[tag] = by_tag.get(tag, 0) + 1
    summary = ", ".join(f"{tag} ({count})" for tag, count in sorted(by_tag.items()))
    optional = [line for line in capability_report().splitlines() if "[YES]" in line]
    extras = ("\n".join(optional) if optional else "\nnothing extra installed - core still fully works")
    return (
        f"I have {len(tools)} tools: {summary}\n"
        f"Optional extras installed:{extras}",
        {"tool": "core.capabilities"},
    )


# -- security -------------------------------------------------------------


def h_security_status(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    status = SEC.status()
    decisions = status["decisions"]
    audit = status.get("audit", {})
    return (
        "Security report\n"
        "--------------\n"
        f"Posture          : {status['posture']} "
        f"(asks above {status['risk_threshold']:.0%} risk)\n"
        f"Decisions        : {decisions.get('allow', 0)} allowed, "
        f"{decisions.get('ask', 0)} confirmed, {decisions.get('block', 0)} blocked\n"
        f"Sandbox          : {'on' if status['sandbox'] else 'off'}\n"
        f"Audit trail      : {audit.get('entries', 0)} entries, "
        f"chain {'intact (' + str(audit.get('checked', 0)) + ' verified)'
           if audit.get('chain_intact')
           else 'BROKEN at line ' + str(audit.get('broken_at'))}\n"
        f"Vault            : {get_vault().health()['cipher']}\n"
        f"Capabilities     : {len(status['capabilities'])} gated tool permissions\n"
        f"My advice        : {status['advice']['why']}",
        {"tool": "security.status", "security": status},
    )


def h_security_scan(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    verdict = SEC.scan_status()
    return (
        "Self scan complete\n"
        "------------------\n"
        f"Vault file protected : {'yes' if verdict['vault_protected'] else 'NO'}\n"
        f"Strong vault key     : {'yes' if verdict['strong_key'] else 'no - set CHARVIS_MASTER_KEY'}\n"
        f"Path jail active     : {'yes' if verdict['path_jail'] else 'NO'}\n"
        f"Secret scrubber      : {verdict['scrubber_tests_passed']}/{verdict['scrubber_tests']} tests passed\n"
        f"Credential paths blocked : {verdict['blocked_path_rules']} rules\n"
        f"Audit chain          : {'intact' if verdict['audit_chain_intact'] else 'BROKEN'}\n"
        f"Assessment           : {verdict['assessment']}",
        {"tool": "security.scan", "scan": verdict},
    )


def h_security_posture(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    posture = intent.slots.get("posture")
    if not posture:
        advice = SEC.advise()
        return (
            f"Postures: paranoid, balanced, sandbox, open. "
            f"You are on {advice['current_posture']}. I recommend "
            f"{advice['recommended_posture']} because {advice['why']}. "
            "Say 'posture paranoid' to switch.",
            {"tool": "security.advise", "advice": advice},
        )
    SEC.apply_posture(posture)
    get_config().security.posture = posture
    return (
        f"Posture changed to {posture}. I will now be more careful before acting.",
        {"tool": "security.posture"},
    )


def h_secret_set(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    text = intent.slots.get("text", "")
    key, _, value = text.partition(":")
    if not value and " " in text:
        key, _, value = text.partition(" ")
    key = key.strip().lower().replace(" ", "_")
    value = value.strip()
    if not key or not value:
        return (
            "Tell me it like: store password netflix as MySecret123 - "
            "it goes in my encrypted vault, never in memory.",
            {"tool": "vault.set"},
        )
    get_vault().set(key, value, note=f"set via chat on {time.strftime('%Y-%m-%d')}")
    return (
        f"Stored '{key}' in the encrypted vault. It is not in my memory and never "
        "appears in logs.",
        {"tool": "vault.set", "key": key},
    )


def h_secret_list(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    listing = get_vault().listing()
    if not listing:
        return "The vault is empty. Tell me 'store password X as Y' and I will keep it safe.",
        {"tool": "vault.list"}
    body = _bullets([f"{i['key']} - {i['note'] or 'no note'}" for i in listing])
    return f"Vault holds {pluralize(len(listing), 'secret')}. Values stay hidden:\n{body}", {
        "tool": "vault.list",
        "count": len(listing),
    }


# -- memory ---------------------------------------------------------------


def h_memory_remember(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    text = intent.slots.get("text", "").strip()
    if not text:
        return "Tell me what to remember and I will keep it.", {"tool": "memory.remember"}
    result = knowledge_tools.memory_remember(text, kind="fact", importance=0.65)
    if not result["ok"]:
        return result["error"], {"tool": "memory.remember"}
    return (
        f"Noted and stored permanently (id {result['id']}). "
        "I will bring this up whenever it is relevant.",
        {"tool": "memory.remember", "id": result["id"]},
    )


def h_memory_recall(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    query = intent.slots.get("query") or intent.raw
    results = knowledge_tools.memory_recall(query, limit=8)
    if not results["count"]:
        return (
            f"I have nothing stored about '{truncate(query, 60)}'. "
            "Tell me and I will remember it from now on.",
            {"tool": "memory.recall", "count": 0},
        )
    body = _bullets(
        [f"{r['text']}  (relevance {r['score']:.0%})" for r in results["results"]], limit=8
    )
    return f"Here is what I remember about that:\n{body}", {
        "tool": "memory.recall",
        "count": results["count"],
        "results": results["results"],
    }


def h_memory_forget(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    target = intent.slots.get("text", "")
    found = _memory().find(target)
    if not found:
        return f"Nothing in memory matches '{truncate(target, 50)}'.", {"tool": "memory.forget"}
    listing = _bullets([f"id {m.id}: {truncate(m.text, 90)}" for m in found[:10]])
    return (
        f"This would remove {pluralize(len(found), 'memory')}:\n{listing}\n"
        "Say 'confirm' and I will do it.",
        {"tool": "memory.forget_preview", "candidates": [m.id for m in found]},
    )


def h_memory_list(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    items = _memory().recent(limit=15)
    if not items:
        return "My memory is empty. Tell me anything worth keeping.", {"tool": "memory.list"}
    body = _bullets(
        [f"[{m.kind}] {truncate(m.text, 88)} ({m.age_days:.0f}d ago)" for m in items], limit=15
    )
    return f"Most recent of {len(items)} memories:\n{body}", {
        "tool": "memory.list",
        "count": len(items),
    }


def h_lesson_teach(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    text = intent.slots.get("text", intent.raw)
    rule = re.sub(r"^(from now on|always|never|remember to)\s+", "", text, flags=2)
    pattern = rule[:40].lower() or "general"
    lesson = _memory().add_lesson(pattern, rule, confidence=0.85, source="owner")
    return (
        f"Rule accepted. From now on: {rule}\n"
        "I will consult this before similar tasks.",
        {"tool": "lesson.add", "lesson": lesson.to_dict()},
    )


# -- system ---------------------------------------------------------------


def h_system_info(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    info = system_tools.system_info()
    parts = []
    for key in ("windows", "platform", "processor", "cpu_cores", "ram_gb", "python"):
        if key in info and info[key]:
            parts.append(f"{key.replace('_', ' ')}: {info[key]}")
    disks = info.get("disks") or []
    if disks:
        parts.append(
            "disk: " + ", ".join(f"{d.get('mount')} {d.get('free_gb')}GB free" for d in disks[:3])
        )
    return "\n".join(parts) or str(info), {"tool": "system.info", "info": info}


def h_open_app(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    target = intent.slots.get("target", "")
    result = system_tools.open_target(target)
    if result.get("ok"):
        return f"Opened {result['opened']}.", {"tool": "app.open", "result": result}
    return (
        f"I could not open '{target}'. {result.get('error') or result.get('detail', '')}\n"
        f"I know how to open: {', '.join(system_tools.list_apps())}.",
        {"tool": "app.open", "result": result},
    )


def h_volume_set(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    percent = intent.slots.get("percent", 50)
    result = system_tools.volume_set(percent)
    return f"Volume is now {percent}%.", {"tool": "volume.set", "result": result}


def h_volume_up(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    result = system_tools.volume_up()
    return f"Volume up. It reads {result.get('volume')}%.", {"tool": "volume.up", "result": result}


def h_volume_down(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    result = system_tools.volume_down()
    return f"Volume down. It reads {result.get('volume')}%.", {"tool": "volume.down", "result": result}


def h_mute(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    return "Mute toggled.", {"tool": "volume.mute", "result": system_tools.volume_mute()}


def h_screenshot(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    result = system_tools.screenshot()
    if result.get("ok"):
        return f"Screen captured to {result['path']}.", {"tool": "screen.screenshot", "result": result}
    return f"Could not capture the screen: {result.get('detail')}", {
        "tool": "screen.screenshot", "result": result,
    }


def h_clipboard_read(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    text = system_tools.clipboard_read()
    return (f"Clipboard holds: {truncate(text, 300)}" if text else "The clipboard is empty."), {
        "tool": "clipboard.read",
    }


def h_clipboard_write(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    text = intent.slots.get("text", "")
    system_tools.clipboard_write(text)
    return f"Copied {len(text)} characters to the clipboard.", {"tool": "clipboard.write"}


def h_notify(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    message = intent.slots.get("message", "Reminder")
    system_tools.notify("Open Charvis", message)
    return f"Notification sent: {message}", {"tool": "notify.send"}


def h_lock(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    system_tools.power_lock()
    return "Screen locked.", {"tool": "power.lock"}


def h_power_sleep(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    return (
        "Putting the computer to sleep. Say 'confirm' if you meant it, "
        "'nahi' to cancel.",
        {"tool": "power.sleep", "needs_confirmation": True},
    )


def h_power_shutdown(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    result = system_tools.power_shutdown()
    return f"{result.get('detail', 'Shutdown scheduled')}", {"tool": "power.shutdown", "result": result}


def h_power_restart(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    result = system_tools.power_restart()
    return f"{result.get('detail', 'Restart scheduled')}", {"tool": "power.restart", "result": result}


def h_search_files(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    query = intent.slots.get("query", "")
    if not query:
        return "What should I look for?", {"tool": "files.search"}
    results = system_tools.files_search(query, limit=25)
    if not results:
        return f"I found nothing called '{query}' in your folders.", {"tool": "files.search"}
    body = _bullets([f"{r['name']} - {r['path']}" for r in results])
    return f"Found {pluralize(len(results), 'match', 'matches')}:\n{body}", {
        "tool": "files.search", "results": results,
    }


def h_read_file(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    path = intent.slots.get("path", "")
    result = system_tools.files_read(path, max_chars=4000)
    if not result.get("ok"):
        return f"Could not read that: {result.get('error')}", {"tool": "files.read", "result": result}
    return (
        f"{result['path']} ({result['chars']} characters)\n\n{result['content'][:2500]}",
        {"tool": "files.read", "result": result},
    )


# -- internet -------------------------------------------------------------


def h_web_search(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    query = intent.slots.get("query", intent.raw)
    result = web_tools.web_search(query, limit=6)
    if not result.get("results"):
        return (
            f"No results for '{truncate(query, 60)}'. {result.get('error', '')}",
            {"tool": "web.search", "result": result},
        )
    body = _bullets(
        [f"{r['title']} - {r['domain']}\n  {r['url']}" for r in result["results"]], limit=6
    )
    return f"Search results for '{query}':\n{body}", {
        "tool": "web.search", "results": result["results"],
    }


def h_learn_topic(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    topic = intent.slots.get("topic", "")
    if not topic:
        return "What should I learn about?", {"tool": "web.learn"}
    result = web_tools.learn_topic(topic, depth=3)
    if not result.get("ok"):
        return f"I could not study '{topic}': {result.get('error')}", {
            "tool": "web.learn", "result": result,
        }
    return (
        f"Studied '{topic}' from {pluralize(result['pages'], 'source')}.\n"
        f"Saved to {result['saved_to']} and stored in memory so I can answer about it later.\n\n"
        f"{result['preview'][:1500]}",
        {"tool": "web.learn", "result": result},
    )


def h_youtube_learn(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    url = intent.slots.get("url") or intent.raw
    result = web_tools.youtube_learn(url)
    if not result.get("ok"):
        return f"I could not learn from that video: {result.get('error')}", {
            "tool": "web.youtube_learn", "result": result,
        }
    return (
        f"Watched '{result.get('title', 'the video')}' by {result.get('channel', 'unknown')} "
        f"({result['cues']} caption cues, {result['words']} words).\n"
        f"{'Stored in memory.' if result['stored'] else ''}\n\n{result['summary'][:1600]}",
        {"tool": "web.youtube_learn", "result": result},
    )


def h_wiki(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    topic = intent.slots.get("topic", "")
    result = web_tools.wikipedia(topic)
    if not result.get("ok"):
        return result.get("error", "Nothing found."), {"tool": "web.wikipedia", "result": result}
    return f"{result['title']}\n{result['summary']}\n{result['url']}", {
        "tool": "web.wikipedia", "result": result,
    }


def h_fetch_url(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    url = intent.slots.get("url", "")
    result = web_tools.web_fetch(url, max_chars=9000)
    if not result.get("ok"):
        return f"Could not read that page: {result.get('error')}", {
            "tool": "web.fetch", "result": result,
        }
    return (
        f"{result['title']}\nSource: {result['url']}  (safety: {result['safety']})\n\n"
        f"{result['content'][:3500]}",
        {"tool": "web.fetch", "result": result},
    )


# -- media ----------------------------------------------------------------


def h_image_generate(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    prompt = intent.slots.get("prompt", intent.raw)
    result = media_tools.media_image(prompt, style="plasma", width=512, height=512)
    if not result.get("ok"):
        return f"I could not paint that: {result.get('error')}", {
            "tool": "media.image", "result": result,
        }
    return (
        f"Painted that for you - {result['width']}x{result['height']} "
        f"({result['style']} style, rendered offline in {result['render_seconds']}s).\n"
        f"Saved to {result['path']}. Ask for a different style and I will paint another.",
        {"tool": "media.image", "result": result},
    )


def h_animate(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    prompt = intent.slots.get("prompt", intent.raw)
    result = media_tools.media_animation(prompt, style="core", frames=20, size=256, fps=12)
    return (
        f"Animation built: {result['frames']} frames at {result['frame_size']}px, "
        f"{result['fps']}fps in {result['render_seconds']}s.\n"
        f"Folder: {result['folder']}\n"
        f"Animated SVG: {result['animated_svg']}"
        + (f"\nMP4: {result['mp4']}" if result.get("mp4") else "")
        + (f"\nGIF: {result['gif']}" if result.get("gif") else "")
        + ("" if result.get("mp4") else "\n(Install ffmpeg and I will also render an MP4.)"),
        {"tool": "media.animation", "result": result},
    )


def h_media_gallery(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    items = media_tools.media_gallery(limit=20)
    if not items:
        return "I have not generated anything yet. Ask me to draw or animate something.",
        {"tool": "media.gallery"}
    body = _bullets([f"{i['name']} ({i['type']}, {i['kb']}KB) - {i['created']}" for i in items])
    return f"Generated media, newest first:\n{body}", {"tool": "media.gallery", "items": items}


# -- code -----------------------------------------------------------------


def h_code_run(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    code = intent.slots.get("code", "")
    language = intent.slots.get("language", "python")
    if not code:
        return (
            "Put the code in a code block, like:\n```python\nprint('hello')\n```\n"
            "and I will run it in a sandbox and show you the output.",
            {"tool": "dev.run"},
        )
    result = dev_tools.dev_run(code, language=language)
    if result.get("error") and not result.get("stdout"):
        return f"Could not run it: {result['error']}", {"tool": "dev.run", "result": result}
    output = result.get("stdout") or "(no output)"
    status = "succeeded" if result.get("ok") else f"failed with code {result.get('exit_code')}"
    return (
        f"The program {status} in {result.get('duration_s')}s.\n\n"
        f"Output:\n{truncate(output, 2500)}\n"
        + (f"\nErrors:\n{truncate(result.get('stderr', ''), 800)}" if result.get("stderr") else ""),
        {"tool": "dev.run", "result": result},
    )


def h_code_languages(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    items = dev_tools.dev_languages()
    ready = [i for i in items if i["ready"]]
    not_ready = [i for i in items if not i["ready"]]
    body = _bullets([f"{i['language']} - {i['runtime']}" for i in ready])
    extra = (
        "\n\nNot installed but supported if you install them:\n"
        + _bullets([f"{i['language']}" for i in not_ready])
        if not_ready
        else ""
    )
    return f"Languages I can run right now:\n{body}{extra}", {"tool": "dev.languages", "items": items}


def h_code_inspect(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    code = intent.slots.get("code", "")
    if not code:
        return "Paste the code and I will explain its structure and flag any risky lines.",
        {"tool": "dev.inspect"}
    result = dev_tools.dev_inspect(code)
    if not result.get("ok"):
        return f"That code does not parse: {result.get('error')}", {
            "tool": "dev.inspect", "result": result,
        }
    body = _bullets([f"{f['name']}({', '.join(f['args'])}) at line {f['line']}" for f in result["functions"]])
    risks = (
        "\n\nPoints worth reviewing:\n" + _bullets([f"line {r['line']}: {r['issue']}" for r in result["risk_points"]])
        if result["risk_points"]
        else ""
    )
    return (
        f"{result['lines']} lines, {len(result['functions'])} functions, "
        f"{len(result['classes'])} classes, branching complexity {result['branching_complexity']}.\n"
        + (f"\nFunctions:\n{body}\n" if body else "")
        + f"\nVerdict: {result['verdict']}{risks}",
        {"tool": "dev.inspect", "result": result},
    )


def h_test_run(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    result = dev_tools.dev_test()
    if not result.get("ok") and result.get("error"):
        return f"I could not run tests: {result['error']}", {"tool": "dev.test", "result": result}
    verdict = "All green" if result.get("passed") else "There are failures"
    return f"{verdict}. {result.get('summary', '')}\n\n{truncate(result.get('output', ''), 2000)}", {
        "tool": "dev.test", "result": result,
    }


def h_scaffold(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    name = intent.slots.get("name", "new-project")
    result = dev_tools.dev_scaffold(name)
    if not result.get("ok"):
        return f"Could not scaffold: {result.get('error')}", {"tool": "dev.scaffold", "result": result}
    return (
        f"Created a {result['language']} project at {result['path']} with: "
        f"{', '.join(result['created'])}.",
        {"tool": "dev.scaffold", "result": result},
    )


# -- notes / settings ------------------------------------------------------


def h_note_write(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    text = intent.slots.get("text", intent.raw)
    result = knowledge_tools.note_write(text)
    return f"Note saved to {result['path']}", {"tool": "note.write", "result": result}


def h_note_search(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    query = intent.slots.get("query", intent.raw)
    hits = knowledge_tools.note_search(query)
    if not hits:
        return f"No notes mention '{truncate(query, 40)}'.", {"tool": "note.search"}
    body = _bullets([f"{h['file']}: {h['excerpt']}" for h in hits])
    return f"Found in {pluralize(len(hits), 'note')}:\n{body}", {"tool": "note.search", "hits": hits}


def h_settings(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    cfg = get_config()
    return f"Current settings:\n{cfg.describe()}", {"tool": "config.describe"}


def h_lesson_list(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    lessons = _memory().lessons(limit=15)
    if not lessons:
        return "I have not written any lessons for myself yet.", {"tool": "lesson.list"}
    body = _bullets([f"[{l.confidence:.0%}] {l.rule}" for l in lessons])
    return f"Rules I have taught myself:\n{body}", {"tool": "lesson.list", "lessons": lessons}


def h_curriculum(intent: Intent) -> Tuple[str, Dict[str, Any]]:
    result = knowledge_tools.curriculum_list()
    if not result["topics"]:
        return "I have not studied any topic yet. Say 'learn about quantum computing'.", {
            "tool": "curriculum.list",
        }
    body = _bullets([f"{t['topic']} ({t['modified']})" for t in result["topics"]])
    return f"Topics I have studied:\n{body}", {"tool": "curriculum.list", "topics": result["topics"]}


# --------------------------------------------------------------------------
# Table
# --------------------------------------------------------------------------

import re  # noqa: E402  (used by h_lesson_teach)

ROUTES: Dict[str, Handler] = {
    "shutdown": h_shutdown,
    "help": h_help,
    "thanks": h_thanks,
    "greeting": h_greeting,
    "identity": h_identity,
    "status": h_status,
    "capabilities": h_capabilities,

    "security_status": h_security_status,
    "security_scan": h_security_scan,
    "security_posture": h_security_posture,
    "secret_set": h_secret_set,
    "secret_list": h_secret_list,

    "memory_remember": h_memory_remember,
    "memory_recall": h_memory_recall,
    "memory_forget": h_memory_forget,
    "memory_list": h_memory_list,
    "lesson_teach": h_lesson_teach,
    "lesson_list": h_lesson_list,
    "curriculum_list": h_curriculum,

    "time_now": lambda i: (time.strftime("It is %I:%M %p."), {"tool": "core.time"}),
    "date_today": lambda i: (time.strftime("Today is %A, %d %B %Y."), {"tool": "core.date"}),

    "system_info": h_system_info,
    "open_app": h_open_app,
    "volume_set": h_volume_set,
    "volume_up": h_volume_up,
    "volume_down": h_volume_down,
    "mute": h_mute,
    "screenshot": h_screenshot,
    "clipboard_read": h_clipboard_read,
    "clipboard_write": h_clipboard_write,
    "notify": h_notify,
    "lock": h_lock,
    "power_sleep": h_power_sleep,
    "power_shutdown": h_power_shutdown,
    "power_restart": h_power_restart,
    "search_files": h_search_files,
    "read_file": h_read_file,

    "web_search": h_web_search,
    "learn_topic": h_learn_topic,
    "youtube_learn": h_youtube_learn,
    "wiki": h_wiki,
    "fetch_url": h_fetch_url,

    "image_generate": h_image_generate,
    "animate": h_animate,
    "media_gallery": h_media_gallery,

    "code_run": h_code_run,
    "code_languages": h_code_languages,
    "code_inspect": h_code_inspect,
    "test_run": h_test_run,
    "scaffold": h_scaffold,

    "note_write": h_note_write,
    "note_search": h_note_search,
    "settings": h_settings,
}


def register(table: Dict[str, Handler]) -> None:
    """Copy the routes into the brain's dispatch table."""
    table.update(ROUTES)


def unmapped_intents(known: List[str]) -> List[str]:
    """Intents the parser can produce but the router does not handle.

    Those fall through to the language model, which is the intended
    behaviour, so this list is for diagnostics only.
    """
    return sorted(set(known) - set(ROUTES))