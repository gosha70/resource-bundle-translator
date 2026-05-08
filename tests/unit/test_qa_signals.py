# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for cycle-5 S5 cheap-signal computation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.app._ids import (
    WEIGHT_BACK_TRANSLATION_COSINE,
    WEIGHT_LENGTH_BUDGET,
    WEIGHT_PLACEHOLDER_PARITY,
    WEIGHT_TERMBASE_COSINE,
)
from ainemo.app.qa.signals import (
    ConfidenceSignals,
    compute_cheap_signals,
)
from ainemo.core.segment import (
    Placeholder,
    PlaceholderKind,
    Segment,
)
from ainemo.core.termbase._ids import TERM_SOURCE_MANUAL
from ainemo.core.termbase.base import Concept, Term
from ainemo.core.termbase.kuzu.store import KuzuTermbase

pytestmark = pytest.mark.unit


@pytest.fixture()
def termbase(tmp_path: Path) -> KuzuTermbase:
    return KuzuTermbase(tmp_path / "termbase.kuzu")


def _seed_termbase(tb: KuzuTermbase, source_lang: str, source_term: str) -> None:
    tb.add_concept(
        Concept(concept_id="c1", qid=None, definition=None, created_at=1),
        [
            Term(
                term_id="t1",
                concept_id="c1",
                lang=source_lang,
                surface=source_term,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            )
        ],
    )


def test_placeholder_parity_is_one_for_clean_translation(termbase: KuzuTermbase) -> None:
    seg = Segment(
        key="k1",
        source_text="Hello {0}",
        source_lang="en",
        placeholders=(Placeholder(kind=PlaceholderKind.POSITIONAL, raw="{0}", span=(6, 9)),),
    )
    sig = compute_cheap_signals(
        segment=seg,
        target_text="Hallo {0}",
        target_lang="de",
        termbase=termbase,
    )
    assert sig.placeholder_parity == 1.0


def test_placeholder_parity_is_zero_when_placeholder_dropped(termbase: KuzuTermbase) -> None:
    seg = Segment(
        key="k1",
        source_text="Hello {0}",
        source_lang="en",
        placeholders=(Placeholder(kind=PlaceholderKind.POSITIONAL, raw="{0}", span=(6, 9)),),
    )
    sig = compute_cheap_signals(
        segment=seg,
        target_text="Hallo (no placeholder)",
        target_lang="de",
        termbase=termbase,
    )
    assert sig.placeholder_parity == 0.0


def test_length_budget_is_one_within_budget(termbase: KuzuTermbase) -> None:
    seg = Segment(
        key="k1",
        source_text="hello",
        source_lang="en",
        metadata={"max_length": "20"},
    )
    sig = compute_cheap_signals(
        segment=seg,
        target_text="hallo welt",
        target_lang="de",
        termbase=termbase,
    )
    assert sig.length_budget == 1.0


def test_length_budget_is_zero_over_budget(termbase: KuzuTermbase) -> None:
    seg = Segment(
        key="k1",
        source_text="hello",
        source_lang="en",
        metadata={"max_length": "5"},
    )
    sig = compute_cheap_signals(
        segment=seg,
        target_text="this target is well past the budget",
        target_lang="de",
        termbase=termbase,
    )
    assert sig.length_budget == 0.0


def test_termbase_cosine_is_zero_when_no_concept_matches(termbase: KuzuTermbase) -> None:
    seg = Segment(
        key="k1",
        source_text="completely unrelated phrase",
        source_lang="en",
    )
    sig = compute_cheap_signals(
        segment=seg,
        target_text="ein anderes thema",
        target_lang="de",
        termbase=termbase,
    )
    assert sig.termbase_cosine == 0.0


def test_back_translation_cosine_starts_none(termbase: KuzuTermbase) -> None:
    """compute_cheap_signals never runs back-translation — that's opt-in via /qa."""
    seg = Segment(key="k1", source_text="hello", source_lang="en")
    sig = compute_cheap_signals(
        segment=seg, target_text="hallo", target_lang="de", termbase=termbase
    )
    assert sig.back_translation_cosine is None


def test_composite_without_back_translation_uses_three_weights() -> None:
    sig = ConfidenceSignals(
        termbase_cosine=1.0,
        placeholder_parity=1.0,
        length_budget=1.0,
        back_translation_cosine=None,
    )
    expected_sum = WEIGHT_TERMBASE_COSINE + WEIGHT_PLACEHOLDER_PARITY + WEIGHT_LENGTH_BUDGET
    assert sig.composite == pytest.approx(expected_sum / expected_sum, rel=1e-9)
    # Should equal exactly 1.0 when all three signals are 1.0.
    assert sig.composite == pytest.approx(1.0, rel=1e-9)


def test_composite_with_back_translation_uses_four_weights() -> None:
    sig = ConfidenceSignals(
        termbase_cosine=1.0,
        placeholder_parity=1.0,
        length_budget=1.0,
        back_translation_cosine=1.0,
    )
    expected_sum = (
        WEIGHT_TERMBASE_COSINE
        + WEIGHT_PLACEHOLDER_PARITY
        + WEIGHT_LENGTH_BUDGET
        + WEIGHT_BACK_TRANSLATION_COSINE
    )
    assert sig.composite == pytest.approx(expected_sum / expected_sum, rel=1e-9)
    assert sig.composite == pytest.approx(1.0, rel=1e-9)


def test_composite_zero_signals_is_zero() -> None:
    sig = ConfidenceSignals(
        termbase_cosine=0.0,
        placeholder_parity=0.0,
        length_budget=0.0,
        back_translation_cosine=None,
    )
    assert sig.composite == pytest.approx(0.0, rel=1e-9)


def test_composite_partial_signals_pinned_value() -> None:
    """Pin a stable composite value so a refactor of the weights or
    normalization formula trips the test."""
    sig = ConfidenceSignals(
        termbase_cosine=0.5,
        placeholder_parity=1.0,
        length_budget=1.0,
        back_translation_cosine=None,
    )
    # weighted = 0.4 * 0.5 + 0.4 * 1.0 + 0.2 * 1.0 = 0.2 + 0.4 + 0.2 = 0.8
    # divided by (0.4 + 0.4 + 0.2) = 1.0 → 0.8
    assert sig.composite == pytest.approx(0.8, rel=1e-9)
