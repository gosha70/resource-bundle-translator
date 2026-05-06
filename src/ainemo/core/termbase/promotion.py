# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Auto-promotion candidate generator.

Cycle-3 S5 — scans cycle-1 :class:`TranslationMemory` rows for source-text
n-grams that meet two thresholds:

- **Frequency**: appears in ``≥ min_frequency`` distinct TM segments
- **Consistency**: of those segments, ``≥ min_consistency`` translate to
  the same target string

N-grams that pass both gates are emitted as
:class:`PromotionCandidate` records — the cycle-3 S5 ``nemo termbase
promote`` CLI either prints them for review or writes them to the
termbase as :class:`Concept` + :class:`Term` rows.

Defaults pinned at /bet (pitch § Open questions Q1, 2026-05-05):

- ``DEFAULT_PROMOTION_FREQUENCY_MIN = 5``
- ``DEFAULT_PROMOTION_CONSISTENCY_MIN = 0.9``

Both override-able per-CLI-flag run; cycle-3 cooldown re-tunes after
real-world ``nemo termbase promote --review`` data is in.

Algorithm
---------

For each (source_text, target_text) pair in the TM:

1. Tokenize ``source_text`` into whitespace-separated tokens.
2. Generate n-grams of length ``n_range[0]`` … ``n_range[1]`` inclusive.
3. For each n-gram, record (n-gram → [target_text, ...]) — the list of
   target strings observed in TM rows whose source contains that n-gram.
4. After scanning, for each n-gram:
   - ``frequency = len(target_strings)``
   - ``consistency = max_count(target_strings) / frequency``
5. Emit a :class:`PromotionCandidate` if both thresholds are met. The
   ``suggested_target`` is the most-frequent target string for that
   n-gram.

Per the pitch's rabbit-hole rule (*Don't introduce vector embeddings
for term lookup yet*), the algorithm is purely literal — no
stemming, no lemmatization, no embedding similarity. Cycle-4+ may
revisit if recall is poor on real corpora.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Final

from ainemo.core.termbase._ids import (
    DEFAULT_PROMOTION_CONSISTENCY_MIN,
    DEFAULT_PROMOTION_FREQUENCY_MIN,
)
from ainemo.core.tm.base import TranslationMemory

# Default n-gram length range (inclusive). 1..4 keeps the candidate
# pool manageable on real TMs while covering single-word terms
# through short multi-word phrases ("user interface", "machine
# learning model").
_DEFAULT_N_MIN: Final = 1
_DEFAULT_N_MAX: Final = 4


@dataclass(frozen=True)
class PromotionCandidate:
    """One n-gram that passed both promotion thresholds.

    The cycle-3 S5 ``nemo termbase promote`` CLI converts each
    accepted candidate into a :class:`Concept` + two
    :class:`Term` rows (one in ``source_lang``, one in
    ``target_lang``) tagged with
    :data:`TERM_SOURCE_TM_PROMOTION` so the cycle-5 reviewer UI
    can audit promoted terms separately from TBX-imported and
    domain-pack-supplied terms.
    """

    source_lang: str
    target_lang: str
    source_ngram: str
    suggested_target: str
    frequency: int
    """Number of distinct TM segments whose source_text contains the
    n-gram. ``frequency >= min_frequency`` is the first gate."""

    consistency: float
    """``count(suggested_target) / frequency`` in 0..1. The fraction
    of those segments that translate the n-gram to the suggested
    target. ``consistency >= min_consistency`` is the second gate."""


def find_candidates(
    tm: TranslationMemory,
    source_lang: str,
    target_lang: str,
    *,
    min_frequency: int = DEFAULT_PROMOTION_FREQUENCY_MIN,
    min_consistency: float = DEFAULT_PROMOTION_CONSISTENCY_MIN,
    n_range: tuple[int, int] = (_DEFAULT_N_MIN, _DEFAULT_N_MAX),
) -> tuple[PromotionCandidate, ...]:
    """Scan ``tm`` for promotable n-grams.

    Returns candidates sorted by ``frequency`` descending, then
    ``consistency`` descending, then ``source_ngram`` ascending so
    the order is deterministic across runs and the highest-signal
    candidates surface first in the ``--review`` loop.
    """
    n_min, n_max = n_range
    if n_min < 1 or n_max < n_min:
        raise ValueError(f"Invalid n_range={n_range!r}; require 1 <= n_min <= n_max")
    if min_frequency < 1:
        raise ValueError(f"min_frequency must be >= 1; got {min_frequency}")
    if not 0.0 <= min_consistency <= 1.0:
        raise ValueError(f"min_consistency must be in [0, 1]; got {min_consistency}")

    # First pass: collect per-segment target observations. The TM v2
    # schema stores multiple translations per segment (one row per
    # (provider, model) combination), so iterating raw rows would
    # double-count one source segment as if it were many. The
    # documented contract for `frequency` is the number of *distinct
    # segments* containing the n-gram — not raw row count — so we
    # bucket by fingerprint here and reduce to one target per
    # segment in pass two.
    segment_buckets: dict[str, _SegmentBucket] = {}
    for translated in tm.iter_translations(source_lang=source_lang, target_lang=target_lang):
        fp = translated.segment.fingerprint
        bucket = segment_buckets.get(fp)
        if bucket is None:
            bucket = _SegmentBucket(source_text=translated.segment.source_text, targets=[])
            segment_buckets[fp] = bucket
        bucket.targets.append(translated.target_text)

    # Second pass: each segment contributes ONE (source_text, target)
    # observation, where target = mode across that segment's
    # provider/model rows. Then aggregate across segments to get
    # per-n-gram frequency + consistency.
    observations: dict[str, list[str]] = {}
    for bucket in segment_buckets.values():
        canonical_target = Counter(bucket.targets).most_common(1)[0][0]
        for ngram in _ngrams(bucket.source_text, n_min, n_max):
            observations.setdefault(ngram, []).append(canonical_target)

    candidates: list[PromotionCandidate] = []
    for ngram, targets in observations.items():
        frequency = len(targets)
        if frequency < min_frequency:
            continue
        counter = Counter(targets)
        suggested_target, top_count = counter.most_common(1)[0]
        consistency = top_count / frequency
        if consistency < min_consistency:
            continue
        candidates.append(
            PromotionCandidate(
                source_lang=source_lang,
                target_lang=target_lang,
                source_ngram=ngram,
                suggested_target=suggested_target,
                frequency=frequency,
                consistency=consistency,
            )
        )

    # Deterministic ordering — highest-signal first, ties broken by
    # n-gram so re-runs surface candidates in the same order.
    candidates.sort(key=lambda c: (-c.frequency, -c.consistency, c.source_ngram))
    return tuple(candidates)


# --- Helpers ---


@dataclass
class _SegmentBucket:
    """One TM segment's source text + every target_text observed for
    it across (provider, model) rows.

    A mutable dataclass (not ``frozen=True``) because the target list
    grows as we iterate the TM. Lifetime is bounded to one
    :func:`find_candidates` call.
    """

    source_text: str
    targets: list[str]


def _ngrams(text: str, n_min: int, n_max: int) -> set[str]:
    """Whitespace-tokenized n-grams of length ``n_min``..``n_max``.

    Returns a *set* — a single TM row contributes each n-gram at
    most once to that row's vote. Without this, a row whose source
    repeats a phrase ("foo bar foo bar") would over-count its own
    target_text, skewing ``frequency`` above the number of distinct
    *segments* containing the n-gram (which is the documented
    semantics).
    """
    tokens = text.split()
    out: set[str] = set()
    for n in range(n_min, n_max + 1):
        if n > len(tokens):
            break
        for i in range(len(tokens) - n + 1):
            out.add(" ".join(tokens[i : i + n]))
    return out


__all__ = ["PromotionCandidate", "find_candidates"]
