"""
Open Charvis - Configuration
===========================
Central, overridable settings for the whole agent.

Everything lives under one folder so the agent is fully portable and
self-contained.  No writes ever happen outside ``OpenCharvisHome``.

Precedence (low -> high):
    1. defaults in this file
    2. config.json inside the home folder
    3. environment variables prefixed ``CHARVIS_``
    4. explicit runtime arguments
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "Open Charvis"
APP_VERSION = "2.1.0"
APP_TAGLINE = "Your personal self-evolving AI"
CODENAME = "CHARVIS-CORE"

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def default_home() -> Path:
    """Where the agent keeps its brain, memory, logs and vault."""
    override = os.environ.get("CHARVIS_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "OpenCharvis"
    return Path(os.path.expanduser("~")) / ".opencharvis"


HOME = default_home()

PATHS = {
    "home": HOME,
    "brain": HOME / "brain",
    "memory": HOME / "memory",
    "memory_db": HOME / "memory" / "charvis_memory.sqlite3",
    "skills": HOME / "skills",
    "learned_skills": HOME / "skills" / "learned",
    "library": HOME / "library",
    "vault": HOME / "vault",
    "vault_file": HOME / "vault" / "secrets.enc",
    "logs": HOME / "logs",
    "audit_log": HOME / "logs" / "audit.log",
    "chat_log": HOME / "logs" / "chat.jsonl",
    "error_log": HOME / "logs" / "charvis.log",
    "curriculum": HOME / "curriculum",
    "cache": HOME / "cache",
    "config_file": HOME / "config.json",
    "identity": HOME / "identity.json",
    "models": HOME / "models",
    "exports": HOME / "exports",
}


def ensure_dirs() -> None:
    """Create every managed directory. Safe to call repeatedly."""
    for key, path in PATHS.items():
        if key.endswith("_file") or key in {"config_file", "memory_db", "audit_log",
                                            "chat_log", "error_log"}:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Security posture
# --------------------------------------------------------------------------


@dataclass
class SecurityConfig:
    """How careful the agent is before doing something."""

    # "paranoid" | "balanced" | "sandbox" | "open"
    posture: str = "balanced"

    # Every mutating / dangerous action needs a spoken confirmation
    require_confirmation: bool = True
    confirmation_phrases: List[str] = field(
        default_factory=lambda: ["haan", "yes", "confirm", "kar do", "abhi karo"]
    )
    deny_phrases: List[str] = field(
        default_factory=lambda: ["nahi", "no", "cancel", "ruk jao", "mat karo"]
    )

    # Hard blocks - never runs, not even with confirmation
    block_registry_edit: bool = True
    block_credential_paths: bool = True
    block_mass_delete: bool = True
    block_disk_raw_write: bool = True

    # Execution sandbox
    sandbox_enabled: bool = True
    process_timeout_seconds: int = 25
    max_output_chars: int = 100_000
    max_input_chars: int = 8_000
    max_memory_mb: int = 1024
    allow_network_in_sandbox: bool = False
    allowed_commands: List[str] = field(default_factory=lambda: ["python", "py", "node"])

    # Vault
    encrypt_vault: bool = True
    vault_master_key_env: str = "CHARVIS_MASTER_KEY"

    # Audit
    audit_enabled: bool = True
    tamper_evident_log: bool = True

    def risk_threshold(self) -> float:
        """Score above which we ask the human."""
        return {
            "paranoid": 0.10,
            "balanced": 0.35,
            "sandbox": 0.60,
            "open": 0.90,
        }.get(self.posture, 0.35)


# --------------------------------------------------------------------------
# Brain
# --------------------------------------------------------------------------


@dataclass
class BrainConfig:
    """LLM + reasoning configuration."""

    # provider: "auto" | "ollama" | "openai" | "groq" | "anthropic" | "gemini"
    #           | "together" | "offline"
    provider: str = "auto"

    model: str = "auto"
    fallback_model: str = "auto"

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"

    openai_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    groq_base: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"
    together_base: str = "https://api.together.xyz/v1"
    together_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    gemini_base: str = "https://generativelanguage.googleapis.com/v1beta/models"
    gemini_model: str = "gemini-2.0-flash"
    anthropic_base: str = "https://api.anthropic.com/v1"
    anthropic_model: str = "claude-3-5-sonnet-latest"

    api_key_env: Dict[str, str] = field(
        default_factory=lambda: {
            "openai": "CHARVIS_OPENAI_KEY",
            "groq": "CHARVIS_GROQ_KEY",
            "together": "CHARVIS_TOGETHER_KEY",
            "gemini": "CHARVIS_GEMINI_KEY",
            "anthropic": "CHARVIS_ANTHROPIC_KEY",
        }
    )

    temperature: float = 0.55
    max_tokens: int = 1400
    timeout_seconds: int = 60
    max_retries: int = 2

    # Local reasoning (always on, even with no LLM)
    enable_reflection: bool = True
    reflection_rounds: int = 1
    enable_planner: bool = True
    context_messages: int = 12
    memory_recall_limit: int = 6


# --------------------------------------------------------------------------
# Voice
# --------------------------------------------------------------------------


@dataclass
class VoiceConfig:
    enabled: bool = True
    wake_words: List[str] = field(
        default_factory=lambda: ["charvis", "jarvis", "hey charvis", "open charvis"]
    )
    require_wake_word: bool = True
    language: str = "hi-IN"
    fallback_language: str = "en-US"
    stt_engine: str = "auto"          # auto | whisper | google | sphinx | vosk
    tts_engine: str = "auto"          # auto | edge | sapi | pyttsx3 | console
    tts_rate: int = 185
    tts_volume: float = 1.0
    speak_responses: bool = True
    speak_confirmations: bool = False
    hindi_boost: bool = True
    mic_energy_threshold: int = 350
    listen_timeout: float = 7.0
    phrase_time_limit: float = 9.0


# --------------------------------------------------------------------------
# Memory + learning
# --------------------------------------------------------------------------


@dataclass
class MemoryConfig:
    embedding_dim: int = 256
    short_term_turns: int = 12
    max_episodes: int = 200_000
    decay_half_life_days: float = 30.0
    min_recall_score: float = 0.16
    auto_summarise_every: int = 40
    keep_summaries: bool = True


@dataclass
class LearningConfig:
    enabled: bool = True
    learn_from_corrections: bool = True
    auto_create_skills: bool = True
    min_repeats_before_skill: int = 3
    skill_promote_score: float = 0.75
    skill_demote_score: float = 0.30
    internet_learning_enabled: bool = True
    curriculum_max_pages: int = 25
    fetch_timeout: int = 20
    allowed_learn_domains: List[str] = field(
        default_factory=lambda: [
            "docs.python.org", "pypi.org", "wikipedia.org", "arxiv.org",
            "developer.mozilla.org", "stackoverflow.com", "github.com",
            "readthedocs.io", "platform.openai.com", "ollama.com",
        ]
    )


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------


@dataclass
class UIConfig:
    theme: str = "arc"                  # arc | matrix | light
    fps: int = 30
    avatar_quality: int = 2            # 0 low, 1 medium, 2 high, 3 ultra
    avatar_size: int = 520
    window_size: str = "1180x760"
    always_on_top: bool = True
    animate_avatar: bool = True
    scanlines: bool = True
    particle_count: int = 180
    show_fps: bool = True


# --------------------------------------------------------------------------
# Root config
# --------------------------------------------------------------------------


@dataclass
class Config:
    name: str = APP_NAME
    codename: str = CODENAME
    version: str = APP_VERSION
    owner: str = "Boss"

    language: str = "hi"
    debug: bool = False
    autostart: bool = True
    telemetry: bool = False
    working_dir: str = str(Path.home())

    security: SecurityConfig = field(default_factory=SecurityConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        """Build config from defaults + config.json + environment."""
        cfg = cls()
        target = Path(path) if path else PATHS["config_file"]
        if target.exists():
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                cfg = _merge(cfg, raw)
            except Exception as exc:  # never crash on a bad config
                print(f"[config] could not read {target}: {exc}")
        cfg._apply_env()
        return cfg

    def _apply_env(self) -> None:
        def env(name: str, cast=str):
            raw = os.environ.get(f"CHARVIS_{name.upper()}")
            if raw is None:
                return None
            try:
                return cast(raw)
            except (TypeError, ValueError):
                return raw

        self.owner = env("owner", str) or self.owner
        self.debug = bool(env("debug", lambda v: v.lower() in {"1", "true", "yes"}))
        self.language = env("language", str) or self.language
        self.security.posture = env("posture", str) or self.security.posture
        self.security.require_confirmation = bool(
            env("confirm", lambda v: v.lower() in {"1", "true", "yes"})
        ) or self.security.require_confirmation
        self.brain.provider = env("provider", str) or self.brain.provider
        self.brain.model = env("model", str) or self.brain.model
        self.voice.enabled = bool(
            env("voice", lambda v: v.lower() in {"1", "true", "yes"})
        ) or self.voice.enabled

    # ------------------------------------------------------------------
    def save(self, path: Optional[str] = None) -> Path:
        target = Path(path) if path else PATHS["config_file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target

    def describe(self) -> str:
        lines = [
            f"{self.name} v{self.version} ({self.codename})",
            f"  owner        : {self.owner}",
            f"  language     : {self.language}",
            f"  home         : {HOME}",
            f"  security     : {self.security.posture} "
            f"(ask above risk {self.security.risk_threshold():.0%})",
            f"  brain        : {self.brain.provider} / {self.brain.model}",
            f"  voice        : {'on' if self.voice.enabled else 'off'} "
            f"(wake: {', '.join(self.voice.wake_words)})",
            f"  learning     : {'on' if self.learning.enabled else 'off'}",
            f"  sandbox      : {'on' if self.security.sandbox_enabled else 'off'}",
            f"  audit trail  : {'on' if self.security.audit_enabled else 'off'}",
        ]
        return "\n".join(lines)


_CONFIG: Optional[Config] = None
_CONFIG_LOCK = threading.Lock()


def get_config(reload: bool = False) -> Config:
    """
    The one shared configuration object.

    Loaded once from ``config.json`` plus ``CHARVIS_*`` environment
    variables.  Pass ``reload=True`` to re-read from disk, for example
    after changing a setting from the UI.
    """
    global _CONFIG
    if _CONFIG is None or reload:
        with _CONFIG_LOCK:
            if _CONFIG is None or reload:
                _CONFIG = Config.load()
    return _CONFIG


def set_config(config: Config) -> Config:
    """Replace the shared config (used by tests and by the settings UI)."""
    global _CONFIG
    with _CONFIG_LOCK:
        _CONFIG = config
    return _CONFIG


def _merge(obj: Any, raw: Dict[str, Any]) -> Any:
    for key, value in raw.items():
        if not hasattr(obj, key):
            continue
        current = getattr(obj, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            setattr(obj, key, _merge(current, value))
        else:
            setattr(obj, key, value)
    return obj


# --------------------------------------------------------------------------
# Optional-dependency probe
# --------------------------------------------------------------------------

OPTIONAL_PACKAGES = {
    "flask": "Web dashboard + REST API",
    "pyttsx3": "Offline text-to-speech",
    "edge_tts": "Natural Microsoft voices (needs internet)",
    "speech_recognition": "Online speech-to-text",
    "vosk": "Fully offline speech-to-text",
    "whisper": "Best local speech-to-text (slow but accurate)",
    "pycaw": "Windows volume control",
    "psutil": "Process control + system stats",
    "cryptography": "Real AES vault encryption",
    "PIL": "Image generation + file previews",
    "pygame": "Alternative audio playback",
    "requests": "Faster HTTP (stdlib works fine too)",
    "numpy": "Faster math (stdlib works fine too)",
    "sentence_transformers": "True semantic embeddings",
    "pyotp": "Two-factor codes in the vault",
}


def available() -> Dict[str, bool]:
    """Report which optional extras are importable."""
    import importlib.util

    return {name: importlib.util.find_spec(name) is not None for name in OPTIONAL_PACKAGES}


def capability_report() -> str:
    """Human readable list of what this machine can do."""
    state = available()
    lines = ["Capability report", "------------------"]
    for name, purpose in OPTIONAL_PACKAGES.items():
        mark = "YES" if state.get(name) else " no"
        lines.append(f"  [{mark}] {name:<24} {purpose}")
    lines.append("")
    lines.append("Core agent works with ZERO extras installed (standard library only).")
    return "\n".join(lines)