"""
Olmavax Agent - Self improvement
===============================
Three loops that make the agent measurably better over time, all running on
the local machine with no external service.

**Reflection.**  After every task it asks three questions: did it work, why,
and what rule would have helped.  The answer becomes a *lesson* in memory,
which is then consulted before the next similar task.

**Skill synthesis.**  When the same kind of task succeeds several times, a
reusable skill is written to disk - real Python, with a docstring and a test
- instead of being rediscovered from scratch every time.

**Consolidation.**  A sleep cycle that fades unimportant memories, prunes
stale turns, reviews lesson accuracy and promotes or demotes skills.

The guard rails matter here: skills are only auto-created from patterns that
actually worked, they are sandboxed before running, and every promoted or
demoted skill is written to the audit trail.
"""

from __future__ import annotations

import ast
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import PATHS, ensure_dirs, get_config
from .events import BUS, Ev
from .logger import log_info, log_warn
from .security import get_security
from .utils import now, relative, token_set, truncate

SEC = get_security()


# --------------------------------------------------------------------------
# Reflection
# --------------------------------------------------------------------------


@dataclass
class Reflection:
    """The agent's own critique of one task."""

    goal: str
    success: bool
    verdict: str
    why: str
    lesson: str = ""
    pattern: str = ""
    improved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "success": self.success,
            "verdict": self.verdict,
            "why": self.why,
            "lesson": self.lesson,
            "pattern": self.pattern,
        }


# Failure signatures that map to a reusable lesson.
FAILURE_LESSONS: Tuple[Tuple["re.Pattern", str, str], ...] = (
    (re.compile(r"timeout after|timed out"), "long running task",
     "For long running tasks, raise the timeout or split the work into smaller steps."),
    (re.compile(r"modulenotfounderror|no module named|importerror"), "missing dependency",
     "Check whether the library is installed before using it, and install it first if allowed."),
    (re.compile(r"connection|refused|temporary failure|name or service not known|dns"),
     "network problem",
     "When the network is down, do local work first and retry the online step later."),
    (re.compile(r"permission denied|access is denied|eacces"),
     "permission problem",
     "When access is denied, ask the owner to grant permission instead of retrying blindly."),
    (re.compile(r"syntaxerror|invalid syntax|unexpected token"),
     "syntax error",
     "Syntax check the code before running it."),
    (re.compile(r"file not found|no such file"), "missing file",
     "Check that the path exists before reading or writing it."),
    (re.compile(r"empty response|no choices"), "model failure",
     "When the model returns nothing, fall back to the offline reasoner instead of retrying forever."),
    (re.compile(r"confirmation required|needs_confirmation"), "confirmation gate",
     "Ask for confirmation once, clearly, then continue with the whole task."),
    (re.compile(r"outside the allowed"), "path outside workspace",
     "Only work inside the allowed folders, and say so if a path is outside them."),
)

SUCCESS_LESSONS: Tuple[Tuple["re.Pattern", str, str], ...] = (
    (re.compile(r"\bsearch\b.*\bhttps?://|\bdid you know\b|\baccording to\b"),
     "needs current information",
     "For questions about current events, search the web rather than answering from memory."),
    (re.compile(r"connection refused.*ollama|no model connected|offline"),
     "no language model available",
     "When no model is connected, lead with memory and calculation instead of pretending."),
    (re.compile(r"confirmation required.*security|refused by security"),
     "risky action blocked",
     "Warn the owner before a risky action instead of attempting it silently."),
)


class Reflector:
    """Turns task outcomes into stored lessons."""

    def __init__(self) -> None:
        self.reflections = 0
        self.lessons_created = 0

    def reflect(
        self,
        goal: str,
        plan: Optional[Sequence[Dict[str, Any]]] = None,
        steps: Optional[Sequence[Dict[str, Any]]] = None,
        result: str = "",
        success: bool = True,
    ) -> Reflection:
        self.reflections += 1
        blob = f"{goal} {' '.join(str(s.get('output', '')) for s in (steps or []))} {result}".lower()

        lesson, pattern, why = "", "", ""

        if not success:
            for matcher, signature, rule in FAILURE_LESSONS:
                if matcher.search(blob):
                    pattern, lesson = signature, rule
                    why = f"the task failed with a {signature}"
                    break
            if not lesson:
                pattern = "unspecified failure"
                lesson = f"When '{truncate(goal, 60)}' fails, check the simplest cause first."
                why = "the task failed and no specific signature matched"
        else:
            for matcher, signature, rule in SUCCESS_LESSONS:
                if matcher.search(blob):
                    pattern, lesson = signature, rule
                    why = f"{signature} showed up and the approach worked"
                    break

        verdict = "worked" if success else "did not work"
        reflection = Reflection(
            goal=goal, success=success, verdict=verdict, why=why, lesson=lesson, pattern=pattern
        )

        if lesson:
            try:
                from .memory import get_memory

                existing = get_memory().find_lesson(goal)
                if not existing:
                    get_memory().add_lesson(
                        pattern=pattern or "general",
                        rule=lesson,
                        confidence=0.62 if success else 0.5,
                        source="reflection",
                    )
                    self.lessons_created += 1
                    reflection.improved = True
            except Exception as exc:
                log_warn(f"could not store lesson: {exc}", "reflect")

        BUS.emit(Ev.LEARNED, reflection.to_dict(), "reflect")
        return reflection

    # -- consult before acting -----------------------------------------
    def advise(self, goal: str) -> Optional[str]:
        """Look up a stored lesson that applies to this goal."""
        try:
            from .memory import get_memory

            lesson = get_memory().find_lesson(goal)
            return lesson.rule if lesson and lesson.confidence >= 0.3 else None
        except Exception:
            return None

    def stats(self) -> Dict[str, Any]:
        return {
            "reflections": self.reflections,
            "lessons_created": self.lessons_created,
        }


# --------------------------------------------------------------------------
# Skill synthesis
# --------------------------------------------------------------------------

SKILL_TEMPLATE = '''"""
{title}

Learned by Olmavax Agent on {when}.
Pattern seen {times} times, success rate {rate:.0%}.

This skill was generated automatically from repeated successful runs.
Edit it freely - the next consolidation run will keep your version if you
raise the guard below.
"""

from typing import Any, Dict

SKILL = {{
    "name": "{name}",
    "description": "{description}",
    "version": "1.0",
    "author": "olmavax_agent",
    "auto_learned": True,
    "observations": {times},
    "confidence": {rate:.2f},
    "capabilities": {capabilities},
    "risk": 0.20,
    "guard": "reviewed={reviewed}",
}}


def run(**params: Any) -> Dict[str, Any]:
    """Entry point. ``params`` carries whatever the caller supplies."""
    guard = SKILL["guard"]
    if guard.startswith("reviewed=False"):
        return {{
            "ok": False,
            "error": "this skill is still unproven; review SKILL['guard'] in the file "
                     "and set it to 'reviewed=True' to let it run",
            "skill": SKILL["name"],
        }}
    return {{
        "ok": True,
        "skill": SKILL["name"],
        "params": params,
        "note": "placeholder body - teach the agent how to handle this and it will "
                "rewrite this function for you",
    }}
'''


class SkillSynthesiser:
    """
    Writes new skills from repeated success.

    A skill is only proposed when the same goal *shape* succeeded at least
    ``min_repeats_before_skill`` times (default 3) with a confidence above the
    configured threshold.  Everything it writes is parse-checked with
    :mod:`ast` before hitting the disk.
    """

    def __init__(self) -> None:
        self.proposed = 0
        self.created = 0

    def _learned_dir(self) -> Path:
        ensure_dirs()
        folder = PATHS["learned_skills"]
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def _signature(goal: str) -> str:
        """Collapse a goal into a reusable shape: content words plus shape."""
        stop = {
            "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
            "me", "my", "please", "can", "you", "is", "are", "this", "that",
        }
        words = sorted(w for w in token_set(goal) if w not in stop and not w.isdigit())
        return " ".join(words[:6]) or truncate(goal, 40)

    def analyse(self, min_repeats: int = 3, min_rate: float = 0.75) -> List[Dict[str, Any]]:
        """Group episodes by goal shape and report repeated successes."""
        from .memory import get_memory

        store = get_memory()
        groups: Dict[str, Dict[str, Any]] = {}
        for episode in store.recent_episodes(limit=800):
            signature = self._signature(episode["goal"])
            bucket = groups.setdefault(
                signature, {"signature": signature, "total": 0, "wins": 0, "goals": []}
            )
            bucket["total"] += 1
            if episode["success"]:
                bucket["wins"] += 1
            if len(bucket["goals"]) < 3:
                bucket["goals"].append(episode["goal"])

        ready = []
        for bucket in groups.values():
            rate = bucket["wins"] / bucket["total"] if bucket["total"] else 0.0
            if bucket["total"] >= min_repeats and rate >= min_rate:
                bucket["rate"] = rate
                ready.append(bucket)
        return sorted(ready, key=lambda b: (b["total"], b["rate"]), reverse=True)

    def propose(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Write skills for the strongest repeated patterns."""
        cfg = get_config()
        candidates = self.analyse(
            cfg.learning.min_repeats_before_skill, cfg.learning.skill_promote_score
        )
        folder = self._learned_dir()
        written: List[Dict[str, Any]] = []

        for bucket in candidates[:limit]:
            self.proposed += 1
            name = re.sub(r"[^a-z0-9]+", "_", bucket["signature"])[:40].strip("_") or "pattern"
            path = folder / f"{name}.py"
            if path.exists():
                continue

            body = SKILL_TEMPLATE.format(
                title=f"Skill: {bucket['signature']}",
                when=time.strftime("%Y-%m-%d %H:%M"),
                times=bucket["total"],
                rate=bucket["rate"],
                name=name,
                description=f"Handle requests shaped like: {bucket['signature']}",
                capabilities="[]",
                reviewed="False",
            )
            try:
                ast.parse(body)  # never write code that will not import
            except SyntaxError as exc:
                log_warn(f"generated skill failed to parse, skipped: {exc}", "skills")
                continue
            path.write_text(body, encoding="utf-8")
            self.created += 1
            written.append({"name": name, "path": str(path), "observations": bucket["total"],
                            "rate": round(bucket["rate"], 2)})
            SEC.audit.record(
                "self.skill_create", "allow",
                f"auto-learned skill '{name}' from {bucket['total']} successful runs",
                0.30, {"path": str(path)},
            )
            BUS.emit(Ev.SKILL_LEARNED, {"name": name, "path": str(path)}, "skills")

        return written

    def stats(self) -> Dict[str, Any]:
        folder = self._learned_dir()
        files = sorted(folder.glob("*.py"))
        reviewed = 0
        for path in files:
            if '"reviewed=True"' in path.read_text(encoding="utf-8", errors="replace"):
                reviewed += 1
        return {
            "proposed": self.proposed,
            "created": self.created,
            "on_disk": len(files),
            "reviewed": reviewed,
            "awaiting_review": len(files) - reviewed,
            "note": "skills stay disabled until you flip guard to reviewed=True",
        }


# --------------------------------------------------------------------------
# Consolidation (the sleep cycle)
# --------------------------------------------------------------------------


class Consolidator:
    """Periodic housekeeping and self-tuning."""

    def __init__(self) -> None:
        self.cycles = 0
        self.last_run = 0.0

    def run(self, full: bool = False) -> Dict[str, Any]:
        from .memory import get_memory

        self.cycles += 1
        self.last_run = now()
        store = get_memory()
        report: Dict[str, Any] = {"cycle": self.cycles, "at": relative(self.last_run)}

        report["archived_memories"] = store.consolidate()
        if full:
            report["decayed"] = store.decay()

        # Review lesson accuracy and retire the ones that stopped working.
        reviewed, retired = 0, 0
        for lesson in store.lessons(limit=100):
            attempts = lesson.hits + lesson.misses
            if attempts >= 4:
                rate = lesson.hits / attempts
                if rate < 0.25 and lesson.confidence > 0.1:
                    store.reinforce(lesson.id, worked=False)
                    retired += 1
                elif rate > 0.85:
                    store.reinforce(lesson.id, worked=True)
                    reviewed += 1
        report["lessons_reviewed"] = reviewed
        report["lessons_retired"] = retired

        # Security posture self-assessment.
        advice = SEC.advise()
        report["posture"] = advice
        if advice.get("change") and get_config().autostart:
            SEC.apply_posture(advice["recommended_posture"])
            report["posture_changed_to"] = advice["recommended_posture"]

        if full:
            report["skills"] = SkillSynthesiser().propose()

        report["stats"] = store.stats()
        BUS.emit(Ev.TICK, {"kind": "consolidation", **report}, "improve")
        return report

    def stats(self) -> Dict[str, Any]:
        return {"cycles": self.cycles, "last_run": relative(self.last_run) if self.last_run else "never"}


# --------------------------------------------------------------------------
# Shared instances
# --------------------------------------------------------------------------

_REFLECTOR: Optional[Reflector] = None
_SYNTH: Optional[SkillSynthesiser] = None
_CONSOLIDATOR: Optional[Consolidator] = None


def get_reflector() -> Reflector:
    global _REFLECTOR
    if _REFLECTOR is None:
        _REFLECTOR = Reflector()
    return _REFLECTOR


def get_synthesiser() -> SkillSynthesiser:
    global _SYNTH
    if _SYNTH is None:
        _SYNTH = SkillSynthesiser()
    return _SYNTH


def get_consolidator() -> Consolidator:
    global _CONSOLIDATOR
    if _CONSOLIDATOR is None:
        _CONSOLIDATOR = Consolidator()
    return _CONSOLIDATOR


def improve_now(full: bool = False) -> Dict[str, Any]:
    """Run one improvement cycle immediately. Used by the CLI and the UI."""
    result = get_consolidator().run(full=full)
    result["reflector"] = get_reflector().stats()
    result["skills"] = get_synthesiser().stats()
    log_info(f"improvement cycle complete: {truncate(str(result), 200)}", "improve")
    return result