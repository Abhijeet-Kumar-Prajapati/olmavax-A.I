"""
Olmavax Agent - Language model bridge
===================================
One interface, many providers, and a working fallback when there is none.

Providers, in auto-detection order:

1. **Ollama** on localhost - fully offline, free, no key
2. **Groq / OpenAI / Together / Gemini / Anthropic** - any key present in the
   environment or the encrypted vault

If no model can be reached the agent does not go silent.  It falls back to
:class:`OfflineReasoner`, which answers by combining its own memory,
retrieved web results and local computation.  That is genuinely useful, and
it is clearly labelled as the offline path rather than pretending to be a
large language model.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import BrainConfig, get_config
from .logger import log_info, log_warn
from .utils import http_get, http_post_json, net_available, now, truncate

Message = Dict[str, str]


@dataclass
class LLMReply:
    text: str
    provider: str
    model: str
    latency: float = 0.0
    error: str = ""
    offline: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


# --------------------------------------------------------------------------
# Provider implementations
# --------------------------------------------------------------------------


class Provider:
    """Base class. Subclasses implement :meth:`call`."""

    name = "none"
    needs_key = False

    def available(self, cfg: BrainConfig, vault: Any) -> bool:
        return False

    def call(self, messages: List[Message], system: str, cfg: BrainConfig, vault: Any) -> Tuple[str, str]:
        """Returns (text, model_used)."""
        raise NotImplementedError


class Ollama(Provider):
    name = "ollama"
    needs_key = False

    def available(self, cfg: BrainConfig, vault: Any) -> bool:
        if cfg.provider not in {"auto", "ollama"}:
            return False
        status, _ = http_get(f"{cfg.ollama_host}/api/tags", timeout=2)
        return status == 200

    def call(self, messages: List[Message], system: str, cfg: BrainConfig, vault: Any) -> Tuple[str, str]:
        payload = {
            "model": cfg.ollama_model if cfg.model == "auto" else cfg.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "stream": False,
            "options": {"temperature": cfg.temperature, "num_predict": cfg.max_tokens},
        }
        status, body = http_post_json(f"{cfg.ollama_host}/api/chat", payload, timeout=cfg.timeout_seconds)
        if status != 200:
            raise RuntimeError(f"ollama returned {status}")
        data = json.loads(body)
        text = data.get("message", {}).get("content", "")
        return text, payload["model"]


class OpenAICompatible(Provider):
    """Groq, Together and OpenAI all speak the same chat completions shape."""

    def __init__(self, name: str, base_key: str, model_key: str, env_key: str, default_model: str):
        self.name = name
        self.base_key = base_key
        self.model_key = model_key
        self.env_key = env_key
        self.default_model = default_model

    def available(self, cfg: BrainConfig, vault: Any) -> bool:
        if cfg.provider not in {"auto", self.name}:
            return False
        return bool(vault.api_key(self.name, self.env_key))

    def call(self, messages: List[Message], system: str, cfg: BrainConfig, vault: Any) -> Tuple[str, str]:
        key = vault.api_key(self.name, self.env_key)
        if not key:
            raise RuntimeError(f"{self.name} key missing")
        base = getattr(cfg, self.base_key)
        model = getattr(cfg, self.model_key)
        if cfg.model != "auto":
            model = cfg.model
        payload = {
            "model": model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "stream": False,
        }
        status, body = http_post_json(
            f"{base}/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=cfg.timeout_seconds,
        )
        if status != 200:
            raise RuntimeError(f"{self.name} returned {status}: {truncate(body, 200)}")
        data = json.loads(body)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("no choices in response")
        return choices[0].get("message", {}).get("content", ""), model


class Anthropic(Provider):
    name = "anthropic"
    needs_key = True

    def available(self, cfg: BrainConfig, vault: Any) -> bool:
        if cfg.provider not in {"auto", "anthropic"}:
            return False
        from .vault import get_vault

        return bool(get_vault().api_key("anthropic", cfg.api_key_env["anthropic"]))

    def call(self, messages: List[Message], system: str, cfg: BrainConfig, vault: Any) -> Tuple[str, str]:
        key = vault.api_key("anthropic", cfg.api_key_env["anthropic"])
        if not key:
            raise RuntimeError("anthropic key missing")
        model = cfg.anthropic_model if cfg.model == "auto" else cfg.model
        system_block = system or "You are Olmavax Agent, a precise and loyal personal assistant."
        status, body = http_post_json(
            f"{cfg.anthropic_base}/messages",
            {
                "model": model,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "system": system_block,
                "messages": messages,
            },
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            timeout=cfg.timeout_seconds,
        )
        if status != 200:
            raise RuntimeError(f"anthropic returned {status}: {truncate(body, 200)}")
        data = json.loads(body)
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text, model


class Gemini(Provider):
    name = "gemini"
    needs_key = True

    def available(self, cfg: BrainConfig, vault: Any) -> bool:
        if cfg.provider not in {"auto", "gemini"}:
            return False
        return bool(vault.api_key("gemini", cfg.api_key_env["gemini"]))

    def call(self, messages: List[Message], system: str, cfg: BrainConfig, vault: Any) -> Tuple[str, str]:
        key = vault.api_key("gemini", cfg.api_key_env["gemini"])
        if not key:
            raise RuntimeError("gemini key missing")
        model = cfg.gemini_model if cfg.model == "auto" else cfg.model
        url = f"{cfg.gemini_base}/{model}:generateContent?key={key}"

        contents = []
        for message in messages:
            role = "model" if message["role"] == "assistant" else "user"
            contents.append(
                {"role": role, "parts": [{"text": message["content"]}]}
            )
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": cfg.temperature,
                "maxOutputTokens": cfg.max_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        status, body = http_post_json(url, payload, timeout=cfg.timeout_seconds)
        if status != 200:
            raise RuntimeError(f"gemini returned {status}: {truncate(body, 200)}")
        data = json.loads(body)
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("no candidates in response")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts), model


# --------------------------------------------------------------------------
# Offline reasoner
# --------------------------------------------------------------------------


class OfflineReasoner:
    """
    Hold a conversation with no language model at all.

    This is not a language model and does not pretend to be one. It is a
    dialogue manager: it keeps track of what you are talking about, resolves
    follow-up questions ("why?", "and?", "tell me more"), answers the
    everyday conversational moves, and pulls real facts from memory and the
    web. When it genuinely does not know, it says so in plain words rather
    than producing confident nonsense.
    """

    def __init__(self) -> None:
        self.uses = 0
        self.topic: str = ""
        self.last_answer: str = ""
        self.turns = 0

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _is_followup(text: str) -> bool:
        probe = text.strip().lower().rstrip("?")
        if probe in {
            "why", "and", "aur", "kyu", "kyun", "how so", "explain",
            "more", "tell me more", "aur batao", "phir", "then", "ok",
            "so what", "matlab", "meaning", "iska matlab", "samjha",
            "aur kya", "what else", "anything else", "continue",
            "haan", "yes", "nahi", "no", "sure", "thanks",
            "aur bata", "phir batao", "suno", "aur suno", "elaborate",
            "detail me", "in detail", "explain more", "why though",
        }:
            return True
        # "tell me more about it" and friends - short, and anchored on the
        # last topic rather than naming a new one.
        return bool(re.match(
            r"^(tell me (more|about)|more about|what about|and about|"
            r"aur |phir |details? (about|on))\S*\s*(about (it|that|this))?$",
            probe,
        ))

    @staticmethod
    def _subject(text: str) -> str:
        """Best guess at what the user is talking about."""
        cleaned = re.sub(
            r"^(tell me about|what is|what's|who is|who's|explain|"
            r"batao|kya hai|kaun hai|samjhao|kyu|kyun|why is|what are)\s+",
            "",
            text.strip(),
            flags=re.I,
        )
        cleaned = re.sub(r"[?.!]+\s*$", "", cleaned)
        return cleaned.strip()

    # -- main ----------------------------------------------------------
    def reason(self, question: str, memories: List[Any], tools_hint: str = "") -> LLMReply:
        from .memory import get_memory
        from .tools import web_tools

        self.uses += 1
        self.turns += 1
        store = get_memory()
        # Only the first line is the question. The brain appends a
        # "(romanised: ...)" hint for a hosted model, and letting that reach
        # follow-up detection made "aur batao" fail to match and poisoned
        # the topic with the translation.
        probe = question.strip().splitlines()[0].strip() if question.strip() else ""
        lowered = probe.lower()

        # --- an attached file is the most concrete thing in the message --
        # Handle it before anything else: if the user pasted a file, that
        # file is the subject, not the words they typed around it.
        attached = self._attachments(question)
        if attached:
            self.topic = self.topic or attached.splitlines()[0][:60]
            self.last_answer = attached
            return LLMReply(attached, "offline-reasoner", "dialogue-v3", offline=True)

        # --- conversational openers and everyday moves ----------------
        opener = self._conversational(lowered, probe)
        if opener:
            self.topic = self.topic or ""
            self.last_answer = opener
            return LLMReply(opener, "offline-reasoner", "dialogue-v2", offline=True)

        # --- follow-up handling ----------------------------------------
        if self._is_followup(probe) and self.topic:
            # "aur batao", "tell me more about it" - the same move with words.
            answer = self._followup(self.topic)
            self.last_answer = answer
            return LLMReply(answer, "offline-reasoner", "dialogue-v2", offline=True)

        # --- what we know, before searching ---------------------------
        subject = self._subject(probe)
        if subject and len(subject) > 2:
            self.topic = subject

        computed = self._compute(probe)
        if computed:
            self.last_answer = computed
            return LLMReply(computed, "offline-reasoner", "dialogue-v2", offline=True)

        # --- a lesson the agent taught itself --------------------------
        lesson = store.find_lesson(probe)
        if lesson and lesson.confidence >= 0.35:
            answer = (
                f"From what I have learned before: {lesson.rule}"
                f"\n\n(That rule is {lesson.confidence:.0%} trusted, learned from my own runs.)"
            )
            self.last_answer = answer
            return LLMReply(answer, "offline-reasoner", "dialogue-v2", offline=True)

        # --- memory ---------------------------------------------------
        strong = [r for r in memories if r.score > 0.28][:4]
        if strong:
            lines = "\n".join(f"- {truncate(r.memory.text, 200)}" for r in strong)
            about = subject if subject else "that"
            answer = (
                f"About {about}, here is what I already know:\n{lines}"
                f"\n\nWant me to look it up online for a fuller answer?"
            )
            self.last_answer = answer
            return LLMReply(answer, "offline-reasoner", "dialogue-v2", offline=True)

        # --- the internet ----------------------------------------------
        if net_available():
            looked_up = self._research(subject or probe)
            if looked_up:
                self.last_answer = looked_up
                return LLMReply(looked_up, "offline-reasoner", "dialogue-v2", offline=True)

        # --- honest fallback -------------------------------------------
        answer = self._honest(probe, subject, len(memories))
        self.last_answer = answer
        return LLMReply(answer, "offline-reasoner", "dialogue-v2", offline=True)

    # ------------------------------------------------------------------
    @staticmethod
    def _attachments(text: str) -> str:
        """
        Answer from the file the user attached.

        The web client uploads the file, runs file.analyze on it, and
        appends the findings as an ``[attached files]`` block. Reading
        that back is the difference between "here is what is in your
        file" and an irrelevant search for the words around it.
        """
        marker = "[attached files]"
        if marker not in text:
            return ""

        head, _, block = text.partition(marker)
        question = head.strip().rstrip("?.!").strip() or "this file"
        lines = [
            ln.strip().lstrip("-").strip()
            for ln in block.strip().splitlines()
            if ln.strip()
        ]
        # The brain appends a "(romanised: ...)" hint to the prompt for a
        # hosted model. It sits inside the block and would otherwise be
        # reported as a second attached file that does not exist.
        lines = [ln for ln in lines if ln and not ln.startswith("(")]
        if not lines:
            return ""

        described = "\n".join(f"- {ln}" for ln in lines)
        detail = ", ".join(lines)
        one = len(lines) == 1
        return (
            f"You attached {len(lines)} file{'' if one else 's'} "
            f"and I read {'it' if one else 'them'}.\n\n{described}\n\n"
            f"From the file itself, about '{question}': "
            f"{truncate(detail, 400)}\n\n"
            "I can go deeper - summarise it, check the numbers, or look up "
            "context online. Which would help?"
        )

    # ------------------------------------------------------------------
    def _conversational(self, lowered: str, original: str) -> str:
        from .config import get_config
        from .memory import get_memory

        cfg = get_config()
        store = get_memory()
        name = store.get_pref("owner_name", cfg.owner)
        stats = store.stats()

        if re.search(r"\b(how are you|kaisa ho|kya haal)\b", lowered):
            return (
                f"I am good, {name}. Running on your machine, nothing sent anywhere.\n"
                f"I know {stats['active_memories']} things, have learned "
                f"{stats['counts'].get('lessons', 0)} rules from my own mistakes, "
                f"and handled {stats['episodes']['total']} tasks "
                f"({stats['episodes']['success_rate']:.0%} success). "
                "What are we doing?"
            )
        if re.search(r"\b(joke|mazak|hasin|funny)\b", lowered):
            return self._joke()
        if re.search(r"\b(thank|shukriya|dhanyavad)\b", lowered):
            return f"Any time, {name}. Ask me for the next thing."
        if re.search(r"\b(are you (a )?(real|alive|human)|conscious|live ho)\b", lowered):
            return (
                "Honest answer: no. I am a program running on your machine.\n"
                "What I do have is real memory, real learning from my own mistakes, and "
                "the ability to act on your computer. Whether that counts as "
                "\"intelligence\" is a fair question - you decide."
            )
        if re.search(r"\b(what.*(know|remember) about me|mera baare)\b", lowered):
            pinned = store.all_pinned()
            recent = store.recent(limit=5)
            lines = [f"- {truncate(m.text, 120)}" for m in (pinned or recent)]
            if not lines:
                return (
                    f"I know almost nothing about you yet, {name}. "
                    "Tell me something - I will remember it for good."
                )
            return f"Here is what I have about you:\n" + "\n".join(lines)
        if re.search(r"\b(are you (sure|honest)|can you (really|actually))\b", lowered):
            return (
                "I only say what I can back up. If I am guessing I will say so, "
                "and if I do not know I will say that too. That is the rule I run on."
            )
        return ""

    def _followup(self, topic: str) -> str:
        from .tools import web_tools

        detail = self._research(topic)
        if detail:
            return detail
        return (
            f"I can go deeper on '{topic}', but I need either my memory or the web "
            "for it, and neither had anything this time.\n"
            "Ask me a more specific question and I will try again."
        )

    def _research(self, subject: str) -> str:
        """Try to actually find an answer, then explain it properly."""
        from .tools import web_tools

        if not subject:
            return ""
        found = web_tools.web_search(subject, limit=4)
        results = found.get("results") or []
        if not results:
            return ""
        summary = web_tools.wikipedia(subject)
        if summary.get("ok") and summary.get("summary"):
            links = "\n".join(f"- {r['title']} - {r['url']}" for r in results[:3])
            return (
                f"{summary['summary']}\n\n"
                f"More: {links}"
            )
        links = "\n".join(f"- {r['title']} ({r['domain']})\n  {r['url']}" for r in results[:4])
        return (
            f"I could not find a clean summary of '{subject}', but here is where to look:\n"
            f"{links}"
        )

    def _honest(self, probe: str, subject: str, memory_count: int) -> str:
        from .config import get_config

        cfg = get_config()
        return (
            f"I do not know about '{subject or probe}' and I will not invent an answer.\n\n"
            "Right now I am running without a language model, so I can only use my own "
            f"memory ({memory_count} things stored), my tools, and the internet.\n"
            "For real conversation, connect a free local model:\n"
            "    ollama serve\n"
            "    ollama pull llama3.1:8b\n"
            f"Then run 'olmavax_agent doctor' - it will confirm. Current provider: {cfg.brain.provider}."
        )

    def _joke(self) -> str:
        return (
            "I tried to write a joke about recursion, but I got stuck trying to "
            "explain it.\n\nActually, here: I store 300 jokes in my memory and I "
            "still tell the same three."
        )

    @staticmethod
    def _compute(question: str) -> str:
        """
        Arithmetic and conversions, done locally.

        Spoken maths uses words ("twenty five times four"), not symbols, so
        the operator words are mapped before parsing - otherwise the most
        common kind of question a person asks goes straight to the web.
        """
        words = {
            "plus": "+", "add": "+", "added to": "+", "and": "+",
            "minus": "-", "subtract": "-", "less": "-", "take away": "-",
            "times": "*", "multiplied by": "*", "multiply": "*", "x": "*",
            "into": "*",
            "divided by": "/", "divide": "/", "over": "/", "by": "/",
        }
        cleaned = question.lower()
        for word, symbol in words.items():
            cleaned = re.sub(rf"\b{re.escape(word)}\b", f" {symbol} ", cleaned)

        expression = re.search(
            r"(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)"
            r"(?:\s*([+\-*/])\s*(-?\d+(?:\.\d+)?))*",
            cleaned,
        )
        if expression:
            left = float(expression.group(1))
            operator = expression.group(2)
            right = float(expression.group(3))
            extra_op, extra_val = expression.group(4), expression.group(5)

            def apply(a: float, op: str, b: float) -> float:
                if op == "+":
                    return a + b
                if op == "-":
                    return a - b
                if op == "*":
                    return a * b
                return a / b if b else float("inf")

            try:
                result = apply(left, operator, right)
                shown = f"{left:g} {operator} {right:g} = **{result:g}**"
                if extra_op and extra_val:
                    result = apply(result, extra_op, float(extra_val))
                    shown += f"\n  then {extra_op} {float(extra_val):g} = **{result:g}**"
                return shown
            except (ZeroDivisionError, ValueError, OverflowError):
                return ""

        conversions = {
            ("celsius", "fahrenheit"): lambda v: v * 9 / 5 + 32,
            ("fahrenheit", "celsius"): lambda v: (v - 32) * 5 / 9,
            ("km", "miles"): lambda v: v * 0.621371,
            ("miles", "km"): lambda v: v / 0.621371,
            ("kg", "pounds"): lambda v: v * 2.20462,
            ("pounds", "kg"): lambda v: v / 2.20462,
            ("meters", "feet"): lambda v: v * 3.28084,
            ("feet", "meters"): lambda v: v / 3.28084,
        }
        lowered = question.lower()
        for (src, dst), function in conversions.items():
            if src in lowered and dst in lowered:
                match = re.search(r"(-?\d+(?:\.\d+)?)", question)
                if match:
                    value = float(match.group(1))
                    return f"{value:g} {src} = **{function(value):.4g} {dst}**"

        # Percentages, since "kitna percent" comes up constantly.
        percent = re.search(
            r"(-?\d+(?:\.\d+)?)\s*(?:is\s+)?what\s+(?:percent|percentage)|"
            r"what\s+(?:percent|percentage)\s+(?:is|of)\s+(-?\d+(?:\.\d+)?)",
            lowered,
        )
        if percent:
            value = float(percent.group(1) or percent.group(2))
            return (
                f"Short answer: I would need the other number to compute that - "
                f"{value:g} is the percentage, not the total."
            )
        return ""


# --------------------------------------------------------------------------
# Facade
# --------------------------------------------------------------------------


class BrainLLM:
    """What the rest of the agent talks to."""

    def __init__(self, config: Optional[BrainConfig] = None):
        self.cfg = config or get_config().brain
        self._lock = threading.RLock()
        self._provider: Optional[Provider] = None
        self._model = "none"
        self.offline = OfflineReasoner()
        self.calls = 0
        self.failures = 0
        self.providers = self._build_providers()

    def _build_providers(self) -> List[Provider]:
        return [
            Ollama(),
            OpenAICompatible("groq", "groq_base", "groq_model",
                             "OLMAVAX_AGENT_GROQ_KEY", "llama-3.3-70b-versatile"),
            OpenAICompatible("together", "together_base", "together_model",
                             "OLMAVAX_AGENT_TOGETHER_KEY", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
            OpenAICompatible("openai", "openai_base", "openai_model",
                             "OLMAVAX_AGENT_OPENAI_KEY", "gpt-4o-mini"),
            Gemini(),
            Anthropic(),
        ]

    # -- availability ---------------------------------------------------
    def detect(self, force: bool = False) -> Optional[Provider]:
        """Find a working provider. Cached until ``force``."""
        with self._lock:
            if self._provider is not None and not force:
                return self._provider
            from .vault import get_vault

            vault = get_vault()
            if self.cfg.provider == "offline":
                self._provider = None
                self._model = "offline"
                return None
            for provider in self.providers:
                try:
                    if provider.available(self.cfg, vault):
                        self._provider = provider
                        self._model = self._model_name(provider)
                        log_info(f"language model: {provider.name} / {self._model}", "llm")
                        return provider
                except Exception as exc:  # a broken probe must not be fatal
                    log_warn(f"provider {provider.name} probe failed: {exc}", "llm")
            self._provider = None
            self._model = "offline"
            return None

    def _model_name(self, provider: Provider) -> str:
        if isinstance(provider, OpenAICompatible):
            value = getattr(self.cfg, provider.model_key)
        elif isinstance(provider, Ollama):
            value = self.cfg.ollama_model
        elif provider.name == "gemini":
            value = self.cfg.gemini_model
        elif provider.name == "anthropic":
            value = self.cfg.anthropic_model
        else:
            value = "unknown"
        return self.cfg.model if self.cfg.model != "auto" else value

    @property
    def provider_name(self) -> str:
        return self.detect().name if self.detect() else "offline"

    @property
    def model_name(self) -> str:
        self.detect()
        return self._model

    # -- generation -----------------------------------------------------
    def complete(
        self,
        prompt: str,
        system: str = "",
        history: Optional[List[Message]] = None,
        memories: Optional[List[Any]] = None,
    ) -> LLMReply:
        """Answer a single turn. Falls back to the offline reasoner."""
        import time

        provider = self.detect()
        if provider is None:
            return self.offline.reason(prompt, memories or [])

        messages: List[Message] = list(history or [])
        messages.append({"role": "user", "content": prompt})

        started = time.perf_counter()
        last_error = ""
        for attempt in range(max(1, self.cfg.max_retries + 1)):
            try:
                text, model = provider.call(messages, system, self.cfg, _vault())
                self.calls += 1
                if text.strip():
                    return LLMReply(
                        text.strip(), provider.name, model, time.perf_counter() - started
                    )
                last_error = "empty response"
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.cfg.max_retries:
                    continue
        self.failures += 1
        log_warn(f"LLM call failed ({last_error}); using offline reasoner", "llm")
        reply = self.offline.reason(prompt, memories or [])
        reply.error = last_error
        return reply

    def ask_with_tools(
        self,
        goal: str,
        tools_manifest: str,
        history: Optional[List[Message]] = None,
        memories: Optional[List[Any]] = None,
    ) -> LLMReply:
        """Answer with the tool list in the system prompt, for planning help."""
        from .tools import manifest

        listing = tools_manifest or manifest()
        system = (
            "You are the reasoning core of Olmavax Agent, a personal AI agent that runs on the "
            "owner's own machine. You are precise, brief and honest. If you do not know "
            "something, say so plainly instead of guessing.\n\n"
            "You can call these tools:\n" + listing
        )
        return self.complete(goal, system=system, history=history, memories=memories)

    # -- diagnostics ----------------------------------------------------
    def status(self) -> Dict[str, Any]:
        provider = self.detect()
        online = net_available()
        keys = {
            name: bool(_vault().api_key(name, env))
            for name, env in self.cfg.api_key_env.items()
        }
        return {
            "provider": provider.name if provider else "offline",
            "model": self._model,
            "configured_provider": self.cfg.provider,
            "temperature": self.cfg.temperature,
            "api_keys_present": keys,
            "internet": online,
            "calls": self.calls,
            "failures": self.failures,
            "offline_fallback_uses": self.offline.uses,
            "note": "offline mode answers from memory and local calculation only",
        }

    def doctor(self) -> List[str]:
        """Actionable instructions for getting a model connected."""
        status = self.status()
        if status["provider"] != "offline":
            return [f"Connected: {status['provider']} / {status['model']}"]
        lines = ["No language model connected. Any one of these fixes it:", ""]
        lines.append("Option 1 - free and fully offline (recommended):")
        lines.append("  1. install Ollama from https://ollama.com/download")
        lines.append("  2. run:  ollama serve")
        lines.append("  3. run:  ollama pull llama3.1:8b")
        lines.append("")
        lines.append("Option 2 - cloud API key (any one):")
        for name, env_var in self.cfg.api_key_env.items():
            lines.append(f"  set {env_var}=... for {name}")
        lines.append("")
        lines.append("Option 3 - do nothing: the agent still works offline using its own")
        lines.append("  memory, skills, tools and calculations.")
        return lines


def _vault():
    from .vault import get_vault

    return get_vault()


_LLM: Optional[BrainLLM] = None
_LLM_LOCK = threading.Lock()


def get_llm(config: Optional[BrainConfig] = None) -> BrainLLM:
    global _LLM
    if _LLM is None:
        with _LLM_LOCK:
            if _LLM is None:
                _LLM = BrainLLM(config=config)
    return _LLM