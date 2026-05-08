# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""CSV-backed :class:`~ainemo.core.termbase.sources.base.TermbaseSource`.

Cycle-4 S2 — reads a CSV file via Python's stdlib :mod:`csv` module
and applies a :class:`~ainemo.core.termbase.sources.mapping.FieldMapping`
to produce :class:`ImportRecord` rows.

Design choices
--------------

- **stdlib csv only.** No pandas, no chardet, no external CSV
  library. The audience use case is hundreds-to-low-thousands of
  rows; stdlib handles RFC 4180 quoting + delimiter overrides
  natively.
- **Streaming via DictReader.** The file is opened once and rows
  stream lazily — :meth:`iter_concepts` is a generator that closes
  the file when the iterator is exhausted (or garbage-collected).
- **Encoding errors at file level.** The file is opened with
  ``errors='strict'``; a non-decodable byte raises
  :class:`UnicodeDecodeError` from inside the iterator, which the
  loader bridge surfaces to the caller. Per pitch § Risks, the
  user re-runs with ``--encoding latin-1`` (or whatever applies)
  rather than auto-detecting.
- **Row-level mapping errors as :class:`SkippedRow`.** Per the
  Protocol contract, a row with a blank source-term cell, a row
  with no non-blank target columns, or any other row-level mapping
  failure yields a :class:`SkippedRow` with a ``"row N: <reason>"``
  message — never raises. Only file-level errors (missing column
  in header, decode error, IO error) raise.
- **Header-column validation up-front.** The CSV's header row must
  contain every column name the mapping references. Missing columns
  raise :class:`MissingColumnError` before the first record is
  yielded, so the operator gets one clear error rather than N
  per-row reports.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import ClassVar, Iterator, Sequence

from ainemo.core.termbase.sources._ids import (
    DEFAULT_CSV_DELIMITER,
    DEFAULT_CSV_ENCODING,
    DEFAULT_CSV_QUOTECHAR,
    SOURCE_FORMAT_CSV,
    TERM_SOURCE_CSV_IMPORT,
)
from ainemo.core.termbase.sources.base import (
    ImportRecord,
    SkippedRow,
)
from ainemo.core.termbase.sources.mapping import FieldMapping


class MissingColumnError(ValueError):
    """Raised when the CSV's header row is missing one or more
    columns the :class:`FieldMapping` references.

    File-level error per the
    :meth:`TermbaseSource.iter_concepts` contract — distinct from
    row-level :class:`SkippedRow` items because no per-row recovery
    is possible: every row in the file is missing the column.
    """


class CsvDecodeError(ValueError):
    """Raised when the CSV cannot be decoded with the configured
    encoding.

    Wraps the stdlib :class:`UnicodeDecodeError` with a message that
    names the ``--encoding`` CLI flag verbatim so the operator
    learns the fix without reading the cycle-4 docs. File-level
    error per the :meth:`TermbaseSource.iter_concepts` contract.
    """


class CsvSource:
    """Reads a CSV file into :class:`ImportRecord` rows.

    Construction is cheap; the file isn't opened until
    :meth:`iter_concepts` is called.
    """

    provenance: ClassVar[str] = TERM_SOURCE_CSV_IMPORT

    def __init__(
        self,
        path: Path,
        mapping: FieldMapping,
        *,
        encoding: str = DEFAULT_CSV_ENCODING,
        delimiter: str = DEFAULT_CSV_DELIMITER,
        quotechar: str = DEFAULT_CSV_QUOTECHAR,
    ) -> None:
        self._path = path
        self._mapping = mapping
        self._encoding = encoding
        self._delimiter = delimiter
        self._quotechar = quotechar

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        try:
            with self._path.open(
                "r",
                encoding=self._encoding,
                errors="strict",
                newline="",
            ) as fh:
                reader = csv.DictReader(
                    fh,
                    delimiter=self._delimiter,
                    quotechar=self._quotechar,
                )
                self._validate_header(reader.fieldnames)
                # csv.DictReader rows are 1-indexed below the header,
                # but humans read line numbers including the header. We
                # report "row N" where N is the 1-indexed file line
                # (header = line 1, first data row = line 2) so
                # operators can grep their CSV directly.
                for line_no, row in enumerate(reader, start=2):
                    outcome = self._row_to_record(row, line_no)
                    if outcome is not None:
                        yield outcome
        except UnicodeDecodeError as exc:
            # Per pitch § Risks: encoding mismatches surface as a
            # clean error mentioning the `--encoding` flag verbatim
            # so the operator can re-run with the right codec
            # without reading cycle-4 docs. The S4 CLI scope wires
            # the flag; this message names it now so the user
            # benefits as soon as both ship.
            raise CsvDecodeError(
                f"Could not decode {self._path} as {self._encoding!r} "
                f"(byte 0x{exc.object[exc.start]:02x} at position "
                f"{exc.start}). Re-run with `--encoding latin-1` "
                "(or whichever codec your file actually uses)."
            ) from exc

    # --- Internals ---

    def _validate_header(self, fieldnames: Sequence[str] | None) -> None:
        if fieldnames is None:
            # Empty file — no header at all. csv.DictReader yields
            # nothing in this case; we surface it as a clean
            # file-level error rather than silently producing zero
            # rows (the operator probably meant to import a real
            # file).
            raise MissingColumnError(f"CSV file {self._path} has no header row (file is empty)")
        header = set(fieldnames)
        missing = [col for col in self._mapping.all_referenced_columns() if col not in header]
        if missing:
            raise MissingColumnError(
                f"CSV file {self._path} header is missing column(s) "
                f"referenced by the mapping: {missing!r}. Available "
                f"columns: {sorted(header)!r}."
            )

    def _row_to_record(
        self, row: dict[str, str | None], line_no: int
    ) -> ImportRecord | SkippedRow | None:
        source_term = _strip_or_none(row.get(self._mapping.source_column))
        if source_term is None:
            return SkippedRow(
                reason=f"row {line_no}: blank {self._mapping.source_column!r} cell",
                row_payload=_row_payload(row),
                row_index=line_no,
                source_path=str(self._path),
                source_format=SOURCE_FORMAT_CSV,
            )

        target_terms: list[tuple[str, str]] = []
        for target_lang, column in self._mapping.target_columns.items():
            surface = _strip_or_none(row.get(column))
            if surface is not None:
                target_terms.append((target_lang, surface))

        if not target_terms:
            return SkippedRow(
                reason=(
                    f"row {line_no}: no non-blank target columns "
                    f"({list(self._mapping.target_columns.values())!r} all blank)"
                ),
                row_payload=_row_payload(row),
                row_index=line_no,
                source_path=str(self._path),
                source_format=SOURCE_FORMAT_CSV,
            )

        domain_id: str | None = None
        if self._mapping.domain_column is not None:
            domain_id = _strip_or_none(row.get(self._mapping.domain_column))

        definition: str | None = None
        if self._mapping.definition_column is not None:
            definition = _strip_or_none(row.get(self._mapping.definition_column))

        return ImportRecord(
            source_term=source_term,
            source_lang=self._mapping.source_lang,
            target_terms=tuple(target_terms),
            domain_id=domain_id,
            definition=definition,
        )


# --- Module-level helpers ---


def _row_payload(row: dict[str, str | None]) -> str:
    """JSON-serialise a ``csv.DictReader`` row dict for storage in
    :attr:`SkippedRow.row_payload`.

    ``csv.DictReader`` may include a ``None`` key when a data row has
    more fields than the header (the extras land under key ``None``
    as a list).  ``json.dumps`` requires string keys, so any ``None``
    key is converted to the literal string ``"__extras__"`` before
    serialisation.  This is an edge case in malformed CSVs; the
    operator fix is to clean the source file, not to round-trip the
    extras faithfully.
    """
    cleaned: dict[str, object] = {(k if k is not None else "__extras__"): v for k, v in row.items()}
    return json.dumps(cleaned, ensure_ascii=False)


def _strip_or_none(value: str | None) -> str | None:
    """Return ``value.strip()`` if it has any non-whitespace
    characters, else ``None``. CSV cells often arrive as ``""`` or
    ``"   "`` for "no value"; the importer treats both identically.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


__all__ = [
    "CsvSource",
    "MissingColumnError",
]
