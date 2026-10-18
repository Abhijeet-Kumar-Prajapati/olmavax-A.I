"""
Olmavax Agent - Memory
====================
The agent's long term brain.  Everything it learns lives here so it never
has to be told twice.

Five stores, one SQLite file:

``memories``  facts, preferences, instructions, observations (with vectors)
``episodes``  every goal it tried, what it did, whether it worked
``lessons``   rules it distilled from repeated wins and failures
``prefs``     small key/value settings the owner set by talking
``turns``     rolling short term conversation window

Retrieval is hybrid: SQLite FTS5 keyword search (with a LIKE fallback if
the interpreter has no FTS5) blended with a cosine similarity search over
hashed word vectors.  Both halves are pure standard library, so memory
works with zero third party packages installed.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import PATHS, MemoryConfig, ensure_dirs
from .events import BUS, Ev
from .logger import log_debug, log_warn
from .utils import clamp, cosine, now, normalize_vector, relative, token_set, truncate

# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL DEFAULT 'fact',
    text        TEXT    NOT NULL,
    tags        TEXT    NOT NULL DEFAULT '',
    importance  REAL    NOT NULL DEFAULT 0.5,
    confidence  REAL    NOT NULL DEFAULT 1.0,
    source      TEXT    NOT NULL DEFAULT 'user',
    dim         INTEGER NOT NULL DEFAULT 0,
    vec         BLOB,
    meta        TEXT    NOT NULL DEFAULT '{}',
    created     REAL    NOT NULL,
    last_used   REAL    NOT NULL,
    use_count   INTEGER NOT NULL DEFAULT 0,
    pinned      INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_mem_kind    ON memories(kind);
CREATE INDEX IF NOT EXISTS ix_mem_created ON memories(created DESC);

CREATE TABLE IF NOT EXISTS episodes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    goal      TEXT NOT NULL,
    plan      TEXT NOT NULL DEFAULT '[]',
    steps     TEXT NOT NULL DEFAULT '[]',
    result    TEXT NOT NULL DEFAULT '',
    success   INTEGER NOT NULL DEFAULT 1,
    score     REAL NOT NULL DEFAULT 0.0,
    duration  REAL NOT NULL DEFAULT 0.0,
    tags      TEXT NOT NULL DEFAULT '',
    created   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ep_created ON episodes(created DESC);
CREATE INDEX IF NOT EXISTS ix_ep_success ON episodes(success);

CREATE TABLE IF NOT EXISTS lessons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern    TEXT NOT NULL,
    rule       TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    hits       INTEGER NOT NULL DEFAULT 0,
    misses     INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'reflection',
    created    REAL NOT NULL,
    updated    REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_lesson_pattern ON lessons(pattern);

CREATE TABLE IF NOT EXISTS prefs (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL,
    kind   TEXT NOT NULL DEFAULT 'pref',
    updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    role    TEXT NOT NULL,
    text    TEXT NOT NULL,
    meta    TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_turn_created ON turns(created DESC);
"""

FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts "
    "USING fts5(text, tags, tokenize='unicode61 remove_diacritics 2')"
)


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


@dataclass
class Memory:
    """One remembered thing."""

    id: int
    kind: str
    text: str
    tags: List[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 1.0
    source: str = "user"
    created: float = 0.0
    last_used: float = 0.0
    use_count: int = 0
    pinned: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_days(self) -> float:
        return max(0.0, (now() - self.created) / 86400.0)

    @property
    def strength(self) -> float:
        """How strongly this memory should compete during recall."""
        value = self.importance * 0.55 + self.confidence * 0.25
        value += min(self.use_count, 25) / 25.0 * 0.12
        if self.pinned:
            value += 0.25
        value *= 0.75 ** (self.age_days / 30.0)  # gentle forgetting curve
        return clamp(value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "tags": self.tags,
            "importance": round(self.importance, 3),
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "created": self.created,
            "age": relative(self.created),
            "use_count": self.use_count,
            "pinned": self.pinned,
            "meta": self.meta,
        }


@dataclass
class Recall:
    """A memory plus why it was recalled."""

    memory: Memory
    score: float
    keyword_score: float = 0.0
    semantic_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory": self.memory.to_dict(),
            "score": round(self.score, 4),
            "keyword": round(self.keyword_score, 4),
            "semantic": round(self.semantic_score, 4),
        }


@dataclass
class Lesson:
    id: int
    pattern: str
    rule: str
    confidence: float = 0.5
    hits: int = 0
    misses: int = 0
    source: str = "reflection"
    updated: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pattern": self.pattern,
            "rule": self.rule,
            "confidence": round(self.confidence, 3),
            "hits": self.hits,
            "misses": self.misses,
            "success_rate": round(
                self.hits / (self.hits + self.misses) if (self.hits + self.misses) else 0.0, 3
            ),
            "source": self.source,
            "updated": relative(self.updated),
        }


# --------------------------------------------------------------------------
# Embeddings (hashed bag of words - stable, offline, no model needed)
# --------------------------------------------------------------------------


def embed(text: str, dim: int = 256) -> List[float]:
    """
    Deterministic hashed word vector.

    ``blake2b`` is used rather than ``hash()`` because CPython randomises
    ``hash()`` per process, which would make memories unfindable after a
    restart.
    """
    vec = [0.0] * dim
    buckets = token_set(text)
    if not buckets:
        return vec
    for token in buckets:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[index] += sign
    # Add bigrams so word order carries a little signal.
    words = sorted(buckets)
    for a, b in zip(words, words[1:]):
        digest = hashlib.blake2b(f"{a} {b}".encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        vec[index] += 0.5 * (1.0 if digest[4] & 1 else -1.0)
    return normalize_vector(vec)


def pack_vector(vec: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> List[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


# Suffixes stripped to make "preferences" also find "prefer".
# FTS5's unicode61 tokenizer does not stem, so we do it at query time
# instead of shipping a dictionary.
SUFFIXES = (
    "ations", "ation", "tions", "tion", "ments", "ment", "ences", "ence",
    "ances", "ance", "ities", "ity", "nesses", "ness", "ings", "ing",
    "ers", "er", "ies", "ied", "ed", "es", "s",
)


STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "so", "as",
    "at", "by", "for", "from", "in", "into", "of", "off", "on", "onto", "to",
    "up", "over", "with", "within", "without", "is", "are", "was", "were",
    "be", "been", "being", "am", "do", "does", "did", "doing", "have", "has",
    "had", "having", "will", "would", "shall", "should", "can", "could",
    "may", "might", "must", "this", "that", "these", "those", "it", "its",
    "i", "me", "my", "mine", "myself", "you", "your", "yours", "he", "him",
    "his", "she", "her", "hers", "we", "us", "our", "they", "them", "their",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "all", "any", "some", "each", "every", "no", "not", "only", "own", "same",
    "just", "also", "very", "there", "here", "about", "again", "more", "most",
    "tell", "show", "find", "know", "remember", "please",
})


def stem_variants(term: str, rounds: int = 2) -> List[str]:
    """
    Cheap suffix stripping, standard library only.

    ``preferences`` -> ``preference`` -> ``prefer``.
    Only applied to words long enough that the stem is still meaningful.
    """
    if len(term) < 6:
        return []
    variants: List[str] = []
    current = term
    for _ in range(rounds):
        for suffix in SUFFIXES:
            if len(current) > len(suffix) + 3 and current.endswith(suffix):
                candidate = current[: -len(suffix)]
                if candidate not in variants:
                    variants.append(candidate)
                current = candidate
                break
        else:
            break
    return variants


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


class MemoryStore:
    """
    Thread-safe persistent memory.

    A single connection guarded by an RLock is plenty here: reads dominate
    and every query is sub-millisecond at personal scale.
    """

    def __init__(self, path: Optional[Path] = None, config: Optional[MemoryConfig] = None):
        ensure_dirs()
        self.path = Path(path or PATHS["memory_db"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg = config or MemoryConfig()
        self.dim = max(32, int(self.cfg.embedding_dim))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.has_fts = False
        self._migrate()

    # -- lifecycle ------------------------------------------------------
    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            try:
                self._conn.execute(FTS_SCHEMA)
                self.has_fts = True
            except sqlite3.OperationalError:
                # Python was built without FTS5 - LIKE search still works.
                self.has_fts = False
                log_warn("SQLite FTS5 unavailable, falling back to LIKE search", "memory")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except sqlite3.Error:
                pass

    def _rows_to_memories(self, rows: Iterable[sqlite3.Row]) -> List[Memory]:
        return [self._row_to_memory(r) for r in rows]

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        try:
            tags = [t for t in (row["tags"] or "").split(",") if t]
        except (IndexError, TypeError):
            tags = []
        try:
            meta = json.loads(row["meta"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return Memory(
            id=row["id"],
            kind=row["kind"],
            text=row["text"],
            tags=tags,
            importance=row["importance"],
            confidence=row["confidence"],
            source=row["source"],
            created=row["created"],
            last_used=row["last_used"],
            use_count=row["use_count"],
            pinned=bool(row["pinned"]),
            meta=meta if isinstance(meta, dict) else {},
        )

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def add(
        self,
        text: str,
        kind: str = "fact",
        tags: Optional[Sequence[str]] = None,
        importance: float = 0.5,
        source: str = "user",
        confidence: float = 1.0,
        meta: Optional[Dict[str, Any]] = None,
        deduplicate: bool = True,
    ) -> Optional[Memory]:
        """
        Remember something.

        When ``deduplicate`` is set, a near identical memory that already
        exists is refreshed instead of duplicated, so the store stays clean
        no matter how often the owner repeats themselves.
        """
        text = (text or "").strip()
        if not text:
            return None

        tag_list = sorted({str(t).strip().lower() for t in (tags or []) if str(t).strip()})
        tag_text = ",".join(tag_list)
        ts = now()

        with self._lock:
            if deduplicate:
                existing = self._conn.execute(
                    "SELECT id FROM memories WHERE text = ? LIMIT 1", (text,)
                ).fetchone()
                if existing:
                    self._conn.execute(
                        "UPDATE memories SET importance = MAX(importance, ?), "
                        "use_count = use_count + 1, last_used = ? WHERE id = ?",
                        (clamp(importance), ts, existing["id"]),
                    )
                    self._conn.commit()
                    row = self._conn.execute(
                        "SELECT * FROM memories WHERE id = ?", (existing["id"],)
                    ).fetchone()
                    BUS.emit(Ev.MEMORY_STORED, {"id": row["id"], "deduped": True}, "memory")
                    return self._row_to_memory(row)

            vector = embed(text, self.dim)
            cur = self._conn.execute(
                "INSERT INTO memories (kind, text, tags, importance, confidence, source, "
                "dim, vec, meta, created, last_used, use_count, pinned, archived) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0)",
                (
                    kind,
                    text,
                    tag_text,
                    clamp(importance),
                    clamp(confidence),
                    source,
                    self.dim,
                    pack_vector(vector),
                    json.dumps(meta or {}, ensure_ascii=False),
                    ts,
                    ts,
                    1,
                ),
            )
            new_id = int(cur.lastrowid)
            if self.has_fts:
                try:
                    self._conn.execute(
                        "INSERT INTO memories_fts (rowid, text, tags) VALUES (?,?,?)",
                        (new_id, text, tag_text),
                    )
                except sqlite3.OperationalError as exc:
                    log_warn(f"FTS insert failed: {exc}", "memory")
            self._conn.commit()

        BUS.emit(Ev.MEMORY_STORED, {"id": new_id, "kind": kind, "text": truncate(text, 80)}, "memory")
        row = self.get_row(new_id)
        return self._row_to_memory(row) if row else None

    def get(self, memory_id: int) -> Optional[Memory]:
        row = self.get_row(memory_id)
        return self._row_to_memory(row) if row else None

    def get_row(self, memory_id: int) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()

    def update(self, memory_id: int, **fields: Any) -> bool:
        allowed = {"text", "kind", "tags", "importance", "confidence", "pinned", "meta"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "tags":
                value = ",".join(sorted({str(v).strip().lower() for v in value if str(v).strip()}))
            elif key == "importance" or key == "confidence":
                value = clamp(float(value))
            elif key == "pinned":
                value = 1 if value else 0
            elif key == "meta":
                value = json.dumps(value or {}, ensure_ascii=False)
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return False
        values.append(memory_id)
        with self._lock:
            self._conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", values)
            self._conn.commit()
        return True

    def pin(self, memory_id: int, pinned: bool = True) -> bool:
        return self.update(memory_id, pinned=pinned)

    def forget(self, memory_id: int, hard: bool = True) -> bool:
        """Remove a memory. ``hard=False`` archives it instead."""
        with self._lock:
            if hard:
                self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                if self.has_fts:
                    try:
                        self._conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
                    except sqlite3.OperationalError:
                        pass
            else:
                self._conn.execute("UPDATE memories SET archived = 1 WHERE id = ?", (memory_id,))
            self._conn.commit()
        return True

    def clear(self, kind: Optional[str] = None) -> int:
        with self._lock:
            if kind:
                ids = [
                    r["id"]
                    for r in self._conn.execute(
                        "SELECT id FROM memories WHERE kind = ?", (kind,)
                    ).fetchall()
                ]
                for mid in ids:
                    self._conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
                    if self.has_fts:
                        try:
                            self._conn.execute(
                                "DELETE FROM memories_fts WHERE rowid = ?", (mid,)
                            )
                        except sqlite3.OperationalError:
                            pass
            else:
                self._conn.execute("DELETE FROM memories")
                if self.has_fts:
                    try:
                        self._conn.execute("DELETE FROM memories_fts")
                    except sqlite3.OperationalError:
                        pass
            deleted = self._conn.total_changes
            self._conn.commit()
        return deleted

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def _keyword_candidates(self, query: str, pool: int = 400) -> List[Tuple[int, float]]:
        """Return (memory_id, keyword_score) for anything textually related."""
        all_terms = sorted(token_set(query))
        # Stopwords are dropped from the query itself. bm25 is dominated by
        # very common words, so a query of "my preferences" would otherwise
        # rank by "my" and ignore "prefer" entirely.
        terms = [t for t in all_terms if t not in STOPWORDS and len(t) > 1] or all_terms
        if not terms:
            return []
        results: Dict[int, float] = {}

        with self._lock:
            if self.has_fts:
                # Match the word itself, its prefixes, and its stems, so
                # "preferences" finds "prefer" and "preference".
                clauses: List[str] = []
                for term in terms[:12]:
                    clauses.append(f'"{term}"')
                    if len(term) >= 4:
                        clauses.append(f'"{term}"*')
                    clauses.extend(f'"{stem}"' for stem in stem_variants(term))
                expression = " OR ".join(dict.fromkeys(clauses))
                try:
                    rows = self._conn.execute(
                        "SELECT rowid, bm25(memories_fts) AS rank FROM memories_fts "
                        "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                        (expression, pool),
                    ).fetchall()
                    # Reciprocal rank rather than the raw bm25 value: bm25's
                    # magnitude depends on corpus size and saturates on small
                    # stores, whereas position is always meaningful.
                    for position, row in enumerate(rows):
                        results[row["rowid"]] = 1.0 / (1.0 + position)
                except sqlite3.OperationalError as exc:
                    log_debug(f"FTS query failed, using LIKE: {exc}", "memory")
            if not results:
                # No FTS hit (or this build has no FTS5): LIKE across terms.
                qset = token_set(query)
                likes = [f"%{t[:40]}%" for t in terms[:8]]
                clause = " OR ".join(["text LIKE ?"] * len(likes) + ["tags LIKE ?"] * len(likes))
                rows = self._conn.execute(
                    f"SELECT id, text, tags FROM memories WHERE {clause} "
                    "ORDER BY use_count DESC, importance DESC LIMIT ?",
                    [*likes, *likes, pool],
                ).fetchall()
                for row in rows:
                    overlap = len(qset & token_set(f"{row['text']} {row['tags']}"))
                    if overlap:
                        results[row["id"]] = overlap / max(1, len(qset))
        return sorted(results.items(), key=lambda kv: kv[1], reverse=True)

    def search(
        self,
        query: str,
        limit: int = 6,
        kinds: Optional[Sequence[str]] = None,
        min_score: Optional[float] = None,
        boost_pinned: bool = True,
    ) -> List[Recall]:
        """
        Hybrid recall.  Keyword matches and vector matches are blended, then
        memory strength (importance, age, use count) breaks ties.
        """
        if not (query or "").strip():
            return []
        floor = self.cfg.min_recall_score if min_score is None else min_score
        query_vec = embed(query, self.dim)
        wanted = {k.lower() for k in kinds} if kinds else None

        scored: Dict[int, Recall] = {}
        candidates = self._keyword_candidates(query)
        candidate_ids = [cid for cid, _ in candidates]
        if not candidate_ids:
            # Nothing matched textually; fall back to a vector sweep.
            with self._lock:
                rows = self._conn.execute(
                    "SELECT id FROM memories WHERE archived = 0 ORDER BY "
                    "use_count DESC LIMIT 1200"
                ).fetchall()
            candidate_ids = [r["id"] for r in rows]

        if not candidate_ids:
            return []

        placeholders = ",".join("?" * len(candidate_ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})", candidate_ids
            ).fetchall()

        keyword_map = dict(candidates)
        query_tokens = token_set(query)
        # Overlap is measured on content words only. Including function words
        # would let "my wifi" and "my preferences" score identically just
        # because both contain "my".
        content = {
            t for t in query_tokens if t not in STOPWORDS and len(t) > 1
        } or set(query_tokens)
        expanded = set(content)
        for term in content:
            expanded.update(stem_variants(term))

        for row in rows:
            if row["archived"]:
                continue
            if wanted and row["kind"].lower() not in wanted:
                continue

            text_tokens = token_set(f"{row['text']} {row['tags']}")

            # Explicit overlap beats relying on bm25 rank alone, and the
            # query is stem-expanded so "preferences" scores "prefer".
            overlap = len(expanded & text_tokens) / max(1, len(expanded))
            keyword = max(keyword_map.get(row["id"], 0.0), overlap)
            semantic = 0.0
            if row["vec"]:
                try:
                    semantic = max(0.0, cosine(query_vec, unpack_vector(row["vec"])))
                except (ValueError, struct.error):
                    semantic = 0.0

            if keyword == 0.0 and semantic < 0.12:
                continue

            memory = self._row_to_memory(row)
            base = 0.55 * keyword + 0.45 * semantic
            combined = clamp(0.68 * base + 0.32 * memory.strength)
            if boost_pinned and memory.pinned:
                combined = clamp(combined + 0.15)
            if combined < floor:
                continue
            scored[memory.id] = Recall(memory, combined, keyword, semantic)

        results = sorted(scored.values(), key=lambda r: r.score, reverse=True)[: max(1, limit)]
        if results:
            BUS.emit(
                Ev.MEMORY_RECALLED,
                {"query": truncate(query, 60), "hits": len(results)},
                "memory",
            )
            self._touch([r.memory.id for r in results])
        return results

    def _touch(self, ids: Sequence[int]) -> None:
        """Record that memories were used so they get stronger over time."""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            try:
                self._conn.execute(
                    f"UPDATE memories SET use_count = use_count + 1, last_used = ? "
                    f"WHERE id IN ({placeholders})",
                    [now(), *ids],
                )
                self._conn.commit()
            except sqlite3.Error:
                pass

    def recent(self, limit: int = 20, kind: Optional[str] = None) -> List[Memory]:
        with self._lock:
            if kind:
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE kind = ? AND archived = 0 "
                    "ORDER BY created DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE archived = 0 "
                    "ORDER BY created DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return self._rows_to_memories(rows)

    def all_pinned(self) -> List[Memory]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE pinned = 1 AND archived = 0 "
                "ORDER BY importance DESC"
            ).fetchall()
        return self._rows_to_memories(rows)

    def find(self, query: str, limit: int = 20) -> List[Memory]:
        """Plain substring search - used by the ``memory find`` CLI command."""
        like = f"%{(query or '').strip()}%"
        if like == "%%":
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE text LIKE ? OR tags LIKE ? "
                "ORDER BY pinned DESC, importance DESC, created DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
        return self._rows_to_memories(rows)

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    def set_pref(self, key: str, value: Any, kind: str = "pref") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO prefs (key, value, kind, updated) VALUES (?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "kind=excluded.kind, updated=excluded.updated",
                (key.strip().lower(), json.dumps(value, ensure_ascii=False), kind, now()),
            )
            self._conn.commit()

    def get_pref(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM prefs WHERE key = ?", (key.strip().lower(),)
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def all_prefs(self, kind: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if kind:
                rows = self._conn.execute(
                    "SELECT key, value FROM prefs WHERE kind = ?", (kind,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT key, value FROM prefs").fetchall()
        out: Dict[str, Any] = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                out[row["key"]] = row["value"]
        return out

    # ------------------------------------------------------------------
    # Episodes (what I tried and whether it worked)
    # ------------------------------------------------------------------
    def record_episode(
        self,
        goal: str,
        plan: Optional[Sequence[Dict[str, Any]]] = None,
        steps: Optional[Sequence[Dict[str, Any]]] = None,
        result: str = "",
        success: bool = True,
        score: float = 0.0,
        duration: float = 0.0,
        tags: Optional[Sequence[str]] = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO episodes (goal, plan, steps, result, success, score, "
                "duration, tags, created) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    goal,
                    json.dumps(list(plan or []), ensure_ascii=False),
                    json.dumps(list(steps or []), ensure_ascii=False, default=str),
                    truncate(result, 4000),
                    1 if success else 0,
                    clamp(score),
                    float(duration),
                    ",".join(tags or []),
                    now(),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def recent_episodes(self, limit: int = 20, only_failures: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM episodes"
        if only_failures:
            sql += " WHERE success = 0"
        sql += " ORDER BY created DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def episode_stats(self) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS wins, "
                "AVG(duration) AS avg_duration, AVG(score) AS avg_score "
                "FROM episodes"
            ).fetchone()
        total = row["total"] or 0
        wins = row["wins"] or 0
        return {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "success_rate": round(wins / total, 3) if total else 0.0,
            "avg_duration": round(row["avg_duration"] or 0.0, 2),
            "avg_score": round(row["avg_score"] or 0.0, 3),
        }

    # ------------------------------------------------------------------
    # Lessons (self distilled rules)
    # ------------------------------------------------------------------
    def add_lesson(
        self,
        pattern: str,
        rule: str,
        confidence: float = 0.5,
        source: str = "reflection",
    ) -> Lesson:
        pattern = (pattern or "").strip().lower()
        rule = (rule or "").strip()
        if not pattern or not rule:
            raise ValueError("lesson needs both a pattern and a rule")
        ts = now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO lessons (pattern, rule, confidence, source, created, updated) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(pattern) DO UPDATE SET "
                "rule = excluded.rule, "
                "confidence = MIN(0.99, lessons.confidence + 0.08), "
                "updated = excluded.updated",
                (pattern, rule, clamp(confidence), source, ts, ts),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM lessons WHERE pattern = ?", (pattern,)
            ).fetchone()
        BUS.emit(Ev.LEARNED, {"pattern": pattern, "rule": truncate(rule, 90)}, "memory")
        return Lesson(
            id=row["id"],
            pattern=row["pattern"],
            rule=row["rule"],
            confidence=row["confidence"],
            hits=row["hits"],
            misses=row["misses"],
            source=row["source"],
            updated=row["updated"],
        )

    def lessons(self, limit: int = 20, min_confidence: float = 0.0) -> List[Lesson]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM lessons WHERE confidence >= ? "
                "ORDER BY confidence DESC, hits DESC LIMIT ?",
                (min_confidence, limit),
            ).fetchall()
        return [
            Lesson(
                id=r["id"],
                pattern=r["pattern"],
                rule=r["rule"],
                confidence=r["confidence"],
                hits=r["hits"],
                misses=r["misses"],
                source=r["source"],
                updated=r["updated"],
            )
            for r in rows
        ]

    def find_lesson(self, text: str) -> Optional[Lesson]:
        """Look up a lesson whose pattern overlaps the given text."""
        target = token_set(text)
        if not target:
            return None
        best, best_score = None, 0.0
        for lesson in self.lessons(limit=200):
            overlap = len(target & token_set(lesson.pattern))
            if overlap:
                score = overlap / max(1, len(target))
                if score > best_score:
                    best, best_score = lesson, score
        return best

    def reinforce(self, lesson_id: int, worked: bool) -> None:
        """A lesson either proved itself or got weaker."""
        with self._lock:
            if worked:
                self._conn.execute(
                    "UPDATE lessons SET hits = hits + 1, "
                    "confidence = MIN(0.99, confidence + 0.05), updated = ? WHERE id = ?",
                    (now(), lesson_id),
                )
            else:
                self._conn.execute(
                    "UPDATE lessons SET misses = misses + 1, "
                    "confidence = MAX(0.05, confidence - 0.09), updated = ? WHERE id = ?",
                    (now(), lesson_id),
                )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Short term conversation window
    # ------------------------------------------------------------------
    def push_turn(self, role: str, text: str, meta: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO turns (role, text, meta, created) VALUES (?,?,?,?)",
                (role, text, json.dumps(meta or {}, ensure_ascii=False), now()),
            )
            self._conn.execute(
                "DELETE FROM turns WHERE id NOT IN "
                "(SELECT id FROM turns ORDER BY created DESC LIMIT ?)",
                (max(20, self.cfg.short_term_turns * 6),),
            )
            self._conn.commit()

    def recent_turns(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        count = limit or self.cfg.short_term_turns
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, text, meta, created FROM turns ORDER BY created DESC LIMIT ?",
                (count,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def clear_turns(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM turns")
            self._conn.commit()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def consolidate(self, archive_below: float = 0.05) -> int:
        """
        Sleep-cycle housekeeping: archive anything that has faded into
        irrelevance.  Pinned and important memories are never touched.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET archived = 1 WHERE archived = 0 AND pinned = 0 "
                "AND importance < ? AND use_count <= 1 AND created < ?",
                (archive_below, now() - 90 * 86400),
            )
            pruned = self._conn.execute(
                "DELETE FROM turns WHERE created < ?", (now() - 30 * 86400,)
            )
            self._conn.execute(
                "DELETE FROM episodes WHERE created < ?", (now() - 365 * 86400,)
            )
            self._conn.commit()
            archived = cur.rowcount or 0
        if archived:
            log_debug(f"consolidated {archived} faded memories", "memory")
        return archived

    def decay(self, factor: float = 0.995) -> int:
        """Gently reduce importance of unpinned memories. Called periodically."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET importance = importance * ? WHERE pinned = 0", (factor,)
            )
            self._conn.commit()
            return cur.rowcount or 0

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            kinds = {
                r["kind"]: r["n"]
                for r in self._conn.execute(
                    "SELECT kind, COUNT(*) AS n FROM memories WHERE archived = 0 GROUP BY kind"
                ).fetchall()
            }
            counts = {
                name: self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                for name, table in (
                    ("memories", "memories"),
                    ("episodes", "episodes"),
                    ("lessons", "lessons"),
                    ("prefs", "prefs"),
                    ("turns", "turns"),
                )
            }
            conn = self._conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE archived = 0"
            ).fetchone()["n"]
        return {
            "counts": counts,
            "active_memories": conn,
            "by_kind": kinds,
            "episodes": self.episode_stats(),
            "vector_dim": self.dim,
            "fts": self.has_fts,
            "db_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    # ------------------------------------------------------------------
    # Portability
    # ------------------------------------------------------------------
    def export(self, target: Path) -> Path:
        """Write a human readable, re-importable dump of everything."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "exported": now(),
            "memories": [m.to_dict() for m in self.recent(limit=100000)],
            "prefs": self.all_prefs(),
            "lessons": [l.to_dict() for l in self.lessons(limit=500)],
            "episodes": self.recent_episodes(limit=5000),
            "stats": self.stats(),
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def import_(self, source: Path) -> Dict[str, int]:
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
        added = 0
        for item in raw.get("memories", []):
            if self.add(
                item["text"],
                kind=item.get("kind", "fact"),
                tags=item.get("tags", []),
                importance=item.get("importance", 0.5),
                source=item.get("source", "import"),
            ):
                added += 1
        for key, value in raw.get("prefs", {}).items():
            self.set_pref(key, value)
        for lesson in raw.get("lessons", []):
            try:
                self.add_lesson(lesson["pattern"], lesson["rule"], lesson.get("confidence", 0.5))
            except ValueError:
                continue
        return {"memories_added": added, "lessons": len(raw.get("lessons", []))}


# --------------------------------------------------------------------------
# Module level singleton + convenience API
# --------------------------------------------------------------------------

_MEMORY: Optional[MemoryStore] = None
_MEMORY_LOCK = threading.Lock()


def get_memory(config: Optional[MemoryConfig] = None) -> MemoryStore:
    global _MEMORY
    if _MEMORY is None:
        with _MEMORY_LOCK:
            if _MEMORY is None:
                _MEMORY = MemoryStore(config=config)
    return _MEMORY


def remember(text: str, **kwargs: Any) -> Optional[Memory]:
    """One line shorthand used all over the codebase."""
    return get_memory().add(text, **kwargs)


def recall(query: str, limit: int = 6) -> List[Recall]:
    return get_memory().search(query, limit=limit)