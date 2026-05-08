# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""JSON-Lines-backed
:class:`~ainemo.core.termbase.sources.base.TermbaseSource`.

Cycle-4 S3 — reads a JSON-Lines file (one JSON object per line) and
applies a :class:`~ainemo.core.termbase.sources.mapping.FieldMapping`
to produce :class:`ImportRecord` rows.

The same :class:`FieldMapping` schema works for both CSV and JSONL —
``source_column`` / ``target_columns`` / ``domain_column`` /
``definition_column`` map to JSON object keys exactly as they map to
CSV header columns. This is why the cycle-4 S1 surface kept the
field-name terminology generic ("column" rather than "csv_column"):
JSONL was always going to share the schema.

Design choices
--------------

- **stdlib json only.** Same shape rule as CsvSource — no jsonpath,
  no schema-validation library. The audience use case is hundreds-
  to-low-thousands of rows of straightforward {key: value} records.
- **One record per line.** Lines whose content is whitespace-only
  are skipped silently (a common convention for human-edited JSONL).
  Malformed JSON on any line yields a :class:`SkippedRow` with the
  line number; the rest of the file continues parsing — same
  contract as CsvSource's row-level skip handling.
- **Per-line shape validation.** Unlike CSV (where a missing column
  is a file-level error because every row is missing it), JSONL
  rows are independent dicts that may legitimately have varying
  keys. Missing required keys / non-object top-level JSON values
  are per-row :class:`SkippedRow` items, not file-level errors.
- **Strict-string on mapped columns.** Any value at a mapped key
  that is not a JSON string (or ``null``, treated as missing)
  yields a :class:`SkippedRow` naming the type: numbers, booleans,
  nested objects, and arrays are all rejected. Rationale: silent
  ``str()``-coercion is a data-loss path — ``{"de_term": true}``
  becomes ``Term(surface="True")``, almost never the author's
  intent (more often a stray Boolean from a spreadsheet export
  where someone defaulted an empty translation cell). The type-
  named skip lets the operator fix the source once and re-run.
  This also keeps CSV / JSONL importer round-trip parity honest
  — CSV always sees strings; JSONL now rejects rather than coerces.
- **UTF-8 default.** JSONL has no IETF RFC; the de facto reference
  (`jsonlines.org`_) recommends UTF-8 by convention. We expose
  ``encoding`` for parity with CsvSource and surface decode errors
  via :class:`JsonlDecodeError` (mirroring CsvSource's
  :class:`CsvDecodeError`) so the operator gets an actionable
  ``--encoding ...`` hint instead of a raw
  :class:`UnicodeDecodeError`.

.. _jsonlines.org: https://jsonlines.org
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar, Iterator

from ainemo.core.termbase.sources._ids import (
    DEFAULT_CSV_ENCODING,
    SOURCE_FORMAT_JSONL,
    TERM_SOURCE_JSONL_IMPORT,
)
from ainemo.core.termbase.sources.base import (
    ImportRecord,
    SkippedRow,
)
from ainemo.core.termbase.sources.mapping import FieldMapping


class JsonlDecodeError(ValueError):
    """Raised when the JSONL file cannot be decoded with the
    configured encoding.

    Wraps the stdlib :class:`UnicodeDecodeError` with a message that
    names the ``--encoding`` CLI flag verbatim — parity with
    :class:`~ainemo.core.termbase.sources.csv_source.CsvDecodeError`
    so operators get the same actionable error shape regardless of
    which source format they're importing.
    """


class _MappedValueError(Exception):
    """Internal — non-string scalar on a mapped column.

    Carries the offending value's type name so the SkippedRow
    reason can name it. Caught and converted to SkippedRow inside
    :meth:`JsonLinesSource._line_to_record`.
    """

    def __init__(self, type_name: str) -> None:
        super().__init__(type_name)
        self.type_name = type_name


class JsonLinesSource:
    """Reads a JSON-Lines file into :class:`ImportRecord` rows.

    Construction is cheap; the file isn't opened until
    :meth:`iter_concepts` is called.
    """

    provenance: ClassVar[str] = TERM_SOURCE_JSONL_IMPORT

    def __init__(
        self,
        path: Path,
        mapping: FieldMapping,
        *,
        encoding: str = DEFAULT_CSV_ENCODING,
    ) -> None:
        self._path = path
        self._mapping = mapping
        self._encoding = encoding

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        try:
            with self._path.open("r", encoding=self._encoding, errors="strict") as fh:
                for line_no, raw_line in enumerate(fh, start=1):
                    stripped = raw_line.strip()
                    if not stripped:
                        # Blank lines are a common JSONL convention
                        # for human-edited files; skip silently
                        # rather than surface as SkippedRow noise.
                        continue
                    yield self._line_to_record(stripped, line_no)
        except UnicodeDecodeError as exc:
            # Parity with CsvSource's CsvDecodeError. Per pitch
            # § Risks: encoding mismatches surface as a clean error
            # mentioning the `--encoding` flag verbatim so the
            # operator can re-run with the right codec.
            raise JsonlDecodeError(
                f"Could not decode {self._path} as {self._encoding!r} "
                f"(byte 0x{exc.object[exc.start]:02x} at position "
                f"{exc.start}). Re-run with `--encoding latin-1` "
                "(or whichever codec your file actually uses)."
            ) from exc

    # --- Internals ---

    def _line_to_record(self, line: str, line_no: int) -> ImportRecord | SkippedRow:
        # ``line`` is the original raw stripped line from the file.
        # For SkippedRow we store it verbatim as ``row_payload`` — lossless
        # round-trip without re-serialisation, and simpler than re-encoding
        # a parsed dict (per pitch § S3 design note).
        source_path = str(self._path)

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            return SkippedRow(
                reason=f"row {line_no}: malformed JSON ({exc.msg})",
                row_payload=line,
                row_index=line_no,
                source_path=source_path,
                source_format=SOURCE_FORMAT_JSONL,
            )

        if not isinstance(payload, dict):
            return SkippedRow(
                reason=(
                    f"row {line_no}: top-level JSON value is "
                    f"{type(payload).__name__}, expected object"
                ),
                row_payload=line,
                row_index=line_no,
                source_path=source_path,
                source_format=SOURCE_FORMAT_JSONL,
            )

        try:
            source_term = _string_at(payload, self._mapping.source_column)
        except _MappedValueError as exc:
            return SkippedRow(
                reason=(
                    f"row {line_no}: {self._mapping.source_column!r} "
                    f"is {exc.type_name}, expected string"
                ),
                row_payload=line,
                row_index=line_no,
                source_path=source_path,
                source_format=SOURCE_FORMAT_JSONL,
            )
        if source_term is None:
            return SkippedRow(
                reason=(f"row {line_no}: missing or blank {self._mapping.source_column!r} key"),
                row_payload=line,
                row_index=line_no,
                source_path=source_path,
                source_format=SOURCE_FORMAT_JSONL,
            )

        target_terms: list[tuple[str, str]] = []
        for target_lang, key in self._mapping.target_columns.items():
            try:
                surface = _string_at(payload, key)
            except _MappedValueError as exc:
                return SkippedRow(
                    reason=(
                        f"row {line_no}: target key {key!r} is {exc.type_name}, expected string"
                    ),
                    row_payload=line,
                    row_index=line_no,
                    source_path=source_path,
                    source_format=SOURCE_FORMAT_JSONL,
                )
            if surface is not None:
                target_terms.append((target_lang, surface))

        if not target_terms:
            return SkippedRow(
                reason=(
                    f"row {line_no}: no non-blank target keys "
                    f"({list(self._mapping.target_columns.values())!r} "
                    "all missing or blank)"
                ),
                row_payload=line,
                row_index=line_no,
                source_path=source_path,
                source_format=SOURCE_FORMAT_JSONL,
            )

        domain_id: str | None = None
        if self._mapping.domain_column is not None:
            try:
                domain_id = _string_at(payload, self._mapping.domain_column)
            except _MappedValueError as exc:
                return SkippedRow(
                    reason=(
                        f"row {line_no}: "
                        f"{self._mapping.domain_column!r} is "
                        f"{exc.type_name}, expected string"
                    ),
                    row_payload=line,
                    row_index=line_no,
                    source_path=source_path,
                    source_format=SOURCE_FORMAT_JSONL,
                )

        definition: str | None = None
        if self._mapping.definition_column is not None:
            try:
                definition = _string_at(payload, self._mapping.definition_column)
            except _MappedValueError as exc:
                return SkippedRow(
                    reason=(
                        f"row {line_no}: "
                        f"{self._mapping.definition_column!r} is "
                        f"{exc.type_name}, expected string"
                    ),
                    row_payload=line,
                    row_index=line_no,
                    source_path=source_path,
                    source_format=SOURCE_FORMAT_JSONL,
                )

        return ImportRecord(
            source_term=source_term,
            source_lang=self._mapping.source_lang,
            target_terms=tuple(target_terms),
            domain_id=domain_id,
            definition=definition,
        )


# --- Module-level helpers ---


def _string_at(payload: dict[str, Any], key: str) -> str | None:
    """Return the string value at ``payload[key]`` or ``None`` if
    the key is missing / the value is JSON ``null`` / the value is
    a blank string.

    Raises :class:`_MappedValueError` when the value is present but
    is not a string (numbers, booleans, nested objects, arrays).
    Caught by :meth:`JsonLinesSource._line_to_record` and converted
    into a typed :class:`SkippedRow`.

    Rationale (per cycle-4 S3 reviewer push-back): silent
    ``str()``-coercion of non-string scalars is a data-loss path —
    ``{"de_term": true}`` would become ``Term(surface="True")``,
    almost never the author's intent. Strict-string at every mapped
    column surfaces the type mismatch as an actionable skip reason
    so the operator can fix the source data once and re-run.
    """
    if key not in payload:
        return None
    value = payload[key]
    if value is None:
        # JSON null is a legitimate "intentionally absent" signal;
        # treat as missing key (same path).
        return None
    if not isinstance(value, str):
        raise _MappedValueError(type(value).__name__)
    stripped = value.strip()
    return stripped if stripped else None


__all__ = ["JsonLinesSource", "JsonlDecodeError"]
