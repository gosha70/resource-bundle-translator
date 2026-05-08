# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""QA Layer — cheap-signal confidence + back-translation opt-in — cycle-5 S5.

Routes
------
GET  /qa                      Per-segment cheap-signal confidence list.
                              Computes three cheap signals (termbase cosine,
                              placeholder parity, length budget) for the most
                              recent N segments in the TM.  No provider call.
GET  /qa/segment/<fp>         Single-segment detail view; same signals +
                              back-translation button.
POST /qa/back-translate       Opt-in per-segment back-translation.
                              Accepts ``segment_fingerprint``, ``provider_id``,
                              ``source_lang``, ``target_lang`` form fields.
                              Returns the refreshed ``qa/_row.html`` HTMX
                              fragment with the back-translation cosine filled
                              in.

Design decisions
----------------
- Cheap signals are computed lazily on GET — no provider calls on page load.
- Back-translation is per-segment and per-click; never bulk.  Per the pitch
  rabbit-hole rule: "Don't try to make back-translation cheap."
- The back-translation must use a *different* provider than the original
  (same-provider back-translation gives no independent signal).
- At least two providers must be registered; otherwise the form rejects with
  a clear message pointing at RoutingConfig.
- Cost is recorded in UsageLog automatically via ProviderRouter._invoke_provider.
- The estimate from UsageLog.estimate_for is displayed before the button
  activates so the reviewer can see the expected cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

from flask import Blueprint, abort, current_app, render_template, request

from ainemo.app._ids import ROUTE_QA_BACK_TRANSLATE, ROUTE_QA_CONFIDENCE
from ainemo.app.qa.signals import ConfidenceSignals, compute_cheap_signals, cosine_similarity
from ainemo.core.segment import Segment
from ainemo.core.tm.base import TranslationMemory
from ainemo.providers._errors import UnknownProviderError
from ainemo.providers.router import (
    ProviderRouteNotFound,
    ProviderRouter,
    ProviderUnsupportedPair,
)

_log = logging.getLogger(__name__)

blueprint = Blueprint("qa", __name__)

# Default language pair when query params are absent.
_DEFAULT_SOURCE_LANG: Final = "en"
_DEFAULT_TARGET_LANG: Final = "de"

# Default number of recent segments shown on the list page.
_DEFAULT_LIMIT: Final = 50
_MAX_LIMIT: Final = 500

# Template paths.
_TEMPLATE_LIST: Final = "qa/list.html"
_TEMPLATE_ROW: Final = "qa/_row.html"
_TEMPLATE_SEGMENT: Final = "qa/segment.html"

# Back-translation segment key sentinel.
_BACK_TRANSLATION_KEY: Final = "back-translation"

# Minimum registered providers required for back-translation.
_MIN_PROVIDERS_FOR_BT: Final = 2


@dataclass(frozen=True)
class _RowData:
    """Data for one row on the QA list / detail page."""

    translated_fingerprint: str
    source_text: str
    source_lang: str
    target_text: str
    target_lang: str
    provider: str
    model: str
    signals: ConfidenceSignals


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@blueprint.get("/qa")
def qa_confidence() -> str:
    """Render per-segment cheap-signal confidence for the TM.

    Supports ``?source_lang=``, ``?target_lang=``, ``?limit=`` query params.
    Signals are computed here (pure, no provider call).
    """
    ext = current_app.extensions["ainemo"]
    source_lang: str = request.args.get("source_lang", _DEFAULT_SOURCE_LANG)
    target_lang: str = request.args.get("target_lang", _DEFAULT_TARGET_LANG)
    try:
        limit = min(int(request.args.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
    except ValueError:
        limit = _DEFAULT_LIMIT

    rows = _build_rows(ext.tm, ext.termbase, source_lang, target_lang, limit)

    return render_template(
        _TEMPLATE_LIST,
        rows=rows,
        source_lang=source_lang,
        target_lang=target_lang,
        limit=limit,
        registered_providers=ext.router.list_registered(),
    )


@blueprint.get("/qa/segment/<fingerprint>")
def qa_segment(fingerprint: str) -> str:
    """Single-segment detail view with cheap signals + back-translation button."""
    ext = current_app.extensions["ainemo"]
    source_lang: str = request.args.get("source_lang", _DEFAULT_SOURCE_LANG)
    target_lang: str = request.args.get("target_lang", _DEFAULT_TARGET_LANG)

    row = _find_row(ext.tm, ext.termbase, fingerprint, source_lang, target_lang)
    if row is None:
        abort(404, description=f"No translation found for fingerprint {fingerprint!r}")

    # Per-option estimates: only the providers the reviewer can actually
    # SELECT (i.e. != the original translation provider) appear in the
    # back-translation dropdown. Compute a cost estimate per selectable
    # option from UsageLog history.  Display "no historical data" when
    # estimate_for returns None.
    from ainemo.providers._usage_log import estimate_tokens_from_chars

    selectable = tuple(p for p in ext.router.list_registered() if p != row.provider)
    # Per-provider tokenizer densities differ — pass provider_id so each
    # estimate uses its own chars/token ratio rather than a global default.
    estimates_by_provider: dict[str, float | None] = {
        p: ext.router._usage_log.estimate_for(
            p,
            None,
            estimate_tokens_from_chars(len(row.source_text), provider_id=p),
        )
        for p in selectable
    }

    return render_template(
        _TEMPLATE_SEGMENT,
        row=row,
        source_lang=source_lang,
        target_lang=target_lang,
        registered_providers=ext.router.list_registered(),
        selectable_providers=selectable,
        estimates_by_provider=estimates_by_provider,
    )


@blueprint.post("/qa/back-translate")
def qa_back_translate() -> str:
    """Opt-in per-segment back-translation.

    Form fields: ``segment_fingerprint``, ``provider_id``,
    ``source_lang`` (default "en"), ``target_lang`` (default "de").

    Validation:
    - ``len(router.list_registered()) >= 2`` — else 400.
    - ``provider_id in router.list_registered()`` — else 400.
    - ``provider_id != original_provider`` — else 400.

    On success: calls ``router.translate_with``, computes cosine between
    the back-translation and the original source text, returns the
    refreshed ``qa/_row.html`` fragment with ``back_translation_cosine``
    filled in.
    """
    ext = current_app.extensions["ainemo"]
    router: ProviderRouter = ext.router

    registered = router.list_registered()
    if len(registered) < _MIN_PROVIDERS_FOR_BT:
        abort(
            400,
            description=(
                "Configure a second provider in RoutingConfig to enable "
                "back-translation. Currently only one provider is registered."
            ),
        )

    fingerprint: str = request.form.get("segment_fingerprint", "").strip()
    provider_id: str = request.form.get("provider_id", "").strip()
    source_lang: str = request.form.get("source_lang", _DEFAULT_SOURCE_LANG)
    target_lang: str = request.form.get("target_lang", _DEFAULT_TARGET_LANG)

    if not fingerprint:
        abort(400, description="segment_fingerprint is required")

    if provider_id not in registered:
        abort(400, description=f"Unknown provider {provider_id!r}. Registered: {list(registered)}")

    row = _find_row(ext.tm, ext.termbase, fingerprint, source_lang, target_lang)
    if row is None:
        abort(404, description=f"No translation found for fingerprint {fingerprint!r}")

    if provider_id == row.provider:
        abort(
            400,
            description=(
                f"Back-translation must use a different provider than the original "
                f"({row.provider!r}). Same-provider back-translation gives no "
                "independent quality signal."
            ),
        )

    # Build the back-translation segment: source = original target text,
    # source_lang = original target_lang, translate back to original source_lang.
    back_segment = Segment(
        key=_BACK_TRANSLATION_KEY,
        source_text=row.target_text,
        source_lang=target_lang,
    )

    try:
        bt_result = router.translate_with(provider_id, back_segment, source_lang)
    except UnknownProviderError as exc:
        abort(400, description=str(exc))
    except ProviderUnsupportedPair as exc:
        abort(
            400,
            description=(
                f"Provider {provider_id!r} does not support the reverse "
                f"language pair ({target_lang!r} → {source_lang!r}): {exc}"
            ),
        )
    except ProviderRouteNotFound as exc:
        # `translate_with` bypasses routing config so this is not currently
        # reachable, but the symmetry keeps the route 4xx-safe if a future
        # refactor re-routes through `translate()`.
        abort(400, description=f"No route for provider {provider_id!r}: {exc}")

    bt_cosine = cosine_similarity(bt_result.target_text, row.source_text)

    # Recompute signals with back_translation_cosine filled in.
    signals_with_bt = ConfidenceSignals(
        termbase_cosine=row.signals.termbase_cosine,
        placeholder_parity=row.signals.placeholder_parity,
        length_budget=row.signals.length_budget,
        back_translation_cosine=bt_cosine,
    )
    updated_row = _RowData(
        translated_fingerprint=row.translated_fingerprint,
        source_text=row.source_text,
        source_lang=row.source_lang,
        target_text=row.target_text,
        target_lang=row.target_lang,
        provider=row.provider,
        model=row.model,
        signals=signals_with_bt,
    )

    # Estimate cost for this provider for UI display. Convert chars → tokens
    # using the provider's own tokenizer ratio (chars/token differs across
    # OpenAI / Anthropic / NLLB / OPUS / Ollama).
    from ainemo.providers._usage_log import estimate_tokens_from_chars

    estimate = router._usage_log.estimate_for(
        provider_id,
        None,
        estimate_tokens_from_chars(len(row.target_text), provider_id=provider_id),
    )

    return render_template(
        _TEMPLATE_ROW,
        row=updated_row,
        source_lang=source_lang,
        target_lang=target_lang,
        registered_providers=registered,
        back_translation_text=bt_result.target_text,
        estimate_usd=estimate,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_rows(
    tm: object,
    termbase: object,
    source_lang: str,
    target_lang: str,
    limit: int,
) -> tuple[_RowData, ...]:
    """Fetch TM translations and compute cheap signals for each.

    Takes the first ``limit`` rows from ``iter_translations``; no
    provider call is made.
    """
    if not isinstance(tm, TranslationMemory):
        return ()

    from ainemo.core.termbase.base import Termbase

    if not isinstance(termbase, Termbase):
        return ()

    rows: list[_RowData] = []
    for translated in tm.iter_translations(source_lang=source_lang, target_lang=target_lang):
        if len(rows) >= limit:
            break
        try:
            signals = compute_cheap_signals(
                segment=translated.segment,
                target_text=translated.target_text,
                target_lang=target_lang,
                termbase=termbase,
            )
        except Exception:
            _log.debug(
                "compute_cheap_signals failed for %s", translated.segment.fingerprint, exc_info=True
            )
            signals = ConfidenceSignals(
                termbase_cosine=0.0,
                placeholder_parity=1.0,
                length_budget=1.0,
                back_translation_cosine=None,
            )
        rows.append(
            _RowData(
                translated_fingerprint=translated.segment.fingerprint,
                source_text=translated.segment.source_text,
                source_lang=translated.segment.source_lang,
                target_text=translated.target_text,
                target_lang=translated.target_lang,
                provider=translated.provider,
                model=translated.model,
                signals=signals,
            )
        )
    return tuple(rows)


def _find_row(
    tm: object,
    termbase: object,
    fingerprint: str,
    source_lang: str,
    target_lang: str,
) -> _RowData | None:
    """Find a single TM row by fingerprint and compute its cheap signals."""
    if not isinstance(tm, TranslationMemory):
        return None

    from ainemo.core.termbase.base import Termbase

    tb_ok = isinstance(termbase, Termbase)

    for translated in tm.iter_translations(source_lang=source_lang, target_lang=target_lang):
        if translated.segment.fingerprint != fingerprint:
            continue
        if tb_ok:
            try:
                signals = compute_cheap_signals(
                    segment=translated.segment,
                    target_text=translated.target_text,
                    target_lang=target_lang,
                    termbase=termbase,  # type: ignore[arg-type]
                )
            except Exception:
                _log.debug("compute_cheap_signals failed for %s", fingerprint, exc_info=True)
                signals = ConfidenceSignals(0.0, 1.0, 1.0, None)
        else:
            signals = ConfidenceSignals(0.0, 1.0, 1.0, None)
        return _RowData(
            translated_fingerprint=fingerprint,
            source_text=translated.segment.source_text,
            source_lang=translated.segment.source_lang,
            target_text=translated.target_text,
            target_lang=translated.target_lang,
            provider=translated.provider,
            model=translated.model,
            signals=signals,
        )
    return None


qa_confidence.__name__ = ROUTE_QA_CONFIDENCE
qa_back_translate.__name__ = ROUTE_QA_BACK_TRANSLATE


def register_qa(app: object) -> None:
    """Register the QA blueprint on *app*.

    Called from ``ainemo.app.create_app`` once S5 is active.
    """
    from flask import Flask

    if isinstance(app, Flask):
        app.register_blueprint(blueprint)


__all__ = ["blueprint", "register_qa"]
