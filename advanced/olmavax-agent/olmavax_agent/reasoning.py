"""
Olmavax Agent - Reasoning
=======================
The part that makes this feel like an assistant rather than a lookup table.

Four things live here, all working with or without a language model:

**Decomposition.**  Turns a goal into ordered steps by recognising which
shape the request has - research, build, debug, decide, analyse - and
running the matching plan. The plan is printed so you can see the working,
not just the answer.

**Solving.**  Walks a problem to a conclusion and then *verifies* that
conclusion. An unverified answer is a guess with better manners.

**Thinking mode.**  When you switch it on, every answer arrives with its
reasoning shown: what it noticed, what it checked, what it ruled out, how
confident it is.

**Coding help.**  Write, fix, explain and refactor code, with the static
analysis from :mod:`tools.dev_tools` feeding the review so the critique is
based on the actual code rather than impressions.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .utils import truncate

# --------------------------------------------------------------------------
# Request shapes
# --------------------------------------------------------------------------

SHAPES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("build", ("build", "make", "create", "design", "develop", "banana", "banao",
               "write a program", "implement", "set up", "setup", "scaffold",
               "launch", "start a", "generate a", "banayiye", "bana do")),
    ("debug", ("bug", "error", "crash", "broken", "not working", "fail", "failing",
               "fix", "repair", "traceback", "exception", "kaam nahi",
               "kaam nahin kar raha", "debug")),
    ("analyse", ("analyse", "analyze", "analysis", "compare", "explain why",
                 "why is", "what causes", "break down", "study", "research",
                 "samjha", "samjhao", "vishleshan")),
    ("decide", ("should i", "which is better", "choose", "pick", "compare",
                "pros and cons", "better to", "decision", "kya karu", "kya karun")),
    ("learn", ("learn", "teach me", "tutorial", "how do i", "how to",
               "steps to", "guide me", "sikhao")),
    ("write", ("write", "draft", "compose", "email", "letter", "essay",
               "blog", "post", "caption", "summary of this", "likho")),
)


@dataclass
class Step:
    """One visible move in the working."""

    title: str
    detail: str = ""
    tool: str = ""
    finding: str = ""
    done: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "tool": self.tool,
            "finding": self.finding,
            "done": self.done,
        }


@dataclass
class Reasoning:
    """A complete, inspectable chain of thought."""

    goal: str
    shape: str
    steps: List[Step] = field(default_factory=list)
    answer: str = ""
    confidence: float = 0.0
    caveats: List[str] = field(default_factory=list)

    def add(self, title: str, detail: str = "", tool: str = "", finding: str = "") -> Step:
        step = Step(title=title, detail=detail, tool=tool, finding=finding, done=True)
        self.steps.append(step)
        return step

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "shape": self.shape,
            "steps": [s.to_dict() for s in self.steps],
            "answer": self.answer,
            "confidence": round(self.confidence, 3),
            "caveats": self.caveats,
        }

    def render(self, verbose: bool = False) -> str:
        """Printable working, for when thinking mode is on."""
        lines = [f"Goal      : {truncate(self.goal, 120)}",
                 f"Shape     : {self.shape}",
                 f"Confidence: {self.confidence:.0%}"]
        if self.steps:
            lines.append("")
            lines.append("How I got there:")
            for index, step in enumerate(self.steps, 1):
                lines.append(f"  {index}. {step.title}")
                if step.detail and (verbose or len(self.steps) < 7):
                    lines.append(f"     {step.detail}")
                if step.finding and verbose:
                    lines.append(f"     -> {truncate(step.finding, 160)}")
        if self.caveats:
            lines.append("")
            lines.append("What I am unsure about:")
            lines.extend(f"  - {c}" for c in self.caveats)
        lines.append("")
        lines.append(self.answer)
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


class Reasoner:
    """
    Plans, executes and verifies.

    Deliberately conservative: confidence is raised only by things that
    actually succeeded, and lowered by anything it had to guess at.
    """

    def __init__(self, memory=None, llm=None):
        self._memory = memory
        self._llm = llm

    @property
    def memory(self):
        if self._memory is None:
            from .memory import get_memory

            self._memory = get_memory()
        return self._memory

    @property
    def llm(self):
        if self._llm is None:
            from .llm import get_llm

            self._llm = get_llm()
        return self._llm

    # ------------------------------------------------------------------
    def classify(self, goal: str) -> str:
        probe = (goal or "").lower()
        best, best_hits = "general", 0
        for shape, markers in SHAPES:
            hits = sum(1 for m in markers if m in probe)
            if hits > best_hits:
                best, best_hits = shape, hits
        return best

    # ------------------------------------------------------------------
    def think(self, goal: str, verbose: bool = False) -> Reasoning:
        """The main entry point: understand, act, verify, answer."""
        shape = self.classify(goal)
        reasoning = Reasoning(goal=goal, shape=shape, confidence=0.35)

        # -- 1. what do I already know about this? --------------------
        recalled = self.memory.search(goal, limit=4)
        if recalled:
            lines = [truncate(r.memory.text, 110) for r in recalled if r.score > 0.25]
            if lines:
                reasoning.add(
                    "Checked my memory",
                    f"{len(lines)} related things I already know",
                    finding="; ".join(lines[:3]),
                )
                reasoning.confidence += 0.12

        # -- 2. has a lesson for this? --------------------------------
        lesson = self.memory.find_lesson(goal)
        if lesson and lesson.confidence >= 0.3:
            reasoning.add("Applied a rule I learned",
                          truncate(lesson.rule, 140), finding=lesson.rule)

        # -- 3. shape-specific working --------------------------------
        handler = getattr(self, f"_{shape}", None)
        if handler:
            handler(goal, reasoning)
        else:
            self._general(goal, reasoning)

        # -- 4. verify before claiming anything ------------------------
        self._verify(goal, reasoning)

        if not reasoning.answer:
            reasoning.answer = (
                "I could not produce a reliable answer for that. "
                "Tell me more, or connect a language model for deeper reasoning."
            )
            reasoning.confidence = min(reasoning.confidence, 0.3)
        return reasoning

    # ------------------------------------------------------------------
    def _general(self, goal: str, r: Reasoning) -> None:
        r.add("Read the request", "no special pattern matched, answering directly")
        reply = self.llm.complete(goal, system=self._system())
        r.answer = reply.text or "I could not answer that."
        r.confidence += 0.25 if not reply.offline else 0.05
        if reply.offline:
            r.caveats.append(
                "answered without a language model, so this is from memory and search only"
            )

    def _build(self, goal: str, r: Reasoning) -> None:
        r.add("Worked out what needs building",
              "breaking the request into parts I can actually do")
        subject = re.sub(r"^(build|make|create|design)\s+(me\s+)?(a|an)?\s*", "", goal, flags=re.I)
        reply = self.llm.complete(
            goal,
            system=self._system() + (
                "\nIf it is code, give one complete runnable code block and say how to run it."
            ),
        )
        r.answer = reply.text or f"I can build: {subject}."
        r.confidence += 0.3 if not reply.offline else 0.05
        r.caveats.append("a design, not something built - say 'scaffold' or 'run this' to execute it")

    def _debug(self, goal: str, r: Reasoning) -> None:
        r.add("Looking for the failure", "parsing the error and the code")
        from .tools import dev_tools

        code_match = re.search(r"```(?:\w+)?\s*(.*?)```", goal, re.S)
        if code_match:
            code = code_match.group(1)
            report = dev_tools.dev_inspect(code)
            if report.get("ok"):
                risks = report.get("risk_points", [])
                r.add("Static analysis",
                      f"{len(report['risk_points'])} risk point(s), "
                      f"complexity {report['branching_complexity']}",
                      tool="dev.inspect",
                      finding="; ".join(f"line {x['line']}: {x['issue']}" for x in risks[:4]))
                if risks:
                    r.caveats.append(
                        "I cannot confirm the fix without the exact error message - "
                        "these are static findings, not the cause"
                    )
            else:
                r.add("Parsed the code", f"syntax error at line {report.get('error')}",
                      tool="dev.inspect")
        r.add("Considered the causes",
              "most common causes: wrong types, off-by-one, unhandled errors, wrong environment")
        reply = self.llm.complete(
            goal,
            system=self._system() + (
                "\nAnswer as a debugger: name the most likely cause, then the exact fix, "
                "then how to confirm it works."
            ),
        )
        r.answer = reply.text or "Share the exact error and I will find the cause."
        r.confidence += 0.25 if not reply.offline else 0.0
        if reply.offline:
            r.caveats.append("no model connected - this is general advice, not a diagnosis")

    def _analyse(self, goal: str, r: Reasoning) -> None:
        r.add("Pulling in what I know", "memory and the open web")
        from .tools import web_tools

        subject = re.sub(r"^(analyse|analyze|explain why|why is|study|research)\s+", "",
                         goal, flags=re.I).strip(" ?.")
        found = web_tools.web_search(subject or goal, limit=4)
        if found.get("results"):
            r.add("Searched the web",
                  f"{len(found['results'])} sources",
                  tool="web.search",
                  finding="; ".join(x["title"][:60] for x in found["results"][:3]))
            r.confidence += 0.1
        reply = self.llm.complete(
            goal,
            system=self._system() + (
                "\nAnswer as an analyst: what the facts are, what they imply, "
                "what is uncertain, and what would settle the uncertainty."
            ),
        )
        r.answer = reply.text or "I could not gather enough to analyse that."
        r.confidence += 0.2 if not reply.offline else 0.05

    def _decide(self, goal: str, r: Reasoning) -> None:
        r.add("Framed the decision", "listing the options and what each costs")
        reply = self.llm.complete(
            goal,
            system=self._system() + (
                "\nAnswer as an advisor: give a recommendation first, then the "
                "trade-offs, then what would change the recommendation."
            ),
        )
        r.answer = reply.text or "Tell me the options and I will weigh them."
        r.caveats.append("I do not know your constraints - this is general reasoning only")
        r.confidence += 0.15 if not reply.offline else 0.0

    def _learn(self, goal: str, r: Reasoning) -> None:
        r.add("Worked out the topic", "then finding real sources")
        from .tools import web_tools

        topic = re.sub(r"^(learn|teach me|sikhao|tutorial)\s+(about\s+)?", "", goal,
                       flags=re.I).strip(" ?.")
        result = web_tools.learn_topic(topic or goal, depth=3)
        if result.get("ok"):
            r.add("Studied the topic",
                  f"{result['pages']} sources, notes stored",
                  tool="web.learn",
                  finding="; ".join(result["sources"][:3]))
            r.confidence += 0.2
            r.answer = (
                f"I studied '{topic}' from {result['pages']} sources and stored the notes.\n\n"
                f"{result['preview'][:1200]}"
            )
        else:
            r.answer = f"I could not study '{topic}': {result.get('error')}"
            r.confidence = 0.2

    def _write(self, goal: str, r: Reasoning) -> None:
        r.add("Planned the draft", "audience, length and tone from your request")
        reply = self.llm.complete(
            goal,
            system=self._system() + "Answer with the finished text first, notes after.",
        )
        r.answer = reply.text or "Tell me the audience and tone and I will draft it."
        r.caveats.append("facts and figures in any draft still need checking")
        r.confidence += 0.2 if not reply.offline else 0.05

    # ------------------------------------------------------------------
    def _verify(self, goal: str, r: Reasoning) -> None:
        """
        Sanity-check the answer before handing it over.

        Not a substitute for the model checking itself, but it catches the
        common failure of confidently producing nothing.
        """
        answer = r.answer or ""
        r.confidence = max(0.05, min(0.97, r.confidence))

        if not answer.strip():
            r.caveats.append("produced no output")
            r.confidence *= 0.4
            return

        if len(answer) < 25:
            r.caveats.append("the answer is very short - there may be little behind it")
            r.confidence *= 0.75

        if re.search(r"\b(i (do not|don't) know|could not find|no model|without a language model)\b",
                     answer, re.I):
            r.caveats.append("this is a limitation notice, not a real answer")
            r.confidence = min(r.confidence, 0.3)

        # Fabricated-citation check: an answer citing a source that was never
        # fetched is the classic hallucination to guard against.
        links = set(re.findall(r"https?://[^\s)]+", answer))
        used = set()
        for step in r.steps:
            used.update(re.findall(r"https?://[^\s;]+", step.finding or ""))
        unsubstantiated = links - used
        if unsubstantiated and len(links) > 0:
            r.caveats.append(
                f"{len(unsubstantiated)} link(s) in the answer were not actually retrieved - "
                "treat them as unverified"
            )
            r.confidence *= 0.85

        r.add("Checked the answer",
              f"length ok, confidence {r.confidence:.0%}",
              finding="; ".join(r.caveats) if r.caveats else "nothing to flag")

    @staticmethod
    def _system() -> str:
        from .config import get_config

        return (
            f"You are {get_config().name}, reasoning carefully. Be concrete, "
            "give the conclusion first, then the reasoning. If you are not sure, "
            "say which part and why."
        )


_REASONER: Optional[Reasoner] = None
_REASONER_LOCK = threading.Lock()


def get_reasoner() -> Reasoner:
    global _REASONER
    if _REASONER is None:
        with _REASONER_LOCK:
            if _REASONER is None:
                _REASONER = Reasoner()
    return _REASONER