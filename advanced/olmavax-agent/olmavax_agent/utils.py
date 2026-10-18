"""Olmavax Agent - Shared utilities (standard library only)."""

from __future__ import annotations

import json
import math
import os
import random
import re
import socket
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus, urlparse

# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

_START = time.time()


def now() -> float:
    return time.time()


def uptime() -> float:
    return time.time() - _START


def stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def clock() -> str:
    return time.strftime("%H:%M:%S")


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def today() -> str:
    return time.strftime("%Y-%m-%d")


def relative(ts: float) -> str:
    delta = time.time() - ts
    if delta < 60:
        return "abhi"
    if delta < 3600:
        return f"{int(delta // 60)} minute pehle"
    if delta < 86400:
        return f"{int(delta // 3600)} ghante pehle"
    return f"{int(delta // 86400)} din pehle"


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace. Keeps Hindi intact."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", " ").replace("\xa0", " ")
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return re.sub(r"\s+", " ", text).strip().lower()


def tokens(text: str) -> List[str]:
    return _WORD_RE.findall(normalize_text(text))


def token_set(text: str) -> set:
    return set(tokens(text))


def strip_accents(text: str) -> str:
    """Remove latin accents but never touch Devanagari."""
    out = []
    for ch in unicodedata.normalize("NFKC", text):
        if "ऀ" <= ch <= "ॿ":      # Devanagari range - keep as is
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFD", ch)
        if decomposed != ch and not ("ऀ" <= ch <= "ॿ"):
            out.append("".join(c for c in decomposed if not unicodedata.combining(c)))
        else:
            out.append(ch)
    return "".join(out)


def truncate(text: str, limit: int = 220, suffix: str = "...") -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def titleize(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in text.split())


def slugify(text: str) -> str:
    text = strip_accents(normalize_text(text))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "item"


def words(text: str) -> int:
    return len(tokens(text))


def reading_time(text: str) -> float:
    return round(words(text) / 200.0, 1)


# --------------------------------------------------------------------------
# Hinglish / Hindi bridge
# --------------------------------------------------------------------------

HINDI_TO_ENGLISH = {
    # questions
    "kya": "what", "kyu": "why", "kyun": "why", "kyada": "how much",
    "kaise": "how", "kab": "when", "kahan": "where", "kaun": "who",
    "konsa": "which", "kaunsa": "which", "kitna": "how much",
    "kitne": "how many", "batao": "tell", "bata": "tell",
    # verbs
    "karo": "do", "kar": "do", "karna": "do", "kardo": "do",
    "chalao": "run", "chala": "run", "kholo": "open", "band": "close",
    "bandh": "close", "band": "close", "banao": "make", "bana": "make",
    "bana": "make", "dikh": "show", "dikhdo": "show", "dikhawa": "show",
    "bolo": "speak", "bol": "speak", "bolo": "speak", "sun": "listen",
    "yaad": "remember", "bhool": "forget", "dhundo": "find", "dhoondo": "find",
    "likho": "write", "padho": "read", "sikho": "learn", "seekho": "learn",
    "samjha": "explain", "sambha": "explain", "banao": "create",
    "theek": "fix", "sudhar": "fix", "badlo": "change", "badal": "change",
    "shuru": "start", "ruk": "stop", "baith": "sit", "soch": "think",
    # particles
    "hai": "is", "hain": "are", "ho": "be", "tha": "was", "thi": "was",
    "mera": "my", "meri": "my", "mujhe": "me", "mujhko": "me",
    "tujhe": "you", "tum": "you", "aap": "you", "abhi": "now",
    "phir": "then", "baad": "after", "pehle": "before", "yaha": "here",
    "waha": "there", "sab": "all", "sabko": "everyone", "kuchh": "some",
    "kuch": "some", "bhi": "also", "nahi": "not", "haan": "yes",
    "mat": "not", "aur": "and", "lekin": "but", "ya": "or", "jab": "when",
    "jahan": "where", "kyunki": "because", "isliye": "therefore",
    "mera": "my", "apna": "own", "khud": "self", "waqt": "time",
    "ghar": "home", "kaam": "work", "file": "file", "program": "program",
    "band karo": "shutdown", "chalu": "on", "off": "off", "on": "on",
}

HINDI_NUMBERS = {
    "zero": 0, "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "gyarah": 11,
    "barah": 12, "tere": 13, "chaudah": 14, "pandrah": 15, "solah": 16,
    "satrah": 17, "atharah": 18, "unnees": 19, "bees": 20, "tees": 30,
    "saees": 60, "ek sau": 100, "sau": 100, "hazaar": 1000,
}


def hinglish_to_english(text: str) -> str:
    """Best-effort transliteration of spoken Hindi into search-friendly English."""
    low = normalize_text(text)
    for src, dst in HINDI_TO_ENGLISH.items():
        low = low.replace(src, dst)
    return low.strip()


def hindi_number(text: str) -> Optional[int]:
    """'sau bees' -> 120. Returns None when not a number phrase."""
    low = normalize_text(text).strip()
    if not low:
        return None
    if low.isdigit():
        return int(low)
    if " " in low:
        total = 0
        matched = False
        for part in reversed(low.split()):
            if part in HINDI_NUMBERS:
                total += HINDI_NUMBERS[part]
                matched = True
        return total if matched else None
    return HINDI_NUMBERS.get(low)


# --------------------------------------------------------------------------
# Math / vectors
# --------------------------------------------------------------------------


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def magnitude(vec: Sequence[float]) -> float:
    return math.sqrt(dot(vec, vec))


def normalize_vector(vec: List[float]) -> List[float]:
    mag = magnitude(vec)
    if mag == 0:
        return vec
    return [v / mag for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = magnitude(a), magnitude(b)
    if na == 0 or nb == 0:
        return 0.0
    return clamp(dot(a, b) / (na * nb), -1.0, 1.0)


# --------------------------------------------------------------------------
# Filesystem
# --------------------------------------------------------------------------


def safe_path(candidate: str, roots: Iterable[Path]) -> Optional[Path]:
    """Resolve ``candidate`` and confirm it stays inside one of ``roots``."""
    try:
        raw = Path(candidate).expanduser()
        target = raw.resolve() if raw.exists() else Path(os.path.normpath(str(raw.absolute())))
    except (OSError, ValueError):
        return None
    for root in roots:
        try:
            root_res = root.resolve()
        except OSError:
            continue
        try:
            target.relative_to(root_res)
            return target
        except ValueError:
            continue
    return None


def human_size(num_bytes: float) -> str:
    step = 1024.0
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < step:
            return f"{num_bytes:,.1f} {unit}"
        num_bytes /= step
    return f"{num_bytes:,.1f} PB"


def file_fingerprint(path: Path, limit: int = 2_000_000) -> str:
    """Fast content hash so the agent notices when a file changes."""
    import hashlib

    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            read = 0
            while read < limit:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
                read += len(chunk)
    except OSError:
        return ""
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------
# Networking (stdlib urllib - no hard dependency on `requests`)
# --------------------------------------------------------------------------

USER_AGENT = "Olmavax Agent/2.0 (+personal-agent)"


def net_available(host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_get(
    url: str,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
    max_bytes: int = 3_000_000,
) -> Tuple[int, str]:
    """GET a URL, return (status, text). Never raises."""
    import urllib.error
    import urllib.request

    if not url.lower().startswith(("http://", "https://")):
        return 0, "unsupported scheme"

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return 0, ""


def http_post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> Tuple[int, str]:
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, str(exc)


def http_get_bytes(
    url: str,
    timeout: int = 60,
    headers: Optional[Dict[str, str]] = None,
    max_bytes: int = 25_000_000,
) -> Tuple[int, bytes, str]:
    """
    GET a URL and return ``(status, raw_bytes, content_type)``.

    ``http_get`` decodes to text, which corrupts binary payloads such as
    images - a JPEG becomes mojibake and fails the header check. Anything
    that downloads a file must use this instead.
    """
    import urllib.error
    import urllib.request

    if not url.lower().startswith(("http://", "https://")):
        return 0, b"", "unsupported scheme"

    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.read(max_bytes),
                response.headers.get_content_type(),
            )
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()[:65536], ""
        except Exception:
            return exc.code, b"", ""
    except Exception as exc:
        return 0, str(exc).encode("utf-8", "replace"), ""


def is_url(text: str) -> bool:
    try:
        parsed = urlparse(text.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def domain_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def search_url(query: str, engine: str = "duckduckgo") -> str:
    q = quote_plus(query)
    engines = {
        "duckduckgo": f"https://duckduckgo.com/html/?q={q}",
        "google": f"https://www.google.com/search?q={q}",
        "bing": f"https://www.bing.com/search?q={q}",
        "wikipedia": f"https://en.wikipedia.org/w/index.php?search={q}",
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "maps": f"https://www.openstreetmap.org/search?query={q}",
    }
    return engines.get(engine, engines["duckduckgo"])


# --------------------------------------------------------------------------
# HTML -> text (no bs4 needed)
# --------------------------------------------------------------------------


def html_to_text(html: str) -> str:
    if not html:
        return ""
    html = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|tr|h[1-6]|section|article)>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    for entity, char in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&mdash;", "-"), ("&ndash;", "-"),
    ):
        html = html.replace(entity, char)
    html = re.sub(r"[ \t]{2,}", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def extract_links(html: str, base_domain: str = "") -> List[str]:
    links = re.findall(r'(?is)<a[^>]+href=["\']([^"\'#]+)["\']', html)
    out = []
    for link in links:
        link = link.strip()
        if link.startswith(("http://", "https://")):
            if not base_domain or base_domain in link:
                out.append(link)
        elif link.startswith("/") and base_domain:
            out.append(f"https://{base_domain}{link}")
    seen, unique = set(), []
    for link in out:
        if link not in seen:
            seen.add(link)
            unique.append(link)
    return unique


def extract_title(html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    return html_to_text(match.group(1)) if match else ""


# --------------------------------------------------------------------------
# System
# --------------------------------------------------------------------------


def open_external(target: str) -> bool:
    """Open a URL / file / folder with the OS default handler."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception:
        return False


def system_summary() -> Dict[str, Any]:
    """Best-effort machine facts, uses psutil when present."""
    info: Dict[str, Any] = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
        "cpus": os.cpu_count(),
    }
    try:
        import psutil  # type: ignore

        info["cpu_percent"] = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        info["ram_total"] = human_size(mem.total)
        info["ram_used"] = human_size(mem.used)
        info["ram_percent"] = mem.percent
        info["battery"] = (
            f"{psutil.sensors_battery().percent}%" if psutil.sensors_battery() else "n/a"
        )
        disk = psutil.disk_usage(str(Path.home()))
        info["disk_total"] = human_size(disk.total)
        info["disk_used"] = human_size(disk.used)
        info["disk_percent"] = disk.percent
    except Exception:
        pass
    return info


def run_command(
    args: Sequence[str],
    timeout: int = 25,
    cwd: Optional[str] = None,
    input_text: Optional[str] = None,
) -> Tuple[int, str, str]:
    """Run a subprocess safely. Returns (code, stdout, stderr)."""
    try:
        completed = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            input=input_text,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform.startswith("win")
            else 0,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"command not found: {args[0] if args else ''}"
    except Exception as exc:
        return -3, "", str(exc)


def fuzzy_match(needle: str, haystack: Sequence[str], cutoff: float = 0.55) -> Optional[str]:
    """Cheap fuzzy matcher (difflib backed) for command correction."""
    import difflib

    needle_l = normalize_text(needle)
    matches = difflib.get_close_matches(needle_l, list(haystack), n=1, cutoff=cutoff)
    return matches[0] if matches else None


def pluralize(count: int, singular: str, plural: Optional[str] = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural or singular + 's'}"


@dataclass
class Timer:
    label: str = ""
    start: float = 0.0

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed = time.perf_counter() - self.start

    @property
    def ms(self) -> float:
        return (time.perf_counter() - self.start) * 1000.0