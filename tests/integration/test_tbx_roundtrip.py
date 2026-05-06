# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-3 S3 — TBX 3.0 Weblate round-trip integration test.

Asserts ``import → export → import → export`` is byte-stable on
the Weblate-style fixtures landed in S2. The first export may
not match the source byte-for-byte (the source has Weblate-specific
header text, comment whitespace, attribute ordering, etc.), but the
*second* export must equal the first — that is the determinism
contract the cycle-3 termbase makes to TBX consumers.

Per the pitch § Test strategy "Integration":

> TBX round-trip: Weblate-exported TBX → TbxImporter → Kuzu →
> TbxExporter → second TBX; assert canonical-XML equivalence
> (element-order normalized).

The exporter writes deterministically by construction (concepts
sorted by id, langSec by lang, terms by surface, single-valued
header fields), so the test is a plain bytes equality check rather
than a canonical-XML diff. The benchmark file (``cycle-3-tbx-roundtrip.md``)
documents the manual procedure for asserting parity against
*real* Weblate exports — that is a checked-in artifact, not a
live test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.termbase.tbx.exporter import TbxExporter
from ainemo.core.termbase.tbx.importer import TbxImporter, TbxImportReport

pytestmark = pytest.mark.integration


_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tbx"

# All five Weblate-style fixtures from S2. The pathological-* fixtures
# are deliberately omitted: the exporter writes deterministic output
# but it does not promise to *re-emit* fixtures that contain
# unsupported elements (those land in skipped_unsupported on import
# and are absent from the export by design).
_WEBLATE_FIXTURES = (
    "weblate-software-en-de.tbx",
    "weblate-multi-lang.tbx",
    "weblate-with-pos-register.tbx",
    "weblate-multi-term-per-lang.tbx",
    "weblate-with-definitions.tbx",
)


@pytest.mark.parametrize("fixture", _WEBLATE_FIXTURES)
def test_weblate_fixture_round_trip_is_byte_stable(fixture: str, tmp_path: Path) -> None:
    source = _FIXTURE_DIR / fixture

    # Pass 1: source TBX → tb1 → export1
    tb1 = KuzuTermbase(tmp_path / "tb1.kuzu")
    report1 = TbxImporter(tb1, now=lambda: 1700000000).import_file(source)
    assert report1.skipped_unsupported == ()
    export1 = TbxExporter(tb1).export_bytes()

    # Pass 2: export1 → tb2 → export2
    tb2 = KuzuTermbase(tmp_path / "tb2.kuzu")
    report2 = TbxImporter(tb2, now=lambda: 1700000000).import_bytes(export1)
    assert report2.skipped_unsupported == ()
    export2 = TbxExporter(tb2).export_bytes()

    assert export1 == export2, (
        f"Round-trip drift on {fixture}: {len(export1)} vs {len(export2)} bytes"
    )


def test_round_trip_preserves_concept_count_and_terms(tmp_path: Path) -> None:
    # Sanity check that the round-trip preserves data semantics, not
    # just bytes. Using weblate-multi-lang because it has the most
    # languages per concept (en/de/fr/es).
    source = _FIXTURE_DIR / "weblate-multi-lang.tbx"
    tb1 = KuzuTermbase(tmp_path / "tb1.kuzu")
    TbxImporter(tb1).import_file(source)
    stats1 = tb1.stats()

    export1 = TbxExporter(tb1).export_bytes()

    tb2 = KuzuTermbase(tmp_path / "tb2.kuzu")
    TbxImporter(tb2).import_bytes(export1)
    stats2 = tb2.stats()

    assert stats1.concept_count == stats2.concept_count
    assert stats1.term_count_by_lang == stats2.term_count_by_lang


def test_round_trip_preserves_register_and_pos(tmp_path: Path) -> None:
    # weblate-with-pos-register.tbx exercises every register value
    # (formal/casual/neutral) and several POS tags. The contract is
    # that every Term field surfaces back identically after a
    # round-trip.
    source = _FIXTURE_DIR / "weblate-with-pos-register.tbx"
    tb1 = KuzuTermbase(tmp_path / "tb1.kuzu")
    TbxImporter(tb1).import_file(source)
    entries1 = sorted(
        tb1.iter_concept_entries(),
        key=lambda e: e.concept.concept_id,
    )

    export1 = TbxExporter(tb1).export_bytes()

    tb2 = KuzuTermbase(tmp_path / "tb2.kuzu")
    TbxImporter(tb2).import_bytes(export1)
    entries2 = sorted(
        tb2.iter_concept_entries(),
        key=lambda e: e.concept.concept_id,
    )

    assert len(entries1) == len(entries2)
    for entry1, entry2 in zip(entries1, entries2):
        terms1 = {(t.lang, t.surface): t for t in entry1.terms}
        terms2 = {(t.lang, t.surface): t for t in entry2.terms}
        assert terms1.keys() == terms2.keys()
        for key in terms1:
            assert terms1[key].register == terms2[key].register
            assert terms1[key].part_of_speech == terms2[key].part_of_speech


def test_round_trip_skipped_unsupported_stays_empty_for_weblate_fixtures(
    tmp_path: Path,
) -> None:
    # Re-importing our own export must not surface any new skipped
    # elements — if it did, the exporter is emitting something the
    # importer rejects, which would be a contract bug.
    for fixture in _WEBLATE_FIXTURES:
        source = _FIXTURE_DIR / fixture
        tb = KuzuTermbase(tmp_path / f"{fixture}.kuzu")
        TbxImporter(tb).import_file(source)
        export = TbxExporter(tb).export_bytes()

        tb_round = KuzuTermbase(tmp_path / f"{fixture}.round.kuzu")
        report: TbxImportReport = TbxImporter(tb_round).import_bytes(export)
        assert report.skipped_unsupported == (), (
            f"{fixture}: unexpected skipped on re-import {report.skipped_unsupported}"
        )
