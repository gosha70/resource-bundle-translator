# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for cycle-5 S6 build_glossary_block extraction.

Byte-equivalence with the cycle-3 pipeline-private builder is the
headline contract — the cycle-3 S6 pipeline integration test
``tests/integration/test_pipeline_with_termbase.py`` asserts exact
``system_prompt_addendum`` strings and must pass byte-stable. This
unit suite covers the new shared builder's per-input semantics; the
pipeline-level byte-stability is proven by that existing test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.termbase._ids import TERM_SOURCE_MANUAL
from ainemo.core.termbase.base import Concept, Domain, Persona, Term
from ainemo.core.termbase.glossary import build_glossary_block, format_glossary_block
from ainemo.core.termbase.kuzu.store import KuzuTermbase

pytestmark = pytest.mark.unit


_GLOSSARY_HEADER = "Glossary (apply to the segment if relevant):"


@pytest.fixture()
def tb(tmp_path: Path) -> KuzuTermbase:
    return KuzuTermbase(tmp_path / "termbase.kuzu")


def _seed_concept(
    tb: KuzuTermbase,
    *,
    concept_id: str,
    source_term: str,
    target_term: str,
    domain_id: str | None = None,
) -> None:
    tb.add_concept(
        Concept(concept_id=concept_id, qid=None, definition=None, created_at=1),
        [
            Term(
                term_id=f"{concept_id}-en",
                concept_id=concept_id,
                lang="en",
                surface=source_term,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            ),
            Term(
                term_id=f"{concept_id}-de",
                concept_id=concept_id,
                lang="de",
                surface=target_term,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            ),
        ],
    )
    if domain_id is not None:
        tb.add_domain(Domain(domain_id=domain_id, parent_id=None, name=domain_id))
        tb.attach_concept_to_domain(concept_id, domain_id)


def _make_persona(
    *,
    persona_id: str = "test-persona",
    domain_id: str | None = None,
    prompt_addendum: str = "",
) -> Persona:
    return Persona(
        persona_id=persona_id,
        name=persona_id,
        forbidden_terms=(),
        prompt_addendum=prompt_addendum,
        domain_id=domain_id,
        register=None,
    )


def test_build_glossary_block_returns_none_when_both_args_none() -> None:
    """No termbase, no persona → no addendum at all."""
    result = build_glossary_block(
        None, None, source_text="hello", source_lang="en", target_lang="de"
    )
    assert result is None


def test_build_glossary_block_termbase_only_returns_glossary(tb: KuzuTermbase) -> None:
    """Termbase set, persona None → just the glossary block, no addendum prefix."""
    _seed_concept(tb, concept_id="c1", source_term="login", target_term="Anmeldung")
    result = build_glossary_block(
        tb, None, source_text="please login here", source_lang="en", target_lang="de"
    )
    assert result is not None
    assert result.startswith(_GLOSSARY_HEADER)
    assert '"login" → "Anmeldung"' in result


def test_build_glossary_block_persona_only_returns_addendum() -> None:
    """Persona set with non-blank prompt_addendum, termbase None →
    just the addendum, no glossary header."""
    persona = _make_persona(prompt_addendum="Use formal address.")
    result = build_glossary_block(
        None, persona, source_text="hello", source_lang="en", target_lang="de"
    )
    assert result == "Use formal address."


def test_build_glossary_block_persona_blank_addendum_returns_none() -> None:
    """Persona set but prompt_addendum is blank, termbase None → None
    (an empty addendum is worse than no addendum)."""
    persona = _make_persona(prompt_addendum="   ")
    result = build_glossary_block(
        None, persona, source_text="hello", source_lang="en", target_lang="de"
    )
    assert result is None


def test_build_glossary_block_both_concatenates_with_double_newline(tb: KuzuTermbase) -> None:
    """Persona prompt + termbase glossary → addendum, blank line, glossary."""
    _seed_concept(tb, concept_id="c1", source_term="login", target_term="Anmeldung")
    persona = _make_persona(prompt_addendum="Use formal address.")
    result = build_glossary_block(
        tb, persona, source_text="please login here", source_lang="en", target_lang="de"
    )
    assert result is not None
    assert result.startswith("Use formal address.\n\n" + _GLOSSARY_HEADER)


def test_build_glossary_block_domain_filter(tb: KuzuTermbase) -> None:
    """Persona with domain_id only surfaces concepts attached to that domain."""
    _seed_concept(
        tb, concept_id="c-legal", source_term="cancel", target_term="kündigen", domain_id="legal"
    )
    _seed_concept(
        tb,
        concept_id="c-software",
        source_term="cancel",
        target_term="abbrechen",
        domain_id="software",
    )

    persona_legal = _make_persona(persona_id="legal", domain_id="legal")
    result_legal = build_glossary_block(
        tb,
        persona_legal,
        source_text="cancel button",
        source_lang="en",
        target_lang="de",
    )
    assert result_legal is not None
    assert '"cancel" → "kündigen"' in result_legal
    assert "abbrechen" not in result_legal

    persona_software = _make_persona(persona_id="software", domain_id="software")
    result_software = build_glossary_block(
        tb,
        persona_software,
        source_text="cancel button",
        source_lang="en",
        target_lang="de",
    )
    assert result_software is not None
    assert '"cancel" → "abbrechen"' in result_software
    assert "kündigen" not in result_software


def test_format_glossary_block_skips_hits_without_target(tb: KuzuTermbase) -> None:
    """format_glossary_block returns None when no hit has a target term."""
    from ainemo.core.termbase.base import ConceptHit

    concept = Concept(concept_id="c-no-target", qid=None, definition=None, created_at=1)
    matched = Term(
        term_id="t-en",
        concept_id="c-no-target",
        lang="en",
        surface="login",
        register=None,
        part_of_speech=None,
        source=TERM_SOURCE_MANUAL,
    )
    hit_no_target = ConceptHit(
        concept=concept, matched_source_term=matched, target_terms=(), relevance=0.5
    )

    assert format_glossary_block((hit_no_target,), "de") is None


def test_pipeline_delegates_to_shared_builder() -> None:
    """Cycle-5 S6 byte-equivalence — the pipeline's
    _build_system_prompt_addendum must remain a thin delegation to
    build_glossary_block. If a future refactor inlines or duplicates
    the logic, the cycle-3 byte-stability invariant is at risk; this
    structural assertion fails before the data-level test would.
    """
    import inspect

    from ainemo.core.pipeline import TranslationPipeline

    src = inspect.getsource(TranslationPipeline._build_system_prompt_addendum)
    assert "build_glossary_block(" in src, (
        "TranslationPipeline._build_system_prompt_addendum must call "
        "build_glossary_block; the cycle-3 byte-stability invariant "
        "depends on the shared builder."
    )
