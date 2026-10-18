"""
Olmavax Agent - Knowledge tools
=============================
Tools over the agent's own mind: memory, notes, identity, preferences and
self-introspection.  These are how the owner talks to the brain directly
("remember that...", "what do you know about...", "forget that...").
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import PATHS, ensure_dirs, get_config
from ..logger import log_warn
from ..security import get_security, scrub
from ..utils import truncate
from . import tool

SEC = get_security()


def _memory():
    from ..memory import get_memory

    return get_memory()


# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------


@tool("memory.remember", "Store a permanent fact, preference or instruction",
      capabilities=["memory.write"], risk=0.05, tags=["memory"])
def memory_remember(text: str, kind: str = "fact", tags: str = "", importance: float = 0.6) -> Dict[str, Any]:
    if not text.strip():
        return {"ok": False, "error": "nothing to remember"}
    clean, leaks = scrub(text)
    if leaks:
        # A credential is never written to the brain.
        return {
            "ok": False,
            "error": f"refused: that text contains {leaks} credential(s). "
            "Use 'secret set' so it is stored encrypted instead.",
        }
    stored = _memory().add(
        clean,
        kind=kind,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        importance=importance,
        source="owner",
    )
    return {"ok": bool(stored), "id": stored.id if stored else None,
            "text": truncate(clean, 160), "kind": kind}


@tool("memory.recall", "Search what the agent remembers",
      capabilities=["memory.read"], risk=0.02, tags=["memory"])
def memory_recall(query: str, limit: int = 8) -> Dict[str, Any]:
    results = _memory().search(query, limit=max(1, min(limit, 50)))
    if not results:
        return {"ok": True, "count": 0, "results": [], "note": "nothing stored about that yet"}
    return {
        "ok": True,
        "count": len(results),
        "results": [
            {
                "text": r.memory.text,
                "kind": r.memory.kind,
                "score": round(r.score, 3),
                "importance": round(r.memory.importance, 2),
                "tags": r.memory.tags,
                "age_days": round(r.memory.age_days, 1),
            }
            for r in results
        ],
    }


@tool("memory.forget", "Delete a memory by id, or everything of one kind",
      capabilities=["memory.write"], risk=0.70, tags=["memory"], confirm=True)
def memory_forget(memory_id: int = 0, kind: str = "") -> Dict[str, Any]:
    if memory_id:
        _memory().forget(int(memory_id), hard=True)
        return {"ok": True, "forgotten": memory_id}
    if kind:
        _memory().clear(kind)
        return {"ok": True, "cleared_kind": kind}
    return {"ok": False, "error": "give me a memory id, or a kind to clear"}


@tool("memory.list", "List stored memories, newest first",
      capabilities=["memory.read"], risk=0.02, tags=["memory"])
def memory_list(limit: int = 25, kind: str = "") -> Dict[str, Any]:
    items = _memory().recent(limit=max(1, min(limit, 500)), kind=kind or None)
    return {
        "ok": True,
        "count": len(items),
        "memories": [
            {"id": m.id, "text": truncate(m.text, 200), "kind": m.kind,
             "importance": round(m.importance, 2), "tags": m.tags, "age_days": round(m.age_days, 1)}
            for m in items
        ],
    }


@tool("memory.stats", "How much the agent knows and how well it is doing",
      capabilities=["memory.read"], risk=0.02, tags=["memory", "stats"])
def memory_stats() -> Dict[str, Any]:
    from ..utils import human_size

    stats = _memory().stats()
    stats["db_size"] = human_size(stats.pop("db_bytes", 0))
    return {"ok": True, **stats}


@tool("memory.export", "Export the whole brain to a JSON file",
      capabilities=["files.read", "files.write"], risk=0.20, tags=["memory", "backup"])
def memory_export(target: str = "") -> Dict[str, Any]:
    path = Path(target) if target else PATHS["exports"] / f"memory-backup-{int(time.time())}.json"
    guarded = SEC.safe_target(str(path), [Path.home(), PATHS["home"], Path.cwd()])
    if not guarded:
        return {"ok": False, "error": "export path is outside the allowed workspace"}
    written = _memory().export(Path(guarded))
    return {"ok": True, "path": str(written)}


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------


def _notes_dir() -> Path:
    ensure_dirs()
    folder = PATHS["home"] / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@tool("note.write", "Write a dated note file",
      capabilities=["files.write"], risk=0.10, tags=["notes"])
def note_write(text: str, title: str = "") -> Dict[str, Any]:
    heading = title.strip() or text.strip().splitlines()[0][:50] or "note"
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:50] or "note"
    path = _notes_dir() / f"{time.strftime('%Y-%m-%d')}-{slug}.md"
    body = f"# {heading}\n\n{time.strftime('%Y-%m-%d %H:%M')}\n\n{text}\n"
    path.write_text(body, encoding="utf-8")
    _memory().add(
        f"Note written: {heading}",
        kind="note", tags=["note", slug[:20]], importance=0.3, source="owner",
    )
    return {"ok": True, "path": str(path)}


@tool("note.search", "Search all notes by content",
      capabilities=["files.read"], risk=0.10, tags=["notes"])
def note_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    needle = (query or "").lower().strip()
    if not needle:
        return []
    hits = []
    for path in sorted(_notes_dir().glob("*.md"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text.lower():
            index = text.lower().index(needle)
            start = max(0, index - 120)
            hits.append(
                {
                    "file": path.name,
                    "excerpt": truncate(text[start : index + 240], 320).replace("\n", " "),
                }
            )
        if len(hits) >= limit:
            break
    return hits


@tool("note.list", "List recent notes", capabilities=["files.read"],
      risk=0.05, tags=["notes"])
def note_list(limit: int = 20) -> List[Dict[str, str]]:
    return [
        {"file": p.name, "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))}
        for p in sorted(_notes_dir().glob("*.md"), reverse=True)[:limit]
        if p.exists()
    ]


# --------------------------------------------------------------------------
# Identity and preferences
# --------------------------------------------------------------------------


@tool("identity.set", "Set the owner's name and how the agent should address them",
      capabilities=["memory.write"], risk=0.05, tags=["identity"])
def identity_set(name: str = "", style: str = "") -> Dict[str, Any]:
    store = _memory()
    updates = {}
    if name.strip():
        store.set_pref("owner_name", name.strip(), kind="identity")
        updates["owner_name"] = name.strip()
    if style.strip():
        store.set_pref("address_style", style.strip(), kind="identity")
        updates["address_style"] = style.strip()
    store.add(
        f"My owner's name is {updates.get('owner_name', store.get_pref('owner_name'))}."
        if "owner_name" in updates
        else f"Address style set to {style}.",
        kind="identity", tags=["identity"], importance=0.95, source="owner", deduplicate=False,
    )
    return {"ok": True, **updates}


@tool("identity.get", "Who the agent thinks its owner is",
      capabilities=["memory.read"], risk=0.02, tags=["identity"])
def identity_get() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "owner": _memory().get_pref("owner_name", cfg.owner),
        "address_style": _memory().get_pref("address_style", "respectful"),
        "language": cfg.language,
        "agent": f"{cfg.name} {cfg.version}",
        "codename": cfg.codename,
    }


@tool("pref.set", "Change any agent setting by name",
      capabilities=["memory.write", "self.modify"], risk=0.35, tags=["settings"])
def pref_set(key: str, value: Any) -> Dict[str, Any]:
    _memory().set_pref(key.strip().lower(), value)
    return {"ok": True, "key": key, "value": value}


@tool("pref.get", "Read an agent setting", capabilities=["memory.read"],
      risk=0.02, tags=["settings"])
def pref_get(key: str) -> Dict[str, Any]:
    return {"key": key, "value": _memory().get_pref(key)}


@tool("pref.all", "Every stored setting", capabilities=["memory.read"],
      risk=0.05, tags=["settings"])
def pref_all() -> Dict[str, Any]:
    return {"ok": True, "preferences": _memory().all_prefs()}


# --------------------------------------------------------------------------
# Curriculum and lessons
# --------------------------------------------------------------------------


@tool("curriculum.list", "Topics the agent has studied and stored notes on",
      capabilities=["memory.read"], risk=0.05, tags=["learn", "memory"])
def curriculum_list() -> Dict[str, Any]:
    ensure_dirs()
    items = []
    for path in sorted(PATHS["curriculum"].glob("*.md"), reverse=True):
        try:
            items.append({"topic": path.stem, "modified": time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))})
        except OSError:
            continue
    return {"ok": True, "count": len(items), "topics": items}


@tool("lesson.list", "Rules the agent has taught itself",
      capabilities=["memory.read"], risk=0.05, tags=["learn", "memory"])
def lesson_list(limit: int = 25) -> Dict[str, Any]:
    lessons = _memory().lessons(limit=limit)
    return {"ok": True, "count": len(lessons), "lessons": [l.to_dict() for l in lessons]}


@tool("lesson.add", "Teach the agent a rule to follow from now on",
      capabilities=["memory.write"], risk=0.10, tags=["learn", "memory"])
def lesson_add(pattern: str, rule: str) -> Dict[str, Any]:
    try:
        lesson = _memory().add_lesson(pattern, rule, confidence=0.8, source="owner")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "lesson": lesson.to_dict()}


# --------------------------------------------------------------------------
# Self introspection
# --------------------------------------------------------------------------


@tool("self.status", "Full health and capability report of the agent",
      capabilities=["chat"], risk=0.02, tags=["self", "stats"])
def self_status() -> Dict[str, Any]:
    from .. import brain as brain_module
    from ..config import capability_report, get_config
    from ..vault import get_vault

    cfg = get_config()
    agent = getattr(brain_module, "get_brain", lambda: None)()
    return {
        "ok": True,
        "agent": {"name": cfg.name, "version": cfg.version, "codename": cfg.codename},
        "config": cfg.describe(),
        "memory": memory_stats(),
        "security": get_security().status(),
        "vault": get_vault().health(),
        "brain": agent.status() if agent else {"state": "not started"},
        "capabilities": capability_report().splitlines(),
    }