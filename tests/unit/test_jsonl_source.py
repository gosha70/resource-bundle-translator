# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for
:class:`ainemo.core.termbase.sources.jsonl_source.JsonLinesSource`.

Cycle-4 S3 contract:

- Empty file yields nothing (not an error).
- Blank lines silently skipped (JSONL convention for human-edited
  files).
- Single valid JSON object → :class:`ImportRecord`.
- Multi-line file preserves order including ``SkippedRow`` items
  inline.
- Malformed JSON → :class:`SkippedRow` with line number; rest of
  file still parses (Protocol contract: row-level errors do not
  abort the import).
- Non-object top-level JSON value (string, number, array) →
  :class:`SkippedRow`.
- Missing or blank source key → :class:`SkippedRow`.
- All target keys missing/blank → :class:`SkippedRow`.
- Optional fields (``domain_id``, ``definition``) populated when
  set, ``None`` otherwise.
- Non-string scalars (numbers, booleans) at mapped keys yield
  :class:`SkippedRow` with the JSON type named — strict-string per
  the cycle-4 S3 P2 review (silent ``str()``-coercion is a data-
  loss path).
- Nested objects / arrays at mapped keys → typed :class:`SkippedRow`
  (P2 review #2 — was silent ``None`` previously).
- JSON ``null`` at a mapped key treated as missing (matches CSV).
- :class:`JsonlDecodeError` wraps :class:`UnicodeDecodeError` with
  ``--encoding`` named verbatim — parity with CsvSource's
  :class:`CsvDecodeError` per the cycle-4 S3 P3 review.
- ``provenance`` ClassVar is ``TERM_SOURCE_JSONL_IMPORT``.
- Satisfies :class:`TermbaseSource` Protocol.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.termbase.sources._ids import TERM_SOURCE_JSONL_IMPORT
from ainemo.core.termbase.sources.base import (
    ImportRecord,
    SkippedRow,
    TermbaseSource,
)
from ainemo.core.termbase.sources.jsonl_source import (
    JsonlDecodeError,
    JsonLinesSource,
)
from ainemo.core.termbase.sources.mapping import FieldMapping

pytestmark = pytest.mark.unit


# --- Builders ---


def _minimal_mapping() -> FieldMapping:
    return FieldMapping(
        source_lang="en-US",
        source_column="source",
        target_columns={"de-DE": "de"},
    )


def _full_mapping() -> FieldMapping:
    return FieldMapping(
        source_lang="en-US",
        source_column="source",
        target_columns={"de-DE": "de", "fr-FR": "fr"},
        domain_column="domain",
        definition_column="def",
    )


def _write_jsonl(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")


# --- Provenance + Protocol conformance ---


def test_provenance_classvar_is_jsonl_import() -> None:
    assert JsonLinesSource.provenance == TERM_SOURCE_JSONL_IMPORT


def test_jsonl_source_satisfies_termbase_source_protocol(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(path, '{"source": "login", "de": "Anmeldung"}\n')
    source = JsonLinesSource(path, _minimal_mapping())
    assert isinstance(source, TermbaseSource)


# --- Happy paths ---


def test_single_line_yields_one_record(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(path, '{"source": "login", "de": "Anmeldung"}\n')
    source = JsonLinesSource(path, _minimal_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.source_term == "login"
    assert record.source_lang == "en-US"
    assert record.target_terms == (("de-DE", "Anmeldung"),)
    assert record.domain_id is None
    assert record.definition is None


def test_multi_line_file_preserves_order(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "login", "de": "Anmeldung"}\n'
        '{"source": "logout", "de": "Abmeldung"}\n'
        '{"source": "cancel", "de": "Abbrechen"}\n',
    )
    source = JsonLinesSource(path, _minimal_mapping())
    records = list(source.iter_concepts())
    assert len(records) == 3
    assert all(isinstance(r, ImportRecord) for r in records)
    surfaces = [r.source_term for r in records if isinstance(r, ImportRecord)]
    assert surfaces == ["login", "logout", "cancel"]


def test_full_mapping_extracts_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        (
            '{"source": "login", "de": "Anmeldung", "fr": "connexion", '
            '"domain": "software", "def": "Authenticate to a system"}\n'
        ),
    )
    source = JsonLinesSource(path, _full_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.domain_id == "software"
    assert record.definition == "Authenticate to a system"
    assert dict(record.target_terms) == {
        "de-DE": "Anmeldung",
        "fr-FR": "connexion",
    }


# --- Edge cases ---


def test_empty_file_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(path, "")
    source = JsonLinesSource(path, _minimal_mapping())
    assert list(source.iter_concepts()) == []


def test_blank_lines_silently_skipped(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "login", "de": "Anmeldung"}\n\n   \n{"source": "logout", "de": "Abmeldung"}\n',
    )
    source = JsonLinesSource(path, _minimal_mapping())
    items = list(source.iter_concepts())
    # Two records, no SkippedRows from the blank lines.
    assert len(items) == 2
    assert all(isinstance(item, ImportRecord) for item in items)


def test_optional_columns_blank_in_row_yield_none(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        ('{"source": "login", "de": "Anmeldung", "fr": "connexion", "domain": "", "def": "   "}\n'),
    )
    source = JsonLinesSource(path, _full_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.domain_id is None
    assert record.definition is None


def test_non_string_source_value_yields_skipped_row(tmp_path: Path) -> None:
    # Cycle-4 S3 P2 reviewer push-back: silent str()-coercion is a
    # data-loss path. A bare integer or boolean at a mapped key
    # almost always indicates a stray spreadsheet-coerced default
    # rather than the author's intent. Strict-string surfaces the
    # type mismatch with an actionable reason.
    path = tmp_path / "g.jsonl"
    _write_jsonl(path, '{"source": 42, "de": "zweiundvierzig"}\n')
    source = JsonLinesSource(path, _minimal_mapping())
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "source" in item.reason
    assert "int" in item.reason
    assert "expected string" in item.reason


def test_non_string_target_value_yields_skipped_row(tmp_path: Path) -> None:
    # The motivating case from the reviewer: a Boolean True landing
    # in a translation column from a spreadsheet's empty-cell
    # default would silently become Term(surface="True") under
    # str()-coercion. Strict-string catches it.
    path = tmp_path / "g.jsonl"
    _write_jsonl(path, '{"source": "yes", "de": true}\n')
    source = JsonLinesSource(path, _minimal_mapping())
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "de" in item.reason
    assert "bool" in item.reason
    assert "expected string" in item.reason


def test_non_string_metadata_value_yields_skipped_row(tmp_path: Path) -> None:
    # Same strict rule applies to optional metadata columns
    # (domain, definition) — non-string values surface as typed
    # SkippedRow rather than silently lose semantic info.
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "login", "de": "Anmeldung", "fr": "connexion", "domain": 7, "def": "x"}\n',
    )
    source = JsonLinesSource(path, _full_mapping())
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "domain" in item.reason
    assert "int" in item.reason


def test_json_null_at_mapped_key_treated_as_missing(tmp_path: Path) -> None:
    # JSON null is the legitimate "intentionally absent" signal;
    # treat the same as a missing key. Source null → SkippedRow
    # (missing source); optional null → None on the field.
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "login", "de": "Anmeldung", "fr": "connexion", "domain": null, "def": null}\n',
    )
    source = JsonLinesSource(path, _full_mapping())
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.domain_id is None
    assert record.definition is None


# --- Row-level skip cases ---


def test_malformed_json_yields_skipped_row(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "login", "de": "Anmeldung"}\n'
        "not-valid-json\n"
        '{"source": "logout", "de": "Abmeldung"}\n',
    )
    source = JsonLinesSource(path, _minimal_mapping())
    items = list(source.iter_concepts())
    assert len(items) == 3
    assert isinstance(items[0], ImportRecord)
    assert isinstance(items[1], SkippedRow)
    assert "row 2" in items[1].reason
    assert "malformed JSON" in items[1].reason
    # Rest of file still parsed.
    assert isinstance(items[2], ImportRecord)
    assert items[2].source_term == "logout"


def test_non_object_top_level_yields_skipped_row(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "login", "de": "Anmeldung"}\n'
        '"a bare string"\n'
        "[1, 2, 3]\n"
        "42\n"
        '{"source": "logout", "de": "Abmeldung"}\n',
    )
    source = JsonLinesSource(path, _minimal_mapping())
    items = list(source.iter_concepts())
    assert len(items) == 5
    assert isinstance(items[1], SkippedRow)
    assert "expected object" in items[1].reason
    assert "str" in items[1].reason
    assert isinstance(items[2], SkippedRow)
    assert "list" in items[2].reason
    assert isinstance(items[3], SkippedRow)
    assert "int" in items[3].reason


def test_missing_source_key_yields_skipped_row(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"other_key": "x", "de": "Anmeldung"}\n{"source": "login", "de": "Anmeldung"}\n',
    )
    source = JsonLinesSource(path, _minimal_mapping())
    items = list(source.iter_concepts())
    assert len(items) == 2
    assert isinstance(items[0], SkippedRow)
    assert "row 1" in items[0].reason
    assert "source" in items[0].reason
    assert isinstance(items[1], ImportRecord)


def test_blank_source_value_yields_skipped_row(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    _write_jsonl(path, '{"source": "   ", "de": "Anmeldung"}\n')
    source = JsonLinesSource(path, _minimal_mapping())
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "missing or blank" in item.reason
    assert "source" in item.reason


def test_all_target_keys_missing_yields_skipped_row(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    mapping = FieldMapping(
        source_lang="en-US",
        source_column="source",
        target_columns={"de-DE": "de", "fr-FR": "fr"},
    )
    _write_jsonl(path, '{"source": "login"}\n')
    source = JsonLinesSource(path, mapping)
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "no non-blank target keys" in item.reason


def test_partial_target_keys_yields_record_with_what_is_present(
    tmp_path: Path,
) -> None:
    # Same as CsvSource: a row with some targets present + some
    # missing lands as a record carrying just what's present, not
    # a skip.
    path = tmp_path / "g.jsonl"
    mapping = FieldMapping(
        source_lang="en-US",
        source_column="source",
        target_columns={"de-DE": "de", "fr-FR": "fr"},
    )
    _write_jsonl(path, '{"source": "login", "fr": "connexion"}\n')
    source = JsonLinesSource(path, mapping)
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.target_terms == (("fr-FR", "connexion"),)


# --- Nested values ---


def test_nested_object_under_target_key_yields_typed_skipped_row(
    tmp_path: Path,
) -> None:
    # Cycle-4 S3 P2 push-back #2: nested objects/arrays under a
    # mapped key used to silently → None (which then surfaced as
    # "no non-blank target keys" — confusing). Now they yield a
    # typed SkippedRow naming the actual JSON shape so the operator
    # learns that nested CMS-export shapes need to be flattened
    # before import. Same pattern as the type-named top-level case.
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "login", "de": {"primary": "Anmeldung"}}\n',
    )
    source = JsonLinesSource(path, _minimal_mapping())
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "de" in item.reason
    assert "dict" in item.reason
    assert "expected string" in item.reason


def test_array_under_target_key_yields_typed_skipped_row(
    tmp_path: Path,
) -> None:
    # Same rule applies to arrays — a list of synonyms in one cell
    # is a flatten-before-import case, not a silent skip.
    path = tmp_path / "g.jsonl"
    _write_jsonl(
        path,
        '{"source": "fast", "de": ["schnell", "rasch"]}\n',
    )
    source = JsonLinesSource(path, _minimal_mapping())
    [item] = list(source.iter_concepts())
    assert isinstance(item, SkippedRow)
    assert "de" in item.reason
    assert "list" in item.reason
    assert "expected string" in item.reason


# --- Cycle-4 S3 P3 push-back: encoding parity with CsvSource ---


def test_default_utf8_raises_jsonl_decode_error_on_latin1_file(
    tmp_path: Path,
) -> None:
    # Parity with CsvSource's CsvDecodeError contract — a latin-1
    # JSONL file read with the default utf-8 encoding raises a
    # JsonlDecodeError whose message names the `--encoding` flag
    # verbatim, with the original UnicodeDecodeError as __cause__.
    # Cheap to fix in S3, expensive to fix in cooldown.
    path = tmp_path / "g.jsonl"
    path.write_text(
        '{"source": "Café", "de": "Kaffeehaus"}\n',
        encoding="latin-1",
    )
    source = JsonLinesSource(path, _minimal_mapping())  # default utf-8
    with pytest.raises(JsonlDecodeError) as excinfo:
        list(source.iter_concepts())
    msg = str(excinfo.value)
    assert "--encoding" in msg
    assert "latin-1" in msg
    assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)


def test_custom_encoding_latin1_decodes_cleanly(tmp_path: Path) -> None:
    # Symmetric with the CsvSource latin-1 test — confirm the
    # explicit `--encoding latin-1` round-trips correctly.
    path = tmp_path / "g.jsonl"
    path.write_text(
        '{"source": "Café", "de": "Kaffeehaus"}\n',
        encoding="latin-1",
    )
    source = JsonLinesSource(path, _minimal_mapping(), encoding="latin-1")
    [record] = list(source.iter_concepts())
    assert isinstance(record, ImportRecord)
    assert record.source_term == "Café"
