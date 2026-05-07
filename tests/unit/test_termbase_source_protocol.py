# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-4 S1 — :class:`TermbaseSource` Protocol contract tests.

Pin the S1 Protocol surface against an in-process test stub so the
S2 / S3 concrete sources have a clear conformance bar before they
land. Mirrors the cycle-3 contract-test convention
(``test_kuzu_termbase.py`` § "Protocol contract").

Cycle-4 S1 P1 review fix: ``iter_concepts()`` now yields
``Iterator[ImportRecord | SkippedRow]`` so row-level parse / mapping
errors travel through the iterator rather than via a side channel.
This file pins the contract.
"""

from __future__ import annotations

from typing import ClassVar, Iterator

import pytest

from ainemo.core.termbase.sources.base import (
    ImportRecord,
    SkippedRow,
    TermbaseSource,
)

pytestmark = pytest.mark.unit


# --- In-process stub source that yields a documented mix of
#     ImportRecord + SkippedRow items, exercising the union return
#     type in both directions. ---


class _StubSource:
    """Minimal :class:`TermbaseSource` test double — yields whatever
    items it was constructed with."""

    provenance: ClassVar[str] = "stub-source"

    def __init__(self, items: list[ImportRecord | SkippedRow]) -> None:
        self._items = items

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        yield from self._items


def _make_record(source_term: str, target_lang: str = "de-DE") -> ImportRecord:
    return ImportRecord(
        source_term=source_term,
        source_lang="en-US",
        target_terms=((target_lang, f"{source_term}-{target_lang}"),),
        domain_id=None,
        definition=None,
    )


# --- Protocol conformance ---


def test_stub_satisfies_termbase_source_protocol() -> None:
    stub = _StubSource([])
    assert isinstance(stub, TermbaseSource)


def test_iter_concepts_yields_records_only() -> None:
    items: list[ImportRecord | SkippedRow] = [
        _make_record("login"),
        _make_record("logout"),
    ]
    stub = _StubSource(items)
    yielded = list(stub.iter_concepts())
    assert len(yielded) == 2
    assert all(isinstance(item, ImportRecord) for item in yielded)


def test_iter_concepts_yields_skipped_rows_inline() -> None:
    """Cycle-4 S1 P1 regression: SkippedRow flows through the same
    iterator as ImportRecord so the loader bridge can accumulate
    skip reasons without a side channel."""
    items: list[ImportRecord | SkippedRow] = [
        _make_record("login"),
        SkippedRow(reason="row 12: blank source_term"),
        _make_record("logout"),
        SkippedRow(reason="row 47: malformed JSON"),
    ]
    stub = _StubSource(items)
    yielded = list(stub.iter_concepts())
    records = [item for item in yielded if isinstance(item, ImportRecord)]
    skips = [item for item in yielded if isinstance(item, SkippedRow)]
    assert len(records) == 2
    assert len(skips) == 2
    assert skips[0].reason == "row 12: blank source_term"
    assert skips[1].reason == "row 47: malformed JSON"


def test_skip_reason_is_immutable() -> None:
    skip = SkippedRow(reason="row 5: empty target column")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        skip.reason = "tampered"  # type: ignore[misc]


def test_import_record_is_immutable() -> None:
    record = _make_record("login")
    with pytest.raises(Exception):
        record.source_term = "logout"  # type: ignore[misc]


def test_iter_concepts_can_be_empty() -> None:
    # Empty source file (no rows) is a legitimate input — should
    # yield nothing rather than raise.
    stub = _StubSource([])
    assert list(stub.iter_concepts()) == []
