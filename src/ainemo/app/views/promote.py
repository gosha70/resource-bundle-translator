# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Auto-promotion candidate queue — cycle-5 S2.

Routes
------
GET  /promote            List all promotion candidates for the selected
                         (source_lang, target_lang) pair. Renders
                         ``promote/list.html``.
POST /promote/decide     Accept, reject, or edit-then-accept one candidate.
                         Returns the refreshed ``promote/_row.html`` HTMX
                         fragment so HTMX swaps the row in place.

Contributing-segment lookup strategy
-------------------------------------
``PromotionCandidate.contributing_segment_fingerprints`` carries the TM
fingerprints that voted for the n-gram. To fetch the source text and
provider/model breakdown for each fingerprint we call
``tm.iter_translations(source_lang=..., target_lang=...)`` once and
bucket the resulting rows by fingerprint.  This is a single streaming
pass over the TM (same traversal ``find_candidates`` already performed)
and avoids adding any new method to the ``TranslationMemory`` Protocol.

Idempotency on re-POST
-----------------------
``write_accepted_candidate`` uses a content-addressed concept id
(``_derive_promotion_concept_id``).  A second POST with the same natural
key upserts onto the same Kuzu rows — no duplicate is created.  The
route does not need to guard against double-submit at the HTTP level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from flask import Blueprint, abort, current_app, render_template, request

from ainemo.app._ids import (
    DECISION_ACCEPT,
    DECISION_EDIT,
    DECISION_REJECT,
    ROUTE_PROMOTE_DECIDE,
    ROUTE_PROMOTE_QUEUE,
)
from ainemo.app.qa.signals import ConfidenceSignals, compute_cheap_signals
from ainemo.core.segment import Segment
from ainemo.core.termbase.promotion import (
    PromotionCandidate,
    find_candidates,
    write_accepted_candidate,
)

# Maximum contributing segments to surface per candidate in the UI.
_MAX_CONTRIBUTING_SEGMENTS: Final = 5
# Maximum existing concept hits to surface per candidate.
_MAX_EXISTING_CONCEPT_HITS: Final = 3

# Default language pair shown when query params are absent.
_DEFAULT_SOURCE_LANG: Final = "en"
_DEFAULT_TARGET_LANG: Final = "de"

blueprint = Blueprint("promote", __name__)


# ---------------------------------------------------------------------------
# Internal data containers (not exported; used only within this module)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SegmentPreview:
    """One TM row shown in the contributing-segments section of a candidate.

    Carries the full ``Segment`` (placeholders + metadata) — not just the
    source text — so the cycle-5 S5 cheap-signal computation can score
    against the original placeholder shape and ``max_length`` budget.
    Reconstructing a partial Segment from text alone would silently
    return placeholder_parity = 1.0 even when the contributing TM row
    actually dropped a placeholder.
    """

    fingerprint: str
    segment: Segment
    provider: str
    model: str
    target_text: str

    @property
    def source_text(self) -> str:
        return self.segment.source_text


@dataclass(frozen=True)
class _AugmentedCandidate:
    """A ``PromotionCandidate`` plus the UI-context data fetched on request."""

    candidate: PromotionCandidate
    segment_previews: tuple[_SegmentPreview, ...]
    existing_hits: tuple[object, ...]  # ConceptHit tuples from tb.lookup_concepts_for
    signals: ConfidenceSignals | None
    """Cheap-signal scores for the first contributing segment, or ``None``
    when no contributing segment preview is available.  Picked from
    ``segment_previews[0]`` — the first contributing fingerprint is the
    most representative single-segment proxy for the n-gram candidate."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_segment_previews(
    tm: object,
    candidate: PromotionCandidate,
) -> tuple[_SegmentPreview, ...]:
    """Return up to ``_MAX_CONTRIBUTING_SEGMENTS`` segment rows for *candidate*.

    Streams ``tm.iter_translations`` once and collects rows whose fingerprint
    is in ``candidate.contributing_segment_fingerprints``.  No new TM Protocol
    method is required — read-only use of the existing ``iter_translations``
    surface.
    """
    from ainemo.core.tm.base import TranslationMemory

    if not isinstance(tm, TranslationMemory):
        return ()

    target_fps = set(candidate.contributing_segment_fingerprints[:_MAX_CONTRIBUTING_SEGMENTS])
    if not target_fps:
        return ()

    previews: dict[str, list[_SegmentPreview]] = {}
    for translated in tm.iter_translations(
        source_lang=candidate.source_lang,
        target_lang=candidate.target_lang,
    ):
        fp = translated.segment.fingerprint
        if fp not in target_fps:
            continue
        previews.setdefault(fp, []).append(
            _SegmentPreview(
                fingerprint=fp,
                segment=translated.segment,
                provider=translated.provider,
                model=translated.model,
                target_text=translated.target_text,
            )
        )
        # Once we have at least one preview per target fingerprint, stop
        # scanning if we have collected enough distinct fingerprints.
        if len(previews) >= _MAX_CONTRIBUTING_SEGMENTS and all(
            fp2 in previews for fp2 in target_fps
        ):
            break

    result: list[_SegmentPreview] = []
    for fp in candidate.contributing_segment_fingerprints[:_MAX_CONTRIBUTING_SEGMENTS]:
        rows = previews.get(fp)
        if rows:
            result.append(rows[0])  # one representative row per fingerprint
    return tuple(result)


def _augment(
    candidate: PromotionCandidate,
    *,
    tm: object,
    tb: object,
) -> _AugmentedCandidate:
    """Augment *candidate* with contributing-segment previews and concept hits."""
    from ainemo.core.termbase.base import Termbase

    previews = _fetch_segment_previews(tm, candidate)

    hits: tuple[object, ...] = ()
    signals: ConfidenceSignals | None = None
    if isinstance(tb, Termbase):
        hits = tb.lookup_concepts_for(
            candidate.source_ngram,
            candidate.source_lang,
            candidate.target_lang,
            max_hits=_MAX_EXISTING_CONCEPT_HITS,
        )
        # Compute cheap signals from the first contributing segment preview.
        # Use the original Segment (with placeholders + metadata) carried
        # through _SegmentPreview rather than reconstructing one — otherwise
        # placeholder_parity / length_budget would always show 1.0 even when
        # the contributing TM row dropped a placeholder or exceeded max_length.
        if previews:
            first = previews[0]
            try:
                signals = compute_cheap_signals(
                    segment=first.segment,
                    target_text=first.target_text,
                    target_lang=candidate.target_lang,
                    termbase=tb,
                )
            except Exception:
                signals = None

    return _AugmentedCandidate(
        candidate=candidate,
        segment_previews=previews,
        existing_hits=hits,
        signals=signals,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@blueprint.get("/promote")
def promote_queue() -> str:
    """Render the full candidate queue for the requested language pair."""
    ext = current_app.extensions["ainemo"]
    source_lang: str = request.args.get("source_lang", _DEFAULT_SOURCE_LANG)
    target_lang: str = request.args.get("target_lang", _DEFAULT_TARGET_LANG)

    candidates = find_candidates(ext.tm, source_lang, target_lang)
    augmented = tuple(_augment(c, tm=ext.tm, tb=ext.termbase) for c in candidates)

    return render_template(
        "promote/list.html",
        augmented_candidates=augmented,
        source_lang=source_lang,
        target_lang=target_lang,
    )


@blueprint.post("/promote/decide")
def promote_decide() -> str:
    """Handle accept / reject / edit decision for one candidate.

    The posted ``(source_lang, target_lang, source_ngram, suggested_target)``
    natural key must match a candidate that ``find_candidates`` would
    surface for that language pair right now. A direct or malformed POST
    that names an unknown candidate is rejected with HTTP 400 so the
    decision endpoint cannot be used to write arbitrary termbase rows.
    """
    ext = current_app.extensions["ainemo"]

    decision: str = request.form.get("decision", DECISION_REJECT)
    source_ngram: str = request.form.get("source_ngram", "").strip()
    source_lang: str = request.form.get("source_lang", _DEFAULT_SOURCE_LANG)
    target_lang: str = request.form.get("target_lang", _DEFAULT_TARGET_LANG)
    suggested_target: str = request.form.get("suggested_target", "").strip()
    edited_target: str = request.form.get("edited_target_surface", "").strip()

    if decision not in (DECISION_ACCEPT, DECISION_REJECT, DECISION_EDIT):
        abort(400, description=f"unknown decision token: {decision!r}")
    if not source_ngram or not suggested_target:
        abort(400, description="source_ngram and suggested_target are required")

    matched = _find_matching_candidate(
        ext.tm,
        source_lang=source_lang,
        target_lang=target_lang,
        source_ngram=source_ngram,
        suggested_target=suggested_target,
    )
    if matched is None:
        abort(
            400,
            description=(
                "posted candidate does not match any current "
                "find_candidates() result for this language pair"
            ),
        )

    if decision == DECISION_EDIT:
        if not edited_target:
            abort(400, description="edited_target_surface is required for decision=edit")
        effective_target = edited_target
    else:
        effective_target = suggested_target

    write_candidate = PromotionCandidate(
        source_lang=matched.source_lang,
        target_lang=matched.target_lang,
        source_ngram=matched.source_ngram,
        suggested_target=effective_target,
        frequency=matched.frequency,
        consistency=matched.consistency,
        contributing_segment_fingerprints=matched.contributing_segment_fingerprints,
    )

    decided = False
    if decision in (DECISION_ACCEPT, DECISION_EDIT):
        write_accepted_candidate(ext.termbase, write_candidate)
        decided = True

    augmented = _augment(write_candidate, tm=ext.tm, tb=ext.termbase)

    return render_template(
        "promote/_row.html",
        ac=augmented,
        decided=decided,
        decision=decision,
    )


def _find_matching_candidate(
    tm: object,
    *,
    source_lang: str,
    target_lang: str,
    source_ngram: str,
    suggested_target: str,
) -> PromotionCandidate | None:
    """Re-load the candidate queue and return the one matching the posted
    natural key, or ``None`` if no match.

    Re-computing on each POST is cheap relative to the cycle-3 promotion
    algorithm's TM scan and avoids holding queue state across requests.
    """
    from ainemo.core.tm.base import TranslationMemory

    if not isinstance(tm, TranslationMemory):
        return None
    for candidate in find_candidates(tm, source_lang, target_lang):
        if (
            candidate.source_ngram == source_ngram
            and candidate.suggested_target == suggested_target
        ):
            return candidate
    return None


promote_queue.__name__ = ROUTE_PROMOTE_QUEUE
promote_decide.__name__ = ROUTE_PROMOTE_DECIDE


def register_promote(app: object) -> None:
    """Register the promote blueprint on *app*.

    Called from ``ainemo.app.create_app`` once S2 is active.
    """
    from flask import Flask

    if isinstance(app, Flask):
        app.register_blueprint(blueprint)


__all__ = ["blueprint", "register_promote"]
