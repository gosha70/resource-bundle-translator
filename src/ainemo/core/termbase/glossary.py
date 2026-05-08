# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Persona-aware glossary-block builder — cycle-5 S6.

Extracted from :meth:`TranslationPipeline._build_system_prompt_addendum`
so both the pipeline and the cycle-5 persona inspector UI share one
implementation.  Byte-equivalence with the pipeline's previous private
method is the headline contract: the cycle-3 S6 pipeline integration
test (``test_pipeline_with_termbase.py``) asserts the pipeline's
``system_prompt_addendum`` content and must pass byte-stable after the
extraction.

The pipeline refactored its private method to delegate here; the UI's
``/personas/<persona_id>/preview-hits`` route calls here directly.
"""

from __future__ import annotations

from typing import Final

from ainemo.core.termbase.base import ConceptHit, Persona, Termbase

_GLOSSARY_HEADER: Final = "Glossary (apply to the segment if relevant):"


def format_glossary_block(hits: tuple[ConceptHit, ...], target_lang: str) -> str | None:
    """Format :class:`ConceptHit` rows into a system-prompt glossary block.

    Returns ``None`` when there are no hits or no hit has a target-lang
    term — an empty block is worse than no block (it tells the model a
    glossary applies and then provides nothing). Hits with no
    target-lang term are skipped silently.

    Format::

        Glossary (apply to the segment if relevant):
        - "login" → "Anmeldung"
        - "logout" → "Abmeldung"

    Each entry uses the matched source term and the *first* available
    target-lang term — the termbase Protocol contract sorts terms by
    ``(lang, surface, term_id)`` so the choice is deterministic.
    """
    lines: list[str] = []
    for hit in hits:
        if not hit.target_terms:
            continue
        target_surface = hit.target_terms[0].surface
        source_surface = hit.matched_source_term.surface
        lines.append(f'- "{source_surface}" → "{target_surface}"')
    if not lines:
        return None
    return "\n".join([_GLOSSARY_HEADER, *lines])


def build_glossary_block(
    termbase: Termbase | None,
    persona: Persona | None,
    *,
    source_text: str,
    source_lang: str,
    target_lang: str,
) -> str | None:
    """Compose persona prompt addendum + termbase glossary block.

    Identical semantics to the cycle-3 pipeline-private method
    ``_build_system_prompt_addendum``; extracted here so the pipeline
    AND the cycle-5 reviewer UI share one builder.

    - Returns ``None`` when both *termbase* and *persona* are ``None``.
    - Concatenates ``persona.prompt_addendum`` (when non-blank) + the
      glossary block of ``termbase.lookup_concepts_for(...)`` hits
      filtered by ``persona.domain_id`` (when persona is set).
    - Sections joined with ``"\\n\\n"``.
    - Empty result (no addendum, no glossary hits) returns ``None``.

    Byte-equivalence guarantee
    --------------------------
    The cycle-3 S6 pipeline integration test asserts exact string values
    produced from known fixtures.  Any change to the output format here
    **must** keep that test green; failing it is a contract violation.
    """
    if termbase is None and persona is None:
        return None

    sections: list[str] = []

    if persona is not None and persona.prompt_addendum.strip():
        sections.append(persona.prompt_addendum.strip())

    if termbase is not None:
        domain_id = persona.domain_id if persona is not None else None
        hits = termbase.lookup_concepts_for(
            source_text,
            source_lang,
            target_lang,
            domain_id=domain_id,
        )
        block = format_glossary_block(hits, target_lang)
        if block:
            sections.append(block)

    if not sections:
        return None

    return "\n\n".join(sections)


__all__ = [
    "build_glossary_block",
    "format_glossary_block",
    "_GLOSSARY_HEADER",
]
