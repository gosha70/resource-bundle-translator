# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S6 — Flask /personas integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Iterator

import pytest

from ainemo.app import create_app
from ainemo.core.segment import Segment, TranslatedSegment
from ainemo.core.termbase._ids import TERM_SOURCE_MANUAL
from ainemo.core.termbase.base import Concept, Persona, Term
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.tm.base import TmHit, TmStats
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

pytestmark = pytest.mark.integration


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


class _StubTm:
    def lookup(self, *args: object, **kwargs: object) -> TmHit | None:
        return None

    def store(self, translated: TranslatedSegment) -> None:
        pass

    def stats(self) -> TmStats:
        return TmStats(segment_count=0, translation_count=0, target_lang_count=0, embedding_count=0)

    def iter_translations(
        self, *, source_lang: str, target_lang: str
    ) -> Iterator[TranslatedSegment]:
        return iter(())


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


def _seed_persona(tb: KuzuTermbase, *, persona_id: str, prompt_addendum: str = "") -> Persona:
    persona = Persona(
        persona_id=persona_id,
        name=persona_id,
        forbidden_terms=(),
        prompt_addendum=prompt_addendum,
        domain_id=None,
        register=None,
    )
    tb.add_persona(persona)
    return persona


def _seed_concept(tb: KuzuTermbase, *, concept_id: str, source: str, target: str) -> None:
    tb.add_concept(
        Concept(concept_id=concept_id, qid=None, definition=None, created_at=1),
        [
            Term(
                term_id=f"{concept_id}-en",
                concept_id=concept_id,
                lang="en",
                surface=source,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            ),
            Term(
                term_id=f"{concept_id}-de",
                concept_id=concept_id,
                lang="de",
                surface=target,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_personas_empty_returns_200(_kuzu_tb: KuzuTermbase, _router: ProviderRouter) -> None:
    from flask import Flask

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.get("/personas")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "No personas synced" in body


def test_get_personas_lists_seeded_personas(
    _kuzu_tb: KuzuTermbase, _router: ProviderRouter
) -> None:
    from flask import Flask

    _seed_persona(_kuzu_tb, persona_id="formal", prompt_addendum="Use formal address.")
    _seed_persona(_kuzu_tb, persona_id="casual", prompt_addendum="Use casual tone.")

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.get("/personas")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "formal" in body
    assert "casual" in body


def test_get_persona_detail_returns_200(_kuzu_tb: KuzuTermbase, _router: ProviderRouter) -> None:
    from flask import Flask

    _seed_persona(_kuzu_tb, persona_id="formal", prompt_addendum="Use formal address.")

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.get("/personas/formal")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Use formal address." in body
    assert "Preview hits" in body


def test_get_persona_detail_unknown_returns_404(
    _kuzu_tb: KuzuTermbase, _router: ProviderRouter
) -> None:
    from flask import Flask

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.get("/personas/no-such-persona")
    assert resp.status_code == 404


def test_post_preview_hits_renders_glossary_block(
    _kuzu_tb: KuzuTermbase, _router: ProviderRouter
) -> None:
    from flask import Flask

    _seed_persona(_kuzu_tb, persona_id="formal", prompt_addendum="Use formal address.")
    _seed_concept(_kuzu_tb, concept_id="c-login", source="login", target="Anmeldung")

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.post(
            "/personas/formal/preview-hits",
            data={
                "source_text": "please login here",
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Use formal address." in body
    assert "login" in body
    assert "Anmeldung" in body
    assert "Glossary (apply to the segment if relevant):" in body


def test_post_preview_hits_unknown_persona_returns_404(
    _kuzu_tb: KuzuTermbase, _router: ProviderRouter
) -> None:
    from flask import Flask

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.post(
            "/personas/unknown/preview-hits",
            data={"source_text": "hello", "source_lang": "en", "target_lang": "de"},
        )
    assert resp.status_code == 404


def test_post_preview_hits_blank_source_returns_400(
    _kuzu_tb: KuzuTermbase, _router: ProviderRouter
) -> None:
    from flask import Flask

    _seed_persona(_kuzu_tb, persona_id="formal", prompt_addendum="Use formal address.")

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.post(
            "/personas/formal/preview-hits",
            data={"source_text": "  ", "source_lang": "en", "target_lang": "de"},
        )
    assert resp.status_code == 400


def test_post_preview_hits_byte_equivalent_to_pipeline(
    _kuzu_tb: KuzuTermbase, _router: ProviderRouter
) -> None:
    """Cycle-5 S6 byte-equivalence regression — the preview-hits fragment
    must include the exact same glossary lines the cycle-3 pipeline would
    inject for the same (persona, segment, target_lang) inputs.

    Asserts the rendered fragment contains every line from the pipeline's
    `_build_system_prompt_addendum(...)` output. Pipeline-level
    byte-stability is also covered by tests/integration/test_pipeline_with_termbase.py.

    Comparison shape: the assertion compares lines from the addendum
    against ``html.unescape(rendered_body)``, which assumes the pipeline
    produces *plain text* (no intentional HTML markup). That assumption
    is implicit in AGENTS.md — provider system-prompt addendums are
    text the model reads, not markup — so any future format change that
    starts emitting `<` or `>` characters as syntax (rather than as
    incidentally-occurring text) would also need to revisit this test.
    """
    from flask import Flask

    from ainemo.core.termbase.glossary import build_glossary_block

    persona = _seed_persona(_kuzu_tb, persona_id="formal", prompt_addendum="Use formal address.")
    _seed_concept(_kuzu_tb, concept_id="c-login", source="login", target="Anmeldung")

    expected_addendum = build_glossary_block(
        _kuzu_tb,
        persona,
        source_text="please login here",
        source_lang="en",
        target_lang="de",
    )
    assert expected_addendum is not None

    app = create_app(termbase=_kuzu_tb, tm=_StubTm(), router=_router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.post(
            "/personas/formal/preview-hits",
            data={
                "source_text": "please login here",
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    import html

    assert resp.status_code == 200
    # Jinja autoescapes the <pre> block content (using numeric entities
    # like &#34;); unescape the body so the byte-equivalence assertion
    # is independent of Jinja's choice of entity encoding.
    body = html.unescape(resp.data.decode())
    for line in expected_addendum.splitlines():
        if line.strip():
            assert line in body, f"expected line missing from preview: {line!r}"
