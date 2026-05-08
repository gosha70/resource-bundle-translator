# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S3 structured ``SkippedRow`` fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainemo.core.termbase.sources._ids import SOURCE_FORMAT_CSV, SOURCE_FORMAT_JSONL
from ainemo.core.termbase.sources.base import SkippedRow
from ainemo.core.termbase.sources.csv_source import CsvSource
from ainemo.core.termbase.sources.jsonl_source import JsonLinesSource
from ainemo.core.termbase.sources.mapping import FieldMapping

pytestmark = pytest.mark.unit


def _mapping() -> FieldMapping:
    return FieldMapping(
        source_lang="en",
        source_column="source",
        target_columns={"de": "target"},
    )


def test_skipped_row_backward_compatible_constructor() -> None:
    row = SkippedRow(reason="row 12: blank source")
    assert row.reason == "row 12: blank source"
    assert row.row_payload is None
    assert row.row_index is None
    assert row.source_path is None
    assert row.source_format is None


def test_csv_source_populates_structured_skip_fields(tmp_path: Path) -> None:
    path = tmp_path / "terms.csv"
    path.write_text("source,target\n,Anmeldung\n", encoding="utf-8")

    item = next(CsvSource(path, _mapping()).iter_concepts())

    assert isinstance(item, SkippedRow)
    assert item.row_index == 2
    assert item.source_path == str(path)
    assert item.source_format == SOURCE_FORMAT_CSV
    assert json.loads(item.row_payload or "") == {"source": "", "target": "Anmeldung"}


def test_jsonl_source_populates_structured_skip_fields(tmp_path: Path) -> None:
    path = tmp_path / "terms.jsonl"
    path.write_text('{"source": "", "target": "Anmeldung"}\n', encoding="utf-8")

    item = next(JsonLinesSource(path, _mapping()).iter_concepts())

    assert isinstance(item, SkippedRow)
    assert item.row_index == 1
    assert item.source_path == str(path)
    assert item.source_format == SOURCE_FORMAT_JSONL
    assert item.row_payload == '{"source": "", "target": "Anmeldung"}'
