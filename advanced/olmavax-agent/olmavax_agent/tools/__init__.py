"""
Olmavax Agent - Tool registry
===========================
Tools are the agent's hands.  A tool is a plain Python function with
metadata attached: what it does, which security capabilities it needs, and
how risky it is.

The registry enforces three things:

* a tool can only use capabilities it declared at definition time
* every call is scored by the security engine before it runs
* every call is recorded in the audit trail and in memory

Registering a tool is one decorator::

    @tool("weather.now", "Current weather for a city", capabilities=["net.fetch"])
    def weather_now(city: str) -> dict: ...
"""

from __future__ import annotations

import inspect
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..events import BUS, Ev
from ..logger import log_debug, log_error
from ..security import ALLOW, ASK, CapabilityDenied, SecurityEngine, get_security
from ..utils import truncate

# Registry of every tool the agent can reach.
TOOLS: Dict[str, "Tool"] = {}

# Set by load_all(). Tracked separately from TOOLS because modules may
# populate the registry partially before the full load runs.
_LOADED = False


@dataclass
class ToolResult:
    """Uniform return shape so the brain can reason about any tool."""

    ok: bool
    output: Any = None
    error: str = ""
    tool: str = ""
    duration: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok

    # Dict-style access so a tool can be called directly from a handler and
    # still be read like the plain dict it usually returns.
    def __getitem__(self, key: str) -> Any:
        if isinstance(self.output, dict):
            return self.output[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if isinstance(self.output, dict):
            return self.output.get(key, default)
        return default

    def keys(self) -> Any:
        return self.output.keys() if isinstance(self.output, dict) else ()

    def unwrap(self) -> Any:
        """The raw value, with the error surfaced if the call failed."""
        if not self.ok:
            raise RuntimeError(self.error or f"{self.tool} failed")
        return self.output

    def summary(self) -> str:
        if self.ok:
            text = self.output if isinstance(self.output, str) else repr(self.output)
            return truncate(text, 400)
        return f"error: {self.error}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "output": self.output,
            "error": self.error,
            "duration": round(self.duration, 4),
            "meta": self.meta,
        }


@dataclass
class Tool:
    name: str
    func: Callable[..., Any]
    description: str
    capabilities: List[str] = field(default_factory=list)
    risk: float = 0.2
    tags: List[str] = field(default_factory=list)
    confirm: bool = False
    guard: Optional[Callable[..., Any]] = None

    @property
    def params(self) -> List[Dict[str, str]]:
        """JSON-schema-lite parameter list, handed to the LLM."""
        try:
            signature = inspect.signature(self.func)
        except (TypeError, ValueError):
            return []
        out = []
        for name, param in signature.parameters.items():
            if name in {"self", "ctx", "kwargs"} or param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            annotation = "string"
            if param.annotation is int:
                annotation = "integer"
            elif param.annotation is float:
                annotation = "number"
            elif param.annotation is bool:
                annotation = "boolean"
            out.append(
                {
                    "name": name,
                    "type": annotation,
                    "required": param.default is inspect.Parameter.empty,
                    "default": None
                    if param.default is inspect.Parameter.empty
                    else str(param.default),
                }
            )
        return out

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.params,
            "capabilities": self.capabilities,
            "risk": self.risk,
            "confirm": self.confirm,
            # Tags drive grouping in the CLI and the web UI. Leaving them out
            # silently made every tool report as "other".
            "tags": self.tags,
            "category": (self.tags[0] if self.tags else "other"),
        }

    def spec(self) -> str:
        """One-line tool documentation for the prompt."""
        args = ", ".join(
            f"{p['name']}:{p['type']}" + ("" if p["required"] else "?") for p in self.params
        )
        return f"- {self.name}({args}) :: {self.description}"


def tool(
    name: str,
    description: str,
    capabilities: Optional[Sequence[str]] = None,
    risk: float = 0.2,
    tags: Optional[Sequence[str]] = None,
    confirm: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a function as a tool."""

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        entry = Tool(
            name=name,
            func=func,
            description=description,
            capabilities=list(capabilities or []),
            risk=risk,
            tags=list(tags or []),
            confirm=confirm,
        )
        TOOLS[name] = entry

        def guarded(*args: Any, **kwargs: Any) -> Any:
            """
            Call the tool through the same security gate ``run()`` uses.

            Returning the plain value keeps internal call sites readable, but
            security still applies on *every* path - a handler in routing.py
            cannot accidentally skip the gate by calling the function directly.
            Refusals and crashes come back as a dict with ``ok: False``.
            """
            try:
                for capability in entry.capabilities:
                    get_security().require_capability(entry.capabilities, capability)
            except CapabilityDenied as exc:
                return {"ok": False, "error": str(exc), "capability_denied": True}

            detail = f"{name} {args} {kwargs}".strip()
            decision = get_security().gate(
                name, detail, capabilities=entry.capabilities, risk=entry.risk
            )
            if decision.verdict == "block":
                BUS.emit(Ev.SECURITY_BLOCK, {"tool": name, "reason": decision.reason}, "tools")
                return {
                    "ok": False,
                    "error": f"refused by security policy: {decision.reason}",
                    "blocked": True,
                    "risk": decision.risk.to_dict(),
                }
            if decision.verdict == ASK and entry.confirm:
                BUS.emit(Ev.SECURITY_WARN, {"tool": name, "risk": decision.risk.score}, "tools")
                return {
                    "ok": False,
                    "error": f"confirmation required: {decision.reason}",
                    "needs_confirmation": True,
                    "risk": decision.risk.to_dict(),
                }

            started = time.perf_counter()
            BUS.emit(Ev.SKILL_INVOKED, {"tool": name, "args": _safe_args(args, kwargs)}, "tools")
            try:
                output = func(*args, **kwargs)
            except Exception as exc:
                log_debug(traceback.format_exc(limit=4), "tools")
                return {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "exception": True,
                    "traceback": traceback.format_exc(limit=4),
                }
            BUS.emit(
                Ev.SKILL_DONE,
                {"tool": name, "ok": _output_ok(output), "ms": round((time.perf_counter() - started) * 1000, 1)},
                "tools",
            )
            return output

        guarded.__name__ = func.__name__
        guarded.__doc__ = func.__doc__
        guarded.tool = entry  # type: ignore[attr-defined]
        entry.guard = guarded  # type: ignore[attr-defined]
        return guarded

    return decorate


def _output_error(output: Any) -> str:
    if isinstance(output, dict):
        return str(output.get("error") or output.get("detail") or "reported failure")
    return "reported failure"


def _output_ok(output: Any) -> bool:
    """Tools signal failure inside their return value, so honour that."""
    if isinstance(output, dict) and "ok" in output:
        return bool(output["ok"])
    return True


# --------------------------------------------------------------------------
# Invocation
# --------------------------------------------------------------------------


def run(name: str, *args: Any, security: Optional[SecurityEngine] = None, **kwargs: Any) -> ToolResult:
    """
    Execute a registered tool after the security gate.

    Security failures come back as ``ok=False`` rather than exceptions, so
    the brain can explain the refusal instead of crashing.
    """
    entry = TOOLS.get(name)
    if entry is None:
        return ToolResult(
            ok=False,
            error=f"no such tool: {name}",
            tool=name,
            meta={"suggestion": _closest(name)},
        )

    sec = security or get_security()

    started = time.perf_counter()
    try:
        output = entry.guard(*args, **kwargs)
    except TypeError as exc:
        duration = time.perf_counter() - started
        result = ToolResult(ok=False, error=f"bad arguments: {exc}", tool=name, duration=duration)
        log_debug(traceback.format_exc(), "tools")
    except Exception as exc:  # defensive: guard already catches tool errors
        duration = time.perf_counter() - started
        result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}", tool=name,
                            duration=duration)
        log_error(f"{name} crashed: {exc}", "tools")
    else:
        duration = time.perf_counter() - started
        ok = _output_ok(output)
        error = "" if ok else _output_error(output)
        result = ToolResult(ok=ok, output=output, error=error, tool=name, duration=duration)
        if not ok:
            log_debug(f"{name} reported: {error}", "tools")

    BUS.emit(
        Ev.SKILL_DONE,
        {"tool": name, "ok": result.ok, "ms": round(result.duration * 1000, 1)},
        "tools",
    )
    return result


def _safe_args(args: Sequence[Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Trim argument payloads for the event stream."""
    return {
        "args": [truncate(str(a), 60) for a in args][:5],
        "kwargs": {k: truncate(str(v), 60) for k, v in list(kwargs.items())[:5]},
    }


def _closest(name: str) -> str:
    from ..utils import fuzzy_match

    return fuzzy_match(name, list(TOOLS)) or ""


# --------------------------------------------------------------------------
# Inspection
# --------------------------------------------------------------------------


def _ensure_loaded() -> None:
    """
    Load the builtin tool modules on first use.

    Without this, any caller that skipped ``boot()`` - a quick script, a
    test, the CLI's ``tools`` command - would see an empty registry.

    Keyed on an explicit flag rather than ``if not TOOLS``. Several modules
    import a handful of tool submodules directly, which partially fills
    the registry; testing the dict would then skip ``load_all()`` and
    silently hide every tool those modules did not import.
    """
    if not _LOADED:
        load_all()


def get(name: str) -> Optional[Tool]:
    _ensure_loaded()
    return TOOLS.get(name)


def list_tools(tag: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_loaded()
    items = [t.schema() for t in TOOLS.values()]
    if tag:
        items = [
            t for t in items
            if tag in t["name"]
            or tag in (t.get("tags") or [])
            or tag in t["description"].lower()
        ]
    return sorted(items, key=lambda t: t["name"])


def names() -> List[str]:
    _ensure_loaded()
    return sorted(TOOLS)


def manifest(max_chars: int = 4000) -> str:
    """Compact tool list for the model prompt."""
    _ensure_loaded()
    lines = [t.spec() for t in sorted(TOOLS.values(), key=lambda x: x.name)]
    text = "\n".join(lines)
    return text[:max_chars]


def search(query: str, limit: int = 6) -> List[Tool]:
    """Rank tools against a natural language request."""
    _ensure_loaded()
    from ..utils import normalize_text, token_set

    target = token_set(query)
    if not target:
        return []
    scored: List[tuple] = []
    for entry in TOOLS.values():
        haystack = token_set(f"{entry.name} {entry.description} {' '.join(entry.tags)}")
        overlap = len(target & haystack)
        if overlap:
            scored.append((overlap / max(1, len(target)), entry.name, entry))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in scored[:limit]]


def load_all() -> int:
    """
    Import every builtin tool module so the registry is populated.

    Returns the number of tools now available. Safe to call more than
    once - the tool decorator replaces an existing entry of the same name
    rather than duplicating it.
    """
    global _LOADED

    from . import (  # noqa: F401  (import for side effects)
        capability_tools,
        dev_tools,
        knowledge_tools,
        media_tools,
        system_tools,
        web_tools,
    )

    _LOADED = True
    return len(TOOLS)


__all__ = [
    "TOOLS",
    "Tool",
    "ToolResult",
    "tool",
    "run",
    "get",
    "list_tools",
    "names",
    "manifest",
    "search",
    "load_all",
]