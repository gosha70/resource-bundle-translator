"""SQLite-backed :class:`ainemo.core.tm.base.TranslationMemory`.

Default TM implementation for cycle 1. File-based SQLite database with
two tables (``segments`` + ``translations``) plus optional 384-dim
MiniLM embeddings stored inline as BLOBs for fuzzy lookup.

Design choices
--------------

- **One file per project** (default ``./.ainemo/tm.sqlite``). Per
  AGENTS.md § Translation-Domain Conventions, project TM is **opt-in**
  for git tracking, not the default — ``.ainemo/`` is in
  ``.gitignore``.
- **Linear cosine scan** for fuzzy lookup. Cycle-1 design choice: a
  vector index (sqlite-vec, hnswlib, faiss) only lands when a
  benchmark on a 50k-segment corpus shows the linear scan crossing
  the p95 < 50ms target.
- **Dependency-injected embedder.** The TM accepts any callable that
  converts a string to a 1-D ``numpy`` array. Production uses a
  lazy-loaded ``sentence-transformers`` model
  (``paraphrase-multilingual-MiniLM-L12-v2``, ~120 MB on first run).
  Tests pass a deterministic stub so they don't download the model.
- **Embedding optional.** If no embedder is provided at construction,
  the TM stores translations and serves exact matches; fuzzy lookups
  always miss. This is the right default for cycle-1 CI runs that
  don't want a 120 MB model download.
- **Idempotent ``store``.** ``INSERT OR REPLACE`` for both tables;
  re-storing a TranslatedSegment refreshes ``created_at`` but does
  not duplicate.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final, Iterator, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from ainemo.core.segment import (
    TRANSLATION_SOURCE_EXACT_TM,
    TRANSLATION_SOURCE_FUZZY_TM,
    Placeholder,
    PlaceholderKind,
    Segment,
    TranslatedSegment,
)
from ainemo.core.tm.base import (
    DEFAULT_FUZZY_THRESHOLD,
    EXACT_MATCH_SIMILARITY,
    TM_MATCH_TYPE_EXACT,
    TM_MATCH_TYPE_FUZZY,
    TmHit,
    TmStats,
)

# Type alias for the embedding arrays the TM produces and consumes.
# `NDArray[np.float32]` is more precise than the bare `np.ndarray`
# (which mypy strict on Python 3.10 rejects for missing type
# parameters); the alias keeps signatures readable.
_EmbeddingArray = NDArray[np.float32]

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Default project-local TM database. Per AGENTS.md, .ainemo/ is in
# .gitignore — committing the TM is opt-in.
DEFAULT_TM_PATH: Final = Path(".ainemo") / "tm.sqlite"

# Embedding dtype. float32 is what sentence-transformers returns and
# what most cosine-similarity pipelines expect; halving precision to
# float16 saves disk but is fine cycle-2+ work if size matters.
_EMBEDDING_DTYPE = np.float32

# Schema version, written into a `meta` table. If we change the
# schema, this gets bumped and a migration runs.
_SCHEMA_VERSION = 1

_DDL_META = "CREATE TABLE IF NOT EXISTS meta (  key TEXT PRIMARY KEY,  value TEXT NOT NULL)"
_DDL_SEGMENTS = (
    "CREATE TABLE IF NOT EXISTS segments ("
    "  fingerprint TEXT PRIMARY KEY,"
    "  source_text TEXT NOT NULL,"
    "  source_lang TEXT NOT NULL,"
    "  placeholders_json TEXT NOT NULL,"
    "  embedding BLOB,"
    "  created_at INTEGER NOT NULL"
    ")"
)
_DDL_TRANSLATIONS = (
    "CREATE TABLE IF NOT EXISTS translations ("
    "  fingerprint TEXT NOT NULL,"
    "  target_lang TEXT NOT NULL,"
    "  target_text TEXT NOT NULL,"
    "  provider TEXT NOT NULL,"
    "  confidence REAL,"
    "  source TEXT NOT NULL,"
    "  created_at INTEGER NOT NULL,"
    "  PRIMARY KEY (fingerprint, target_lang, provider)"
    ")"
)
_DDL_TRANSLATIONS_LANG_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_translations_lang ON translations(target_lang)"
)

# meta-table keys
_META_KEY_SCHEMA_VERSION = "schema_version"


@runtime_checkable
class Embedder(Protocol):
    """Callable converting a string into a 1-D numpy array."""

    def __call__(self, text: str) -> _EmbeddingArray: ...


class SqliteTranslationMemory:
    """File-based SQLite TM. See module docstring for design notes."""

    def __init__(
        self,
        db_path: Path,
        embedder: Embedder | None = None,
    ) -> None:
        self._db_path = db_path
        self._embedder = embedder
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    # --- TranslationMemory Protocol ---

    def lookup(
        self,
        segment: Segment,
        target_lang: str,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    ) -> TmHit | None:
        exact = self._lookup_exact(segment, target_lang)
        if exact is not None:
            return exact
        if self._embedder is None:
            return None
        return self._lookup_fuzzy(segment, target_lang, fuzzy_threshold)

    def store(self, translated: TranslatedSegment) -> None:
        seg = translated.segment
        embedding_blob: bytes | None = None
        if self._embedder is not None:
            embedding_blob = _encode_embedding(self._embedder(seg.source_text))
        now = _now_seconds()
        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO segments "
                "(fingerprint, source_text, source_lang, placeholders_json, "
                " embedding, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    seg.fingerprint,
                    seg.source_text,
                    seg.source_lang,
                    _placeholders_to_json(seg.placeholders),
                    embedding_blob,
                    now,
                ),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO translations "
                "(fingerprint, target_lang, target_text, provider, "
                " confidence, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    seg.fingerprint,
                    translated.target_lang,
                    translated.target_text,
                    translated.provider,
                    translated.confidence,
                    translated.source,
                    now,
                ),
            )

    def stats(self) -> TmStats:
        cursor = self._conn.execute("SELECT COUNT(*) FROM segments")
        segment_count = int(cursor.fetchone()[0])
        cursor = self._conn.execute("SELECT COUNT(*) FROM translations")
        translation_count = int(cursor.fetchone()[0])
        cursor = self._conn.execute("SELECT COUNT(DISTINCT target_lang) FROM translations")
        target_lang_count = int(cursor.fetchone()[0])
        cursor = self._conn.execute("SELECT COUNT(*) FROM segments WHERE embedding IS NOT NULL")
        embedding_count = int(cursor.fetchone()[0])
        return TmStats(
            segment_count=segment_count,
            translation_count=translation_count,
            target_lang_count=target_lang_count,
            embedding_count=embedding_count,
        )

    # --- Internals ---

    def _init_schema(self) -> None:
        with self._transaction():
            self._conn.execute(_DDL_META)
            self._conn.execute(_DDL_SEGMENTS)
            self._conn.execute(_DDL_TRANSLATIONS)
            self._conn.execute(_DDL_TRANSLATIONS_LANG_INDEX)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (_META_KEY_SCHEMA_VERSION, str(_SCHEMA_VERSION)),
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN")
        try:
            yield
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def _lookup_exact(self, segment: Segment, target_lang: str) -> TmHit | None:
        cursor = self._conn.execute(
            "SELECT target_text, provider, confidence, source "
            "FROM translations "
            "WHERE fingerprint = ? AND target_lang = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (segment.fingerprint, target_lang),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        target_text, provider, confidence, _stored_source = row
        translated = TranslatedSegment(
            segment=segment,
            target_lang=target_lang,
            target_text=target_text,
            provider=provider,
            confidence=confidence,
            source=TRANSLATION_SOURCE_EXACT_TM,
        )
        return TmHit(
            translated=translated,
            similarity=EXACT_MATCH_SIMILARITY,
            match_type=TM_MATCH_TYPE_EXACT,
        )

    def _lookup_fuzzy(
        self,
        segment: Segment,
        target_lang: str,
        threshold: float,
    ) -> TmHit | None:
        if self._embedder is None:
            return None
        query_embedding = self._embedder(segment.source_text)
        cursor = self._conn.execute(
            "SELECT s.fingerprint, s.source_text, s.source_lang, "
            "       s.placeholders_json, s.embedding, "
            "       t.target_text, t.provider, t.confidence "
            "FROM segments s "
            "JOIN translations t "
            "  ON s.fingerprint = t.fingerprint "
            " AND t.target_lang = ? "
            "WHERE s.source_lang = ? "
            "  AND s.embedding IS NOT NULL",
            (target_lang, segment.source_lang),
        )
        best_similarity: float = -1.0
        best_row: _FuzzyRow | None = None
        for raw_row in cursor.fetchall():
            row = _row_to_fuzzy(raw_row)
            similarity = _cosine_similarity(query_embedding, _decode_embedding(row.embedding))
            if similarity > best_similarity:
                best_similarity = similarity
                best_row = row
        if best_row is None or best_similarity < threshold:
            return None
        match_segment = Segment(
            key=segment.key,  # caller's key; the cached segment's is incidental
            source_text=best_row.source_text,
            source_lang=best_row.source_lang,
            placeholders=_placeholders_from_json(best_row.placeholders_json),
        )
        translated = TranslatedSegment(
            segment=match_segment,
            target_lang=target_lang,
            target_text=best_row.target_text,
            provider=best_row.provider,
            confidence=best_row.confidence,
            source=TRANSLATION_SOURCE_FUZZY_TM,
        )
        return TmHit(
            translated=translated,
            similarity=best_similarity,
            match_type=TM_MATCH_TYPE_FUZZY,
        )


# --- Module-level helpers ---


@dataclass(frozen=True)
class _FuzzyRow:
    """One row from the fuzzy-lookup JOIN, with fields named so the
    caller doesn't index untyped tuple slots."""

    fingerprint: str
    source_text: str
    source_lang: str
    placeholders_json: str
    embedding: bytes
    target_text: str
    provider: str
    confidence: float | None


def _row_to_fuzzy(raw: tuple[Any, ...]) -> _FuzzyRow:
    """Coerce a raw sqlite3 row into a typed :class:`_FuzzyRow`.

    sqlite3 row elements are typed `Any` by the stdlib stubs; this
    function is the single boundary where we coerce them into our
    domain types so the rest of the module type-checks strictly.
    """
    embedding_field = raw[4]
    if not isinstance(embedding_field, (bytes, bytearray, memoryview)):
        raise TypeError(
            f"Expected bytes-like for embedding column; got {type(embedding_field).__name__}"
        )
    return _FuzzyRow(
        fingerprint=str(raw[0]),
        source_text=str(raw[1]),
        source_lang=str(raw[2]),
        placeholders_json=str(raw[3]),
        embedding=bytes(embedding_field),
        target_text=str(raw[5]),
        provider=str(raw[6]),
        confidence=None if raw[7] is None else float(raw[7]),
    )


def _now_seconds() -> int:
    return int(time.time())


def _placeholders_to_json(placeholders: tuple[Placeholder, ...]) -> str:
    return json.dumps(
        [{"kind": ph.kind.value, "raw": ph.raw, "span": list(ph.span)} for ph in placeholders]
    )


def _placeholders_from_json(payload: str) -> tuple[Placeholder, ...]:
    items = json.loads(payload)
    return tuple(
        Placeholder(
            kind=PlaceholderKind(item["kind"]),
            raw=item["raw"],
            span=(int(item["span"][0]), int(item["span"][1])),
        )
        for item in items
    )


def _encode_embedding(arr: _EmbeddingArray) -> bytes:
    return arr.astype(_EMBEDDING_DTYPE).tobytes()


def _decode_embedding(blob: bytes) -> _EmbeddingArray:
    return np.frombuffer(blob, dtype=_EMBEDDING_DTYPE)


def _cosine_similarity(a: _EmbeddingArray, b: _EmbeddingArray) -> float:
    a_norm = np.linalg.norm(a)
    b_norm = np.linalg.norm(b)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def make_default_embedder(
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
) -> Callable[[str], _EmbeddingArray]:
    """Lazy-loaded default embedder: ``sentence-transformers`` MiniLM.

    Constructed on first call so importing this module doesn't trigger
    a 120 MB model download. Tests typically pass their own stub
    embedder rather than calling this.
    """
    # The model is held in a list so the inner closure can mutate the
    # singleton across calls. `Any` because sentence-transformers ships
    # without type stubs and is masked via `[[tool.mypy.overrides]]`
    # ignore_missing_imports — its returned types are Any anyway.
    model_holder: list[Any] = []

    def _embed(text: str) -> _EmbeddingArray:
        if not model_holder:
            from sentence_transformers import SentenceTransformer

            model_holder.append(SentenceTransformer(model_name))
        model = model_holder[0]
        embedding = model.encode(text, convert_to_numpy=True)
        return np.asarray(embedding, dtype=_EMBEDDING_DTYPE)

    return _embed


__all__ = [
    "DEFAULT_TM_PATH",
    "Embedder",
    "SqliteTranslationMemory",
    "make_default_embedder",
]
