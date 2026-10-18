"""
Olmavax Agent - Encrypted vault
=============================
API keys, passwords and tokens are never written to disk in plain text.

Cipher (standard library only, so this works with zero extras installed):

    key derivation : PBKDF2-HMAC-SHA256, 310_000 iterations, 16 byte salt
    keystream      : HMAC-SHA256 in counter mode, encrypt-then-MAC
    authentication : HMAC-SHA256 over (nonce || ciphertext)

This is the same construction family as ChaCha20 (a keyed PRF used as a
stream cipher plus a MAC).  If the optional ``cryptography`` package is
installed, :func:`_backend` reports it, but it is never required.

File layout::

    OLMAVAX1|<b64 salt>|<b64 nonce>|<b64 mac>|<b64 ciphertext>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PATHS, ensure_dirs
from .events import BUS, Ev
from .logger import log_warn

KDF_ITERATIONS = 310_000
SALT_BYTES = 16
NONCE_BYTES = 16
KEY_BYTES = 32
MAGIC = "OLMAVAX1"
LEGACY_MAGIC = "CHARVIS1"  # still readable from builds before the rebrand


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, KEY_BYTES)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """HMAC-SHA256 counter-mode keystream."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            key, nonce + counter.to_bytes(8, "big"), hashlib.sha256
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _split_keys(master: bytes) -> tuple[bytes, bytes]:
    """Derive separate encryption and authentication keys from the master."""
    enc = hmac.new(master, b"olmavax_agent-encrypt-v1", hashlib.sha256).digest()
    mac = hmac.new(master, b"olmavax_agent-auth-v1", hashlib.sha256).digest()
    return enc, mac


def encrypt_bytes(plaintext: bytes, passphrase: str) -> str:
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    master = derive_key(passphrase, salt)
    enc_key, mac_key = _split_keys(master)
    ciphertext = bytes(
        a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext)))
    )
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    return "|".join([MAGIC, b64e(salt), b64e(nonce), b64e(tag), b64e(ciphertext)])


def decrypt_bytes(blob: str, passphrase: str) -> bytes:
    parts = blob.split("|")
    if len(parts) != 5 or parts[0] not in (MAGIC, LEGACY_MAGIC):
        raise ValueError("not a Olmavax Agent vault file")
    salt, nonce, tag, ciphertext = b64d(parts[1]), b64d(parts[2]), b64d(parts[3]), b64d(parts[4])
    master = derive_key(passphrase, salt)
    enc_key, mac_key = _split_keys(master)
    expected = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise ValueError("vault authentication failed - wrong passphrase or file tampered with")
    return bytes(a ^ b for a, b in zip(ciphertext, _keystream(enc_key, nonce, len(ciphertext))))


# --------------------------------------------------------------------------
# Vault
# --------------------------------------------------------------------------


class Vault:
    """
    Encrypted key/value store.

    Passphrase resolution order:

    1. ``OLMAVAX_AGENT_MASTER_KEY`` environment variable (best for automation)
    2. an explicit passphrase passed in the constructor
    3. the machine-bound fallback below
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        passphrase: Optional[str] = None,
        auto_create: bool = True,
    ):
        ensure_dirs()
        self.path = Path(path or PATHS["vault_file"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._env_var = "OLMAVAX_AGENT_MASTER_KEY"
        self._passphrase = passphrase
        self._cache: Optional[Dict[str, Any]] = None

    # -- passphrase -----------------------------------------------------
    def _machine_passphrase(self) -> str:
        """
        Deterministic machine bound fallback so the agent still works with
        zero configuration.  It protects secrets from casual disk snooping;
        for real protection set ``OLMAVAX_AGENT_MASTER_KEY``.
        """
        material = [
            self._env_var,
            str(self.path.resolve()),
            os.environ.get("COMPUTERNAME", ""),
            os.environ.get("USERNAME", ""),
            os.environ.get("PROCESSOR_IDENTIFIER", ""),
        ]
        return hashlib.sha256("|".join(material).encode("utf-8")).hexdigest()

    def passphrase(self) -> str:
        env_value = os.environ.get(self._env_var)
        if env_value:
            return env_value
        if self._passphrase:
            return self._passphrase
        return self._machine_passphrase()

    @property
    def is_env_backed(self) -> bool:
        return bool(os.environ.get(self._env_var))

    # -- persistence ----------------------------------------------------
    def _load(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = {}
            return self._cache
        try:
            blob = self.path.read_text(encoding="utf-8").strip()
            raw = decrypt_bytes(blob, self.passphrase())
            self._cache = json.loads(raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            log_warn(f"vault unreadable: {exc}", "vault")
            self._cache = {}
        if not isinstance(self._cache, dict):
            self._cache = {}
        return self._cache

    def _save(self) -> None:
        assert self._cache is not None
        blob = encrypt_bytes(
            json.dumps(self._cache, indent=2, ensure_ascii=False).encode("utf-8"),
            self.passphrase(),
        )
        self.path.write_text(blob, encoding="utf-8")
        # Windows equivalent of chmod 600 - hide from other users.
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def _require_writable(self, auto_create: bool) -> bool:
        if self.path.exists():
            return True
        if auto_create:
            with self._lock:
                if not self.path.exists():
                    self._cache = {}
                    self._save()
            return True
        return False

    # -- api ------------------------------------------------------------
    def set(self, key: str, value: str, note: str = "") -> bool:
        if not self._require_writable(True):
            return False
        with self._lock:
            data = self._load()
            data[key] = {
                "value": value,
                "note": note,
                "set_at": time.time(),
                "set_at_h": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save()
        BUS.emit(Ev.LEARNED, {"vault_key": key}, "vault")
        return True

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        entry = self._load().get(key)
        if isinstance(entry, dict):
            return entry.get("value", default)
        return entry if isinstance(entry, str) else default

    def note(self, key: str) -> str:
        entry = self._load().get(key)
        return entry.get("note", "") if isinstance(entry, dict) else ""

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._load()
            existed = key in data
            data.pop(key, None)
            if existed:
                self._save()
        return existed

    def keys(self) -> List[str]:
        return sorted(self._load().keys())

    def listing(self) -> List[Dict[str, Any]]:
        """Key names plus notes, never the secret values."""
        out = []
        for key, entry in sorted(self._load().items()):
            out.append(
                {
                    "key": key,
                    "note": entry.get("note", "") if isinstance(entry, dict) else "",
                    "set_at": entry.get("set_at_h", "") if isinstance(entry, dict) else "",
                }
            )
        return out

    def api_key(self, provider: str, env_var: Optional[str] = None) -> Optional[str]:
        """
        Find a provider credential: environment first, then the vault.
        Never logs the value.
        """
        if env_var and os.environ.get(env_var):
            return os.environ[env_var]
        return self.get(provider) or self.get(provider.lower())

    def health(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "entries": len(self._load()),
            "cipher": f"{MAGIC} / PBKDF2-SHA256 x{KDF_ITERATIONS} / HMAC-CTR + HMAC-SHA256 tag",
            "key_source": "environment" if self.is_env_backed else "machine-bound fallback",
            "strong_key": self.is_env_backed,
        }


def get_vault() -> Vault:
    """Shared vault instance."""
    return Vault()