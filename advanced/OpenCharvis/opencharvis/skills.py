"""
Open Charvis - Skill loader
===========================
Skills are plain Python files on disk.  The agent loads them, reads their
``SKILL`` metadata block and exposes their ``run`` function as a tool.

That means a new capability needs no framework changes at all: write a file,
restart, and the agent can do it.

Two folders are watched:

``skills/``          skills the owner wrote or approved
``skills/learned/``  skills the agent generated for itself

Every skill's declared capabilities are enforced at call time, so a skill
cannot quietly escalate itself to ``files.delete``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import PATHS, ensure_dirs
from .events import BUS, Ev
from .logger import log_info, log_warn
from .security import get_security
from .tools import Tool, TOOLS, ToolResult
from .utils import now, relative, truncate

SEC = get_security()

# Skills deliberately marked as not yet reviewed refuse to run.
GUARD_TOKEN = "reviewed=True"


@dataclass
class SkillInfo:
    name: str
    path: Path
    description: str = ""
    version: str = "1.0"
    auto_learned: bool = False
    confidence: float = 0.0
    observations: int = 0
    capabilities: List[str] = field(default_factory=list)
    risk: float = 0.2
    guard: str = "reviewed=True"
    error: str = ""

    @property
    def enabled(self) -> bool:
        return not self.error and GUARD_TOKEN in (self.guard or "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "description": self.description,
            "version": self.version,
            "auto_learned": self.auto_learned,
            "confidence": round(self.confidence, 2),
            "observations": self.observations,
            "capabilities": self.capabilities,
            "risk": self.risk,
            "enabled": self.enabled,
            "reason": self.error or ("" if self.enabled else "guard is not reviewed=True"),
            "modified": relative(self.path.stat().st_mtime) if self.path.exists() else "unknown",
        }


class SkillRegistry:
    """Discovers, validates and runs skill files."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.skills: Dict[str, SkillInfo] = {}
        self.modules: Dict[str, Any] = {}
        self.loaded_at = 0.0

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def folders(self) -> List[Path]:
        ensure_dirs()
        owned = PATHS["skills"]
        learned = PATHS["learned_skills"]
        for folder in (owned, learned):
            folder.mkdir(parents=True, exist_ok=True)
        return [owned, learned]

    def discover(self) -> List[Path]:
        files: List[Path] = []
        for folder in self.folders():
            files.extend(sorted(folder.glob("*.py")))
        return files

    def load(self, verbose: bool = False) -> Dict[str, Any]:
        """(Re)load every skill file. Bad files are reported, not fatal."""
        with self._lock:
            report = {"loaded": [], "failed": [], "skipped": []}

            for path in self.discover():
                info = self._load_one(path)
                if info.error.startswith("no SKILL"):
                    report["skipped"].append(path.name)
                    continue
                if info.error:
                    report["failed"].append({"file": path.name, "error": info.error})
                    log_warn(f"skill {path.name} rejected: {info.error}", "skills")
                    continue
                self.skills[info.name] = info
                self._register_tool(info)
                report["loaded"].append(info.name)
                if verbose:
                    print(f"  loaded skill: {info.name}")

            self.loaded_at = now()
            report["total"] = len(self.skills)
            return report

    def _load_one(self, path: Path) -> SkillInfo:
        """Validate then import a single skill file."""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return SkillInfo(path.stem, path, error=f"unreadable: {exc}")

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return SkillInfo(
                path.stem, path,
                error=f"syntax error at line {exc.lineno}: {exc.msg}",
            )

        if not any(
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "SKILL" for t in node.targets)
            for node in tree.body
        ):
            return SkillInfo(path.stem, path, error="no SKILL dict at module level")

        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
            for node in tree.body
        ):
            return SkillInfo(path.stem, path, error="no run() function")

        module_name = f"charvis_skill_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                return SkillInfo(path.stem, path, error="could not build an import spec")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            return SkillInfo(
                path.stem, path,
                error=f"import failed: {type(exc).__name__}: {exc}",
            )

        meta = getattr(module, "SKILL", {}) or {}
        self.modules[path.stem] = module

        return SkillInfo(
            name=str(meta.get("name") or path.stem),
            path=path,
            description=str(meta.get("description", "")).strip(),
            version=str(meta.get("version", "1.0")),
            auto_learned=bool(meta.get("auto_learned", False)),
            confidence=float(meta.get("confidence", 0.0) or 0.0),
            observations=int(meta.get("observations", 0) or 0),
            capabilities=list(meta.get("capabilities", []) or []),
            risk=float(meta.get("risk", 0.2) or 0.2),
            guard=str(meta.get("guard", GUARD_TOKEN)),
        )

    def _register_tool(self, info: SkillInfo) -> None:
        """Expose a skill's run() as a callable tool."""
        module = self.modules.get(info.path.stem)
        if module is None:
            return
        entry = getattr(module, "run", None)
        if not callable(entry):
            return

        from .tools import run as run_tool

        def make_wrapper(skill: SkillInfo, func: Callable[..., Any]):
            def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
                if not skill.enabled:
                    return ToolResult(
                        ok=False,
                        error=(
                            f"skill '{skill.name}' is loaded but disabled. "
                            f"Open {skill.path}, set SKILL['guard'] to 'reviewed=True', "
                            "then run 'charvis skills reload'."
                        ),
                        tool=f"skill.{skill.name}",
                    )
                try:
                    output = func(*args, **kwargs)
                except Exception as exc:
                    return ToolResult(
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}",
                        tool=f"skill.{skill.name}",
                        meta={"traceback": traceback.format_exc(limit=3)},
                    )
                return ToolResult(ok=True, output=output, tool=f"skill.{skill.name}")

            return wrapper

        tool_name = f"skill.{info.name}"
        TOOLS[tool_name] = Tool(
            name=tool_name,
            func=make_wrapper(info, entry),
            description=info.description or f"Custom skill {info.name}",
            capabilities=info.capabilities or ["chat"],
            risk=info.risk,
            tags=["skill", "custom"],
        )
        BUS.emit(Ev.SKILL_INVOKED, {"loaded": info.name}, "skills")

    # ------------------------------------------------------------------
    # Use
    # ------------------------------------------------------------------
    def call(self, name: str, **params: Any) -> ToolResult:
        tool_name = name if name.startswith("skill.") else f"skill.{name}"
        if tool_name not in TOOLS:
            return ToolResult(
                ok=False, error=f"no skill named '{name}'", tool=tool_name,
                meta={"available": self.names()},
            )
        from .tools import run as run_tool

        return run_tool(tool_name, security=SEC, **params)

    def names(self) -> List[str]:
        return sorted(self.skills)

    def get(self, name: str) -> Optional[SkillInfo]:
        return self.skills.get(name)

    def listing(self) -> List[Dict[str, Any]]:
        return [info.to_dict() for info in sorted(self.skills.values(), key=lambda i: i.name)]

    def enable(self, name: str) -> Dict[str, Any]:
        """Flip a skill's guard to reviewed=True after the owner looks at it."""
        info = self.skills.get(name)
        if not info:
            return {"ok": False, "error": f"no skill named '{name}'"}
        try:
            text = info.path.read_text(encoding="utf-8")
            if GUARD_TOKEN not in text:
                return {"ok": False, "error": "guard token not found in that file"}
            text = text.replace("reviewed=False", GUARD_TOKEN)
            info.path.write_text(text, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        SEC.audit.record("skill.enable", "allow", f"owner enabled skill '{name}'", 0.25)
        self.load()
        return {"ok": True, "name": name, "note": "read the file first - you are enabling code"}

    def disable(self, name: str) -> Dict[str, Any]:
        info = self.skills.get(name)
        if not info:
            return {"ok": False, "error": f"no skill named '{name}'"}
        try:
            text = info.path.read_text(encoding="utf-8")
            info.path.write_text(text.replace(GUARD_TOKEN, "reviewed=False"), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        self.load()
        return {"ok": True, "name": name}

    def create(self, name: str, description: str, body: str = "") -> Path:
        """Write a starter skill the owner can then edit."""
        path = PATHS["skills"] / f"{name}.py"
        if path.exists():
            return path
        if not body:
            body = f'''"""
{description}
"""

from typing import Any, Dict

SKILL = {{
    "name": "{name}",
    "description": "{description}",
    "version": "1.0",
    "author": "owner",
    "auto_learned": False,
    "capabilities": ["chat"],
    "risk": 0.10,
    "guard": "reviewed=True",
}}


def run(**params: Any) -> Dict[str, Any]:
    """Your logic here. Return a dict with an 'ok' key."""
    return {{"ok": True, "skill": "{name}", "received": params}}
'''
        path.write_text(body, encoding="utf-8")
        self.load()
        BUS.emit(Ev.SKILL_LEARNED, {"created": name}, "skills")
        return path

    def stats(self) -> Dict[str, Any]:
        return {
            "loaded": len(self.skills),
            "enabled": sum(1 for i in self.skills.values() if i.enabled),
            "auto_learned": sum(1 for i in self.skills.values() if i.auto_learned),
            "files": len(self.discover()),
            "loaded_at": relative(self.loaded_at) if self.loaded_at else "never",
        }


_REGISTRY: Optional[SkillRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> SkillRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = SkillRegistry()
    return _REGISTRY