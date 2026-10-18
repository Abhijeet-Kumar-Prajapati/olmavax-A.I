"""Open Charvis - Event bus.

A tiny synchronous publish/subscribe system so the GUI, web dashboard,
voice layer and logs can all react to what the brain is doing without
knowing about each other.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional


@dataclass(frozen=True)
class Event:
    name: str
    payload: Any = None
    source: str = "kernel"
    ts: float = field(default_factory=time.time)

    def age(self) -> float:
        return time.time() - self.ts


Handler = Callable[[Event], None]


class EventBus:
    """Thread-safe event bus with wildcard subscription and a replay buffer."""

    def __init__(self, history: int = 300):
        self._handlers: Dict[str, List[Handler]] = {}
        self._lock = threading.RLock()
        self._history: Deque[Event] = deque(maxlen=history)

    # -- subscription ---------------------------------------------------
    def on(self, name: str, handler: Handler) -> Handler:
        """Subscribe. Use ``"*"`` to catch everything."""
        with self._lock:
            self._handlers.setdefault(name, []).append(handler)
        return handler

    def once(self, name: str, handler: Handler) -> Handler:
        def wrapper(event: Event) -> None:
            self.off(name, wrapper)
            handler(event)

        return self.on(name, wrapper)

    def off(self, name: str, handler: Optional[Handler] = None) -> None:
        with self._lock:
            if handler is None:
                self._handlers.pop(name, None)
            elif name in self._handlers and handler in self._handlers[name]:
                self._handlers[name].remove(handler)

    # -- publishing -----------------------------------------------------
    def emit(self, name: str, payload: Any = None, source: str = "kernel") -> Event:
        event = Event(name=name, payload=payload, source=source)
        with self._lock:
            self._history.append(event)
            targets = list(self._handlers.get(name, [])) + list(self._handlers.get("*", []))

        for handler in targets:
            try:
                handler(event)
            except Exception:
                # A broken listener must never break the agent.
                traceback.print_exc()
        return event

    def emit_async(self, name: str, payload: Any = None, source: str = "kernel") -> None:
        threading.Thread(
            target=self.emit, args=(name, payload, source), daemon=True
        ).start()

    # -- inspection -----------------------------------------------------
    def recent(self, limit: int = 40, prefix: Optional[str] = None) -> List[Event]:
        with self._lock:
            items = list(self._history)
        if prefix:
            items = [e for e in items if e.name.startswith(prefix)]
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()


# Canonical event names used across the system.
class Ev:
    THINKING = "agent.thinking"
    PLAN = "agent.plan"
    RESPONSE = "agent.response"
    ERROR = "agent.error"
    COMMAND_RECEIVED = "agent.command"
    SKILL_INVOKED = "skill.invoked"
    SKILL_DONE = "skill.done"
    MEMORY_STORED = "memory.stored"
    MEMORY_RECALLED = "memory.recalled"
    LEARNED = "learning.event"
    SKILL_LEARNED = "learning.skill"
    SECURITY_BLOCK = "security.block"
    SECURITY_WARN = "security.warn"
    SECURITY_SCAN = "security.scan"
    VOICE_START = "voice.start"
    VOICE_HEARD = "voice.heard"
    VOICE_STOP = "voice.stop"
    STATE = "kernel.state"
    TICK = "kernel.tick"
    AVATAR_MOOD = "ui.mood"
    SHUTDOWN = "kernel.shutdown"


BUS = EventBus()