# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-4 S2 — namespace-collision contract for the importer
loader bridge.

Pins the concept-id derivation rules the cycle-4 S1 P2 review
settled on:

1. Same ``source_term`` + same ``source_lang`` + DIFFERENT
   ``domain_id`` values → DIFFERENT concept ids (the marketing
   ``cancel`` and the legal ``cancel`` are distinct concepts).
2. Same ``source_term`` + same ``source_lang`` + SAME ``domain_id``
   → SAME concept id across re-imports (idempotency: re-running the
   same import upserts onto the same row).
3. Per-import ``namespace`` argument honored when the row has no
   ``domain_id``.
4. Row-level ``domain_id`` takes precedence over the per-import
   ``namespace`` argument when both are set.
5. Empty / global namespace falls through when neither is set.

The ``_derive_import_concept_id`` function is the contract surface;
the loader uses it internally and tests pin it directly.
"""

from __future__ import annotations

from typing import ClassVar, Iterator

import pytest

from ainemo.core.termbase.sources._ids import TERM_SOURCE_CSV_IMPORT
from ainemo.core.termbase.sources.base import (
    ImportRecord,
    SkippedRow,
)
from ainemo.core.termbase.sources.loader import (
    _derive_import_concept_id,
    load_into_termbase,
)
from tests.termbase_stub import RecordingTermbase

pytestmark = pytest.mark.unit


# --- In-process Source stub yielding pre-built records ---


class _RecordSource:
    """Yields pre-built :class:`ImportRecord` items (no parsing).
    Lets these tests focus on the loader's derivation logic without
    spinning up a CSV parser."""

    provenance: ClassVar[str] = TERM_SOURCE_CSV_IMPORT

    def __init__(self, items: list[ImportRecord | SkippedRow]) -> None:
        self._items = items

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        yield from self._items


def _record(
    source_term: str,
    *,
    source_lang: str = "en-US",
    target_lang: str = "de-DE",
    target_surface: str | None = None,
    domain_id: str | None = None,
) -> ImportRecord:
    return ImportRecord(
        source_term=source_term,
        source_lang=source_lang,
        target_terms=((target_lang, target_surface or f"{source_term}-translated"),),
        domain_id=domain_id,
        definition=None,
    )


# --- _derive_import_concept_id directly ---


def test_same_term_different_domain_produces_different_ids() -> None:
    """Cycle-4 S1 P2 contract: marketing ``cancel`` and legal
    ``cancel`` must be distinct concepts."""
    marketing_id = _derive_import_concept_id(
        source_lang="en-US", source_term="cancel", namespace="marketing"
    )
    legal_id = _derive_import_concept_id(
        source_lang="en-US", source_term="cancel", namespace="legal"
    )
    assert marketing_id != legal_id
    # Both follow the documented prefix convention.
    assert marketing_id.startswith("import-")
    assert legal_id.startswith("import-")


def test_same_triple_produces_same_id_across_calls() -> None:
    """Idempotency at the derivation level — pure function."""
    first = _derive_import_concept_id(
        source_lang="en-US", source_term="login", namespace="software"
    )
    second = _derive_import_concept_id(
        source_lang="en-US", source_term="login", namespace="software"
    )
    assert first == second


def test_global_namespace_collides_for_same_term() -> None:
    """When namespace is empty (global), same source_term + same
    source_lang produces the same concept id — the merge-on-import
    semantic the user opted into by not supplying a domain or a
    --namespace flag."""
    a = _derive_import_concept_id(source_lang="en-US", source_term="login", namespace="")
    b = _derive_import_concept_id(source_lang="en-US", source_term="login", namespace="")
    assert a == b


def test_different_source_lang_produces_different_id() -> None:
    en_id = _derive_import_concept_id(source_lang="en-US", source_term="login", namespace="")
    de_id = _derive_import_concept_id(source_lang="de-DE", source_term="login", namespace="")
    assert en_id != de_id


def test_derive_import_concept_id_pins_literal_format() -> None:
    """The on-disk concept-id is a durable contract.

    Every concept stored in a user's ``.ainemo/termbase.kuzu/``
    carries an id of the form ``import-<sha256[:16]>``. The four
    relational tests above (different inputs differ, same inputs
    match) would all still pass if a refactor flipped ``\\x1f`` to
    ``|``, reordered the join fields, or migrated from
    ``sha256[:16]`` to ``sha256[:20]`` — but every previously-
    imported termbase would silently fragment on the next import:
    re-imports would create duplicate concepts and the cycle-4
    idempotency claim would quietly break.

    Pin a literal output for one known input so any change to the
    derivation is a deliberate migration, not a silent drift.

    The pinned value was computed once via:
    ``hashlib.sha256(b"en\\x1flogin\\x1fsoftware-ui").hexdigest()[:16]``.
    """
    assert (
        _derive_import_concept_id(
            source_lang="en",
            source_term="login",
            namespace="software-ui",
        )
        == "import-4c6ff660e73cc587"
    )


# --- load_into_termbase end-to-end namespace contract ---


def test_loader_writes_distinct_concepts_for_different_domains() -> None:
    """Two records with the same source_term but different
    ``domain_id`` must land as two concepts in the termbase."""
    stub = RecordingTermbase()
    source = _RecordSource(
        [
            _record("cancel", domain_id="marketing", target_surface="Abbrechen"),
            _record("cancel", domain_id="legal", target_surface="Stornieren"),
        ]
    )
    report = load_into_termbase(stub, source)
    assert report.concepts_added == 2
    assert len(stub.concepts) == 2
    # Both renderings preserved (the cycle-4 S1 P2 collision repro).
    surfaces = sorted(t.surface for t in stub.all_terms() if t.lang == "de-DE")
    assert surfaces == ["Abbrechen", "Stornieren"]


def test_loader_re_import_is_idempotent_with_same_namespace() -> None:
    stub = RecordingTermbase()
    source = _RecordSource([_record("login", domain_id="software", target_surface="Anmeldung")])
    load_into_termbase(stub, source)
    after_first = (len(stub.concepts), len(stub.all_terms()))

    # Run it again with a fresh source yielding the same record.
    source2 = _RecordSource([_record("login", domain_id="software", target_surface="Anmeldung")])
    load_into_termbase(stub, source2)
    after_second = (len(stub.concepts), len(stub.all_terms()))

    assert after_first == after_second  # upsert, not duplicate


def test_per_import_namespace_honored_when_no_domain_column() -> None:
    """When the record has no ``domain_id`` (mapping omitted
    ``domain_column``), the per-import ``namespace`` argument
    participates in concept-id derivation."""
    stub_a = RecordingTermbase()
    source_a = _RecordSource([_record("cancel", target_surface="Abbrechen")])
    load_into_termbase(stub_a, source_a, namespace="marketing")

    stub_b = RecordingTermbase()
    source_b = _RecordSource([_record("cancel", target_surface="Stornieren")])
    load_into_termbase(stub_b, source_b, namespace="legal")

    [marketing_concept_id] = stub_a.concepts.keys()
    [legal_concept_id] = stub_b.concepts.keys()
    assert marketing_concept_id != legal_concept_id


def test_record_domain_id_overrides_per_import_namespace() -> None:
    """Resolution chain priority: row's ``domain_id`` wins over
    per-import ``namespace`` when both are set."""
    stub = RecordingTermbase()
    source = _RecordSource(
        [
            # Row says domain=legal; per-import says marketing.
            # Resolution: legal wins (row-level beats per-import).
            _record("cancel", domain_id="legal", target_surface="Stornieren"),
        ]
    )
    load_into_termbase(stub, source, namespace="marketing")

    expected_id = _derive_import_concept_id(
        source_lang="en-US", source_term="cancel", namespace="legal"
    )
    assert expected_id in stub.concepts


# --- Loader meta: skip rows + report aggregation ---


def test_loader_aggregates_skipped_rows_into_report() -> None:
    stub = RecordingTermbase()
    source = _RecordSource(
        [
            _record("login", target_surface="Anmeldung"),
            SkippedRow(reason="row 5: blank source_term"),
            _record("logout", target_surface="Abmeldung"),
            SkippedRow(reason="row 9: malformed JSON"),
        ]
    )
    report = load_into_termbase(stub, source)
    assert report.concepts_added == 2
    assert report.rows_skipped == 2
    assert report.skipped_details == (
        "row 5: blank source_term",
        "row 9: malformed JSON",
    )


def test_loader_attaches_concept_to_domain_idempotently() -> None:
    """Domain attachment is idempotent: two records sharing
    ``domain_id`` create the Domain row once but attach both
    concepts to it."""
    stub = RecordingTermbase()
    source = _RecordSource(
        [
            _record("login", domain_id="software", target_surface="Anmeldung"),
            _record("logout", domain_id="software", target_surface="Abmeldung"),
        ]
    )
    report = load_into_termbase(stub, source)
    assert report.domains_added == 1  # only first-touch counts
    assert len(stub.domains) == 1
    assert "software" in stub.domains
    # Both concepts attached.
    for cid in stub.concepts:
        assert "software" in stub.concept_to_domains[cid]


def test_loader_stamps_provenance_on_terms() -> None:
    """Term.source comes from source.provenance ClassVar."""
    stub = RecordingTermbase()
    source = _RecordSource([_record("login", target_surface="Anmeldung")])
    load_into_termbase(stub, source)
    for term in stub.all_terms():
        assert term.source == TERM_SOURCE_CSV_IMPORT
