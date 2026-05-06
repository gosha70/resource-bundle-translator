# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Termbase Protocol + entity dataclasses.

The Protocol is the only thing :mod:`ainemo.core` consumers (cycle-3
S6 pipeline integration; cycle-4 domain packs; cycle-5 reviewer UI)
import. Concrete backends live in their own subpackages and import
their drivers (cycle 3 ships :mod:`ainemo.core.termbase.kuzu` only;
cycle 5+ may add an in-memory :class:`MemoryTermbase` test double, or
a remote-API-backed alternative).

Entity model rationale (per pitch § Solution shape):

- :class:`Concept` is the language-neutral anchor — one identity per
  meaning. ``qid`` (Wikidata) is nullable in cycle 3; cycle-4's
  ``legal-en`` pack populates it.
- :class:`Term` is a surface form of a concept in a single language.
  A concept has many terms; a term belongs to exactly one concept.
- :class:`Domain` is the optional taxonomy that scopes which concepts
  apply where (``software-ui`` vs ``legal``); modeled as a tree via
  ``parent_id``.
- :class:`Persona` is the configuration record that selects which
  concepts/terms to inject as prompt context for which provider call
  — ``forbidden_terms`` is the existing cycle-1
  :class:`~ainemo.core.validators.forbidden.ForbiddenTermsValidator`
  surface, lifted into the persona so domain packs can author it.
- :class:`ConceptHit` is what ``lookup_concepts_for`` returns to the
  cycle-3 S6 pipeline so it can build a glossary block for the
  provider system prompt.
- :class:`TermbaseStats` mirrors the cycle-1
  :class:`~ainemo.core.tm.base.TmStats` shape — ``nemo termbase
  stats`` (cycle-3 S5) reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class Concept:
    """Language-neutral anchor for a set of synonymous terms.

    ``concept_id`` is a stable UUID4 string assigned by whoever
    creates the concept (TBX importer, TM-promotion CLI, domain pack,
    or the reviewer UI). ``qid`` is the Wikidata anchor (e.g.
    ``"Q11460"`` for *clothing*) and stays nullable in cycle 3 —
    cycle-4 domain packs populate it.
    """

    concept_id: str
    qid: str | None
    definition: str | None
    created_at: int
    """Epoch seconds. Same shape as cycle-1 ``Segment.created_at``."""


@dataclass(frozen=True)
class Term:
    """A surface form of a :class:`Concept` in a single language.

    ``register`` and ``part_of_speech`` are nullable in cycle 3 —
    Weblate exports rarely populate them, so requiring them would
    block import. ``source`` is one of the
    ``TERM_SOURCE_*`` constants in :mod:`ainemo.core.termbase._ids`.
    """

    term_id: str
    concept_id: str
    lang: str
    """BCP-47 tag — same shape as ``Segment.source_lang``."""

    surface: str
    register: str | None
    part_of_speech: str | None
    source: str


@dataclass(frozen=True)
class Domain:
    """Optional taxonomy node. Modeled as a tree via ``parent_id``.

    Domains are not required for cycle-3 termbase use; they exist so
    the cycle-4 ``legal-en`` pack and the cycle-5 reviewer UI can
    scope concept lookups to a relevant subtree.
    """

    domain_id: str
    parent_id: str | None
    name: str


@dataclass(frozen=True)
class GlossaryOverride:
    """A persona-level override that wins over termbase lookup.

    Authored by a domain pack or a project-specific persona to force a
    specific target rendering for a given source surface, regardless
    of what the termbase would otherwise return. Cycle-3 S6 consults
    these before calling
    :meth:`Termbase.lookup_concepts_for`.
    """

    source_term: str
    target_lang: str
    target_term: str


@dataclass(frozen=True)
class Persona:
    """Configuration record for prompt-injection + forbidden-term gating.

    Q2 from the pitch (resolved at /bet, 2026-05-05): four mandatory
    fields (``persona_id``, ``name``, ``forbidden_terms``,
    ``prompt_addendum``) plus four optional fields. The fifth
    proposed-but-dropped optional field — ``provider_hints`` — is
    intentionally absent; persona-aware routing lives in cycle-2's
    :class:`~ainemo.providers.router.RoutingConfig`
    ``persona``/``domain`` matchers, not duplicated on the persona.
    """

    persona_id: str
    """Filename stem of the persona's YAML file (cycle-3 S4)."""

    name: str
    forbidden_terms: tuple[str, ...]
    """Strings the
    :class:`~ainemo.core.validators.forbidden.ForbiddenTermsValidator`
    rejects on output. Cycle-1 took a tuple via the CLI's repeatable
    ``--forbidden-term`` flag; cycle-3 lifts the source of truth into
    the persona (see pitch open question 4)."""

    prompt_addendum: str
    """Free-text block appended to the provider system prompt.
    ``temperature=0`` is preserved across all providers (AGENTS.md
    § Architecture Rules: *Reproducibility by default*)."""

    domain_id: str | None = None
    register: str | None = None
    """One of ``"formal"`` | ``"casual"`` | ``"neutral"`` | ``None``."""

    style_guide_url: str | None = None
    glossary_overrides: tuple[GlossaryOverride, ...] = ()


@dataclass(frozen=True)
class ConceptHit:
    """One match returned by :meth:`Termbase.lookup_concepts_for`."""

    concept: Concept
    matched_source_term: Term
    """The :class:`Term` in ``source_lang`` that matched
    ``source_text``. Cycle-3 uses literal n-gram match; cycle-4+ may
    swap in embedding similarity per the pitch rabbit-hole rule
    (*Don't introduce vector embeddings for term lookup yet*)."""

    target_terms: tuple[Term, ...]
    """All :class:`Term` rows in ``target_lang`` for ``concept``.
    Empty when the concept has no term in the requested target — the
    pipeline (S6) skips zero-target hits when building the glossary
    block but the lookup still surfaces them so the reviewer UI
    (cycle 5) can flag missing-target-term opportunities."""

    relevance: float
    """0..1. Cycle-3 v1: ``len(matched_source_term.surface) /
    len(source_text)`` — a coarse n-gram overlap proxy. The
    Protocol does not pin the exact formula; consumers treat it
    as a sortable score."""


@dataclass(frozen=True)
class TermbaseStats:
    """Aggregate counts surfaced by ``nemo termbase stats`` (S5)."""

    concept_count: int
    term_count_by_lang: tuple[tuple[str, int], ...]
    """``((lang, count), ...)`` sorted by ``lang`` ascending so output
    is deterministic across runs."""

    domain_count: int
    persona_count: int


@runtime_checkable
class Termbase(Protocol):
    """Concept-oriented terminology store.

    Cycle-3 ships :class:`~ainemo.core.termbase.kuzu.store.KuzuTermbase`
    as the only concrete implementation; the Protocol exists so cycle-4
    domain packs and cycle-5 reviewer UI consume the surface, not the
    Kuzu API directly. Mirrors the BundleAdapter / Provider /
    TranslationMemory / Validator protocol-first conventions in
    AGENTS.md § Architecture Rules.
    """

    def lookup_concepts_for(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
        domain_id: str | None = None,
        max_hits: int = 16,
    ) -> tuple[ConceptHit, ...]:
        """Return concepts whose ``source_lang`` term appears in
        ``source_text``, ranked by relevance descending.

        ``domain_id`` (when supplied) restricts the search to concepts
        ``IN_DOMAIN`` that domain. ``max_hits`` caps the result size
        — cycle-3 S6 pipeline injects the top-K into the provider
        system prompt and 16 is enough headroom that the prompt budget
        becomes the binding constraint, not this cap.
        """
        ...

    def add_concept(self, concept: Concept, terms: Sequence[Term]) -> None:
        """Insert or update a concept and its terms.

        Idempotent on ``concept_id`` and ``term_id`` — re-adding the
        same concept refreshes the row but does not duplicate. The
        relationship ``(concept)-[:HAS_TERM]->(term)`` is created for
        every term in ``terms``.
        """
        ...

    def add_domain(self, domain: Domain) -> None:
        """Insert or update a domain. Idempotent on ``domain_id``."""
        ...

    def attach_concept_to_domain(self, concept_id: str, domain_id: str) -> None:
        """Idempotent ``(concept)-[:IN_DOMAIN]->(domain)`` edge.

        Cycle-3 S2 (TBX importer) calls this for each
        ``<descrip type="domain">`` it encounters on a ``<conceptEntry>``;
        a concept may be attached to multiple domains. The cycle-1+2
        ``add_concept`` / ``add_domain`` Protocol surface deliberately
        kept the edge concern out — this is the third Protocol method
        that touches the (concept, domain) relation, so it lifts here
        rather than living only on
        :class:`~ainemo.core.termbase.kuzu.store.KuzuTermbase`.
        """
        ...

    def add_persona(self, persona: Persona) -> None:
        """Insert or update a persona. Idempotent on ``persona_id``.

        Cycle-3 S4's persona YAML loader calls this once per file on
        first start — duplicate loads are no-ops.
        """
        ...

    def get_persona(self, persona_id: str) -> Persona | None:
        """Return the persona for ``persona_id``, or ``None``."""
        ...

    def list_personas(self) -> tuple[Persona, ...]:
        """All personas, sorted by ``persona_id`` ascending."""
        ...

    def stats(self) -> TermbaseStats:
        """Aggregate counts. Used by ``nemo termbase stats`` (S5)."""
        ...


__all__ = [
    "Concept",
    "Term",
    "Domain",
    "GlossaryOverride",
    "Persona",
    "ConceptHit",
    "TermbaseStats",
    "Termbase",
]
