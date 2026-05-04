"""Translation memory Protocol + result types.

Every TM backend (cycle 1 ships SqliteTranslationMemory; cycle 6+ may
add a redis-backed or remote-API-backed alternative) implements this
Protocol. The pipeline (scope 9) only knows about the Protocol — never
about a specific backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable

from ainemo.core.segment import Segment, TranslatedSegment

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Match-type tags returned in TmHit. Same Final/Literal pattern as
# TRANSLATION_SOURCE_* in segment.py so callers can pass the constants
# directly into TmHit(match_type=...) under mypy strict.
TM_MATCH_TYPE_EXACT: Final = "exact"
TM_MATCH_TYPE_FUZZY: Final = "fuzzy"

TmMatchType = Literal["exact", "fuzzy"]

# Default fuzzy similarity threshold. Below this, the TM treats the
# closest match as a miss and the pipeline forwards to a provider.
# 0.85 is the cycle-1 starting point per AGENTS.md § Translation-Domain
# Conventions; teams can tune per-project.
DEFAULT_FUZZY_THRESHOLD: Final = 0.85

# Exact-match similarity. Used in TmHit.similarity for exact hits so
# callers don't have to special-case match_type when reading scores.
EXACT_MATCH_SIMILARITY: Final = 1.0


@dataclass(frozen=True)
class TmHit:
    """Result of a successful TM lookup."""

    translated: TranslatedSegment
    similarity: float
    """1.0 for exact match; cosine similarity in [0, 1] for fuzzy."""

    match_type: TmMatchType


@dataclass(frozen=True)
class TmStats:
    """Aggregate TM statistics surfaced by `nemo tm stats` (CLI scope 10)."""

    segment_count: int
    """Distinct (source_text, source_lang, placeholder_shape) tuples."""

    translation_count: int
    """Distinct (segment, target_lang, provider) tuples."""

    target_lang_count: int
    """Number of target languages with at least one stored translation."""

    embedding_count: int
    """Number of segments that have an embedding stored — relevant for
    fuzzy-lookup readiness."""


@runtime_checkable
class TranslationMemory(Protocol):
    """Lookup, store, and report on cached translations."""

    def lookup(
        self,
        segment: Segment,
        target_lang: str,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> TmHit | None:
        """Return the best hit at or above ``fuzzy_threshold``, else None.

        Implementations check exact match first (cheap); only on miss
        do they consider fuzzy. Returning ``None`` means the pipeline
        should forward the segment to a provider.

        ``provider`` and ``model`` (cycle-2 additions) narrow the
        lookup to a specific (provider, model) combination so the
        cycle-2 router can ask: "is there a translation for *this*
        segment+lang from *this* provider with *this* model?" When
        either is ``None``, that field is unconstrained and the most
        recent matching row wins (cycle-1-style "any cached
        translation" semantics, which the pipeline still uses for
        the no-explicit-route case).
        """
        ...

    def store(self, translated: TranslatedSegment) -> None:
        """Persist ``translated`` so future lookups can find it.

        Implementations should be idempotent: storing the same
        TranslatedSegment twice is a no-op (or refreshes the
        ``created_at`` timestamp — cycle 1 chooses to refresh).
        """
        ...

    def stats(self) -> TmStats:
        """Aggregate counts. Used by ``nemo tm stats``."""
        ...


__all__ = [
    "TmHit",
    "TmStats",
    "TmMatchType",
    "TranslationMemory",
    "TM_MATCH_TYPE_EXACT",
    "TM_MATCH_TYPE_FUZZY",
    "DEFAULT_FUZZY_THRESHOLD",
    "EXACT_MATCH_SIMILARITY",
]
