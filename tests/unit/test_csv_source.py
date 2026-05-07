# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for
:class:`ainemo.core.termbase.sources.csv_source.CsvSource`.

Cycle-4 S2 contract:

- Empty CSV (no header) raises :class:`MissingColumnError`.
- Empty CSV (header only, no rows) yields nothing.
- Single-row file produces one :class:`ImportRecord`.
- Multi-target-lang row produces target_terms in mapping-declaration
  order.
- Optional columns (domain_column, definition_column) absent from
  mapping → ``ImportRecord.domain_id`` / ``definition`` is ``None``.
- Optional columns present but blank in a row → still ``None`` for
  that row.
- Blank source-term cell yields :class:`SkippedRow` with
  ``"row N: blank ..."``.
- Row with no non-blank target columns yields :class:`SkippedRow`.
- RFC 4180 quoted fields with embedded commas + newlines round-trip.
- Custom ``--delimiter`` (tab) honored.
- Custom ``--encoding`` (latin-1) honored.
- Header missing a referenced column → :class:`MissingColumnError`.
- ``provenance`` ClassVar is ``TERM_SOURCE_CSV_IMPORT``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.termbase.sources._ids import TERM_SOURCE_CSV_IMPORT
from ainemo.core.termbase.sources.base import (
    ImportRecord,
    SkippedRow,
    TermbaseSource,
)
from ainemo.core.termbase.sources.csv_source import (
    CsvDecodeError,
    CsvSource,
    MissingColumnError,
)
from ainemo.core.termbase.sources.mapping import FieldMapping

pytestmark = pytest.mark.unit


# --- Builders ---


def _minimal_mapping() -> FieldMapping:
    return FieldMapping(
        source_lang="en-US",
        source_column="term_en",
        target_columns={"de-DE": "term_de"},
    )


def _full_mapping() -> FieldMapping:
    return FieldMapping(
        source_lang="en-US",
        source_column="term_en",
        target_columns={"de-DE": "term_de", "fr-FR": "term_fr"},
        domain_column="category",
        definition_column="notes",
    )


def _write_csv(path: Path, contents: str, *, encoding: str = "utf-8") -> None:
    path.write_text(contents, encoding=encoding)


# --- Provenance + Protocol conformance ---


def test_provenance_classvar_is_csv_import() -> None:
    assert CsvSource.provenance == TERM_SOURCE_CSV_IMPORT


def test_csv_source_satisfies_termbase_source_protocol(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(path, "term_en,term_de\nlogin,Anmeldung\n")
    source = CsvSource(path, _minimal_mapping())
    assert isinstance(source, TermbaseSource)


# --- Header validation (file-level errors raise) ---


def test_empty_file_raises_missing_column(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    _write_csv(path, "")
    source = CsvSource(path, _minimal_mapping())
    with pytest.raises(MissingColumnError) as excinfo:
        list(source.iter_concepts())
    assert "no header" in str(excinfo.value).lower()


def test_header_missing_referenced_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(path, "term_en,term_fr\nlogin,connexion\n")
    source = CsvSource(path, _minimal_mapping())  # references term_de
    with pytest.raises(MissingColumnError) as excinfo:
        list(source.iter_concepts())
    msg = str(excinfo.value)
    assert "term_de" in msg
    assert "term_en" in msg or "term_fr" in msg  # header listed for context


def test_header_only_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(path, "term_en,term_de\n")
    source = CsvSource(path, _minimal_mapping())
    assert list(source.iter_concepts()) == []


# --- Happy-path row → ImportRecord ---


def test_single_row_produces_one_record(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(path, "term_en,term_de\nlogin,Anmeldung\n")
    source = CsvSource(path, _minimal_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.source_term == "login"
    assert record.source_lang == "en-US"
    assert record.target_terms == (("de-DE", "Anmeldung"),)
    assert record.domain_id is None
    assert record.definition is None


def test_multi_target_lang_row(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        "term_en,term_de,term_fr\nlogin,Anmeldung,connexion\n",
    )
    mapping = FieldMapping(
        source_lang="en-US",
        source_column="term_en",
        target_columns={"de-DE": "term_de", "fr-FR": "term_fr"},
    )
    source = CsvSource(path, mapping)
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    target_dict = dict(record.target_terms)
    assert target_dict == {"de-DE": "Anmeldung", "fr-FR": "connexion"}


def test_full_mapping_extracts_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        "term_en,term_de,term_fr,category,notes\n"
        "login,Anmeldung,connexion,software,Authenticate to a system\n",
    )
    source = CsvSource(path, _full_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.domain_id == "software"
    assert record.definition == "Authenticate to a system"


def test_optional_columns_blank_in_row_yields_none(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        "term_en,term_de,term_fr,category,notes\nlogin,Anmeldung,connexion,,   \n",
    )
    source = CsvSource(path, _full_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.domain_id is None
    assert record.definition is None


# --- Row-level skip cases (yield SkippedRow inline) ---


def test_blank_source_term_yields_skipped_row(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        "term_en,term_de\n,Anmeldung\nlogout,Abmeldung\n",
    )
    source = CsvSource(path, _minimal_mapping())
    items = list(source.iter_concepts())
    assert len(items) == 2
    skipped = items[0]
    assert isinstance(skipped, SkippedRow)
    # Header is line 1; first data row is line 2.
    assert "row 2" in skipped.reason
    assert "term_en" in skipped.reason
    record = items[1]
    assert isinstance(record, ImportRecord)
    assert record.source_term == "logout"


def test_all_blank_target_columns_yields_skipped_row(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        "term_en,term_de,term_fr\nlogin,, \n",
    )
    mapping = FieldMapping(
        source_lang="en-US",
        source_column="term_en",
        target_columns={"de-DE": "term_de", "fr-FR": "term_fr"},
    )
    source = CsvSource(path, mapping)
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "row 2" in item.reason
    assert "no non-blank target columns" in item.reason


def test_partial_blank_targets_yields_record_with_what_is_present(
    tmp_path: Path,
) -> None:
    # Only French has a value; German is blank. The record lands
    # with just the French target — no skip.
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        "term_en,term_de,term_fr\nlogin,,connexion\n",
    )
    mapping = FieldMapping(
        source_lang="en-US",
        source_column="term_en",
        target_columns={"de-DE": "term_de", "fr-FR": "term_fr"},
    )
    source = CsvSource(path, mapping)
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.target_terms == (("fr-FR", "connexion"),)


# --- RFC 4180 quoting ---


def test_quoted_field_with_embedded_comma(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        'term_en,term_de\n"login, button","Anmeldung, Schaltfläche"\n',
    )
    source = CsvSource(path, _minimal_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.source_term == "login, button"
    assert record.target_terms == (("de-DE", "Anmeldung, Schaltfläche"),)


def test_quoted_field_with_embedded_newline(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        'term_en,term_de\n"line one\nline two",Anmeldung\n',
    )
    source = CsvSource(path, _minimal_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.source_term == "line one\nline two"


# --- Dialect overrides ---


def test_custom_delimiter_tab(tmp_path: Path) -> None:
    path = tmp_path / "g.tsv"
    _write_csv(path, "term_en\tterm_de\nlogin\tAnmeldung\n")
    source = CsvSource(path, _minimal_mapping(), delimiter="\t")
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.source_term == "login"


def test_custom_encoding_latin1(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    # "Café" only round-trips through latin-1 if both write and read
    # use it; utf-8 read of latin-1 bytes raises UnicodeDecodeError.
    _write_csv(path, "term_en,term_de\nCafé,Kaffeehaus\n", encoding="latin-1")
    source = CsvSource(path, _minimal_mapping(), encoding="latin-1")
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.source_term == "Café"


def test_default_utf8_raises_csv_decode_error_on_latin1_file(
    tmp_path: Path,
) -> None:
    # Same file as above, but default utf-8 read. Per pitch § Risks:
    # encoding mismatches surface as a clean CsvDecodeError whose
    # message names the `--encoding` flag verbatim so the operator
    # learns the fix without reading the cycle-4 docs.
    path = tmp_path / "g.csv"
    _write_csv(path, "term_en,term_de\nCafé,Kaffeehaus\n", encoding="latin-1")
    source = CsvSource(path, _minimal_mapping())  # default utf-8
    with pytest.raises(CsvDecodeError) as excinfo:
        list(source.iter_concepts())
    msg = str(excinfo.value)
    assert "--encoding" in msg
    assert "latin-1" in msg
    # Original UnicodeDecodeError is the chained cause for callers
    # that want the byte-level details.
    assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)


# --- Multi-row scenario ---


def test_multi_row_file_yields_records_in_order(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    _write_csv(
        path,
        "term_en,term_de\n"
        "login,Anmeldung\n"
        ",skip-me\n"  # blank source — skipped row
        "logout,Abmeldung\n",
    )
    source = CsvSource(path, _minimal_mapping())
    items = list(source.iter_concepts())
    assert len(items) == 3
    assert isinstance(items[0], ImportRecord)
    assert items[0].source_term == "login"
    assert isinstance(items[1], SkippedRow)
    assert "row 3" in items[1].reason
    assert isinstance(items[2], ImportRecord)
    assert items[2].source_term == "logout"
