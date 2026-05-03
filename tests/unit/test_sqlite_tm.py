"""Unit + contract tests for
:class:`ainemo.core.tm.sqlite.SqliteTranslationMemory`.

These tests pin both the cycle-1 scope-6 contract (schema + exact
match + store + stats) and the cycle-1 scope-7 contract (embedding-
based fuzzy match) using a deterministic stub embedder. The real
MiniLM embedder is exercised in an integration test gated on whether
the model is already cached locally.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ainemo.core.segment import (
    TRANSLATION_SOURCE_EXACT_TM,
    TRANSLATION_SOURCE_FUZZY_TM,
    TRANSLATION_SOURCE_PROVIDER,
    Placeholder,
    PlaceholderKind,
    Segment,
    TranslatedSegment,
)
from ainemo.core.tm.base import (
    DEFAULT_FUZZY_THRESHOLD,
    EXACT_MATCH_SIMILARITY,
    TM_MATCH_TYPE_EXACT,
    TM_MATCH_TYPE_FUZZY,
    TranslationMemory,
)
from ainemo.core.tm.sqlite import Embedder, SqliteTranslationMemory

# --- Test fixtures ---------------------------------------------------------

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"
_PROVIDER_TEST = "test"


def _seg(
    *,
    key: str = "k",
    source_text: str = "Hello",
    source_lang: str = _LANG_EN_US,
    placeholders: tuple[Placeholder, ...] = (),
) -> Segment:
    return Segment(
        key=key,
        source_text=source_text,
        source_lang=source_lang,
        placeholders=placeholders,
    )


def _ts(
    seg: Segment,
    target_text: str = "Hallo",
    target_lang: str = _LANG_DE,
    provider: str = _PROVIDER_TEST,
) -> TranslatedSegment:
    return TranslatedSegment(
        segment=seg,
        target_lang=target_lang,
        target_text=target_text,
        provider=provider,
        confidence=0.92,
        source=TRANSLATION_SOURCE_PROVIDER,
    )


def _stub_embedder(text: str) -> np.ndarray:
    """Deterministic embedder that returns a 16-dim vector based on a
    hash of the text. Identical text → identical vector; similar text
    → distant vector (no semantic similarity captured). Good enough
    to test exact/fuzzy logic without downloading a real model."""
    rng = np.random.default_rng(seed=hash(text) & 0xFFFFFFFF)
    return rng.random(16, dtype=np.float32)


def _identical_embedder(text: str) -> np.ndarray:
    """All texts get the same vector. Forces fuzzy matches to score
    1.0 cosine similarity regardless of input — useful for testing the
    fuzzy lookup pathway without engineering similarity."""
    return np.ones(16, dtype=np.float32)


# --- Protocol conformance --------------------------------------------------


def test_satisfies_protocol(tmp_path: Path) -> None:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    assert isinstance(tm, TranslationMemory)
    tm.close()


def test_creates_database_directory(tmp_path: Path) -> None:
    """The .ainemo/ directory is created if missing — users don't have
    to mkdir before instantiating the TM."""
    db_path = tmp_path / "nested" / "subdir" / "tm.sqlite"
    tm = SqliteTranslationMemory(db_path)
    assert db_path.exists()
    tm.close()


# --- Store + exact match (scope 6) ----------------------------------------


def test_store_then_exact_lookup(tmp_path: Path) -> None:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    seg = _seg()
    tm.store(_ts(seg, target_text="Hallo"))

    hit = tm.lookup(seg, _LANG_DE)
    assert hit is not None
    assert hit.match_type == TM_MATCH_TYPE_EXACT
    assert hit.similarity == EXACT_MATCH_SIMILARITY
    assert hit.translated.target_text == "Hallo"
    assert hit.translated.source == TRANSLATION_SOURCE_EXACT_TM
    tm.close()


def test_lookup_misses_for_unknown_segment(tmp_path: Path) -> None:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    assert tm.lookup(_seg(source_text="never seen"), _LANG_DE) is None
    tm.close()


def test_lookup_misses_for_other_target_lang(tmp_path: Path) -> None:
    """Storing for de-DE must not surface for fr-FR."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    seg = _seg()
    tm.store(_ts(seg, target_lang=_LANG_DE))

    assert tm.lookup(seg, "fr-FR") is None
    tm.close()


def test_store_is_idempotent(tmp_path: Path) -> None:
    """Storing the same translated twice must not duplicate rows."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    seg = _seg()
    tm.store(_ts(seg, target_text="Hallo"))
    tm.store(_ts(seg, target_text="Hallo"))

    stats = tm.stats()
    assert stats.segment_count == 1
    assert stats.translation_count == 1
    tm.close()


def test_store_overwrites_for_same_provider(tmp_path: Path) -> None:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    seg = _seg()
    tm.store(_ts(seg, target_text="Hallo v1"))
    tm.store(_ts(seg, target_text="Hallo v2"))

    hit = tm.lookup(seg, _LANG_DE)
    assert hit is not None
    assert hit.translated.target_text == "Hallo v2"
    tm.close()


def test_different_providers_coexist(tmp_path: Path) -> None:
    """Two providers translating the same segment store independently;
    the most recent (by created_at) wins on lookup."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    seg = _seg()
    tm.store(_ts(seg, target_text="From NLLB", provider="nllb"))
    tm.store(_ts(seg, target_text="From OpenAI", provider="openai"))

    stats = tm.stats()
    assert stats.translation_count == 2
    tm.close()


def test_lookup_with_placeholder_aware_fingerprint(tmp_path: Path) -> None:
    """Two segments with the same text but different placeholder
    classification must NOT collide in the TM."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    text = "Click {0}"
    positional = _seg(
        source_text=text,
        placeholders=(Placeholder(kind=PlaceholderKind.POSITIONAL, raw="{0}", span=(6, 9)),),
    )
    named = _seg(
        source_text=text,
        placeholders=(Placeholder(kind=PlaceholderKind.NAMED, raw="{0}", span=(6, 9)),),
    )
    tm.store(_ts(positional, target_text="Klick {0}"))

    assert tm.lookup(named, _LANG_DE) is None
    assert tm.lookup(positional, _LANG_DE) is not None
    tm.close()


# --- Stats ----------------------------------------------------------------


def test_stats_counts(tmp_path: Path) -> None:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    seg1 = _seg(source_text="One")
    seg2 = _seg(source_text="Two")
    tm.store(_ts(seg1, target_lang=_LANG_DE))
    tm.store(_ts(seg1, target_lang="fr-FR"))
    tm.store(_ts(seg2, target_lang=_LANG_DE))

    stats = tm.stats()
    assert stats.segment_count == 2
    assert stats.translation_count == 3
    assert stats.target_lang_count == 2
    tm.close()


def test_stats_embedding_count_zero_without_embedder(tmp_path: Path) -> None:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    tm.store(_ts(_seg()))
    assert tm.stats().embedding_count == 0
    tm.close()


# --- Persistence ---------------------------------------------------------


def test_persists_across_sessions(tmp_path: Path) -> None:
    """Closing and reopening the TM must surface previously-stored
    translations."""
    db_path = tmp_path / "tm.sqlite"
    tm = SqliteTranslationMemory(db_path)
    seg = _seg()
    tm.store(_ts(seg, target_text="Hallo"))
    tm.close()

    tm2 = SqliteTranslationMemory(db_path)
    hit = tm2.lookup(seg, _LANG_DE)
    assert hit is not None
    assert hit.translated.target_text == "Hallo"
    tm2.close()


# --- Fuzzy lookup (scope 7) -----------------------------------------------


def test_fuzzy_lookup_returns_none_without_embedder(tmp_path: Path) -> None:
    """No embedder → fuzzy is silently disabled. The TM serves exact
    matches only."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    seg = _seg(source_text="A different text that won't exact-match")
    assert tm.lookup(seg, _LANG_DE) is None
    tm.close()


def test_fuzzy_lookup_returns_match_above_threshold(tmp_path: Path) -> None:
    """With an embedder that returns identical vectors for all inputs,
    every cross-segment cosine similarity is 1.0 → fuzzy matches return
    the stored translation."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=_identical_embedder)
    stored = _seg(source_text="Hello world")
    tm.store(_ts(stored, target_text="Hallo Welt"))

    query = _seg(source_text="Greetings universe")
    hit = tm.lookup(query, _LANG_DE)
    assert hit is not None
    assert hit.match_type == TM_MATCH_TYPE_FUZZY
    assert hit.translated.source == TRANSLATION_SOURCE_FUZZY_TM
    assert hit.translated.target_text == "Hallo Welt"
    assert hit.similarity >= DEFAULT_FUZZY_THRESHOLD
    tm.close()


def test_fuzzy_lookup_below_threshold_returns_none(tmp_path: Path) -> None:
    """The deterministic stub embedder returns near-orthogonal vectors
    for unrelated texts, so cosine similarity is well below 0.85."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=_stub_embedder)
    tm.store(_ts(_seg(source_text="completely different")))

    query = _seg(source_text="something unrelated")
    assert tm.lookup(query, _LANG_DE) is None
    tm.close()


def test_fuzzy_only_considers_same_source_lang(tmp_path: Path) -> None:
    """A stored segment in fr-FR must not surface for an en-US query
    even if their embeddings are identical."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=_identical_embedder)
    tm.store(_ts(_seg(source_text="Bonjour", source_lang="fr-FR")))

    query = _seg(source_text="Hello", source_lang=_LANG_EN_US)
    assert tm.lookup(query, _LANG_DE) is None
    tm.close()


def test_fuzzy_only_considers_target_lang_with_translation(tmp_path: Path) -> None:
    """A stored segment with a de-DE translation must not surface as a
    fuzzy match for a fr-FR target."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=_identical_embedder)
    tm.store(_ts(_seg(), target_lang=_LANG_DE))

    query = _seg(source_text="Greetings")
    assert tm.lookup(query, "fr-FR") is None
    tm.close()


def test_exact_match_preferred_over_fuzzy(tmp_path: Path) -> None:
    """When an exact match exists, fuzzy is not consulted."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=_identical_embedder)
    seg = _seg()
    tm.store(_ts(seg, target_text="EXACT"))
    tm.store(_ts(_seg(source_text="something else"), target_text="FUZZY"))

    hit = tm.lookup(seg, _LANG_DE)
    assert hit is not None
    assert hit.match_type == TM_MATCH_TYPE_EXACT
    assert hit.translated.target_text == "EXACT"
    tm.close()


def test_store_with_embedder_populates_embedding(tmp_path: Path) -> None:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=_identical_embedder)
    tm.store(_ts(_seg()))
    assert tm.stats().embedding_count == 1
    tm.close()


def test_custom_threshold(tmp_path: Path) -> None:
    """The caller's `fuzzy_threshold` overrides the default."""
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=_identical_embedder)
    tm.store(_ts(_seg()))

    # Identical-embedder gives similarity == 1.0; threshold 1.5 is
    # impossible to meet, so this returns None.
    query = _seg(source_text="different text")
    assert tm.lookup(query, _LANG_DE, fuzzy_threshold=1.5) is None
    tm.close()


# --- Many-segment fuzzy lookup -------------------------------------------


def test_fuzzy_picks_best_match_among_many(tmp_path: Path) -> None:
    """Across N stored segments with varying embeddings, fuzzy returns
    the one with the highest cosine similarity. We craft embeddings to
    place a clear winner."""

    def _make_embedder(scores: dict[str, float]) -> Embedder:
        class _ScoredEmbedder:
            def __call__(self, text: str) -> np.ndarray:
                score = scores.get(text, 0.0)
                return np.array([score, 1.0 - score], dtype=np.float32)

        return _ScoredEmbedder()

    embedder = _make_embedder(
        {
            "query text": 1.0,
            "near match": 0.99,
            "medium match": 0.5,
            "far match": 0.05,
        }
    )
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite", embedder=embedder)
    tm.store(_ts(_seg(source_text="near match"), target_text="NEAR"))
    tm.store(_ts(_seg(source_text="medium match"), target_text="MEDIUM"))
    tm.store(_ts(_seg(source_text="far match"), target_text="FAR"))

    query = _seg(source_text="query text")
    hit = tm.lookup(query, _LANG_DE, fuzzy_threshold=0.5)
    assert hit is not None
    assert hit.translated.target_text == "NEAR"
    tm.close()
