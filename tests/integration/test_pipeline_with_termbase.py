# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-3 S6 — pipeline + termbase + persona integration.

Asserts the pipeline injects a persona prompt addendum + termbase
glossary block into the provider system prompt on TM-miss segments,
while staying byte-stable when neither is configured (the cycle-1
e2e regress-clean contract).

Tests use a recording fake provider so we can inspect the
``system_prompt_addendum`` value the pipeline forwarded — that's
the integration contract; what the LLM does with the addendum is
the provider's concern, not the pipeline's.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from ainemo.core.adapters.java_properties import JavaPropertiesAdapter
from ainemo.core.pipeline import TranslationPipeline
from ainemo.core.segment import Segment
from ainemo.core.termbase.base import (
    Concept,
    Domain,
    Persona,
    Term,
)
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.tm.sqlite import SqliteTranslationMemory
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers.base import ProviderResult

pytestmark = pytest.mark.integration


# --- Recording fake provider --------------------------------------------


class _RecordingProvider:
    """Captures every translate call so tests can assert the
    system_prompt_addendum the pipeline forwarded."""

    provider_id: ClassVar[str] = PROVIDER_ID_NOOP

    def __init__(self) -> None:
        self.calls: list[tuple[Segment, str, str | None]] = []

    def translate(
        self,
        segment: Segment,
        target_lang: str,
        *,
        system_prompt_addendum: str | None = None,
    ) -> ProviderResult:
        self.calls.append((segment, target_lang, system_prompt_addendum))
        return ProviderResult(
            target_text=f"[{target_lang}] {segment.source_text}",
            provider=self.provider_id,
            model=self.provider_id,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
            cost_usd=None,
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


def _seed_bundle(tmp_path: Path) -> Path:
    src = tmp_path / "messages_en_US.properties"
    src.write_text(
        "greeting=Hello\nlogin.button=login button\n",
        encoding="utf-8",
    )
    return src


def _seed_termbase(tb_path: Path) -> KuzuTermbase:
    tb = KuzuTermbase(tb_path)
    tb.add_domain(Domain(domain_id="software", parent_id=None, name="Software"))
    tb.add_concept(
        Concept(concept_id="c-login", qid=None, definition=None, created_at=1),
        [
            Term(
                term_id="t-login-en",
                concept_id="c-login",
                lang="en-US",
                surface="login",
                register=None,
                part_of_speech="noun",
                source="manual",
            ),
            Term(
                term_id="t-login-de",
                concept_id="c-login",
                lang="de-DE",
                surface="Anmeldung",
                register=None,
                part_of_speech="noun",
                source="manual",
            ),
        ],
    )
    tb.attach_concept_to_domain("c-login", "software")
    return tb


def _build_pipeline(
    tmp_path: Path,
    provider: _RecordingProvider,
    *,
    termbase: KuzuTermbase | None = None,
    persona: Persona | None = None,
) -> TranslationPipeline:
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    return TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=provider,
        validators=(),
        target_langs=("de-DE",),
        source_lang="en-US",
        termbase=termbase,
        persona=persona,
    )


# --- No termbase / no persona = cycle-1+2 path ---------------------------


def test_pipeline_without_termbase_or_persona_passes_no_addendum(
    tmp_path: Path,
) -> None:
    src = _seed_bundle(tmp_path)
    provider = _RecordingProvider()
    pipeline = _build_pipeline(tmp_path, provider)
    pipeline.translate_file(src, tmp_path / "out")

    # Cycle-1+2 contract: every translate call receives None for the
    # cycle-3 system_prompt_addendum, indistinguishable from the
    # pre-cycle-3 (segment, target_lang) signature.
    assert provider.calls, "provider was never called"
    for _segment, _target_lang, addendum in provider.calls:
        assert addendum is None


# --- Persona only --------------------------------------------------------


def test_pipeline_with_persona_only_injects_prompt_addendum(
    tmp_path: Path,
) -> None:
    src = _seed_bundle(tmp_path)
    provider = _RecordingProvider()
    persona = Persona(
        persona_id="software-ui",
        name="Software UI",
        forbidden_terms=(),
        prompt_addendum="Translate UI strings tightly.",
        domain_id="software",
    )
    pipeline = _build_pipeline(tmp_path, provider, persona=persona)
    pipeline.translate_file(src, tmp_path / "out")

    addenda = [a for _, _, a in provider.calls]
    assert all(a == "Translate UI strings tightly." for a in addenda)


# --- Termbase only -------------------------------------------------------


def test_pipeline_with_termbase_only_injects_glossary_block(
    tmp_path: Path,
) -> None:
    src = _seed_bundle(tmp_path)
    provider = _RecordingProvider()
    tb = _seed_termbase(tmp_path / "tb.kuzu")
    pipeline = _build_pipeline(tmp_path, provider, termbase=tb)
    pipeline.translate_file(src, tmp_path / "out")

    # `login.button` value is "login button" — the n-gram "login"
    # matches concept c-login → "Anmeldung". The "greeting" segment
    # ("Hello") has no termbase hits; addendum stays None.
    addenda_by_text = {seg.source_text: a for seg, _, a in provider.calls}
    addendum_login = addenda_by_text["login button"]
    assert addendum_login is not None
    assert "Glossary (apply to the segment if relevant):" in addendum_login
    assert '- "login" → "Anmeldung"' in addendum_login

    # No persona, no glossary hit → no addendum on the unrelated segment.
    assert addenda_by_text["Hello"] is None


# --- Persona + termbase combined ----------------------------------------


def test_persona_and_termbase_combine_into_one_addendum(
    tmp_path: Path,
) -> None:
    src = _seed_bundle(tmp_path)
    provider = _RecordingProvider()
    tb = _seed_termbase(tmp_path / "tb.kuzu")
    persona = Persona(
        persona_id="software-ui",
        name="Software UI",
        forbidden_terms=(),
        prompt_addendum="Translate UI strings tightly.",
        domain_id="software",
    )
    pipeline = _build_pipeline(tmp_path, provider, termbase=tb, persona=persona)
    pipeline.translate_file(src, tmp_path / "out")

    addenda_by_text = {seg.source_text: a for seg, _, a in provider.calls}
    login_addendum = addenda_by_text["login button"]
    assert login_addendum is not None
    # Order: persona prompt first, glossary second, separated by blank line.
    assert login_addendum.startswith("Translate UI strings tightly.")
    assert "Glossary (apply to the segment if relevant):" in login_addendum
    assert '- "login" → "Anmeldung"' in login_addendum

    # Segments without termbase hits get just the persona addendum.
    hello_addendum = addenda_by_text["Hello"]
    assert hello_addendum == "Translate UI strings tightly."


# --- TM-hit short-circuits the addendum ---------------------------------


def test_tm_hit_does_not_call_provider_or_build_addendum(
    tmp_path: Path,
) -> None:
    src = _seed_bundle(tmp_path)
    provider = _RecordingProvider()
    tb = _seed_termbase(tmp_path / "tb.kuzu")
    persona = Persona(
        persona_id="software-ui",
        name="Software UI",
        forbidden_terms=(),
        prompt_addendum="Tight UI translation.",
        domain_id="software",
    )
    # Pre-seed the TM so both segments are exact-hits on the second run.
    pipeline = _build_pipeline(tmp_path, provider, termbase=tb, persona=persona)
    pipeline.translate_file(src, tmp_path / "out")
    first_call_count = len(provider.calls)
    assert first_call_count == 2

    pipeline2 = _build_pipeline(tmp_path, provider, termbase=tb, persona=persona)
    pipeline2.translate_file(src, tmp_path / "out2")
    # Provider not called again — TM hits short-circuit.
    assert len(provider.calls) == first_call_count


# --- Domain narrowing ---------------------------------------------------


def test_persona_domain_narrows_termbase_lookup(tmp_path: Path) -> None:
    # Add a competing concept in a different domain — the persona's
    # domain_id should narrow the termbase lookup so only same-domain
    # hits land in the glossary block.
    src = _seed_bundle(tmp_path)
    provider = _RecordingProvider()
    tb = _seed_termbase(tmp_path / "tb.kuzu")
    tb.add_domain(Domain(domain_id="aerospace", parent_id=None, name="Aerospace"))
    tb.add_concept(
        Concept(concept_id="c-login-air", qid=None, definition=None, created_at=2),
        [
            Term(
                term_id="t-login-air-en",
                concept_id="c-login-air",
                lang="en-US",
                surface="login",
                register=None,
                part_of_speech=None,
                source="manual",
            ),
            Term(
                term_id="t-login-air-de",
                concept_id="c-login-air",
                lang="de-DE",
                surface="Cockpit-Anmeldung",
                register=None,
                part_of_speech=None,
                source="manual",
            ),
        ],
    )
    tb.attach_concept_to_domain("c-login-air", "aerospace")

    software_persona = Persona(
        persona_id="software-ui",
        name="Software UI",
        forbidden_terms=(),
        prompt_addendum="Tight UI translation.",
        domain_id="software",
    )
    pipeline = _build_pipeline(tmp_path, provider, termbase=tb, persona=software_persona)
    pipeline.translate_file(src, tmp_path / "out")

    addenda_by_text = {seg.source_text: a for seg, _, a in provider.calls}
    login_addendum = addenda_by_text["login button"]
    assert login_addendum is not None
    # Software-domain hit lands; aerospace-domain is filtered out.
    assert "Anmeldung" in login_addendum
    assert "Cockpit-Anmeldung" not in login_addendum


# --- Empty addendum gracefully suppressed --------------------------------


def test_pipeline_threads_persona_and_domain_to_router(
    tmp_path: Path,
) -> None:
    """Regression for the cycle-3 S6 P2 finding.

    The pipeline was building the persona prompt addendum but never
    passing ``persona`` / ``domain`` to ``ProviderRouter.translate()``,
    so a ``RoutingRule(provider_id=..., persona=..., domain=...)``
    never matched even when the pipeline was constructed with a
    matching :class:`Persona`. This test wires two providers behind a
    router with a persona+domain-scoped rule and asserts the rule
    fires when the pipeline forwards the call.
    """
    from ainemo.providers._usage_log import UsageLog
    from ainemo.providers.router import ProviderRouter, RoutingConfig, RoutingRule

    src = _seed_bundle(tmp_path)
    legal_provider = _RecordingProvider()
    default_provider = _RecordingProvider()

    # Two providers behind one router. Without persona/domain plumbing,
    # the rule never matches → default_provider is called for everything.
    router = ProviderRouter(
        providers={"legal-noop": legal_provider, "default-noop": default_provider},
        routing_config=RoutingConfig(
            rules=(
                RoutingRule(
                    provider_id="legal-noop",
                    persona="legal-fmt",
                    domain="legal",
                ),
            ),
            default_provider="default-noop",
        ),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    persona = Persona(
        persona_id="legal-fmt",
        name="Legal Formal",
        forbidden_terms=(),
        prompt_addendum="Legal register.",
        domain_id="legal",
    )
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=SqliteTranslationMemory(tmp_path / "tm.sqlite"),
        provider=router,
        validators=(),
        target_langs=("de-DE",),
        source_lang="en-US",
        persona=persona,
    )
    pipeline.translate_file(src, tmp_path / "out")

    # Routing rule fired: every segment went through legal_provider.
    assert len(legal_provider.calls) > 0
    assert default_provider.calls == []


def test_persona_with_empty_addendum_and_no_termbase_hit_returns_none(
    tmp_path: Path,
) -> None:
    src = _seed_bundle(tmp_path)
    provider = _RecordingProvider()
    persona = Persona(
        persona_id="empty",
        name="Empty",
        forbidden_terms=(),
        prompt_addendum="   ",  # whitespace-only
    )
    # Termbase configured but no concepts — both addendum sources are
    # empty, so the pipeline must pass None (not an empty string).
    tb = KuzuTermbase(tmp_path / "tb.kuzu")
    pipeline = _build_pipeline(tmp_path, provider, termbase=tb, persona=persona)
    pipeline.translate_file(src, tmp_path / "out")

    for _seg, _lang, addendum in provider.calls:
        assert addendum is None
