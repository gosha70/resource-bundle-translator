# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Import-skip store — cycle-5 S3.

Stores skipped rows from ``nemo termbase import-from-csv`` /
``import-from-jsonl`` in a SQLite database so the reviewer UI can
triage and retry them without re-editing the source file.

Public surfaces
---------------
:class:`ImportSkipRow`
    Frozen dataclass representing one persisted skip entry.
:class:`ImportSkipStore`
    Protocol for the store — tests swap in an in-memory double.
:class:`SqliteImportSkipStore`
    SQLite-backed implementation; schema bootstrap is idempotent.
:func:`single_row_source`
    Factory that reconstructs a one-shot ``TermbaseSource`` from a
    stored ``ImportSkipRow`` for the ``/imports`` retry path.
:func:`_derive_skip_id`
    Content-addressed ``skip_id`` derivation — called from
    :mod:`ainemo.core.termbase.sources.loader` via a deferred import.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, Iterator, Protocol, runtime_checkable

from ainemo.core.termbase.sources._ids import (
    SOURCE_FORMAT_CSV,
    SOURCE_FORMAT_JSONL,
    TERM_SOURCE_CSV_IMPORT,
    TERM_SOURCE_JSONL_IMPORT,
)
from ainemo.core.termbase.sources.base import ImportRecord, SkippedRow, TermbaseSource
from ainemo.core.termbase.sources.mapping import FieldMapping

# ---------------------------------------------------------------------------
# Module-level constants — no magic strings (project memory rule).
# ---------------------------------------------------------------------------

_SKIP_ID_PREFIX: Final = "skip-"
_SKIP_ID_HASH_LENGTH: Final = 16
_SKIP_ID_SEPARATOR: Final = "\x1f"  # ASCII unit separator; same as loader.py

# SQLite table / column names
_TABLE_IMPORT_SKIPS: Final = "import_skips"
_COL_SKIP_ID: Final = "skip_id"
_COL_SOURCE_PATH: Final = "source_path"
_COL_SOURCE_FORMAT: Final = "source_format"
_COL_ROW_INDEX: Final = "row_index"
_COL_ROW_PAYLOAD: Final = "row_payload"
_COL_SKIP_REASON: Final = "skip_reason"
_COL_CREATED_AT: Final = "created_at"
_COL_LAST_RETRIED_AT: Final = "last_retried_at"

_CREATE_TABLE_SQL: Final = f"""
CREATE TABLE IF NOT EXISTS {_TABLE_IMPORT_SKIPS} (
    {_COL_SKIP_ID}         TEXT PRIMARY KEY,
    {_COL_SOURCE_PATH}     TEXT NOT NULL,
    {_COL_SOURCE_FORMAT}   TEXT NOT NULL,
    {_COL_ROW_INDEX}       INTEGER NOT NULL,
    {_COL_ROW_PAYLOAD}     TEXT NOT NULL,
    {_COL_SKIP_REASON}     TEXT NOT NULL,
    {_COL_CREATED_AT}      INTEGER NOT NULL,
    {_COL_LAST_RETRIED_AT} INTEGER
)
"""

_UPSERT_SQL: Final = f"""
INSERT INTO {_TABLE_IMPORT_SKIPS} (
    {_COL_SKIP_ID}, {_COL_SOURCE_PATH}, {_COL_SOURCE_FORMAT},
    {_COL_ROW_INDEX}, {_COL_ROW_PAYLOAD}, {_COL_SKIP_REASON},
    {_COL_CREATED_AT}, {_COL_LAST_RETRIED_AT}
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT({_COL_SKIP_ID}) DO UPDATE SET
    {_COL_SKIP_REASON}     = excluded.{_COL_SKIP_REASON},
    {_COL_LAST_RETRIED_AT} = excluded.{_COL_LAST_RETRIED_AT}
"""

_SELECT_ALL_SQL: Final = (
    f"SELECT * FROM {_TABLE_IMPORT_SKIPS} ORDER BY {_COL_SOURCE_PATH}, {_COL_ROW_INDEX}"
)
_SELECT_BY_PATH_SQL: Final = (
    f"SELECT * FROM {_TABLE_IMPORT_SKIPS} WHERE {_COL_SOURCE_PATH} = ? ORDER BY {_COL_ROW_INDEX}"
)
_SELECT_BY_ID_SQL: Final = f"SELECT * FROM {_TABLE_IMPORT_SKIPS} WHERE {_COL_SKIP_ID} = ?"
_DELETE_BY_ID_SQL: Final = f"DELETE FROM {_TABLE_IMPORT_SKIPS} WHERE {_COL_SKIP_ID} = ?"
_UPDATE_RETRY_SQL: Final = f"""
UPDATE {_TABLE_IMPORT_SKIPS}
SET {_COL_SKIP_REASON} = ?, {_COL_LAST_RETRIED_AT} = ?
WHERE {_COL_SKIP_ID} = ?
"""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportSkipRow:
    """One persisted skip entry in the :class:`ImportSkipStore`.

    ``skip_id`` is content-addressed over ``(source_path, row_index,
    row_payload)`` so re-importing the same source file is idempotent —
    the same row always produces the same ``skip_id`` and the upsert
    overwrites the previous reason.
    """

    skip_id: str
    """Content-addressed identifier: ``skip-<sha256(…)[:16]>``."""

    source_path: str
    """Absolute or relative path of the source file."""

    source_format: str
    """``"csv"`` or ``"jsonl"`` — matches the ``SOURCE_FORMAT_*`` constants."""

    row_index: int
    """1-based row index matching the ``"row N:"`` prefix in ``skip_reason``."""

    row_payload: str
    """JSON-serialised original row (CSV → dict, JSONL → raw line string)."""

    skip_reason: str
    """Human-readable skip reason from :attr:`SkippedRow.reason`."""

    created_at: int
    """Unix epoch seconds when this skip was first recorded."""

    last_retried_at: int | None
    """Unix epoch seconds of the most recent retry attempt, or ``None``."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ImportSkipStore(Protocol):
    """Read/write surface for the import-skip queue.

    Concrete implementations: :class:`SqliteImportSkipStore` (production)
    and ``_MemoryImportSkipStore`` (test double in the contract-test suite).
    """

    def add(self, row: ImportSkipRow) -> None:
        """Upsert ``row`` by ``skip_id``.

        Idempotent — re-importing the same source row overwrites the
        previous ``skip_reason`` and ``last_retried_at``; ``created_at``
        is preserved from the first insert (by the SQL upsert semantics).
        """
        ...

    def list(self, *, source_path: str | None = None) -> tuple[ImportSkipRow, ...]:
        """Return all skip rows, optionally filtered by ``source_path``."""
        ...

    def get(self, skip_id: str) -> ImportSkipRow | None:
        """Return the row for ``skip_id``, or ``None`` if not found."""
        ...

    def remove(self, skip_id: str) -> None:
        """Delete the row for ``skip_id``.  No-op if not found."""
        ...

    def update_retry(self, skip_id: str, *, success: bool, new_reason: str | None) -> None:
        """Record the outcome of a retry attempt.

        On ``success=True``: remove the row from the store (the skip is
        resolved; the concept is now in the termbase).
        On ``success=False``: update ``skip_reason`` to ``new_reason``
        and stamp ``last_retried_at`` with the current epoch seconds.
        """
        ...


# ---------------------------------------------------------------------------
# SQLite implementation
# ---------------------------------------------------------------------------


class SqliteImportSkipStore:
    """SQLite-backed :class:`ImportSkipStore`.

    Schema bootstrap is idempotent (``CREATE TABLE IF NOT EXISTS``) —
    mirrors :class:`~ainemo.core.tm.sqlite.SqliteTranslationMemory` and
    :class:`~ainemo.core.termbase.kuzu.store.KuzuTermbase`.

    The database file is created (including parent directories) on first
    use.  The caller is responsible for ensuring the path is writable.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()

    def add(self, row: ImportSkipRow) -> None:
        self._conn.execute(
            _UPSERT_SQL,
            (
                row.skip_id,
                row.source_path,
                row.source_format,
                row.row_index,
                row.row_payload,
                row.skip_reason,
                row.created_at,
                row.last_retried_at,
            ),
        )
        self._conn.commit()

    def list(self, *, source_path: str | None = None) -> tuple[ImportSkipRow, ...]:
        if source_path is not None:
            cursor = self._conn.execute(_SELECT_BY_PATH_SQL, (source_path,))
        else:
            cursor = self._conn.execute(_SELECT_ALL_SQL)
        return tuple(_row_from_sqlite(r) for r in cursor.fetchall())

    def get(self, skip_id: str) -> ImportSkipRow | None:
        cursor = self._conn.execute(_SELECT_BY_ID_SQL, (skip_id,))
        row = cursor.fetchone()
        return _row_from_sqlite(row) if row is not None else None

    def remove(self, skip_id: str) -> None:
        self._conn.execute(_DELETE_BY_ID_SQL, (skip_id,))
        self._conn.commit()

    def update_retry(self, skip_id: str, *, success: bool, new_reason: str | None) -> None:
        if success:
            self.remove(skip_id)
        else:
            reason = new_reason if new_reason is not None else "retry failed"
            self._conn.execute(
                _UPDATE_RETRY_SQL,
                (reason, int(time.time()), skip_id),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Content-addressed skip_id derivation
# ---------------------------------------------------------------------------


def _derive_skip_id(
    *,
    source_path: str,
    row_index: int,
    row_payload: str,
) -> str:
    """Stable content-addressed ``skip_id``.

    ``sha256(source_path || \\x1f || row_index || \\x1f || row_payload)``
    truncated to 16 hex chars, prefixed ``"skip-"``.  The unit-separator
    ``\\x1f`` cannot appear in normal text, so the three fields cannot
    collide via delimiter ambiguity — same convention as the cycle-3/4
    concept-id helpers.

    Called from :mod:`ainemo.core.termbase.sources.loader` via a
    deferred import to preserve the ports-and-adapters boundary.
    """
    raw = _SKIP_ID_SEPARATOR.join((source_path, str(row_index), row_payload))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{_SKIP_ID_PREFIX}{digest[:_SKIP_ID_HASH_LENGTH]}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_from_sqlite(row: sqlite3.Row) -> ImportSkipRow:
    return ImportSkipRow(
        skip_id=row[_COL_SKIP_ID],
        source_path=row[_COL_SOURCE_PATH],
        source_format=row[_COL_SOURCE_FORMAT],
        row_index=row[_COL_ROW_INDEX],
        row_payload=row[_COL_ROW_PAYLOAD],
        skip_reason=row[_COL_SKIP_REASON],
        created_at=row[_COL_CREATED_AT],
        last_retried_at=row[_COL_LAST_RETRIED_AT],
    )


# ---------------------------------------------------------------------------
# single_row_source factory
# ---------------------------------------------------------------------------


class _SingleRowSource:
    """One-shot :class:`~ainemo.core.termbase.sources.base.TermbaseSource`
    that yields exactly one item reconstructed from a stored
    :class:`ImportSkipRow`.

    Used by the ``/imports`` retry path to feed a single skipped row
    back through :func:`~ainemo.core.termbase.sources.loader.load_into_termbase`
    without writing a temporary file or re-parsing the entire source.
    """

    def __init__(self, row: ImportSkipRow, mapping: FieldMapping) -> None:
        self._row = row
        self._mapping = mapping

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        raise NotImplementedError


class _SingleRowCsvSource(_SingleRowSource):
    provenance: ClassVar[str] = TERM_SOURCE_CSV_IMPORT

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        yield from _iter_from_csv_payload(self._row, self._mapping)


class _SingleRowJsonlSource(_SingleRowSource):
    provenance: ClassVar[str] = TERM_SOURCE_JSONL_IMPORT

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        yield from _iter_from_jsonl_payload(self._row, self._mapping)


def single_row_source(row: ImportSkipRow, mapping: FieldMapping) -> TermbaseSource:
    """Return a one-shot ``TermbaseSource`` for the retry path.

    Reads ``row.row_payload`` and ``row.source_format`` to reconstruct
    a single-row source that yields exactly one ``ImportRecord`` (on
    successful re-parse) or one ``SkippedRow`` (if the row is still
    malformed after edits).

    The ``provenance`` ClassVar matches the original importer provenance
    tag (``"csv-import"`` / ``"jsonl-import"``) so
    ``load_into_termbase`` stamps the same ``Term.source`` value as a
    normal full-file import.

    Parameters
    ----------
    row:
        The stored skip entry to retry.
    mapping:
        The :class:`~ainemo.core.termbase.sources.mapping.FieldMapping`
        that was used for the original import — the caller is responsible
        for supplying the same mapping (or an edited one for the
        edit-then-retry path).
    """
    if row.source_format == SOURCE_FORMAT_CSV:
        return _SingleRowCsvSource(row, mapping)
    if row.source_format == SOURCE_FORMAT_JSONL:
        return _SingleRowJsonlSource(row, mapping)
    raise ValueError(f"Unsupported import-skip source_format: {row.source_format!r}")


# ---------------------------------------------------------------------------
# Payload reconstruction helpers (private)
# ---------------------------------------------------------------------------


def _iter_from_csv_payload(
    row: ImportSkipRow, mapping: FieldMapping
) -> Iterator[ImportRecord | SkippedRow]:
    """Reconstruct an ``ImportRecord | SkippedRow`` from a CSV-format
    ``row_payload`` (JSON-serialised ``dict[str, str | None]``).

    Re-applies the same mapping logic as ``CsvSource._row_to_record``
    without going through the file-parsing layer.
    """
    from ainemo.core.termbase.sources.csv_source import CsvSource  # noqa: PLC0415

    try:
        raw_payload = json.loads(row.row_payload)
    except (json.JSONDecodeError, TypeError):
        yield SkippedRow(
            reason=f"row {row.row_index}: retry payload is not valid JSON",
            row_payload=row.row_payload,
            row_index=row.row_index,
            source_path=row.source_path,
            source_format=row.source_format,
        )
        return
    if not isinstance(raw_payload, dict):
        yield SkippedRow(
            reason=(
                f"row {row.row_index}: retry payload is "
                f"{type(raw_payload).__name__}, expected object"
            ),
            row_payload=row.row_payload,
            row_index=row.row_index,
            source_path=row.source_path,
            source_format=row.source_format,
        )
        return
    raw: dict[str, str | None] = {}
    for key, value in raw_payload.items():
        if not isinstance(key, str):
            yield SkippedRow(
                reason=f"row {row.row_index}: retry payload contains non-string key",
                row_payload=row.row_payload,
                row_index=row.row_index,
                source_path=row.source_path,
                source_format=row.source_format,
            )
            return
        if value is not None and not isinstance(value, str):
            yield SkippedRow(
                reason=(
                    f"row {row.row_index}: retry payload key {key!r} "
                    f"is {type(value).__name__}, expected string"
                ),
                row_payload=row.row_payload,
                row_index=row.row_index,
                source_path=row.source_path,
                source_format=row.source_format,
            )
            return
        raw[key] = value

    # Delegate to the existing CsvSource internal helper via a minimal
    # in-memory instance (no file I/O — _row_to_record reads only
    # self._mapping, self._path, and the passed row dict).
    source = CsvSource(Path(row.source_path), mapping)
    outcome = source._row_to_record(raw, row.row_index)  # noqa: SLF001
    if outcome is not None:
        yield outcome


def _iter_from_jsonl_payload(
    row: ImportSkipRow, mapping: FieldMapping
) -> Iterator[ImportRecord | SkippedRow]:
    """Reconstruct an ``ImportRecord | SkippedRow`` from a JSONL-format
    ``row_payload`` (original raw line string).

    Re-applies the same mapping logic as ``JsonLinesSource._line_to_record``
    without going through the file-parsing layer.
    """
    from ainemo.core.termbase.sources.jsonl_source import JsonLinesSource  # noqa: PLC0415

    source = JsonLinesSource(Path(row.source_path), mapping)
    yield source._line_to_record(row.row_payload, row.row_index)  # noqa: SLF001


__all__ = [
    "ImportSkipRow",
    "ImportSkipStore",
    "SqliteImportSkipStore",
    "_derive_skip_id",
    "single_row_source",
]
