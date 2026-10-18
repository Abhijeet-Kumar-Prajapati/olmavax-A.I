"""Open Charvis - logging, chat history and tamper-evident audit trail."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PATHS, ensure_dirs
from .utils import stamp, truncate

_LOCK = threading.RLock()


def setup_logging(debug: bool = False) -> logging.Logger:
    """Configure the agent logger. Safe to call more than once."""
    ensure_dirs()
    logger = logging.getLogger("charvis")
    if logger.handlers:
        logger.setLevel(logging.DEBUG if debug else logging.INFO)
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        PATHS["error_log"], maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    logger.addHandler(console)

    logging.getLogger("charvis.urllib").setLevel(logging.WARNING)
    return logger


LOG = setup_logging()


def log_debug(message: str, area: str = "core") -> None:
    LOG.debug("[%s] %s", area, message)


def log_info(message: str, area: str = "core") -> None:
    LOG.info("[%s] %s", area, message)


def log_warn(message: str, area: str = "core") -> None:
    LOG.warning("[%s] %s", area, message)


def log_error(message: str, area: str = "core") -> None:
    LOG.error("[%s] %s", area, message)


def log_exception(message: str, area: str = "core") -> None:
    LOG.exception("[%s] %s", area, message)


# --------------------------------------------------------------------------
# Chat history (JSON lines, greppable, append-only)
# --------------------------------------------------------------------------


class ChatHistory:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or PATHS["chat_log"])
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, role: str, text: str, meta: Optional[Dict[str, Any]] = None) -> None:
        record = {
            "ts": time.time(),
            "time": stamp(),
            "role": role,
            "text": text,
            "meta": meta or {},
        }
        with _LOCK:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as exc:
                log_warn(f"chat log write failed: {exc}", "logger")

    def tail(self, limit: int = 30, role: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-4000:]
        except OSError:
            return []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if role and record.get("role") != role:
                continue
            out.append(record)
        return out[-limit:]

    def export(self, target: Path) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            self.path.read_text(encoding="utf-8", errors="replace")
            if self.path.exists()
            else "",
            encoding="utf-8",
        )
        return target


# --------------------------------------------------------------------------
# Audit trail - append-only and hash chained so tampering is detectable
# --------------------------------------------------------------------------


class AuditTrail:
    """
    Every security-relevant action is recorded here.

    Each entry stores ``sha256(previous_hash + entry_payload)`` so if anyone
    edits or removes a line, :meth:`verify` will report the break.
    """

    def __init__(self, path: Optional[Path] = None, enabled: bool = True,
                 tamper_evident: bool = True):
        self.path = Path(path or PATHS["audit_log"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self.tamper_evident = tamper_evident
        self.rotated_from: Optional[str] = None
        self._rotate_if_legacy()
        self._last_hash = self._load_last_hash()
        self._last_size = self.path.stat().st_size if self.path.exists() else 0

    def _refresh_if_changed(self) -> None:
        """
        Re-read the chain head if the file changed underneath us.

        Without this, a process that stays running across an archive or a
        repair keeps appending to a chain rooted in a hash that no longer
        exists, and every new line immediately breaks verification.
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            # The file was archived or removed underneath us. Treat that as
            # an empty log, otherwise we would keep chaining from a hash that
            # no longer exists and every new line would fail verification.
            size = 0
        if size == self._last_size:
            return
        self._last_hash = self._load_last_hash()
        self._last_size = size

    # -- legacy migration ------------------------------------------------
    def _verify_legacy(self) -> bool:
        """
        Verify using the *old*, buggy rule (hash included the ``prev`` field).

        Only used to recognise logs written before the fix, so they can be
        archived instead of being reported as permanently "broken".
        """
        if not self.path.exists():
            return True
        prev = "GENESIS"
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("prev") != prev:
                        return False
                    if "hash" in entry:
                        if self._chain(prev, entry) != entry["hash"]:
                            return False
                        prev = entry["hash"]
        except (json.JSONDecodeError, OSError):
            return False
        return True

    def _rotate_if_legacy(self) -> None:
        """
        Move a pre-fix audit log aside so the chain starts clean.

        Those entries were hashed with a rule that verification could never
        reproduce, so they would report the trail as broken forever. They are
        archived, never deleted, and the rotation is recorded in the new log.
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        if self.verify().get("valid", True):
            return
        if not self._verify_legacy():
            return  # a genuinely tampered log: leave it and report the break

        stamp = time.strftime("%Y%m%d-%H%M%S")
        archive = self.path.with_name(f"{self.path.name}.pre-fix-{stamp}")
        try:
            self.path.rename(archive)
        except OSError:
            return
        self.rotated_from = archive.name
        self.record(
            "audit.rotate", "allow",
            f"archived a pre-fix audit log to {archive.name}; "
            "those entries used a hash rule that could never verify",
            0.0,
        )

    # -- internals ------------------------------------------------------
    def _load_last_hash(self) -> str:
        if not self.path.exists():
            return "GENESIS"
        last = ""
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.strip():
                        last = line.strip()
        except OSError:
            return "GENESIS"
        if not last:
            return "GENESIS"
        try:
            return json.loads(last).get("hash", "GENESIS")
        except json.JSONDecodeError:
            return "GENESIS"

    @staticmethod
    def _chain(prev: str, payload: Dict[str, Any]) -> str:
        blob = prev + json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return sha256(blob.encode("utf-8")).hexdigest()

    # -- api ------------------------------------------------------------
    def record(
        self,
        action: str,
        decision: str,
        detail: str = "",
        risk: float = 0.0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self._refresh_if_changed()
        entry = {
            "ts": time.time(),
            "time": stamp(),
            "action": action,
            "decision": decision,
            "risk": round(risk, 4),
            "detail": truncate(detail, 400),
            "extra": extra or {},
        }
        if self.tamper_evident:
                entry["prev"] = self._last_hash
                # Hash exactly the body that verify() will recompute: the
                # "prev" and "hash" fields themselves are excluded. Hashing
                # the entry *including* "prev" here made every later
                # verification fail, so the trail looked permanently broken.
                body = {k: v for k, v in entry.items() if k not in ("hash", "prev")}
                entry["hash"] = self._chain(self._last_hash, body)
                self._last_hash = entry["hash"]
        self._last_size = self.path.stat().st_size if self.path.exists() else 0
        with _LOCK:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError as exc:
                log_warn(f"audit write failed: {exc}", "audit")
        return entry

    def entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-5000:]
        except OSError:
            return []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out[-limit:]

    def verify(self) -> Dict[str, Any]:
        """Recompute the whole chain. Detects edits and deletions."""
        if not self.path.exists():
            return {"valid": True, "entries": 0, "broken_at": None}
        prev = "GENESIS"
        count = 0
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    return {"valid": False, "entries": count,
                            "broken_at": lineno, "reason": "unreadable line"}
                if entry.get("prev") != prev:
                    return {"valid": False, "entries": count,
                            "broken_at": lineno, "reason": "chain mismatch"}
                if "hash" in entry:
                    body = {k: v for k, v in entry.items()
                            if k not in ("hash", "prev")}
                    expected = self._chain(prev, body)
                    if expected != entry["hash"]:
                        return {"valid": False, "entries": count,
                                "broken_at": lineno, "reason": "hash mismatch"}
                    prev = entry["hash"]
                count += 1
        return {"valid": True, "entries": count, "broken_at": None}

    def stats(self) -> Dict[str, Any]:
        entries = self.entries(limit=5000)
        decisions: Dict[str, int] = {}
        actions: Dict[str, int] = {}
        for entry in entries:
            decisions[entry.get("decision", "?")] = decisions.get(entry.get("decision", "?"), 0) + 1
            actions[entry.get("action", "?")] = actions.get(entry.get("action", "?"), 0) + 1
        return {
            "total": len(entries),
            "decisions": decisions,
            "top_actions": sorted(actions.items(), key=lambda kv: -kv[1])[:10],
            "verified": self.verify(),
        }


CHAT = ChatHistory()
AUDIT = AuditTrail()


# --------------------------------------------------------------------------
# Pretty console banner
# --------------------------------------------------------------------------

BANNER = r"""
   ___                      _____ _     _     ___
  / _ \ _ __   ___ _ __    / ___| |__ | |__ |_ _|
 | | | | '_ \ / _ \ '_ \   | |   | '_ \| '_ \| __|
 | |_| | | | |  __/ | | |  | |___| | | | | | | |_
  \___/|_| |_|\___|_| |_|   \____|_| |_|_| |_|\__|
        v{version}  |  {codename}
"""


def banner(version: str = "2.0.0", codename: str = "CHARVIS-CORE") -> str:
    return BANNER.format(version=version, codename=codename).replace("\\___/", "___/")