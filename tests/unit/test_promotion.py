# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for :func:`ainemo.core.termbase.promotion.find_candidates`.

Cycle-3 S5 contract:

- Frequency gate: an n-gram appearing in fewer than ``min_frequency``
  distinct TM segments is filtered out.
- Consistency gate: an n-gram whose dominant target string covers
  fewer than ``min_consistency`` of the segments is filtered out.
- Suggested target = most-frequent target across the segments.
- Output sorted by (frequency desc, consistency desc, n-gram asc).
- Repeated phrases within one TM row count once toward frequency
  (per-row deduplication via the ``_ngrams`` set).

Tests use a synthetic in-memory TM stub that implements only the
read surface promotion needs (``iter_translations``).
"""

from __future__ import annotations

from typing import Iterator

import pytest

from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    Segment,
    TranslatedSegment,
)
from ainemo.core.termbase._ids import (
    DEFAULT_PROMOTION_CONSISTENCY_MIN,
    DEFAULT_PROMOTION_FREQUENCY_MIN,
)
from ainemo.core.termbase.promotion import find_candidates
from ainemo.core.tm.base import TmHit, TmStats

pytestmark = pytest.mark.unit


# --- Fake TM ---


class _FakeTm:
    """Minimal TranslationMemory implementing the read surface
    promotion needs. Lookup / store are no-ops because find_candidates
    only iterates."""

    def __init__(self, pairs: list[tuple[str, str]]) -> None:
        self._pairs = pairs

    def lookup(self, *args: object, **kwargs: object) -> TmHit | None:
        return None

    def store(self, translated: TranslatedSegment) -> None:
        return None

    def stats(self) -> TmStats:
        return TmStats(
            segment_count=len(self._pairs),
            translation_count=len(self._pairs),
            target_lang_count=1,
            embedding_count=0,
        )

    def iter_translations(
        self, *, source_lang: str, target_lang: str
    ) -> Iterator[TranslatedSegment]:
        for index, (source, target) in enumerate(self._pairs):
            seg = Segment(
                key=f"k{index}",
                source_text=source,
                source_lang=source_lang,
            )
            yield TranslatedSegment(
                segment=seg,
                target_lang=target_lang,
                target_text=target,
                provider="noop",
                model="",
                confidence=None,
                source=TRANSLATION_SOURCE_PROVIDER,
            )


def _tm(*pairs: tuple[str, str]) -> _FakeTm:
    return _FakeTm(list(pairs))


# --- Threshold gates ---


def test_below_frequency_gate_is_filtered() -> None:
    # n-gram "login" appears in only 4 rows; default min_frequency = 5.
    pairs = [
        ("login screen", "Anmeldebildschirm"),
        ("login button", "Anmeldeschaltfläche"),
        ("login flow", "Anmeldevorgang"),
        ("login page", "Anmeldeseite"),
        ("logout link", "Abmeldelink"),
    ]
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en", "de")
    assert all(c.source_ngram != "login" for c in candidates)


def test_at_frequency_gate_passes_when_consistent() -> None:
    # 5 rows each containing "login" → frequency=5, all map to the
    # same target → consistency=1.0 ≥ 0.9.
    pairs = [(f"login {suffix}", "Anmeldung") for suffix in "abcde"]
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en", "de")
    by_ngram = {c.source_ngram: c for c in candidates}
    assert "login" in by_ngram
    login = by_ngram["login"]
    assert login.frequency == 5
    assert login.consistency == pytest.approx(1.0)
    assert login.suggested_target == "Anmeldung"


def test_below_consistency_gate_is_filtered() -> None:
    # 5 rows; 3 map to "Login", 2 to "Anmeldung" — consistency = 0.6 < 0.9.
    pairs = [
        ("login a", "Login"),
        ("login b", "Login"),
        ("login c", "Login"),
        ("login d", "Anmeldung"),
        ("login e", "Anmeldung"),
    ]
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en", "de")
    assert all(c.source_ngram != "login" for c in candidates)


def test_at_consistency_gate_passes() -> None:
    # 10 rows; 9 to "Anmeldung", 1 outlier — consistency = 0.9 ≥ 0.9.
    pairs = [(f"login pane {i}", "Anmeldung") for i in range(9)]
    pairs.append(("login pane outlier", "Login"))
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en", "de")
    by_ngram = {c.source_ngram: c for c in candidates}
    login = by_ngram.get("login")
    assert login is not None
    assert login.frequency == 10
    assert login.consistency == pytest.approx(0.9)
    assert login.suggested_target == "Anmeldung"


# --- N-gram tokenization ---


def test_multi_word_ngrams_emitted() -> None:
    # n_range default (1,4) — "log in" and "log in button" should both
    # land if they meet thresholds.
    pairs = [(f"please log in row {i}", "bitte einloggen") for i in range(5)]
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en", "de")
    ngrams = {c.source_ngram for c in candidates}
    assert "log in" in ngrams
    assert "please log" in ngrams


def test_repeated_phrase_in_one_row_counts_once() -> None:
    # If "ok" appeared three times in one row and we naively counted,
    # we'd see frequency=7 (3 + 4 single-occurrence rows). The
    # set-based ngram extraction deduplicates per-row, so frequency
    # caps at the number of *distinct rows* containing the ngram.
    # All five rows translate the ngram to "OK" so consistency=1.0
    # and the candidate clears the threshold gates — making the
    # frequency=5 assertion observable.
    pairs = [
        ("ok ok ok", "OK"),
        ("ok world", "OK Welt"),
        ("ok beam", "OK Strahl"),
        ("ok flag", "OK Flagge"),
        ("ok thing", "OK Ding"),
    ]
    tm = _tm(*pairs)
    # Lower consistency threshold so the suggested-target candidates
    # ("OK Welt", "OK Strahl", ...) don't all-match-each-other —
    # we're testing the per-row dedup of `ok`, not consistency.
    candidates = find_candidates(tm, "en", "de", min_frequency=5, min_consistency=0.0)
    by_ngram = {c.source_ngram: c for c in candidates}
    ok = by_ngram.get("ok")
    assert ok is not None
    # 5 distinct rows contain "ok" — even though row 1 has it three
    # times, frequency is 5, not 7.
    assert ok.frequency == 5


def test_n_range_can_be_narrowed() -> None:
    pairs = [(f"alpha bravo charlie {i}", "T") for i in range(5)]
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en", "de", n_range=(2, 2))
    ngrams = {c.source_ngram for c in candidates}
    # Length-1 n-grams ("alpha") must be absent; length-2 present.
    assert "alpha" not in ngrams
    assert "alpha bravo" in ngrams
    assert "bravo charlie" in ngrams


# --- Output ordering ---


def test_output_ordered_by_frequency_then_consistency_then_ngram() -> None:
    pairs = []
    # n-gram "alpha" — frequency=10, consistency=1.0
    pairs.extend([(f"alpha row {i}", "alpha-de") for i in range(10)])
    # n-gram "bravo" — frequency=8, consistency=1.0
    pairs.extend([(f"bravo row {i}", "bravo-de") for i in range(8)])
    # n-gram "charlie" — frequency=10, consistency=0.9 (1 outlier)
    pairs.extend([(f"charlie row {i}", "charlie-de") for i in range(9)])
    pairs.append(("charlie outlier row", "other"))
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en", "de")
    by_ngram = {
        c.source_ngram: c.frequency
        for c in candidates
        if c.source_ngram in {"alpha", "bravo", "charlie"}
    }
    # All three should be present.
    assert set(by_ngram) == {"alpha", "bravo", "charlie"}
    # Order: alpha (10, 1.0) before charlie (10, 0.9) before bravo (8, 1.0).
    ordered = [
        c.source_ngram for c in candidates if c.source_ngram in {"alpha", "bravo", "charlie"}
    ]
    assert ordered.index("alpha") < ordered.index("charlie") < ordered.index("bravo")


# --- Edge cases ---


def test_empty_tm_returns_empty_tuple() -> None:
    candidates = find_candidates(_tm(), "en", "de")
    assert candidates == ()


def test_zero_min_frequency_raises() -> None:
    with pytest.raises(ValueError):
        find_candidates(_tm(), "en", "de", min_frequency=0)


def test_invalid_consistency_raises() -> None:
    with pytest.raises(ValueError):
        find_candidates(_tm(), "en", "de", min_consistency=-0.1)
    with pytest.raises(ValueError):
        find_candidates(_tm(), "en", "de", min_consistency=1.5)


def test_invalid_n_range_raises() -> None:
    with pytest.raises(ValueError):
        find_candidates(_tm(), "en", "de", n_range=(0, 4))
    with pytest.raises(ValueError):
        find_candidates(_tm(), "en", "de", n_range=(3, 2))


def test_default_thresholds_match_q1_resolution() -> None:
    # Q1 from /bet (2026-05-05): take the proposed defaults.
    # Pin them so an accidental edit during cooldown re-tuning shows
    # up as a contract change.
    assert DEFAULT_PROMOTION_FREQUENCY_MIN == 5
    assert DEFAULT_PROMOTION_CONSISTENCY_MIN == pytest.approx(0.9)


def test_multiple_provider_rows_for_same_segment_count_once() -> None:
    # Regression for the P2 finding: TM v2 stores multiple
    # translations per segment (one row per (provider, model)). The
    # promotion algorithm documents `frequency` as the count of
    # *distinct segments* containing the n-gram, so two provider
    # rows for the same segment must contribute one observation,
    # not two. A single segment under two providers must NOT be
    # promotable at min_frequency=2.
    seg = Segment(key="single", source_text="login button", source_lang="en")
    rows = [
        TranslatedSegment(
            segment=seg,
            target_lang="de",
            target_text="Anmeldeschaltfläche",
            provider="openai",
            model="gpt-4o",
            confidence=None,
            source=TRANSLATION_SOURCE_PROVIDER,
        ),
        TranslatedSegment(
            segment=seg,
            target_lang="de",
            target_text="Anmeldeschaltfläche",
            provider="nllb",
            model="nllb-200",
            confidence=None,
            source=TRANSLATION_SOURCE_PROVIDER,
        ),
    ]

    class _DupTm:
        def lookup(self, *args: object, **kwargs: object) -> TmHit | None:
            return None

        def store(self, translated: TranslatedSegment) -> None:
            return None

        def stats(self) -> TmStats:
            return TmStats(
                segment_count=1,
                translation_count=2,
                target_lang_count=1,
                embedding_count=0,
            )

        def iter_translations(
            self, *, source_lang: str, target_lang: str
        ) -> Iterator[TranslatedSegment]:
            yield from rows

    candidates = find_candidates(_DupTm(), "en", "de", min_frequency=2, min_consistency=0.0)
    # No n-gram should clear the gate — there's only one segment.
    assert all(c.frequency == 1 for c in candidates) or candidates == ()
    assert not any(c.source_ngram == "login" for c in candidates)
    assert not any(c.source_ngram == "button" for c in candidates)


def test_candidates_carry_lang_pair() -> None:
    pairs = [(f"login row {i}", "Anmeldung") for i in range(5)]
    tm = _tm(*pairs)
    candidates = find_candidates(tm, "en-US", "de-DE")
    assert candidates
    for candidate in candidates:
        assert candidate.source_lang == "en-US"
        assert candidate.target_lang == "de-DE"
