# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S2 — Flask /promote integration tests.

Test inventory (>= 6 cases, per pitch):
1.  GET /promote returns 200 with the queue rendered (seeded TM).
2.  GET /promote with no candidates returns 200 with an empty-queue message.
3.  POST /promote/decide accept writes Concept + 2 Terms with
    provenance tm-promotion and the stable concept id (tm-promo-<sha256[:16]>).
4.  POST /promote/decide accept is idempotent on re-POST (concept count stable).
5.  POST /promote/decide edit + edited_target_surface writes the edited surface.
6.  POST /promote/decide reject writes nothing.
7.  CLI parity: a candidate accepted via write_accepted_candidate (the CLI
    path) and the same candidate accepted via the UI POST produce identical
    termbase rows (same concept_id, same Term surfaces and ids).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Iterator

import pytest

from ainemo.app import create_app
from ainemo.core.segment import TRANSLATION_SOURCE_PROVIDER, Segment, TranslatedSegment
from ainemo.core.termbase._ids import TERM_SOURCE_TM_PROMOTION
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.termbase.promotion import (
    PromotionCandidate,
    _derive_promotion_concept_id,
    write_accepted_candidate,
)
from ainemo.core.tm.base import TmHit, TmStats
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_LANG = "en"
_TARGET_LANG = "de"
# n-gram that will exceed frequency + consistency thresholds in the seeded TM.
_NGRAM = "login"
_TARGET = "Anmeldung"
# Number of distinct TM segments required; default min_frequency = 5.
_SEGMENT_COUNT = 5


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _NoOpProvider:
    provider_id: ClassVar[str] = PROVIDER_ID_NOOP

    def translate(
        self,
        segment: Segment,
        target_lang: str,
        *,
        system_prompt_addendum: str | None = None,
    ) -> ProviderResult:
        del system_prompt_addendum
        return ProviderResult(
            target_text=segment.source_text,
            provider=PROVIDER_ID_NOOP,
            model=PROVIDER_ID_NOOP,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
            cost_usd=None,
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


class _SeedableTm:
    """In-memory TM stub with a pre-seeded pair list.

    ``find_candidates`` only calls ``iter_translations``; lookup / store /
    stats are stubs so this double stays minimal.
    """

    def __init__(self, pairs: list[tuple[str, str]]) -> None:
        self._pairs = pairs

    def lookup(self, *args: object, **kwargs: object) -> TmHit | None:
        return None

    def store(self, translated: TranslatedSegment) -> None:
        pass

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
        for idx, (source, target) in enumerate(self._pairs):
            seg = Segment(key=f"k{idx}", source_text=source, source_lang=source_lang)
            yield TranslatedSegment(
                segment=seg,
                target_lang=target_lang,
                target_text=target,
                provider="noop",
                model="",
                confidence=None,
                source=TRANSLATION_SOURCE_PROVIDER,
            )


def _promotable_pairs() -> list[tuple[str, str]]:
    """5 distinct segments each containing _NGRAM, all mapping to _TARGET."""
    return [(f"{_NGRAM} step{i}", _TARGET) for i in range(_SEGMENT_COUNT)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _kuzu_tb(tmp_path: Path) -> Iterator[KuzuTermbase]:
    tb = KuzuTermbase(tmp_path / "termbase.kuzu")
    yield tb
    tb.close()


@pytest.fixture()
def _router(tmp_path: Path) -> ProviderRouter:
    noop: Provider = _NoOpProvider()
    return ProviderRouter(
        providers={PROVIDER_ID_NOOP: noop},
        routing_config=RoutingConfig(default_provider=PROVIDER_ID_NOOP),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )


@pytest.fixture()
def _seeded_app(_kuzu_tb: KuzuTermbase, _router: ProviderRouter) -> object:
    """Flask app wired with a TM seeded with _SEGMENT_COUNT promotable rows."""
    tm = _SeedableTm(_promotable_pairs())
    return create_app(termbase=_kuzu_tb, tm=tm, router=_router)


@pytest.fixture()
def _empty_app(_kuzu_tb: KuzuTermbase, _router: ProviderRouter) -> object:
    """Flask app wired with an empty TM (no candidates)."""
    tm = _SeedableTm([])
    return create_app(termbase=_kuzu_tb, tm=tm, router=_router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate_form(
    *,
    decision: str,
    ngram: str = _NGRAM,
    source_lang: str = _SOURCE_LANG,
    target_lang: str = _TARGET_LANG,
    suggested_target: str = _TARGET,
    edited_target_surface: str = "",
) -> dict[str, str]:
    return {
        "decision": decision,
        "source_ngram": ngram,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "suggested_target": suggested_target,
        "edited_target_surface": edited_target_surface,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_promote_returns_200_with_queue(_seeded_app: object) -> None:
    """GET /promote returns 200 and renders candidate rows."""
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    with _seeded_app.test_client() as client:
        resp = client.get(f"/promote?source_lang={_SOURCE_LANG}&target_lang={_TARGET_LANG}")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert _NGRAM in body
    assert _TARGET in body


def test_get_promote_empty_tm_returns_200_with_empty_message(_empty_app: object) -> None:
    """GET /promote with no candidates returns 200 and an empty-queue message."""
    from flask import Flask

    assert isinstance(_empty_app, Flask)
    with _empty_app.test_client() as client:
        resp = client.get(f"/promote?source_lang={_SOURCE_LANG}&target_lang={_TARGET_LANG}")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "No promotion candidates" in body


def test_post_accept_writes_concept_and_terms(_seeded_app: object, _kuzu_tb: KuzuTermbase) -> None:
    """POST accept writes exactly one Concept + 2 Terms with tm-promotion source
    and a stable ``tm-promo-<sha256[:16]>`` concept id."""
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    with _seeded_app.test_client() as client:
        resp = client.post("/promote/decide", data=_candidate_form(decision="accept"))
    assert resp.status_code == 200

    stats = _kuzu_tb.stats()
    assert stats.concept_count == 1

    candidate = PromotionCandidate(
        source_lang=_SOURCE_LANG,
        target_lang=_TARGET_LANG,
        source_ngram=_NGRAM,
        suggested_target=_TARGET,
        frequency=0,
        consistency=0.0,
    )
    expected_id = _derive_promotion_concept_id(candidate)
    assert expected_id.startswith("tm-promo-")

    hits = _kuzu_tb.lookup_concepts_for(_NGRAM, _SOURCE_LANG, _TARGET_LANG)
    assert len(hits) == 1
    terms = hits[0].target_terms + (hits[0].matched_source_term,)
    for term in terms:
        assert term.source == TERM_SOURCE_TM_PROMOTION


def test_post_accept_is_idempotent(_seeded_app: object, _kuzu_tb: KuzuTermbase) -> None:
    """POST accept twice for the same candidate produces exactly one Concept."""
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    form = _candidate_form(decision="accept")
    with _seeded_app.test_client() as client:
        client.post("/promote/decide", data=form)
        client.post("/promote/decide", data=form)

    assert _kuzu_tb.stats().concept_count == 1


def test_post_edit_writes_edited_surface(_seeded_app: object, _kuzu_tb: KuzuTermbase) -> None:
    """POST edit with edited_target_surface writes the edited surface to the Term."""
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    edited = "Einloggen"
    with _seeded_app.test_client() as client:
        resp = client.post(
            "/promote/decide",
            data=_candidate_form(decision="edit", edited_target_surface=edited),
        )
    assert resp.status_code == 200

    hits = _kuzu_tb.lookup_concepts_for(_NGRAM, _SOURCE_LANG, _TARGET_LANG)
    assert len(hits) == 1
    target_surfaces = {t.surface for t in hits[0].target_terms}
    assert edited in target_surfaces


def test_post_reject_writes_nothing(_seeded_app: object, _kuzu_tb: KuzuTermbase) -> None:
    """POST reject must not write any concept or term."""
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    with _seeded_app.test_client() as client:
        resp = client.post("/promote/decide", data=_candidate_form(decision="reject"))
    assert resp.status_code == 200
    assert _kuzu_tb.stats().concept_count == 0


def test_cli_and_ui_accept_produce_identical_rows(tmp_path: Path, _router: ProviderRouter) -> None:
    """CLI path (write_accepted_candidate) and UI POST produce identical rows.

    This is the canary test for the shared-helper extraction (cycle-5 S2 P3
    mitigation in the pitch § Risks). If anyone drifts the CLI or UI write
    path, concept_id or term surfaces will diverge and this test will fail.
    """
    candidate = PromotionCandidate(
        source_lang=_SOURCE_LANG,
        target_lang=_TARGET_LANG,
        source_ngram=_NGRAM,
        suggested_target=_TARGET,
        frequency=_SEGMENT_COUNT,
        consistency=1.0,
    )

    # CLI path: write directly via the shared helper into tb_cli.
    tb_cli = KuzuTermbase(tmp_path / "cli_tb.kuzu")
    write_accepted_candidate(tb_cli, candidate)
    cli_hits = tb_cli.lookup_concepts_for(_NGRAM, _SOURCE_LANG, _TARGET_LANG)
    cli_concept_id = cli_hits[0].concept.concept_id
    cli_term_ids = {t.term_id for t in (cli_hits[0].matched_source_term, *cli_hits[0].target_terms)}
    cli_surfaces = {t.surface for t in (cli_hits[0].matched_source_term, *cli_hits[0].target_terms)}
    tb_cli.close()

    # UI path: POST to /promote/decide via the Flask test client into tb_ui.
    tb_ui = KuzuTermbase(tmp_path / "ui_tb.kuzu")
    tm = _SeedableTm(_promotable_pairs())
    app = create_app(termbase=tb_ui, tm=tm, router=_router)
    with app.test_client() as client:
        client.post("/promote/decide", data=_candidate_form(decision="accept"))
    ui_hits = tb_ui.lookup_concepts_for(_NGRAM, _SOURCE_LANG, _TARGET_LANG)
    ui_concept_id = ui_hits[0].concept.concept_id
    ui_term_ids = {t.term_id for t in (ui_hits[0].matched_source_term, *ui_hits[0].target_terms)}
    ui_surfaces = {t.surface for t in (ui_hits[0].matched_source_term, *ui_hits[0].target_terms)}
    tb_ui.close()

    assert cli_concept_id == ui_concept_id, "concept_id differs between CLI and UI paths"
    assert cli_term_ids == ui_term_ids, "term_ids differ between CLI and UI paths"
    assert cli_surfaces == ui_surfaces, "term surfaces differ between CLI and UI paths"


def test_post_decide_rejects_unknown_candidate(_seeded_app: object, _kuzu_tb: KuzuTermbase) -> None:
    """POST with a (source_ngram, suggested_target) pair that does not match
    any current find_candidates() result must return 400 and write nothing.

    Regression for the cycle-5 S2 P1 review finding: /promote/decide used
    to trust hidden form fields and write any posted candidate, turning
    the decision endpoint into an unauthenticated arbitrary termbase write.
    """
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    with _seeded_app.test_client() as client:
        resp = client.post(
            "/promote/decide",
            data=_candidate_form(
                decision="accept",
                ngram="not-a-real-ngram",
                suggested_target="not-a-real-target",
            ),
        )
    assert resp.status_code == 400
    assert _kuzu_tb.stats().concept_count == 0


def test_post_decide_rejects_blank_natural_key(_seeded_app: object, _kuzu_tb: KuzuTermbase) -> None:
    """POST with blank source_ngram or blank suggested_target must 400
    and write nothing.

    Regression for the cycle-5 S2 P1 review finding: blank fields used
    to default to empty strings and produce a Concept with blank Terms.
    """
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    with _seeded_app.test_client() as client:
        resp_blank_ngram = client.post(
            "/promote/decide",
            data=_candidate_form(decision="accept", ngram="", suggested_target=_TARGET),
        )
        resp_blank_target = client.post(
            "/promote/decide",
            data=_candidate_form(decision="accept", ngram=_NGRAM, suggested_target=""),
        )
    assert resp_blank_ngram.status_code == 400
    assert resp_blank_target.status_code == 400
    assert _kuzu_tb.stats().concept_count == 0


def test_promote_signals_carry_segment_metadata(_kuzu_tb: KuzuTermbase, tmp_path: Path) -> None:
    """Cycle-5 S5 P2 regression — the promote queue's confidence signals must
    score against the *original* contributing segment, not a partial copy.

    Asserts per-field round-trip (key, source_text, source_lang, placeholders,
    metadata, fingerprint) plus per-signal correctness (placeholder_parity,
    length_budget). A future refactor that swaps in a partial Segment will
    fail at least one assertion regardless of which field gets dropped.
    """
    from ainemo.app.qa.signals import compute_cheap_signals
    from ainemo.app.views.promote import _augment
    from ainemo.core.segment import Placeholder, PlaceholderKind, Segment, TranslatedSegment

    seg_with_meta = Segment(
        key="k0",
        source_text="Welcome {0}!",
        source_lang=_SOURCE_LANG,
        placeholders=(Placeholder(kind=PlaceholderKind.POSITIONAL, raw="{0}", span=(8, 11)),),
        metadata={"max_length": "5"},  # tight budget — translation will exceed
    )
    translated = TranslatedSegment(
        segment=seg_with_meta,
        target_lang=_TARGET_LANG,
        target_text="Willkommen!",  # placeholder dropped + over budget
        provider=PROVIDER_ID_NOOP,
        model="",
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )

    class _PhTm:
        def lookup(self, *args: object, **kwargs: object) -> None:
            return None

        def store(self, t: TranslatedSegment) -> None:
            pass

        def stats(self) -> TmStats:
            return TmStats(
                segment_count=1, translation_count=1, target_lang_count=1, embedding_count=0
            )

        def iter_translations(
            self, *, source_lang: str, target_lang: str
        ) -> Iterator[TranslatedSegment]:
            for _ in range(_SEGMENT_COUNT):
                yield translated

    candidate = PromotionCandidate(
        source_lang=_SOURCE_LANG,
        target_lang=_TARGET_LANG,
        source_ngram="Welcome",
        suggested_target="Willkommen!",
        frequency=_SEGMENT_COUNT,
        consistency=1.0,
        contributing_segment_fingerprints=tuple(
            seg_with_meta.fingerprint for _ in range(_SEGMENT_COUNT)
        ),
    )
    augmented = _augment(candidate, tm=_PhTm(), tb=_kuzu_tb)
    assert augmented.segment_previews, "expected ≥ 1 contributing-segment preview"
    preview = augmented.segment_previews[0]

    # Per-field round-trip — each is a distinct way the partial-Segment
    # bug could regress.
    assert preview.segment.key == seg_with_meta.key
    assert preview.segment.source_text == seg_with_meta.source_text
    assert preview.segment.source_lang == seg_with_meta.source_lang
    assert preview.segment.placeholders == seg_with_meta.placeholders
    assert dict(preview.segment.metadata) == dict(seg_with_meta.metadata)
    assert preview.segment.fingerprint == seg_with_meta.fingerprint

    # Per-signal correctness.
    assert augmented.signals is not None
    assert augmented.signals.placeholder_parity == 0.0, (
        "placeholder_parity must be 0.0 — translation dropped {0}"
    )
    assert augmented.signals.length_budget == 0.0, (
        "length_budget must be 0.0 — translation exceeds max_length=5"
    )

    # Sanity: independently computed signals match what _augment produced.
    direct = compute_cheap_signals(
        segment=seg_with_meta,
        target_text="Willkommen!",
        target_lang=_TARGET_LANG,
        termbase=_kuzu_tb,
    )
    assert augmented.signals.placeholder_parity == direct.placeholder_parity
    assert augmented.signals.length_budget == direct.length_budget


def test_post_decide_edit_requires_edited_target(
    _seeded_app: object, _kuzu_tb: KuzuTermbase
) -> None:
    """POST decision=edit with a blank edited_target_surface must 400.

    Without this guard, an edit decision would silently fall back to the
    suggested_target and quietly become an accept — confusing UX and a
    write the operator did not intend.
    """
    from flask import Flask

    assert isinstance(_seeded_app, Flask)
    with _seeded_app.test_client() as client:
        resp = client.post(
            "/promote/decide",
            data=_candidate_form(decision="edit", edited_target_surface=""),
        )
    assert resp.status_code == 400
    assert _kuzu_tb.stats().concept_count == 0
