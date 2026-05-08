# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for :func:`ainemo.core.termbase.promotion.write_accepted_candidate`.

Covers:
1. Round-trip: ``write_accepted_candidate`` writes Concept + 2 Terms,
   ``RecordingTermbase`` reflects them.
2. Idempotency: calling ``write_accepted_candidate`` twice with the same
   ``PromotionCandidate`` produces exactly one Concept (cycle-3 stable-id
   regression).
3. Literal-hash regression: pin ``_derive_promotion_concept_id`` output for
   a known candidate so any format drift trips the test (mirrors
   ``test_loader_concept_ids.py:test_derive_import_concept_id_pins_literal_format``).
4. Source provenance: both terms carry ``TERM_SOURCE_TM_PROMOTION``.
5. Term ids follow the ``<concept_id>-<lang>`` convention.
"""

from __future__ import annotations

import pytest

from ainemo.core.termbase._ids import TERM_SOURCE_TM_PROMOTION
from ainemo.core.termbase.promotion import (
    PromotionCandidate,
    _derive_promotion_concept_id,
    write_accepted_candidate,
)
from tests.termbase_stub import RecordingTermbase

pytestmark = pytest.mark.unit

_CANDIDATE = PromotionCandidate(
    source_lang="en",
    target_lang="de",
    source_ngram="login",
    suggested_target="Anmeldung",
    frequency=5,
    consistency=1.0,
)


def test_write_accepted_candidate_round_trip() -> None:
    """write_accepted_candidate writes exactly one Concept and two Terms."""
    tb = RecordingTermbase()
    write_accepted_candidate(tb, _CANDIDATE)

    assert len(tb.concepts) == 1
    all_terms = tb.all_terms()
    assert len(all_terms) == 2

    langs = {t.lang for t in all_terms}
    assert langs == {"en", "de"}

    surfaces = {t.surface for t in all_terms}
    assert surfaces == {"login", "Anmeldung"}


def test_write_accepted_candidate_idempotent() -> None:
    """Calling write_accepted_candidate twice with the same candidate must
    produce exactly one Concept and two Terms (upsert, not duplicate).
    Cycle-3 stable-id regression."""
    tb = RecordingTermbase()
    write_accepted_candidate(tb, _CANDIDATE)
    write_accepted_candidate(tb, _CANDIDATE)

    assert len(tb.concepts) == 1
    assert len(tb.all_terms()) == 2


def test_write_accepted_candidate_provenance() -> None:
    """Both written Terms must carry TERM_SOURCE_TM_PROMOTION."""
    tb = RecordingTermbase()
    write_accepted_candidate(tb, _CANDIDATE)

    for term in tb.all_terms():
        assert term.source == TERM_SOURCE_TM_PROMOTION


def test_write_accepted_candidate_term_ids() -> None:
    """Term ids follow the ``<concept_id>-<lang>`` convention."""
    tb = RecordingTermbase()
    write_accepted_candidate(tb, _CANDIDATE)

    concept_id = _derive_promotion_concept_id(_CANDIDATE)
    term_ids = {t.term_id for t in tb.all_terms()}
    assert term_ids == {f"{concept_id}-en", f"{concept_id}-de"}


def test_derive_promotion_concept_id_pins_literal_format() -> None:
    """The on-disk concept-id is a durable contract.

    Every concept promoted via ``nemo termbase promote`` or the reviewer UI
    carries an id of the form ``tm-promo-<sha256[:16]>``. Pin a literal
    output so any change to the derivation (field order, separator, prefix,
    truncation length) is a deliberate migration, not silent drift.

    The pinned value was computed once via::

        import hashlib
        payload = "\\x1f".join(("en", "de", "login", "Anmeldung"))
        print("tm-promo-" + hashlib.sha256(payload.encode()).hexdigest()[:16])
    """
    assert _derive_promotion_concept_id(_CANDIDATE) == "tm-promo-06435c8114b78116"


def test_write_accepted_candidate_edited_surface() -> None:
    """When the reviewer edits the target surface, the edited text is written."""
    tb = RecordingTermbase()
    edited = PromotionCandidate(
        source_lang="en",
        target_lang="de",
        source_ngram="login",
        suggested_target="Einloggen",
        frequency=5,
        consistency=1.0,
    )
    write_accepted_candidate(tb, edited)

    de_terms = [t for t in tb.all_terms() if t.lang == "de"]
    assert len(de_terms) == 1
    assert de_terms[0].surface == "Einloggen"
