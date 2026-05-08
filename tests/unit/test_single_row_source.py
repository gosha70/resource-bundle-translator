# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S3 ``single_row_source`` retry adapter tests."""

from __future__ import annotations

import pytest

from ainemo.app.store.import_skips import ImportSkipRow, _derive_skip_id, single_row_source
from ainemo.core.termbase.sources._ids import (
    SOURCE_FORMAT_CSV,
    SOURCE_FORMAT_JSONL,
    TERM_SOURCE_CSV_IMPORT,
    TERM_SOURCE_JSONL_IMPORT,
)
from ainemo.core.termbase.sources.base import ImportRecord, SkippedRow
from ainemo.core.termbase.sources.mapping import FieldMapping

pytestmark = pytest.mark.unit


def _mapping() -> FieldMapping:
    return FieldMapping(
        source_lang="en",
        source_column="source",
        target_columns={"de": "target"},
    )


def _row(*, source_format: str, payload: str) -> ImportSkipRow:
    return ImportSkipRow(
        skip_id=_derive_skip_id(source_path="terms", row_index=2, row_payload=payload),
        source_path="terms",
        source_format=source_format,
        row_index=2,
        row_payload=payload,
        skip_reason="row 2: skipped",
        created_at=100,
        last_retried_at=None,
    )


def test_single_row_csv_source_yields_import_record() -> None:
    row = _row(
        source_format=SOURCE_FORMAT_CSV,
        payload='{"source": "login", "target": "Anmeldung"}',
    )
    source = single_row_source(row, _mapping())

    items = tuple(source.iter_concepts())

    assert source.provenance == TERM_SOURCE_CSV_IMPORT
    assert len(items) == 1
    assert isinstance(items[0], ImportRecord)
    assert items[0].source_term == "login"
    assert items[0].target_terms == (("de", "Anmeldung"),)


def test_single_row_csv_source_yields_skipped_row_when_still_invalid() -> None:
    row = _row(source_format=SOURCE_FORMAT_CSV, payload='{"source": "", "target": "Anmeldung"}')
    source = single_row_source(row, _mapping())

    item = next(source.iter_concepts())

    assert isinstance(item, SkippedRow)
    assert item.row_index == 2
    assert item.source_format == SOURCE_FORMAT_CSV


def test_single_row_csv_source_rejects_non_object_payload() -> None:
    row = _row(source_format=SOURCE_FORMAT_CSV, payload='["not", "an", "object"]')
    source = single_row_source(row, _mapping())

    item = next(source.iter_concepts())

    assert isinstance(item, SkippedRow)
    assert "expected object" in item.reason


def test_single_row_csv_source_rejects_non_string_values() -> None:
    row = _row(source_format=SOURCE_FORMAT_CSV, payload='{"source": 12, "target": "Anmeldung"}')
    source = single_row_source(row, _mapping())

    item = next(source.iter_concepts())

    assert isinstance(item, SkippedRow)
    assert "expected string" in item.reason


def test_single_row_jsonl_source_yields_import_record() -> None:
    row = _row(
        source_format=SOURCE_FORMAT_JSONL,
        payload='{"source": "login", "target": "Anmeldung"}',
    )
    source = single_row_source(row, _mapping())

    item = next(source.iter_concepts())

    assert source.provenance == TERM_SOURCE_JSONL_IMPORT
    assert isinstance(item, ImportRecord)
    assert item.source_term == "login"


def test_single_row_source_rejects_unknown_format() -> None:
    row = _row(source_format="xml", payload="<row />")

    with pytest.raises(ValueError, match="Unsupported import-skip source_format"):
        single_row_source(row, _mapping())
