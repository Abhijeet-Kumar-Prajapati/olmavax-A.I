"""
Open Charvis
============
A self-evolving personal AI agent that runs entirely on your own machine.

    from opencharvis import get_brain
    reply = get_brain().think("remember that my wifi password is on the fridge")

Architecture, outermost first::

    cli.py        command line: chat, voice, ui, memory, skills, security, test
    server.py     loopback HTTP API + serves the 3D interface
    voice.py      speech in / speech out, wake word
    brain.py      the kernel: parse -> recall -> gate -> act -> verify -> learn
    routing.py    one handler per intent
    nlu.py        English / Hindi / Hinglish intent parsing
    llm.py        provider bridge with an offline fallback reasoner
    tools/        the hands: system, web, code, media, knowledge
    self_improve.py  reflection, skill synthesis, sleep-cycle consolidation
    skills.py     loads skill files as tools
    memory.py     SQLite memory with hybrid keyword + vector recall
    security.py   risk scoring, capability gates, path jail, secret scrubbing
    vault.py      encrypted secret storage
    events.py     publish/subscribe so UI, voice and logs stay decoupled
    config.py     every setting, overridable
    logger.py     logging plus a tamper-evident audit trail
    utils.py      shared helpers

Nothing here requires a third party package. Optional extras make it better,
never required.
"""

from __future__ import annotations

__version__ = "2.1.0"
__codename__ = "CHARVIS-CORE"
__author__ = "Built for Abhijeet Kumar Prajapati"

from .config import PATHS, Config, capability_report, get_config
from .events import BUS, EventBus, Ev

__all__ = [
    "__version__",
    "__codename__",
    "Config",
    "get_config",
    "capability_report",
    "PATHS",
    "EventBus",
    "BUS",
    "Ev",
    "boot",
    "get_brain",
    "say",
    "shutdown",
]


def boot(config: Config | None = None, load_skills: bool = True) -> dict:
    """
    Start everything the agent needs and return a readiness report.

    Safe to call more than once.
    """
    from .config import ensure_dirs
    from .memory import get_memory
    from .security import get_security
    from .tools import load_all

    ensure_dirs()
    tool_count = load_all()

    skill_report = {"loaded": [], "failed": [], "skipped": [], "total": 0}
    if load_skills:
        from .skills import get_registry

        skill_report = get_registry().load()

    memory = get_memory()
    security = get_security()

    return {
        "version": __version__,
        "codename": __codename__,
        "tools": tool_count,
        "skills": skill_report,
        "memory": memory.stats(),
        "security_posture": security.cfg.posture,
    }


def get_brain():
    """The agent kernel (lazy import keeps startup fast)."""
    from .brain import get_brain as _get

    return _get()


def say(text: str, source: str = "api") -> dict:
    """One-line convenience wrapper around the brain."""
    return get_brain().think(text, source=source).to_dict()


def shutdown() -> dict:
    """Ask the agent to power down."""
    brain = get_brain()
    brain.stop()
    return {"stopped": True, "state": brain.state}