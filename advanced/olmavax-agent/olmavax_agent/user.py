"""
Olmavax Agent - Profile, history and settings
============================================
The three things every real assistant has and this one was missing.

**Profile** is deliberately optional. The agent is usable the second it
starts; signing in only adds a name, an accent colour and a passphrase for
the vault. Nothing is locked behind a login, because an assistant you have
to log into is an assistant you cannot ask at 2am.

**History** groups past exchanges into conversations, so you can scroll back
through a real thread rather than a flat log.

**Settings** is a live view of the config that the running process actually
uses, plus the things the UI can change without a restart.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PATHS, ensure_dirs, get_config
from .events import BUS, Ev
from .logger import log_info, log_warn
from .utils import now, relative, truncate

SESSIONS = "sessions.json"
PROFILE = "profile.json"


# ==========================================================================
# Profile / optional sign-in
# ==========================================================================


class Profile:
    """
    Who is using the agent, and what they like it to look like.

    No account is required. A profile is created on first use, and the only
    "login" is matching a local passphrase that never leaves the machine.
    """

    ACCENTS = ("cyan", "violet", "amber", "emerald", "rose")

    def __init__(self, home: Optional[Path] = None):
        ensure_dirs()
        self.dir = Path(home or PATHS["home"]) / "profile"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / PROFILE
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.file.exists():
            try:
                loaded = json.loads(self.file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except (json.JSONDecodeError, OSError):
                log_warn("profile unreadable, starting a fresh one", "profile")
        return self._blank()

    def _blank(self) -> Dict[str, Any]:
        return {
            "name": "",
            "title": "Boss",
            "accent": "cyan",
            "voice": True,
            "voice_rate": 185,
            "passphrase_hash": "",
            "salt": "",
            "created": now(),
        }

    def save(self) -> None:
        self.file.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # -- identity ------------------------------------------------------
    def set(self, **fields: Any) -> Dict[str, Any]:
        for key, value in fields.items():
            if key in self.data and value is not None:
                self.data[key] = value
        self.save()
        BUS.emit(Ev.LEARNED, {"profile": "updated"}, "profile")
        return self.public()

    def public(self) -> Dict[str, Any]:
        return {
            "name": self.data.get("name", ""),
            "title": self.data.get("title", "Boss"),
            "accent": self.data.get("accent", "cyan"),
            "voice": bool(self.data.get("voice", True)),
            "voice_rate": int(self.data.get("voice_rate", 185)),
            "signed_in": bool(self.data.get("passphrase_hash")),
            "created": relative(self.data.get("created", now())),
        }

    # -- local sign-in --------------------------------------------------
    def set_passphrase(self, passphrase: str) -> bool:
        if len(passphrase) < 4:
            return False
        salt = secrets.token_hex(16)
        self.data["salt"] = salt
        self.data["passphrase_hash"] = self._hash(passphrase, salt)
        self.save()
        return True

    def _hash(self, passphrase: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", passphrase.encode("utf-8"), salt.encode("ascii"), 200_000
        ).hex()

    def check_passphrase(self, passphrase: str) -> bool:
        stored = self.data.get("passphrase_hash")
        salt = self.data.get("salt")
        if not stored or not salt:
            return True  # no passphrase set: nothing to verify against
        return hmac.compare_digest(self._hash(passphrase, salt), stored)

    def clear_passphrase(self) -> None:
        self.data["passphrase_hash"] = ""
        self.data["salt"] = ""
        self.save()


# ==========================================================================
# Conversation history
# ==========================================================================


class History:
    """Past exchanges, grouped into conversations."""

    def __init__(self, home: Optional[Path] = None):
        ensure_dirs()
        self.dir = Path(home or PATHS["home"]) / "history"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.dir / SESSIONS

    def _sessions(self) -> Dict[str, Any]:
        if self.index_file.exists():
            try:
                loaded = json.loads(self.index_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self, sessions: Dict[str, Any]) -> None:
        self.index_file.write_text(
            json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _file(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "default"
        return self.dir / f"{safe}.json"

    def append(
        self,
        role: str,
        text: str,
        session: str = "default",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store one message. Called by the brain on every turn."""
        sessions = self._sessions()
        if session not in sessions:
            sessions[session] = {
                "id": session,
                "title": truncate(text.strip(), 48) or "New conversation",
                "started": now(),
                "messages": 0,
            }
        path = self._file(session)
        messages = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    messages = loaded
            except (json.JSONDecodeError, OSError):
                messages = []
        messages.append({
            "role": role,
            "text": text,
            "at": now(),
            "meta": meta or {},
        })
        # Keep files from growing without bound.
        messages = messages[-600:]
        path.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
        sessions[session]["messages"] = len(messages)
        sessions[session]["updated"] = now()
        self._save(sessions)
        return sessions[session]

    def sessions(self, limit: int = 40) -> List[Dict[str, Any]]:
        rows = list(self._sessions().values())
        rows.sort(key=lambda s: s.get("updated", s.get("started", 0)), reverse=True)
        out = []
        for row in rows[:limit]:
            out.append({
                "id": row.get("id"),
                "title": row.get("title"),
                "messages": row.get("messages", 0),
                "started": relative(row.get("started", now())),
                "updated": relative(row.get("updated", row.get("started", now()))),
            })
        return out

    def messages(self, session: str = "default", limit: int = 200) -> List[Dict[str, Any]]:
        path = self._file(session)
        if not path.exists():
            return []
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(rows, list):
            return []
        return [
            {
                "role": r.get("role", "user"),
                "text": r.get("text", ""),
                "at": relative(r.get("at", now())),
                "intent": (r.get("meta") or {}).get("intent", ""),
            }
            for r in rows[-limit:]
        ]

    def clear(self, session: Optional[str] = None) -> int:
        if session:
            path = self._file(session)
            removed = 1 if path.exists() else 0
            path.unlink(missing_ok=True)
            sessions = self._sessions()
            sessions.pop(session, None)
            self._save(sessions)
            return removed
        removed = 0
        for path in self.dir.glob("*.json"):
            path.unlink(missing_ok=True)
            removed += 1
        self._save({})
        return removed

    def export(self) -> Path:
        target = PATHS["exports"] / f"history-{int(now())}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self._sessions(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return target

    def stats(self) -> Dict[str, Any]:
        sessions = self._sessions()
        total = sum(s.get("messages", 0) for s in sessions.values())
        return {
            "sessions": len(sessions),
            "messages": total,
            "path": str(self.dir),
        }


# ==========================================================================
# Settings
# ==========================================================================

# Which settings the interface may change live, and how to coerce them.
LIVE_SETTINGS = {
    "voice_enabled": ("voice.enabled", "bool"),
    "voice_rate": ("voice.tts_rate", "int"),
    "speak_responses": ("voice.speak_responses", "bool"),
    "require_wake_word": ("voice.require_wake_word", "bool"),
    "wake_words": ("voice.wake_words", "list"),
    "language": ("language", "str"),
    "posture": ("security.posture", "posture"),
    "require_confirmation": ("security.require_confirmation", "bool"),
    "sandbox_enabled": ("security.sandbox_enabled", "bool"),
    "audit_enabled": ("security.audit_enabled", "bool"),
    "context_messages": ("brain.context_messages", "int"),
    "temperature": ("brain.temperature", "float"),
    "provider": ("brain.provider", "str"),
    "model": ("brain.model", "str"),
    "theme": ("ui.theme", "str"),
    "fps": ("ui.fps", "int"),
    "particle_count": ("ui.particle_count", "int"),
    "autostart": ("autostart", "bool"),
}


def _coerce(value: Any, kind: str) -> Any:
    try:
        if kind == "bool":
            if isinstance(value, str):
                return value.lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "list":
            if isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            return list(value)
        if kind == "posture":
            text = str(value)
            if text not in {"paranoid", "balanced", "sandbox", "open"}:
                raise ValueError(f"unknown posture: {text}")
            return text
        return str(value)
    except (TypeError, ValueError):
        raise ValueError(f"cannot read {value!r} as {kind}")


class Settings:
    """Read and change the live configuration safely."""

    def __init__(self) -> None:
        self.config = get_config()

    def describe(self) -> List[Dict[str, Any]]:
        """Every live setting with its current value, grouped for the UI."""
        groups = [
            ("voice", "Voice", [
                ("voice_enabled", "Enable voice", "bool"),
                ("speak_responses", "Speak replies aloud", "bool"),
                ("voice_rate", "Speaking rate", "int"),
                ("require_wake_word", "Require the wake word", "bool"),
                ("wake_words", "Wake words (comma separated)", "list"),
            ]),
            ("brain", "Thinking", [
                ("provider", "Model provider", "str"),
                ("model", "Model name", "str"),
                ("temperature", "Temperature", "float"),
                ("context_messages", "Conversation memory (turns)", "int"),
            ]),
            ("security", "Security", [
                ("posture", "Posture", "posture"),
                ("require_confirmation", "Ask before risky actions", "bool"),
                ("sandbox_enabled", "Sandbox code execution", "bool"),
                ("audit_enabled", "Write the audit trail", "bool"),
            ]),
            ("ui", "Interface", [
                ("theme", "Theme", "str"),
                ("fps", "Frames per second", "int"),
                ("particle_count", "Particles", "int"),
            ]),
            ("general", "General", [
                ("language", "Language", "str"),
                ("autostart", "Start with Windows", "bool"),
            ]),
        ]
        rows: List[Dict[str, Any]] = []
        for group_id, title, entries in groups:
            for key, label, kind in entries:
                path, _ = LIVE_SETTINGS[key]
                rows.append({
                    "group": group_id,
                    "group_title": title,
                    "key": key,
                    "label": label,
                    "kind": kind,
                    "value": self.get(key),
                })
        return rows

    def _resolve(self, key: str):
        path, kind = LIVE_SETTINGS[key]
        target: Any = self.config
        parts = path.split(".")
        for part in parts[:-1]:
            target = getattr(target, part)
        return target, parts[-1], kind

    def get(self, key: str) -> Any:
        if key not in LIVE_SETTINGS:
            raise KeyError(key)
        parent, attr, _kind = self._resolve(key)
        return getattr(parent, attr)

    def set(self, key: str, value: Any) -> Any:
        """
        Change one setting. Values are validated and clamped so a bad input
        cannot break the running agent.
        """
        if key not in LIVE_SETTINGS:
            raise KeyError(f"unknown setting: {key}")
        parent, attr, kind = self._resolve(key)
        coerced = _coerce(value, kind)

        if key == "voice_rate":
            coerced = max(60, min(400, coerced))
        elif key == "temperature":
            coerced = max(0.0, min(2.0, coerced))
        elif key == "fps":
            coerced = max(10, min(120, coerced))
        elif key == "particle_count":
            coerced = max(0, min(2000, coerced))
        elif key == "context_messages":
            coerced = max(2, min(100, coerced))
        elif key == "posture":
            from .security import get_security

            get_security().apply_posture(coerced)

        setattr(parent, attr, coerced)

        if key in {"voice_enabled", "speak_responses", "voice_rate",
                   "require_wake_word", "wake_words", "language"}:
            from .config import get_config as fresh

            fresh()._apply_env()
        return coerced

    def save(self) -> Path:
        from dataclasses import asdict

        path = self.config.save()
        log_info(f"settings written to {path}", "settings")
        return path

    def reset(self) -> None:
        from .config import Config

        fresh = Config.load()
        self.config.__dict__.update(fresh.__dict__)
        self.save()


# Shared instances
_PROFILE: Optional[Profile] = None
_HISTORY: Optional[History] = None
_SETTINGS: Optional[Settings] = None


def get_profile() -> Profile:
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = Profile()
    return _PROFILE


def get_history() -> History:
    global _HISTORY
    if _HISTORY is None:
        _HISTORY = History()
    return _HISTORY


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings()
    return _SETTINGS