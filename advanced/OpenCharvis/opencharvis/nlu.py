"""
Open Charvis - Natural language understanding
=============================================
Turns whatever the owner says (typed or spoken) into a structured intent
the brain can act on.

Design notes:

* **Rule first.** Every intent has an explicit pattern, so the agent stays
  responsive and predictable even with no language model connected.
* **Hindi aware.** Devanagari and Roman Hinglish are both understood -
  ``"band karo"``, ``"याद रखो"`` and ``"remember this"`` reach the same code.
* **Honest about confidence.** An unmatched sentence becomes
  ``intent="chat"`` with low confidence and is handed to the language model
  rather than being force-matched into something destructive.
* **Exit is first class.** ``bus`` / ``exit`` / ``band karo`` / ``बंद करो``
  all resolve to ``intent="shutdown"``, which is what closes the agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .utils import hinglish_to_english, hindi_number, normalize_text, strip_accents, token_set

# --------------------------------------------------------------------------
# Intent record
# --------------------------------------------------------------------------


@dataclass
class Intent:
    name: str
    slots: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw: str = ""
    normalised: str = ""
    matched_pattern: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.name,
            "slots": self.slots,
            "confidence": round(self.confidence, 3),
            "raw": self.raw,
        }


# --------------------------------------------------------------------------
# Shutdown vocabulary - checked before anything else, every time
# --------------------------------------------------------------------------

EXIT_WORDS = (
    "exit", "quit", "bye", "goodbye", "close", "stop", "shutdown", "shut down",
    "sign off", "power down", "band karo", "band kar", "band kardo", "ruk jao",
    "chalo", "jao", "exit karo", "close app",
)

EXIT_DEVANAGRI = ("बंद", "बन्द", "बंद करो", "रुको", "बाहर")

WAKE_WORDS = ("charvis", "jarvis", "hey charvis", "ok charvis", "open charvis")

# --------------------------------------------------------------------------
# Pattern table
# --------------------------------------------------------------------------

# (intent, compiled pattern, slot extractor name, confidence)
Pattern = Tuple[str, "re.Pattern", str, float]


def _c(pattern: str) -> "re.Pattern":
    return re.compile(pattern, re.I)


PATTERNS: List[Pattern] = [
    # -- lifecycle -------------------------------------------------------
    ("shutdown", _c(r"^\s*(exit|quit|bye|goodbye|close|band karo|band kar|chalo)\s*[.!]?\s*$"), "_none", 0.99),
    ("shutdown", _c(r"\b(exit|quit|shut\s*down|band)\s*(kar\s*do|kar|kardo|this app|yourself)\b"), "_none", 0.95),
    ("shutdown", _c(r"\b(band|exit|quit)\b\s*$"), "_none", 0.9),
    ("help", _c(r"\b(help|what can you do|kya kar sakte|sahiyana|kaise istemal)\b"), "_none", 0.9),
    ("thanks", _c(r"\b(thanks|thank you|shukriya|dhanyavad|thanks a lot)\b"), "_none", 0.92),
    ("greeting", _c(r"^\s*(hi|hello|hey|namaste|hola|good (morning|evening|afternoon)|kaise ho)\b"), "_none", 0.9),
    ("identity", _c(r"\b(who are you|what are you|your name|introduce yourself|tum kaun ho|apna naam)\b"), "_none", 0.92),
    ("status", _c(r"\b(status|kaisa (haal|ho)|system status|diagnostics|health check)\b"), "_none", 0.8),

    # -- security --------------------------------------------------------
    ("security_status", _c(r"\b(security|secur|suraksha|protection)\b.*\b(status|report|check|level|kya)\b"), "_none", 0.88),
    ("security_scan", _c(r"\b(security|machine|system)\b.*\b(scan|check|audit)\b"
                         r"|\b(scan|check|audit)\b.*\b(security|machine|system|files)\b"),
     "_none", 0.92),
    ("security_posture", _c(r"\b(posture|security level|raksha level|more careful|strict mode)\b"), "_posture", 0.85),
    ("secret_set", _c(r"\b(store|save|remember)\b.*\b(password|api key|secret|token|credential)\b"), "_secret_value", 0.9),
    ("secret_list", _c(r"\b(list|show|what)\b.*\b(passwords|api keys|secrets|credentials)\b"), "_none", 0.88),

    # -- memory ----------------------------------------------------------
    # 'remember' must be the leading verb, otherwise "what do you remember"
    # would be parsed as an instruction to store something.
    ("memory_remember",
     _c(r"^\s*(?:please\s+|aur\s+|hey\s+)?(?:remember|note\s+down|yaad\s+rakh\w*|yaad\s+kar\w*"
        r"|don'?t\s+forget|keep\s+in\s+mind)\b"), "_remember", 0.93),
    ("memory_recall", _c(r"\b(what\s+do\s+you\s+(remember|know)|do\s+you\s+remember|recall|"
                         r"kya\s+yaad|kya\s+pata|what'?s\s+in\s+your\s+memory)\b"), "_recall_query", 0.97),
    ("memory_forget", _c(r"\b(forget|delete|remove|bhool|mita)\b.*\b(memory|remember|yaad)\b"), "_forget", 0.9),
    ("memory_list", _c(r"\b(list|show|dikh)\b.*\b(memories|memory|yaad)\b"), "_none", 0.82),
    ("lesson_teach", _c(r"\b(from now on|always|never|remember to|lesson|rule)\b.*\b\w+"), "_lesson", 0.78),

    # -- system ----------------------------------------------------------
    ("time_now", _c(r"^\s*(time|ghadi)\b"
                    r"|\bwhat\s+time\s+is\b"
                    r"|\bwhat'?s\s+(the\s+)?(time|clock)\b"
                    r"|\b(time|clock)\b.*\b(current|now|kya|kitna|batao)\b"
                    r"|\bkitna\s+time\b"), "_none", 0.93),
    ("date_today", _c(r"\b(date|today|aaj|kaun\s+sa\s+din)\b"), "_none", 0.92),
    ("system_info", _c(r"\b(system info|pc info|computer|hardware|battery|ram|cpu|specs)\b"), "_none", 0.8),
    ("open_app", _c(r"\b(open|launch|start|run|kholo|chalao)\b\s+(.+)$"), "_target", 0.85),
    ("search_files", _c(r"\b(find|search|locate|dhundo|dhoondo)\b.*\b(file|folder|document)\b"), "_query", 0.85),
    ("read_file", _c(r"\b(read|open|show|dikh|padho)\b.*\bfile\b\s*(.+)$"), "_path", 0.82),
    ("volume_set", _c(r"\b(volume|sound|awaaz)\b.*\b(set|to)\b\s*(\d{1,3})"), "_percent", 0.92),
    ("volume_up", _c(r"\b(volume|sound|awaaz)\b.*\b(up|badhao|increase|zyada)\b"), "_none", 0.9),
    ("volume_down", _c(r"\b(volume|sound|awaaz)\b.*\b(down|kam|lower|reduce)\b"), "_none", 0.9),
    ("mute", _c(r"\b(mute|silent|chup|awaaz band)\b"), "_none", 0.9),
    ("screenshot", _c(r"\b(screenshot|screen shot|photo|khud ka|ss)\b.*\b(take|lelo|click|of screen)\b|\bscreenshot\b"), "_none", 0.88),
    ("clipboard_read", _c(r"\b(clipboard|copy)\b.*\b(what|read|kya|show)\b"), "_none", 0.88),
    ("clipboard_write", _c(r"\b(copy|put)\b\s+(.+?)\s*(to|on|into)?\s*(the )?clipboard"), "_clipboard", 0.85),
    ("notify", _c(r"\b(notify|notification|remind)\b"), "_notify", 0.85),
    ("lock", _c(r"\b(lock|safai)\b.*\b(computer|screen|pc)\b"), "_none", 0.85),

    # -- power (dangerous - confidence kept but security engine gates) ----
    ("power_sleep", _c(r"\b(sleep|so jao|hibernate)\b"), "_none", 0.85),
    ("power_shutdown", _c(r"\b(shut\s*down|band kar do system|power off)\b"), "_none", 0.9),
    ("power_restart", _c(r"\b(restart|reboot|dobara chalu)\b"), "_none", 0.9),

    # -- knowledge / internet -------------------------------------------
    ("web_search", _c(r"\b(search|google|look up|find online|dhoondo|google karo)\b\s+(.+)$"), "_query", 0.85),
    ("learn_topic", _c(r"\b(learn|teach me|padhao|sikho|study)\b.*\b(about|on|topic)\b\s+(.+)$"), "_topic", 0.92),
    ("youtube_learn", _c(r"\b(youtube|video)\b.*\b(learn|watch|seekho|dekho|summar)\b"), "_url", 0.88),
    ("wiki", _c(r"\b(wikipedia|wiki)\b.*\b(about|on)?\s*(.+)$"), "_topic", 0.88),
    ("fetch_url", _c(r"\b(read|open|fetch|summarise|summarize)\b\s+(https?://\S+)"), "_url", 0.9),

    # -- media -----------------------------------------------------------
    ("image_generate", _c(r"\b(draw|paint|create|generate|make|design|render|banao|banai|bana)\b.*"
                         r"\b(image|picture|art|photo|drawing|painting|poster|wallpaper|artwork)\b"),
     "_prompt", 0.92),
    ("animate", _c(r"\b(animate|animation|movie|video banai|clip)\b"), "_prompt", 0.88),
    ("media_gallery", _c(r"\b(gallery|media|images)\b.*\b(list|show|dikh)\b"), "_none", 0.85),

    # -- code ------------------------------------------------------------
    ("code_run", _c(r"\b(run|execute|compile|chalao|chala)\b.*\b(python|javascript|java|typescript|"
                        r"c\s+code|code|program|script|function|snippet|this)\b"), "_code", 0.90),
    ("code_languages", _c(r"\b(what|which)\b.*\b(languages?|programming)\b.*\b(can|support)\b"), "_none", 0.9),
    ("code_inspect", _c(r"\b(explain|understand|review|describe)\b.*\b(code|program|script|function)\b"), "_code", 0.82),
    ("test_run", _c(r"\b(run|execute)\b.*\btests?\b"), "_none", 0.88),
    ("scaffold", _c(r"\b(create|make|start|scaffold)\b.*\b(new )?project\b"), "_project", 0.85),

    # -- notes -----------------------------------------------------------
    ("note_write", _c(r"\b(write|note|l likho)\b.*\bnote\b"), "_text", 0.82),
    ("note_search", _c(r"\b(find|search)\b.*\b(in my )?notes?\b"), "_query", 0.85),

    # -- vault / settings -------------------------------------------------
    ("settings", _c(r"\b(setting|config|option)\b.*\b(change|show|list)\b"), "_none", 0.78),
    ("capabilities", _c(r"\bcapabilit|\bwhat\s+can\s+you|\bkya\s+kar\s+sakte|\bfeatures\b|"
                         r"\bwhat\s+tools\b"), "_none", 0.88),
]


# --------------------------------------------------------------------------
# Slot extractors
# --------------------------------------------------------------------------


def _strip_command_words(text: str) -> str:
    text = re.sub(
        r"^\s*(please|pls|jarvis|charvis|hey charvis|ok charvis|bhai|yaar)\b[:,]?\s*",
        "",
        text,
        flags=re.I,
    )
    return text.strip()


def _clean_target(text: Optional[str]) -> str:
    """Strip filler words from a spoken target."""
    if not text:
        return ""
    text = re.sub(r"\b(for me|on my|please|pls|now|abhi)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .,:;?!\"'")
    return text


def _extract_prompt(text: str) -> str:
    """
    Pull the creative description out of "draw an image of a blue dragon".

    Strips the verb, the medium noun and filler so the renderer is seeded
    with the actual subject rather than the word "image".
    """
    probe = re.sub(
        r"^\s*(?:please\s+)?(?:draw|paint|create|generate|make|design|banao|banai|bana|render)\b",
        "",
        text,
        flags=re.I,
    )
    probe = re.sub(
        r"\b(?:an?|the)?\s*(?:image|picture|art|photo|drawing|painting|artwork|"
        r"illustration|poster|wallpaper|scene|video|animation|animation|clip|movie|film)\b",
        " ",
        probe,
        flags=re.I,
    )
    probe = re.sub(
        r"^\s*(?:of|about|showing|with|that|which|based on)\b", "", probe, flags=re.I
    )
    probe = re.sub(r"\b(?:for me|on my|please|pls|abhi|now)\b", " ", probe, flags=re.I)
    probe = re.sub(r"\s+", " ", probe).strip(" .,:;?!\"'")
    return probe or _clean_target(text)


def _first_number(text: str) -> Optional[int]:
    match = re.search(r"\d{1,3}", text)
    if match:
        return int(match.group())
    return hindi_number(text)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


class NLU:
    """Rule-based intent parser with fuzzy fallback."""

    def __init__(self) -> None:
        self._compiled = PATTERNS
        #: Public view of the pattern table, used by the mind to re-extract
        #: slots when its learned model overrides a weak rule.
        self.patterns = PATTERNS
        self.stats: Dict[str, int] = {}

    # -- wake word ------------------------------------------------------
    @staticmethod
    def strip_wake_word(text: str) -> Tuple[str, bool]:
        """Remove a leading wake word. Returns (text, was_awake)."""
        probe = normalize_text(text)
        woke = False
        for word in sorted(WAKE_WORDS, key=len, reverse=True):
            if probe.startswith(word):
                text = text.strip()[len(word):]
                woke = True
                break
        return _strip_command_words(text), woke

    @staticmethod
    def is_exit(text: str) -> bool:
        """
        Should this shut the agent down?

        Deliberately strict: only a short, unambiguous farewell counts, so
        "exit the loop in this code" never kills the agent.
        """
        probe = normalize_text(strip_accents(text)).strip(" .!?,")
        if not probe or len(probe) > 24:
            return False
        for word in EXIT_WORDS:
            if probe == word:
                return True
        for word in EXIT_DEVANAGRI:
            if word in probe and len(probe) <= 12:
                return True
        if probe in {"bye bye", "ok bye", "good bye", "see you", "see ya"}:
            return True
        return False

    # -- parsing --------------------------------------------------------
    def parse(self, text: str) -> Intent:
        raw = (text or "").strip()
        if not raw:
            return Intent("chat", {}, 0.0, raw)

        cleaned, _woke = self.strip_wake_word(raw)
        probe = normalize_text(cleaned)
        probe = re.sub(r"\s+", " ", probe).strip()

        # Exit beats everything, including an LLM in the loop.
        if self.is_exit(cleaned):
            return Intent("shutdown", {}, 0.99, raw, probe, "exit")

        best: Optional[Intent] = None
        best_name: Optional[str] = None
        best_extractor = "_none"
        best_match: Any = None
        best_confidence = 0.0
        best_pattern = ""

        for name, pattern, extractor, confidence in self._compiled:
            match = pattern.search(cleaned)
            if not match:
                continue
            if best_name is None or confidence > best_confidence:
                best_name, best_extractor = name, extractor
                best_match, best_confidence, best_pattern = match, confidence, pattern.pattern
            if confidence >= 0.95:
                break

        if best_name is not None:
            # Slots are extracted once, for the winner only.  Doing it
            # inside the loop would let a losing candidate's extraction
            # error abort an otherwise correct parse.
            best = Intent(
                name=best_name,
                slots=self._slots(best_extractor, cleaned, best_match),
                confidence=best_confidence,
                raw=raw,
                normalised=probe,
                matched_pattern=best_pattern,
            )

        if best is not None:
            self.stats[best.name] = self.stats.get(best.name, 0) + 1
            return best

        # Nothing matched: general conversation, plus a Hinglish translation
        # attached so the model and the search tools understand it.
        slots: Dict[str, Any] = {"text": cleaned}
        translated = hinglish_to_english(cleaned)
        if translated.lower() != probe.lower():
            slots["hinglish"] = translated
        return Intent("chat", slots, 0.25, raw, probe, "fallback")

    def _slots(self, extractor: str, text: str, match: "re.Match") -> Dict[str, Any]:
        groups = match.groups()
        value = groups[-1] if groups else ""

        if extractor == "_none":
            return {}
        if extractor == "_target":
            return {"target": _clean_target(value)}
        if extractor == "_path":
            return {"path": _clean_target(value)}
        if extractor == "_query":
            query = _clean_target(value)
            return {"query": query or text, "hinglish": hinglish_to_english(query or text)}
        if extractor == "_recall_query":
            # "what do you remember about X" -> "X", never the verb itself.
            tail = re.split(
                r"\b(?:about|on|regarding|concerning|of|for)\b", text, maxsplit=1, flags=re.I
            )
            query = _clean_target(tail[1]) if len(tail) > 1 else ""
            if not query or len(query) < 2:
                query = _clean_target(re.sub(r"[^a-z0-9 ]", " ", text))
            return {"query": query, "hinglish": hinglish_to_english(query)}
        if extractor == "_topic":
            return {"topic": _clean_target(value), "query": _clean_topic(_clean_target(value))}
        if extractor == "_url":
            url = value if str(value).startswith("http") else text
            match_url = re.search(r"https?://\S+", url)
            return {"url": match_url.group() if match_url else text}
        if extractor == "_prompt":
            return {"prompt": _extract_prompt(text)}
        if extractor == "_percent":
            number = _first_number(text)
            return {"percent": max(0, min(100, number or 50))}
        if extractor == "_remember":
            payload = re.sub(
                r"^\s*(please\s*)?(remember|note down|yaad rakh\w*|yaad kar\w*|don't forget|dont forget|keep in mind)\b[:,]?\s*",
                "",
                text,
                flags=re.I,
            ).strip()
            return {"text": payload or text}
        if extractor == "_forget":
            return {"text": _clean_target(value) or text}
        if extractor == "_code":
            fence = re.search(r"```([\w+-]*)\s*\n?(.*?)```", text, re.S)
            if fence:
                return {
                    "code": fence.group(2).strip(),
                    "language": (fence.group(1) or "python").lower(),
                }
            # "run this python: print(1)" / "explain this code: def f(): ..."
            body = text.split(":", 1)[1] if ":" in text else ""
            if not body.strip():
                body = re.sub(
                    r"^\s*(please\s+)?(run|execute|compile|explain|review|describe|understand|"
                    r"chalao|chala)\b.*?\b(python|javascript|java|typescript|code|program|"
                    r"script|function|snippet|this)\b[:\s]*",
                    "",
                    text,
                    flags=re.I,
                )
            language = "python"
            for name, keyword in (
                ("javascript", r"\b(javascript|js|node)\b"),
                ("typescript", r"\btypescript\b"),
                ("java", r"\bjava\b"),
                ("python", r"\bpython\b"),
            ):
                if re.search(keyword, text, re.I):
                    language = name
                    break
            return {"code": body.strip() or text, "language": language}
        if extractor == "_posture":
            for posture in ("paranoid", "balanced", "sandbox", "open"):
                if posture in text.lower():
                    return {"posture": posture}
            return {}
        if extractor == "_lesson":
            return {"text": _clean_target(text)}
        if extractor == "_secret_value":
            return {"text": text}
        if extractor == "_clipboard":
            return {"text": value}
        if extractor == "_notify":
            return {"message": _clean_target(value) or text}
        if extractor == "_project":
            return {"name": _clean_target(value), "language": "python"}
        if extractor == "_text":
            return {"text": text}
        return {}

    # -- introspection --------------------------------------------------
    def intents(self) -> List[str]:
        return sorted({name for name, *_ in PATTERNS})

    def stats_report(self) -> Dict[str, Any]:
        total = sum(self.stats.values())
        return {
            "total_parsed": total,
            "by_intent": dict(sorted(self.stats.items(), key=lambda kv: kv[1], reverse=True)),
            "known_intents": len(self.intents()),
            "wake_words": list(WAKE_WORDS),
            "exit_words": list(EXIT_WORDS[:6]),
        }


def _clean_topic(text: str) -> str:
    topic = re.sub(r"^(about|on|topic|regarding)\s+", "", text.strip(), flags=re.I)
    return topic or text


_NLU: Optional[NLU] = None


def get_nlu() -> NLU:
    global _NLU
    if _NLU is None:
        _NLU = NLU()
    return _NLU


def parse(text: str) -> Intent:
    return get_nlu().parse(text)