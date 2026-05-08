# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Pure-Python cheap-signal confidence computation — cycle-5 S5.

All four signals reuse existing cycle-1/3 infrastructure; none make
provider calls.

Signal definitions
------------------
termbase_cosine
    MiniLM cosine similarity between the segment source text and the
    surface of the nearest matching termbase concept.  0.0 when no
    concept matches the source text.

placeholder_parity
    Binary: 1.0 when the target text has exactly the same set of
    placeholders as the source; 0.0 when any placeholder is missing
    or extra.  Binary (not graded) because the
    :class:`~ainemo.core.validators.placeholder.PlaceholderParityValidator`
    returns violations per-placeholder, not a ratio — and the
    use-case here is "is this translation safe at runtime?", which is
    a yes/no question.

length_budget
    Binary: 1.0 when the target text fits within ``max_length`` (from
    ``segment.metadata``), or when no budget is set.  0.0 when the
    target exceeds the budget.

back_translation_cosine
    MiniLM cosine between the back-translated text and the original
    source text.  ``None`` until the reviewer opts in per-segment.

Composite normalization
-----------------------
Without back-translation: the three cheap-signal weights sum to 1.0
(0.4 + 0.4 + 0.2), so ``composite = weighted_sum / 1.0``.

With back-translation: the four weights sum to 2.0
(0.4 + 0.4 + 0.2 + 1.0), so ``composite = weighted_sum / 2.0``.

Dividing by the sum of active weights keeps the composite in [0, 1]
regardless of whether back-translation is present.

Embedder reuse
--------------
The MiniLM embedder is constructed lazily on first use via
:func:`~ainemo.core.tm.sqlite.make_default_embedder` and cached in a
module-level list (same singleton-via-list pattern as the TM's own
internal model holder).  A single instance is reused for every request
rather than re-instantiated, matching the TM's design.  Embedder
failures (sentence-transformers not installed, OOM) are caught and
return 0.0 with a debug log so a missing model never crashes the
reviewer UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import numpy as np
from numpy.typing import NDArray

from ainemo.app._ids import (
    WEIGHT_BACK_TRANSLATION_COSINE,
    WEIGHT_LENGTH_BUDGET,
    WEIGHT_PLACEHOLDER_PARITY,
    WEIGHT_TERMBASE_COSINE,
)
from ainemo.core.segment import Segment, TranslatedSegment
from ainemo.core.validators.length import LengthBudgetValidator
from ainemo.core.validators.placeholder import PlaceholderParityValidator

if TYPE_CHECKING:
    from ainemo.core.termbase.base import Termbase

_log = logging.getLogger(__name__)

# Module-level lazy singleton for the MiniLM embedder.
# Same pattern as SqliteTranslationMemory's internal model_holder list:
# a mutable list acts as a single-slot cache so the 120 MB model is
# loaded at most once per interpreter process.
_embedder_holder: list[Callable[[str], NDArray[np.float32]]] = []

# QA provider sentinel — used to construct TranslatedSegment for
# validator calls without polluting TM attribution.
_QA_PROVIDER: str = "qa-signals"
_QA_MODEL: str = ""

# Weights-sum constants for composite normalization (no magic numbers).
_WEIGHTS_WITHOUT_BT: float = (
    WEIGHT_TERMBASE_COSINE + WEIGHT_PLACEHOLDER_PARITY + WEIGHT_LENGTH_BUDGET
)
_WEIGHTS_WITH_BT: float = _WEIGHTS_WITHOUT_BT + WEIGHT_BACK_TRANSLATION_COSINE


@dataclass(frozen=True)
class ConfidenceSignals:
    """The four cheap-signal scores for one (segment, target_text) pair.

    All float fields are in [0.0, 1.0].  ``back_translation_cosine``
    is ``None`` until the reviewer opts in for the segment via
    ``POST /qa/back-translate``.
    """

    termbase_cosine: float
    placeholder_parity: float
    length_budget: float
    back_translation_cosine: float | None

    @property
    def composite(self) -> float:
        """Weighted composite score, normalized to [0, 1].

        Without back-translation:
            ``(0.4 * termbase_cosine + 0.4 * placeholder_parity
               + 0.2 * length_budget) / 1.0``

        With back-translation:
            ``(0.4 * termbase_cosine + 0.4 * placeholder_parity
               + 0.2 * length_budget + 1.0 * back_translation_cosine) / 2.0``

        Dividing by the sum of active weights keeps the result in [0, 1].
        """
        weighted = (
            WEIGHT_TERMBASE_COSINE * self.termbase_cosine
            + WEIGHT_PLACEHOLDER_PARITY * self.placeholder_parity
            + WEIGHT_LENGTH_BUDGET * self.length_budget
        )
        if self.back_translation_cosine is not None:
            weighted += WEIGHT_BACK_TRANSLATION_COSINE * self.back_translation_cosine
            return weighted / _WEIGHTS_WITH_BT
        return weighted / _WEIGHTS_WITHOUT_BT


def compute_cheap_signals(
    *,
    segment: Segment,
    target_text: str,
    target_lang: str,
    termbase: Termbase,
) -> ConfidenceSignals:
    """Compute the three cheap signals for ``(segment, target_text)``.

    ``back_translation_cosine`` is always ``None`` here — it is filled
    in by ``POST /qa/back-translate`` when the reviewer opts in.

    Parameters
    ----------
    segment:
        Source segment (carries source text, source lang, placeholders,
        metadata including optional ``max_length``).
    target_text:
        The translated text to score.
    target_lang:
        BCP-47 target language tag (used for termbase concept lookup).
    termbase:
        The cycle-3 ``Termbase`` Protocol implementation.
    """
    translated = TranslatedSegment(
        segment=segment,
        target_lang=target_lang,
        target_text=target_text,
        provider=_QA_PROVIDER,
        model=_QA_MODEL,
    )
    return ConfidenceSignals(
        termbase_cosine=_termbase_cosine(segment, target_lang, termbase),
        placeholder_parity=_placeholder_parity(segment, translated),
        length_budget=_length_budget(segment, translated),
        back_translation_cosine=None,
    )


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Embed two strings and return their cosine similarity.

    Uses the module-level lazy MiniLM embedder singleton.  Returns 0.0
    on any exception (embedder unavailable, OOM, etc.) rather than
    surfacing an error to the reviewer UI.
    """
    try:
        embedder = _get_embedder()
        vec_a: NDArray[np.float32] = embedder(text_a)
        vec_b: NDArray[np.float32] = embedder(text_b)
        norm_a = float(np.linalg.norm(vec_a))
        norm_b = float(np.linalg.norm(vec_b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
    except Exception:
        _log.debug("MiniLM embedder failed; returning 0.0 for cosine similarity", exc_info=True)
        return 0.0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_embedder() -> Callable[[str], NDArray[np.float32]]:
    """Return the module-level lazy MiniLM embedder singleton."""
    if not _embedder_holder:
        from ainemo.core.tm.sqlite import make_default_embedder

        _embedder_holder.append(make_default_embedder())
    return _embedder_holder[0]


def _termbase_cosine(
    segment: Segment,
    target_lang: str,
    termbase: Termbase,
) -> float:
    """MiniLM cosine to the nearest matching termbase concept surface.

    Looks up concepts whose source-side term appears in the segment
    source text; if any match, embeds the source text and the matched
    surface and returns the max cosine across all hits.  Returns 0.0
    when there are no hits or when the embedder fails.
    """
    try:
        hits = termbase.lookup_concepts_for(
            segment.source_text,
            segment.source_lang,
            target_lang,
            max_hits=8,
        )
    except Exception:
        _log.debug("Termbase lookup failed; termbase_cosine = 0.0", exc_info=True)
        return 0.0

    if not hits:
        return 0.0

    best = 0.0
    for hit in hits:
        surface = hit.matched_source_term.surface
        score = cosine_similarity(segment.source_text, surface)
        if score > best:
            best = score
    return best


def _placeholder_parity(segment: Segment, translated: TranslatedSegment) -> float:
    """Binary placeholder-parity score.

    Returns 1.0 when
    :class:`~ainemo.core.validators.placeholder.PlaceholderParityValidator`
    finds no violations; 0.0 otherwise.

    Binary rather than graded because the validator counts
    per-placeholder mismatches (not a ratio), and the practical
    question — "will this translation crash at runtime?" — is yes/no.
    """
    violations = PlaceholderParityValidator().check(segment, translated)
    return 1.0 if not violations else 0.0


def _length_budget(segment: Segment, translated: TranslatedSegment) -> float:
    """Binary length-budget score.

    Returns 1.0 when
    :class:`~ainemo.core.validators.length.LengthBudgetValidator` finds
    no violations (including when no ``max_length`` is set in
    ``segment.metadata`` — absence of constraint is treated as within
    budget).  Returns 0.0 when the target exceeds the budget.
    """
    violations = LengthBudgetValidator().check(segment, translated)
    return 1.0 if not violations else 0.0


__all__ = [
    "ConfidenceSignals",
    "compute_cheap_signals",
    "cosine_similarity",
]
