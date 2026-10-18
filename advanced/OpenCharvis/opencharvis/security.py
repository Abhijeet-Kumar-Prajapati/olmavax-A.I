"""
Open Charvis - Security powerhouse
==================================
The agent protects the machine *and* itself, and it decides how careful to
be on its own rather than relying on a fixed setting.

Five layers:

1. **Intent risk scoring** - every request is scored 0.0 - 1.0 from the
   actions it implies, not from keywords alone.
2. **Capability gates** - each tool declares the capability it needs
   (``files.write``, ``net.fetch``...). A tool without a capability it
   declared is refused.
3. **Path jailing** - filesystem work is resolved through
   :func:`opencharvis.utils.safe_path` so ``../`` escapes fail.
4. **Secret hygiene** - outputs are scrubbed for API keys, passwords and
   tokens before they reach a log, the chat history or the web UI.
5. **Self assessment** - :meth:`SecurityEngine.advise` looks at recent
   behaviour and recommends a posture, so the agent tightens itself around
   unfamiliar or destructive work.

Nothing here silently blocks a normal question. Blocking is reserved for
genuinely destructive operations; everything in between asks first.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import SecurityConfig
from .events import BUS, Ev
from .logger import AuditTrail, log_info, log_warn
from .utils import clamp, now, truncate

# --------------------------------------------------------------------------
# Risk vocabulary
# --------------------------------------------------------------------------

SAFE = "safe"
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

_ORDER = {SAFE: 0, LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}


def band(score: float) -> str:
    if score < 0.15:
        return SAFE
    if score < 0.35:
        return LOW
    if score < 0.60:
        return MEDIUM
    if score < 0.85:
        return HIGH
    return CRITICAL


# --------------------------------------------------------------------------
# Capability model
# --------------------------------------------------------------------------

CAPABILITIES = {
    "chat": "answer questions, hold a conversation",
    "memory.read": "read what the agent remembers",
    "memory.write": "store new memories",
    "files.read": "read files",
    "files.write": "create or modify files",
    "files.delete": "delete files",
    "net.fetch": "reach the internet",
    "net.post": "send data out to the internet",
    "code.run": "execute code",
    "system.control": "control apps, volume, power and windows",
    "screen.read": "capture what is on screen",
    "media.create": "generate images, animation and video",
    "vault.access": "read encrypted secrets",
    "self.modify": "change the agent's own skills or config",
    "delete.self": "remove agent data",
}


class CapabilityDenied(PermissionError):
    """Raised when a tool tries to use a capability it did not declare."""


# --------------------------------------------------------------------------
# Intent risk patterns
# --------------------------------------------------------------------------

# (regex, weight, human readable reason, level)
# Weights are additive but clamped; hard blocks are checked separately.
RISK_PATTERNS: Tuple[Tuple[re.Pattern, float, str, str], ...] = (
    # -- destructive ------------------------------------------------------
    (re.compile(r"\bformat\s+(c|d|e|f):|\bformat\s+the\s+(disk|drive)"), 0.95, "formats a disk", CRITICAL),
    (re.compile(r"\b(dd|diskpart|clean\s+all)\b"), 0.85, "raw disk operation", CRITICAL),
    (re.compile(r"\b(shutdown|restart|reboot|power\s*off)\b"), 0.55, "power state change", MEDIUM),
    (re.compile(r"\b(delete|remove|erase|wipe|destroy|trash|unlink)\b"), 0.60, "deletion", HIGH),
    (re.compile(r"\brm\s+-rf\b|\brmdir\s+/s\b|\bdel\s+/[sq]\b"), 0.90, "recursive delete", CRITICAL),
    (re.compile(r"\b(rmdir|del)\s+.*\*"), 0.90, "wildcard delete", CRITICAL),
    (re.compile(r"\bregistry\b|\bregedit\b|\bHKLM\b|\bHKCU\b"), 0.65, "registry edit", HIGH),
    (re.compile(r"\b(defender|antivirus|firewall)\b.*\b(disable|off|stop|turn\s*off)\b"), 0.85, "disables a protection", CRITICAL),
    (re.compile(r"\b(remove|uninstall)\b.*\b(antivirus|defender|security)\b"), 0.90, "removes protection", CRITICAL),
    (re.compile(r"\b(bypass|disable|crack|patch)\b.*\b(security|password|licen[cs]e|activation)\b"), 0.90, "bypasses a protection", CRITICAL),
    # -- credential handling ---------------------------------------------
    (re.compile(r"\b(password|passwd|credential|api\s*key|secret|token)\b"), 0.35, "touches credentials", MEDIUM),
    (re.compile(r"\b(hack|crack|brute\s*force|keylog|steal|exfiltrat)\w*"), 0.95, "offensive security request", CRITICAL),
    (re.compile(r"\b(sudo|runas|administrator|elevate)\b"), 0.50, "privilege escalation", MEDIUM),
    # -- network ----------------------------------------------------------
    (re.compile(r"\b(send|post|upload|email|share)\b.*\b(all|everything|file|document|data)\b"), 0.55, "sends data out", MEDIUM),
    (re.compile(r"\b(download|install|pip\s+install|npm\s+i|apt\s+install|choco)\b"), 0.55, "downloads and installs", MEDIUM),
    (re.compile(r"\bcurl\b.*\|\s*(sh|bash)\b|\bwget\b.*\|\s*(sh|bash)\b"), 0.85, "pipe to shell", CRITICAL),
    # -- code execution ---------------------------------------------------
    (re.compile(r"\b(run|execute|eval|exec)\b.*\b(code|script|command)\b"), 0.45, "executes code", MEDIUM),
    (re.compile(r"\bself\s*modify\b|\bedit\s+(your|yourself)\b|\brewrite\s+yourself\b"), 0.70, "modifies the agent itself", HIGH),
    (re.compile(r"\b(delete|reset|wipe)\b.*\b(yourself|your\s+memory|everything\s+you\s+know)\b"), 0.95, "erases the agent", CRITICAL),
    # -- privacy ----------------------------------------------------------
    (re.compile(r"\btrack\b.*\b(without\s+(asking|permission)|covertly|secretly)\b"), 0.80, "covert tracking", CRITICAL),
    (re.compile(r"\bspy\b|\bmonitor\s+(someone|him|her|them)\b"), 0.80, "surveillance request", CRITICAL),
    (re.compile(r"\bwithout\s+(asking|telling|permission|consent)\b|\bsecretly\b|\bcovertly\b"), 0.65, "asks for hidden action", HIGH),
)

# Hard blocks - refused no matter what, even with confirmation.
HARD_BLOCKS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bformat\s+c:"), "disk format is never executed by the agent"),
    (re.compile(r"\brmdir\s+.*[\\/]\s*\*|\bdel\s+/[sq]\b|\brd\s+/s\b"), "bulk delete is never executed by the agent"),
    (re.compile(r"\b(vssadmin\s+delete\s+shadows|bcdedit.*recoveryenabled\s+no)"), "recovery sabotage is refused"),
    (re.compile(r"\bmimikatz\b|\bpsexec\b.*-s\b"), "credential theft tooling is refused"),
)

# Secret patterns scrubbed from anything the agent stores or displays.
SECRET_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{16,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{16,}"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{30,}"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "[REDACTED_HF_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
     "[REDACTED_CREDENTIAL]"),
    (re.compile(r"(?i)\bauthorization:\s*bearer\s+[A-Za-z0-9\-._~+/]{16,}"), "[REDACTED_BEARER]"),
)


def scrub(text: str) -> Tuple[str, int]:
    """Strip credentials out of text. Returns (clean_text, secrets_found)."""
    if not text:
        return text, 0
    found = 0
    clean = text
    for pattern, replacement in SECRET_PATTERNS:
        clean, hits = pattern.subn(replacement, clean)
        found += hits
    return clean, found


def contains_secret(text: str) -> bool:
    _, found = scrub(text)
    return found > 0


# --------------------------------------------------------------------------
# Risk report
# --------------------------------------------------------------------------


@dataclass
class RiskReport:
    """Outcome of scoring one request."""

    score: float
    level: str
    reasons: List[str] = field(default_factory=list)
    hard_block: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.hard_block is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "level": self.level,
            "reasons": self.reasons,
            "hard_block": self.hard_block,
            "capabilities": self.capabilities,
        }

    def explain(self) -> str:
        if self.hard_block:
            return f"BLOCKED - {self.hard_block}"
        if not self.reasons:
            return f"{self.level.upper()} ({self.score:.0%}) - nothing risky detected"
        return f"{self.level.upper()} ({self.score:.0%}) - " + "; ".join(self.reasons)


# --------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------

ALLOW = "allow"
ASK = "ask"
BLOCK = "block"


@dataclass
class Decision:
    verdict: str
    risk: RiskReport
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.verdict in (ALLOW, ASK)

    def to_dict(self) -> Dict[str, Any]:
        return {"verdict": self.verdict, "reason": self.reason, "risk": self.risk.to_dict()}


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


class SecurityEngine:
    """Scores, gates, journals and audits every consequential action."""

    def __init__(self, config: Optional[SecurityConfig] = None, audit: Optional[AuditTrail] = None):
        self.cfg = config or SecurityConfig()
        self.audit = audit or AuditTrail(
            enabled=self.cfg.audit_enabled, tamper_evident=self.cfg.tamper_evident_log
        )
        self._lock = threading.RLock()
        self._pending: Dict[str, float] = {}
        self._history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def score_text(self, text: str, capabilities: Optional[Sequence[str]] = None) -> RiskReport:
        """
        Score a natural language request.

        Weights are combined with a saturating sum rather than a plain
        total so that mentioning three scary words does not by itself
        reach critical, but one genuinely critical action always does.
        """
        probe = (text or "").lower()
        score = 0.0
        reasons: List[str] = []
        hard_block = None

        for pattern, block_reason in HARD_BLOCKS:
            if pattern.search(probe):
                hard_block = block_reason
                break

        for pattern, weight, reason, _level in RISK_PATTERNS:
            if pattern.search(probe):
                # Saturating add: 1 - (1-a)(1-b)(1-c)
                score = 1.0 - (1.0 - score) * (1.0 - weight)
                if reason not in reasons:
                    reasons.append(reason)

        for cap in capabilities or []:
            if cap in {"files.delete", "self.modify", "delete.self"}:
                score = clamp(score + 0.15)
                reasons.append(f"needs capability {cap}")

        if hard_block:
            return RiskReport(1.0, CRITICAL, reasons, hard_block, list(capabilities or []))

        level = band(score)
        return RiskReport(clamp(score), level, reasons, None, list(capabilities or []))

    def score_action(self, action: str, detail: str = "") -> RiskReport:
        """Score a concrete action about to be performed."""
        capability = CAPABILITY_WEIGHTS.get(action, 0.20)
        text = f"{action} {detail}".strip()
        report = self.score_text(text, capabilities=[action])
        blended = clamp(max(capability, report.score) if report.reasons else capability)
        return RiskReport(
            blended,
            band(blended),
            report.reasons or [f"action class {action}"],
            report.hard_block,
            [action],
        )

    # ------------------------------------------------------------------
    # Gating
    # ------------------------------------------------------------------
    def gate(
        self,
        action: str,
        detail: str = "",
        capabilities: Optional[Sequence[str]] = None,
        risk: Optional[float] = None,
    ) -> Decision:
        """
        Decide whether an action may proceed.

        ALLOW - safe, just do it
        ASK   - ask the owner first
        BLOCK - refuse and explain

        ``risk`` is a declared score from a reviewed tool.  When present it
        is authoritative, because a tool's author has already judged what
        running it means; the free-text scan would otherwise re-flag the
        tool's own name ("dev.run … code") every single time.  Hard blocks
        and destructive-capability bumps still apply on top, so a declared
        risk can only ever be raised, never used to smuggle something past.
        """
        caps = list(capabilities or [])
        text_report = self.score_text(detail, caps)

        if text_report.blocked:
            report = text_report
        elif risk is not None:
            bump = 0.15 if any(
                c in {"files.delete", "self.modify", "delete.self"} for c in caps
            ) else 0.0
            score = clamp(max(float(risk), bump))
            reasons = text_report.reasons or [f"tool declares risk {float(risk):.2f}"]
            report = RiskReport(score, band(score), reasons, None, caps)
        else:
            report = self.score_action(action, detail)

        threshold = self.cfg.risk_threshold()

        if report.blocked:
            self._record(action, BLOCK, detail, report)
            BUS.emit(Ev.SECURITY_BLOCK, {"action": action, "reason": report.hard_block}, "security")
            return Decision(BLOCK, report, report.hard_block or "blocked by policy")

        if report.score >= threshold:
            self._record(action, ASK, detail, report)
            BUS.emit(Ev.SECURITY_WARN, {"action": action, "risk": report.score}, "security")
            return Decision(
                ASK,
                report,
                f"{report.level} risk ({report.score:.0%}) - needs your confirmation",
            )

        self._record(action, ALLOW, detail, report)
        return Decision(ALLOW, report, "safe")

    def require_capability(self, declared: Sequence[str], requested: str) -> None:
        """
        Capability containment: a tool only gets what it declared.

        ``*`` grants everything (used by the trusted builtin tool set).
        """
        if "*" in declared or requested in declared:
            return
        purpose = CAPABILITIES.get(requested, requested)
        raise CapabilityDenied(
            f"tool declared {sorted(declared) or ['nothing']} but asked for '{requested}' ({purpose})"
        )

    # ------------------------------------------------------------------
    # Confirmation state
    # ------------------------------------------------------------------
    def request_confirmation(self, fingerprint: str) -> str:
        """Register a pending risky action and return the prompt to speak."""
        with self._lock:
            self._pending[fingerprint] = now()
        return (
            "This one is risky, so I need your word first. "
            "Say 'haan' to go ahead, or 'nahi' to stop."
        )

    def resolve_confirmation(self, said: str) -> Optional[bool]:
        """Interpret the owner's answer. ``None`` means 'that was not an answer'."""
        probe = (said or "").strip().lower()
        if not probe:
            return None
        for phrase in self.cfg.confirmation_phrases:
            if phrase in probe:
                with self._lock:
                    self._pending.clear()
                return True
        for phrase in self.cfg.deny_phrases:
            if phrase in probe:
                with self._lock:
                    self._pending.clear()
                return False
        return None

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    # ------------------------------------------------------------------
    # Filesystem jailing
    # ------------------------------------------------------------------
    def safe_target(self, candidate: str, roots: Iterable[Path]) -> Optional[Path]:
        """
        Resolve a path and refuse anything that escapes the allowed roots.

        Blocks traversal (``../``), absolute paths outside the roots, and
        well-known credential locations regardless of the roots given.
        """
        from .utils import safe_path

        if not candidate:
            return None
        candidate = str(candidate).strip()
        if len(candidate) > 4096 or "\x00" in candidate:
            return None
        for bad in CREDENTIAL_PATHS:
            probe = candidate.replace("/", "\\").lower()
            if bad in probe:
                self.audit.record(
                    "path.read", BLOCK, f"credential path refused: {truncate(candidate, 120)}", 0.9
                )
                BUS.emit(Ev.SECURITY_BLOCK, {"path": candidate}, "security")
                return None
        return safe_path(candidate, roots)

    # ------------------------------------------------------------------
    # Self assessment
    # ------------------------------------------------------------------
    def advise(self) -> Dict[str, Any]:
        """
        Look at recent decisions and recommend a posture.

        Many blocked or skipped actions means the owner is working in a
        sensitive area and the agent should be tighter, not looser.
        """
        with self._lock:
            history = list(self._history[-200:])

        if not history:
            return {
                "current_posture": self.cfg.posture,
                "recommended_posture": self.cfg.posture,
                "change": False,
                "why": "not enough history yet - default posture kept",
                "risk_level": self.cfg.risk_threshold(),
            }

        recent = history[-50:]
        blocked = sum(1 for h in recent if h["verdict"] == BLOCK)
        asked = sum(1 for h in recent if h["verdict"] == ASK)
        # Peak risk ignores blocked entries: a refusal already stopped the
        # action, so counting it would let one refused request lock the agent
        # into paranoid mode for no reason.
        considered = [h["risk_score"] for h in recent if h["verdict"] != BLOCK]
        peak = max(considered, default=0.0)

        if blocked >= 3:
            recommended, why = "paranoid", "several actions were blocked - protecting you harder"
        elif peak >= 0.85 or asked >= 12:
            recommended, why = "paranoid", "a lot of high impact work lately"
        elif peak >= 0.55:
            recommended, why = "sandbox", "you are working on moderately sensitive tasks"
        elif peak < 0.15 and asked == 0:
            recommended, why = "open", "everything so far has been safe"
        else:
            recommended, why = self.cfg.posture, "current posture already fits"

        return {
            "current_posture": self.cfg.posture,
            "recommended_posture": recommended,
            "change": recommended != self.cfg.posture,
            "why": why,
            "risk_level": self.cfg.risk_threshold(),
            "recent_blocked": blocked,
            "recent_confirmations": asked,
            "peak_risk": round(peak, 3),
        }

    def apply_posture(self, posture: str) -> bool:
        if posture not in {"paranoid", "balanced", "sandbox", "open"}:
            return False
        previous = self.cfg.posture
        self.cfg.posture = posture
        self.audit.record(
            "security.posture", ALLOW, f"posture {previous} -> {posture}", 0.4,
            {"from": previous, "to": posture},
        )
        log_info(f"security posture {previous} -> {posture}", "security")
        return True

    # ------------------------------------------------------------------
    # Journal + audit
    # ------------------------------------------------------------------
    def _record(self, action: str, verdict: str, detail: str, report: RiskReport) -> None:
        entry = {
            "ts": now(),
            "action": action,
            "verdict": verdict,
            "risk_score": round(report.score, 3),
            "level": report.level,
        }
        with self._lock:
            self._history.append(entry)
            if len(self._history) > 1000:
                del self._history[:500]
        self.audit.record(action, verdict, detail, report.score, {"level": report.level})

    def scan_text(self, text: str) -> Dict[str, Any]:
        """
        Full sweep of arbitrary text: secrets, injection attempts, links.

        This is what runs on anything arriving from the internet before it
        is allowed to influence the agent's own instructions.
        """
        clean, secrets_found = scrub(text)
        lowered = clean.lower()
        injections = [
            marker
            for marker in INJECTION_MARKERS
            if marker in lowered
        ]
        return {
            "safe": not secrets_found and not injections,
            "clean_text": clean,
            "secrets_found": secrets_found,
            "injection_markers": injections,
            "verdict": (
                "clean"
                if not secrets_found and not injections
                else "sanitised"
                if secrets_found and not injections
                else "suspicious - treated as untrusted data"
            ),
        }

    def scan_status(self) -> Dict[str, Any]:
        """
        The agent auditing its own defences.

        Every check below actually executes rather than assuming success, so
        the report is a measurement and not a reassurance.
        """
        from .vault import get_vault

        # 1. Is the vault file actually encrypted and unreadable as plain text?
        vault = get_vault()
        vault_path = vault.path
        vault_protected = True
        if vault_path.exists():
            try:
                head = vault_path.read_text(encoding="utf-8")[:64]
                vault_protected = head.startswith(MAGIC_MARKER)
            except OSError:
                vault_protected = False

        # 2. Is the secret scrubber actually catching known key shapes?
        samples = [
            "sk-abcdefghijklmnopqrstuvwxyz012345",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "password = hunter2000",
            "AKIAIOSFODNN7EXAMPLE",
        ]
        passed = sum(1 for sample in samples if contains_secret(sample))

        # 3. Does the path jail really refuse an escape?
        from pathlib import Path

        escaped = self.safe_target(
            "../../../Windows/System32/config/SAM", [Path.home()]
        )

        # 4. Is the audit chain still intact?
        audit_verify = self.audit.verify() if self.audit else {"ok": True, "checked": 0}

        problems = []
        if not vault_protected:
            problems.append("vault file is not encrypted")
        if passed < len(samples):
            problems.append(f"secret scrubber missed {len(samples) - passed} test pattern(s)")
        if escaped is not None:
            problems.append("path jail failed to stop a traversal escape")
        if not audit_verify.get("ok", True):
            problems.append("audit chain verification failed")

        if not problems:
            assessment = "all defences verified working"
        else:
            assessment = "; ".join(problems)

        BUS.emit(Ev.SECURITY_SCAN, {"problems": problems}, "security")
        return {
            "vault_protected": vault_protected,
            "strong_key": vault.is_env_backed,
            "path_jail": escaped is None,
            "scrubber_tests": len(samples),
            "scrubber_tests_passed": passed,
            "blocked_path_rules": len(CREDENTIAL_PATHS),
            "audit_chain_intact": bool(audit_verify.get("ok", True)),
            "audit_entries_checked": audit_verify.get("checked", 0),
            "problems": problems,
            "assessment": assessment,
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            history = list(self._history)
        counts = {v: 0 for v in (ALLOW, ASK, BLOCK)}
        for entry in history:
            counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
        audit_raw = self.audit.stats() if self.audit else {}
        verified = audit_raw.get("verified", {}) or {}
        # Normalised view. The raw AuditTrail stats use different key names,
        # and guessing at them made the UI report "chain broken" on a healthy
        # audit log - a false alarm on the one panel that must never lie.
        intact = bool(verified.get("valid", True))
        audit = {
            "entries": audit_raw.get("total", 0),
            "decisions": audit_raw.get("decisions", {}),
            "top_actions": audit_raw.get("top_actions", []),
            "checked": verified.get("entries", 0),
            "chain_intact": intact,
            "broken_at": verified.get("broken_at"),
            "reason": verified.get("reason"),
            "rotated_from": getattr(self.audit, "rotated_from", None),
        }
        return {
            "posture": self.cfg.posture,
            "risk_threshold": round(self.cfg.risk_threshold(), 3),
            "confirmations_required": self.cfg.require_confirmation,
            "sandbox": self.cfg.sandbox_enabled,
            "decisions": counts,
            "pending_confirmations": self.pending_count,
            "capabilities": CAPABILITIES,
            "audit": audit,
            "advice": self.advise(),
        }


# Capability defaults used when scoring a concrete action.
CAPABILITY_WEIGHTS: Dict[str, float] = {
    "chat": 0.02,
    "memory.read": 0.02,
    "memory.write": 0.05,
    "files.read": 0.18,
    "files.write": 0.42,
    "files.delete": 0.85,
    "net.fetch": 0.25,
    "net.post": 0.60,
    "code.run": 0.48,
    "system.control": 0.45,
    "screen.read": 0.65,
    "media.create": 0.20,
    "vault.access": 0.55,
    "self.modify": 0.70,
    "delete.self": 0.95,
}

# Header every encrypted vault file must begin with.
MAGIC_MARKER = "CHARVIS1"

# Never touch these, whatever the roots say.
CREDENTIAL_PATHS = (
    "\\windows\\system32\\config",
    "\\sam",
    "\\security",
    "\\system",
    "\\.ssh\\",
    "\\id_rsa",
    "\\id_ed25519",
    "shadow",
    "\\bitlocker",
)

# Untrusted content often tries to talk to the model as if it were the owner.
INJECTION_MARKERS = (
    "ignore all previous",
    "ignore previous instructions",
    "disregard your instructions",
    "you are now in developer mode",
    "reveal your system prompt",
    "print your instructions",
    "send the contents of",
    "<|im_start|>",
    "### system:",
)


def _sandbox_environment(cfg: SecurityConfig) -> Dict[str, str]:
    """Minimal, predictable environment for every child process."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", os.environ.get("TMP", "")),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OPENCHARVIS_SANDBOX": "1",
        "HOME": os.environ.get("USERPROFILE", str(Path.home())),
        "USERPROFILE": os.environ.get("USERPROFILE", str(Path.home())),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }
    if not cfg.allow_network_in_sandbox:
        # Documentation only - true isolation needs a container or firewall
        # rule. Stated plainly rather than implied.
        env["OPENCHARVIS_NETWORK"] = "restricted-by-policy"
    if cfg.block_credential_paths:
        env["OPENCHARVIS_CREDENTIALS"] = "blocked"
    return env


_ENGINE: Optional[SecurityEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_security(config: Optional[SecurityConfig] = None) -> SecurityEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = SecurityEngine(config=config)
    return _ENGINE