"""
Olmavax Agent - The brain
========================
The kernel.  Every request, whether spoken, typed or fetched from the web
UI, enters here and leaves as a :class:`Reply`.

The loop for each request::

    parse -> recall -> consult lessons -> security gate -> act -> verify -> record -> reflect

That last step is what makes it self-improving: the outcome of *every* task
is written to memory as an episode, and the reflector distils a rule from it.
Next time a similar request arrives the rule is already in hand.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .config import Config, get_config
from .events import BUS, Ev
from .llm import BrainLLM, get_llm
from .logger import log_info, log_warn
from .memory import Memory, MemoryStore, Recall, get_memory
from .mind import get_mind
from .nlu import Intent, get_nlu
from .security import ASK, BLOCK, Decision, get_security
from .self_improve import get_consolidator, get_reflector
from .tools import ToolResult, list_tools, run
from .utils import clamp, human_duration, relative, truncate, uptime

SEC = get_security()

# Agent states
IDLE = "idle"
THINKING = "thinking"
ACTING = "acting"
LEARNING = "learning"
SLEEPING = "sleeping"
STOPPED = "stopped"


@dataclass
class Reply:
    """The agent's answer, with everything the UI needs to render it."""

    text: str
    intent: str = "chat"
    confidence: float = 0.0
    tool: str = ""
    tool_result: Optional[Dict[str, Any]] = None
    memories_used: List[Dict[str, Any]] = field(default_factory=list)
    offline: bool = False
    risk: float = 0.0
    security: str = "allow"
    needs_confirmation: bool = False
    confirmation_prompt: str = ""
    elapsed: float = 0.0
    reflection: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.text.lower().startswith(("i could not", "i am unable"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "intent": self.intent,
            "confidence": round(self.confidence, 3),
            "tool": self.tool,
            "tool_result": self.tool_result,
            "memories_used": self.memories_used,
            "offline": self.offline,
            "risk": round(self.risk, 3),
            "security": self.security,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_prompt": self.confirmation_prompt,
            "elapsed": round(self.elapsed, 3),
            "reflection": self.reflection,
            "suggestions": self.suggestions,
        }


class Brain:
    """Stateful agent kernel. One instance per process."""

    def __init__(self, config: Optional[Config] = None):
        self.cfg = config or get_config()
        self.nlu = get_nlu()
        self.memory: MemoryStore = get_memory()
        self.llm: BrainLLM = get_llm(self.cfg.brain)
        self.security = SEC
        self.reflector = get_reflector()
        self.mind = get_mind()

        self.state = IDLE
        self.started_at = time.time()
        self.session = "default"
        self.think_mode = False
        self.last_voice = 0.0
        self.stop_requested = False
        self.pending_confirmation: Optional[str] = None
        self.pending_correction: Optional[Tuple[str, str]] = None
        self.last_exchange: Optional[Tuple[str, str]] = None
        self.handlers: Dict[str, Callable[[Intent], Tuple[str, Dict[str, Any]]]] = {}
        self.totals = {"requests": 0, "tools_run": 0, "blocked": 0, "offline": 0}
        self._unsaved = 0
        self._lock = threading.RLock()
        self._last_error: str = ""
        self._last_intent: Intent = Intent("chat", {}, 0.0, "")
        self._last_route_source: str = "rule"
        self._register_handlers()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def _register_handlers(self) -> None:
        from . import routing

        routing.register(self.handlers)
        log_info(f"brain ready with {len(self.handlers)} intent handlers", "brain")

    # ------------------------------------------------------------------
    def set_think_mode(self, enabled: bool) -> bool:
        """
        Thinking mode: every answer arrives with its working shown.

        Off, you get just the answer. On, you get the goal, the shape it
        recognised, each step taken, what was found, the confidence, and -
        importantly - what it is unsure about.
        """
        self.think_mode = bool(enabled)
        return self.think_mode

    def deep_think(self, text: str) -> Reply:
        """Answer with the full reasoning chain visible."""
        from .reasoning import get_reasoner

        started = time.perf_counter()
        self.state = THINKING
        reasoning = get_reasoner().think(text, verbose=self.think_mode)
        reply = Reply(
            text=reasoning.render(verbose=self.think_mode),
            intent=f"think:{reasoning.shape}",
            confidence=reasoning.confidence,
            elapsed=time.perf_counter() - started,
        )
        reply.tool_result = reasoning.to_dict()
        reply.suggestions.extend(reasoning.caveats)

        from .nlu import get_nlu

        intent = get_nlu().parse(text)
        self._last_intent = intent
        self.memory.push_turn("user", text, {"intent": intent.name})
        self.memory.push_turn("assistant", reply.text, {"intent": reply.intent})
        self.memory.record_episode(goal=text, plan=reasoning.to_dict()["steps"],
                                    result=reply.text, success=bool(reasoning.answer))
        self._train(intent, reply, "rule")

        self.state = IDLE
        BUS.emit(Ev.RESPONSE, reply.to_dict(), "brain")
        return reply

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def think(self, text: str, source: str = "text") -> Reply:
        """
        Process one request end to end.

        Never raises: any unexpected failure becomes a Reply explaining
        what went wrong, because an assistant that crashes mid-sentence is
        worse than one that admits a problem.
        """
        started = time.perf_counter()
        self.state = THINKING
        self.totals["requests"] += 1
        self._last_intent = Intent("chat", {}, 0.0, text)
        self._last_route_source = "rule"
        BUS.emit(Ev.THINKING, {"text": truncate(text, 120), "source": source}, "brain")

        try:
            reply = self._pipeline(text, source, started)
            self._train(self._last_intent, reply, self._last_route_source)
        except Exception as exc:  # last line of defence
            self._last_error = f"{type(exc).__name__}: {exc}"
            log_warn(f"pipeline crashed: {self._last_error}", "brain")
            reply = Reply(
                text=f"Something went wrong inside me: {self._last_error}. "
                "I logged it - say 'status' and I will show you what I know.",
                intent="error",
                elapsed=time.perf_counter() - started,
            )
            BUS.emit(Ev.ERROR, {"error": self._last_error}, "brain")

        self.state = IDLE
        reply.elapsed = reply.elapsed or (time.perf_counter() - started)
        BUS.emit(Ev.RESPONSE, reply.to_dict(), "brain")
        return reply

    def _train(self, intent: Intent, reply: Reply, route_source: str) -> None:
        """
        Every completed request is a training example.

        Label confidence reflects how sure we are of the label itself:
        a confident rule is a better teacher than a weak guess, and a learned
        routing decision is weaker still because it came from this same
        model.
        """
        success = bool(reply.text) and not reply.text.lower().startswith(
            ("i could not", "i am unable", "something went wrong")
        )
        if reply.security == "block":
            # Being stopped for a hard block is *correct* behaviour, not a
            # failure to route - do not poison the label.
            success = True

        teacher = {"rule": 1.0, "ensemble": 0.8, "learned": 0.45, "untrained": 0.6}
        self.mind.learn(
            intent.raw,
            intent.name,
            success=success,
            confidence=teacher.get(route_source, 0.6),
        )

        if reply.tool:
            self.mind.reward(
                intent.name,
                reply.tool,
                1.0 if success else 0.0,
                slots=intent.slots,
            )

        self.last_exchange = (intent.raw, intent.name)
        self._unsaved += 1
        if self._unsaved >= 25:
            self._unsaved = 0
            try:
                self.mind.save()
            except OSError as exc:
                log_warn(f"could not save the mind: {exc}", "brain")

    def _slots_for(self, text: str, intent_name: str) -> Dict[str, Any]:
        """
        Recover slots when the learned model overrode the regex parser.

        The regex for that intent exists (otherwise it would not be a known
        class), so run just that one pattern to pull the arguments out.
        """
        try:
            for name, pattern, extractor, _confidence in self.nlu.patterns:
                if name != intent_name:
                    continue
                match = pattern.search(text)
                if match:
                    return self.nlu._slots(extractor, text, match)
        except Exception:
            pass
        return {}

    def _pipeline(self, text: str, source: str, started: float) -> Reply:
        # Thinking mode takes over everything: it is the reasoning path,
        # not a special case bolted onto one intent.
        if self.think_mode:
            return self.deep_think(text)

        intent = self.nlu.parse(text)

        # -- corrections: "nahi, ye galat hai" ------------------------
        # The owner's correction is the highest-value training signal there
        # is. The wrong label is recorded now; the right one is learned from
        # whatever they ask for next, which is how people correct each other.
        if self.mind.looks_like_correction(text) and self.last_exchange:
            rejected_text, rejected_intent = self.last_exchange
            self.pending_correction = (rejected_text, rejected_intent)
            return Reply(
                text=(
                    "You are right, that was my mistake. I have marked "
                    f"'{truncate(rejected_text, 50)}' as NOT "
                    f"'{rejected_intent}' so I stop making it.\n"
                    "Tell me what you actually wanted and I will remember that instead."
                ),
                intent="correction",
                confidence=1.0,
                elapsed=time.perf_counter() - started,
            )

        # -- rules propose, the learned mind disposes ------------------
        routed, routed_confidence, source_of_intent = self.mind.route(
            text, intent.name, intent.confidence
        )
        if routed != intent.name:
            intent.name = routed
            intent.confidence = routed_confidence
            intent.slots = self._slots_for(text, routed)

        # A correction is applied once we know what they asked for instead.
        if self.pending_correction:
            rejected_text, rejected_intent = self.pending_correction
            self.pending_correction = None
            self.mind.correct(rejected_text, rejected_intent, intent.name)

        BUS.emit(Ev.COMMAND_RECEIVED, intent.to_dict(), "brain")
        self._last_intent = intent
        self._last_route_source = source_of_intent
        if source_of_intent == "learned":
            log_info(
                f"learned routing: '{truncate(text, 50)}' -> {intent.name}",
                "brain",
            )

        # -- exit is handled first and directly ------------------------
        if intent.name == "shutdown":
            self.stop_requested = True
            self.state = SLEEPING
            return Reply(
                text=self._farewell(),
                intent="shutdown",
                confidence=1.0,
                elapsed=time.perf_counter() - started,
            )

        # -- security gate on the raw request -------------------------
        decision = self.security.gate("request", text)
        reply = Reply(
            text="", intent=intent.name, confidence=intent.confidence,
            risk=decision.risk.score, security=decision.verdict,
        )
        reply.confidence = self.mind.calibrate(intent.name, reply.confidence)
        if decision.verdict == BLOCK:
            self.totals["blocked"] += 1
            reply.text = (
                f"I will not do that one. {decision.reason}. "
                "That rule protects you, and I do not bypass it even when asked politely."
            )
            self._record(intent, reply, False, started)
            return reply

        # -- recall -----------------------------------------------------
        memories = self.memory.search(text, limit=self.cfg.brain.memory_recall_limit)
        reply.memories_used = [r.to_dict() for r in memories]

        # -- pending confirmation short-circuit -----------------------
        if self.pending_confirmation:
            answered = self.security.resolve_confirmation(text)
            if answered is True:
                carried, self.pending_confirmation = self.pending_confirmation, None
                return self._resume(carried, reply, started)
            if answered is False:
                self.pending_confirmation = None
                reply.text = "Understood. I stopped."
                return reply

        # -- confidence gate for risky-but-allowed requests -------------
        if decision.verdict == ASK and intent.confidence < 0.6 and intent.name in {
            "power_shutdown", "power_restart", "power_sleep", "memory_forget"
        }:
            self.pending_confirmation = text
            reply.needs_confirmation = True
            reply.confirmation_prompt = self.security.request_confirmation(f"c{abs(hash(text))}")
            reply.text = (
                f"I understood that as '{intent.name}', which changes your machine. "
                f"{reply.confirmation_prompt}"
            )
            self._record(intent, reply, False, started)
            return reply

        # -- lesson lookup ----------------------------------------------
        if self.cfg.brain.enable_reflection:
            hint = self.reflector.advise(text)
            if hint:
                reply.suggestions.append(f"lesson applied: {hint}")

        # -- dispatch ----------------------------------------------------
        handler = self.handlers.get(intent.name)
        if handler is not None:
            self.state = ACTING
            # Keep the dialogue layer's idea of "what we are talking about"
            # in sync, so a bare follow-up ("and?", "why?") lands on the
            # right subject even when the last thing said was a command
            # rather than a question.
            topic = intent.slots.get("topic") or intent.slots.get("query")
            if topic and self.llm.offline:
                self.llm.offline.topic = str(topic)

            output, data = handler(intent)
            reply.text = output
            reply.tool = data.get("tool", intent.name)
            reply.tool_result = {k: v for k, v in data.items() if k != "tool"}
            self.totals["tools_run"] += 1

            # A tool can ask for confirmation on its own (paranoid posture,
            # a destructive action). Surface that instead of leaking the raw
            # refusal text.
            if data.get("needs_confirmation") or reply.tool_result.get("needs_confirmation"):
                self.pending_confirmation = text
                reply.needs_confirmation = True
                reply.confirmation_prompt = self.security.request_confirmation(
                    f"c{abs(hash(text))}"
                )
                reply.text = f"{reply.text}\n\n{reply.confirmation_prompt}"
        else:
            self.state = THINKING
            reply = self._converse(intent, memories, reply)

        reply.elapsed = time.perf_counter() - started
        self._record(intent, reply, bool(reply.text) and not reply.text.startswith("I could not"), started)
        return reply

    def _resume(self, original: str, reply: Reply, started: float) -> Reply:
        """Re-run a request the owner has just confirmed."""
        intent = self.nlu.parse(original)
        handler = self.handlers.get(intent.name)
        self.state = ACTING
        if handler is not None:
            output, data = handler(intent)
            reply.text = f"Confirmed. {output}"
            reply.tool = data.get("tool", intent.name)
            reply.tool_result = {k: v for k, v in data.items() if k != "tool"}
        else:
            memories = self.memory.search(original, limit=self.cfg.brain.memory_recall_limit)
            reply = self._converse(intent, memories, reply)
            reply.text = f"Confirmed. {reply.text}"
        reply.intent = intent.name
        reply.elapsed = time.perf_counter() - started
        self._record(intent, reply, True, started)
        return reply

    # ------------------------------------------------------------------
    # Conversation path
    # ------------------------------------------------------------------
    def _converse(self, intent: Intent, memories: List[Recall], reply: Reply) -> Reply:
        question = intent.slots.get("text") or intent.raw
        if intent.slots.get("hinglish"):
            question = f"{question}\n(romanised: {intent.slots['hinglish']})"

        # Special cases that do not need a model at all.
        special = self._local_answer(question)
        if special:
            reply.text = special
            reply.intent = "chat"
            reply.offline = True
            return reply

        history = self.memory.recent_turns(limit=self.cfg.brain.context_messages)
        answer = self.llm.complete(
            prompt=question,
            system=self._system_prompt(memories),
            history=[
                {"role": t["role"], "content": t["text"]}
                for t in history
                if t["role"] in {"user", "assistant"}
            ],
            memories=memories,
        )

        reply.text = answer.text or "I had nothing useful to say about that."
        reply.offline = answer.offline
        reply.intent = "chat"
        if answer.error:
            reply.suggestions.append(f"model issue: {truncate(answer.error, 120)}")
        if answer.offline:
            self.totals["offline"] += 1
        return reply

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------
    def stream_think(self, text: str, source: str = "web") -> Iterator[Dict[str, Any]]:
        """
        Think, but narrate the process as it happens.

        Yields a sequence of events the web layer forwards straight to the
        browser, which is what makes the interface feel live instead of
        frozen: you see 'thinking', then 'searching', then the answer
        arriving word by word.
        """
        started = time.perf_counter()
        self.state = THINKING
        self.totals["requests"] += 1
        self._last_intent = Intent("chat", {}, 0.0, text)
        self._last_route_source = "rule"
        BUS.emit(Ev.THINKING, {"text": truncate(text, 120), "source": source}, "brain")

        yield {"event": "status", "state": "thinking", "text": text[:200]}

        collected: List[str] = []
        # Named `chunks`, not `queue`: a local named `queue` shadows the
        # module and the very next line raises UnboundLocalError.
        chunks: "queue.Queue[Optional[Tuple[str, str]]]" = queue.Queue()
        result: Dict[str, Any] = {}

        def worker() -> None:
            try:
                reply = self._pipeline(text, source, started)
                self._train(self._last_intent, reply, self._last_route_source)
                result["reply"] = reply
                for word in reply.text.split(" "):
                    chunks.put(("delta", word + " "))
                chunks.put(("done", ""))
            except Exception as exc:  # keep the stream alive
                result["error"] = f"{type(exc).__name__}: {exc}"
                chunks.put(("error", str(exc)))
            finally:
                chunks.put((None, ""))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            try:
                kind, payload = chunks.get(timeout=0.25)
            except queue.Empty:
                yield {"event": "heartbeat"}
                continue
            if kind is None:
                break
            if kind == "delta":
                collected.append(payload)
                yield {"event": "delta", "text": payload}
            elif kind == "error":
                yield {"event": "error", "message": payload}
            elif kind == "done":
                break

        reply = result.get("reply")
        if reply is not None:
            reply.elapsed = reply.elapsed or (time.perf_counter() - started)
            BUS.emit(Ev.RESPONSE, reply.to_dict(), "brain")
            yield {
                "event": "final",
                "intent": reply.intent,
                "tool": reply.tool,
                "offline": reply.offline,
                "confidence": round(reply.confidence, 3),
                "elapsed": round(reply.elapsed, 3),
                "memories": len(reply.memories_used),
                "security": reply.security,
                "needs_confirmation": reply.needs_confirmation,
                "reflection": reply.reflection,
            }
        else:
            yield {"event": "error", "message": result.get("error", "unknown failure")}

    def _local_answer(self, question: str) -> str:
        """Deterministic answers that never need a language model."""
        import re
        import time as _time

        probe = question.lower().strip()

        if re.match(r"^\s*(hi|hello|hey|namaste|good (morning|evening|afternoon))\b", probe):
            name = self.memory.get_pref("owner_name", self.cfg.owner)
            return (
                f"Hello {name}. I am {self.cfg.name} {self.cfg.version}, awake and listening. "
                "What are we doing today?"
            )
        if re.search(r"\b(thank|shukriya|dhanyavad)\b", probe):
            return "Any time. I am here whenever you need me."
        if re.search(r"\bwho are you\b|\bwhat are you\b|\btum kaun ho\b", probe):
            return (
                f"I am {self.cfg.name} {self.cfg.version}, codename {self.cfg.codename}. "
                "I run entirely on your machine. I remember what you tell me, I learn rules from "
                "my own mistakes, I can control your computer, search the internet, write and run "
                "code in several languages, and generate images and animation. "
                "Nothing leaves this machine unless you ask it to."
            )
        if re.search(r"\b(time|ghadi)\b", probe) and re.search(r"\b(time|ghadi|what|kitna|now)\b", probe):
            return _time.strftime("It is %I:%M %p on %A, %d %B %Y.")
        if re.search(r"\b(date|today|aaj)\b", probe):
            return _time.strftime("Today is %A, %d %B %Y.")
        if re.search(r"\b(how are you|kaisa ho|kya haal)\b", probe):
            # Let the dialogue layer answer this: it gives a warmer, more
            # specific answer than a status dump.
            return ""
        return ""

    def _system_prompt(self, memories: List[Recall]) -> str:
        owner = self.memory.get_pref("owner_name", self.cfg.owner)
        parts = [
            f"You are {self.cfg.name} ({self.cfg.codename} v{self.cfg.version}), a personal AI "
            f"agent running on {owner}'s own Windows machine. Everything is local and private.",
            "Rules:",
            "- Be direct and concise. No filler, no preamble.",
            "- If you are unsure, say so plainly. Never invent facts, files or capabilities.",
            "- If a task needs a tool, say what you are about to do, then do it.",
            "- Speak the owner's language. If they write Hinglish, reply naturally.",
            "- Talk like a person, not a manual: greet back, ask a follow-up when it helps.",
            "- Keep replies short enough that they sound right read out loud.",
            f"- Today's date is {_today()}.",
        ]
        relevant = [r for r in memories if r.score > 0.25][:4]
        if relevant:
            lines = "\n".join(f"  - {truncate(r.memory.text, 160)}" for r in relevant)
            parts.append(f"What you already know that is relevant:\n{lines}")
        pinned = [m.text for m in self.memory.all_pinned()[:5]]
        if pinned:
            parts.append("Standing instructions the owner has pinned:\n" +
                        "\n".join(f"  - {truncate(t, 120)}" for t in pinned))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Learning from every request
    # ------------------------------------------------------------------
    def _record(self, intent: Intent, reply: Reply, success: bool, started: float) -> None:
        self.memory.push_turn(
            "user", intent.raw,
            {"intent": intent.name, "source": "agent"},
        )
        self.memory.push_turn(
            "assistant", reply.text,
            {"intent": reply.intent, "tool": reply.tool, "offline": reply.offline},
        )

        # Also written to the durable conversation history, which is what the
        # interface shows and what survives a restart.
        try:
            from .user import get_history

            history = get_history()
            history.append("user", intent.raw, session=self.session,
                           meta={"intent": intent.name})
            history.append("assistant", reply.text, session=self.session,
                           meta={"intent": reply.intent, "tool": reply.tool})
        except Exception as exc:
            log_warn(f"could not write history: {exc}", "brain")

        steps = [{"tool": reply.tool, "output": truncate(reply.text, 300)}] if reply.tool else []
        self.memory.record_episode(
            goal=intent.raw,
            plan=[{"step": intent.name}],
            steps=steps,
            result=reply.text,
            success=success,
            score=clamp(intent.confidence * (1.0 if success else 0.3)),
            duration=time.perf_counter() - started,
            tags=[intent.name],
        )

        if self.cfg.brain.enable_reflection:
            self.state = LEARNING
            reflection = self.reflector.reflect(
                goal=intent.raw,
                steps=steps,
                result=reply.text,
                success=success,
            )
            reply.reflection = reflection.to_dict()
            self.state = IDLE

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _farewell(self) -> str:
        return (
            f"Powering down. {self.totals['requests']} requests handled, "
            f"{self.memory.stats()['active_memories']} memories kept. "
            "Everything is saved - say the wake word and I am back."
        )

    def stop(self) -> None:
        self.stop_requested = True
        self.state = SLEEPING
        try:
            self.mind.save()
        except OSError:
            pass
        BUS.emit(Ev.SHUTDOWN, self.status(), "brain")

    def should_stop(self) -> bool:
        return self.stop_requested

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        stats = self.memory.stats()
        return {
            "name": self.cfg.name,
            "version": self.cfg.version,
            "codename": self.cfg.codename,
            "state": self.state,
            "uptime": human_duration(time.time() - self.started_at),
            "started": relative(self.started_at),
            "totals": dict(self.totals),
            "memory": {
                "active": stats["active_memories"],
                "episodes": stats["episodes"]["total"],
                "success_rate": stats["episodes"]["success_rate"],
                "lessons": stats["counts"].get("lessons", 0),
                "size": stats["db_bytes"],
            },
            "model": self.llm.status(),
            "security": {
                "posture": self.cfg.security.posture,
                "decisions": self.security.status()["decisions"],
            },
            "learning": {
                "reflection": self.reflector.stats(),
                "consolidation": get_consolidator().stats(),
                "mind": self.mind.status(),
            },
            "intents": self.nlu.stats_report(),
            "tools": len(list_tools()),
            "last_error": self._last_error,
            "pending_confirmation": self.pending_confirmation,
        }


def _today() -> str:
    return time.strftime("%A %d %B %Y")


_BRAIN: Optional[Brain] = None
_BRAIN_LOCK = threading.Lock()


def get_brain(config: Optional[Config] = None) -> Brain:
    global _BRAIN
    if _BRAIN is None:
        with _BRAIN_LOCK:
            if _BRAIN is None:
                _BRAIN = Brain(config=config)
    return _BRAIN