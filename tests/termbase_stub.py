# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""In-process :class:`Termbase` test double.

Shared across cycle-3 unit tests so the importer (S2), exporter
(S3), and any future Termbase consumer can be exercised without
spinning up the on-disk Kuzu backend. The Kuzu round-trip is
covered separately by integration tests (e.g.
``test_importer_into_kuzu_round_trip``,
``test_tbx_roundtrip``).

Implements the full :class:`Termbase` Protocol surface so
``isinstance(stub, Termbase)`` passes — the
``runtime_checkable`` Protocol verifies method existence by
attribute lookup.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from ainemo.core.termbase.base import (
    Concept,
    ConceptEntry,
    ConceptHit,
    Domain,
    Persona,
    Term,
    TermbaseStats,
)


class RecordingTermbase:
    """Records every call; exposes mutator state as plain attributes
    so tests can assert exactly what was written."""

    def __init__(self) -> None:
        self.concepts: dict[str, Concept] = {}
        self.terms_by_concept: dict[str, list[Term]] = {}
        self.domains: dict[str, Domain] = {}
        self.concept_to_domains: dict[str, list[str]] = {}
        self.personas: dict[str, Persona] = {}

    # --- Termbase Protocol — write side ---

    def add_concept(self, concept: Concept, terms: Sequence[Term]) -> None:
        # Validate-before-write atomicity contract (matches the cycle-3
        # S1 KuzuTermbase fix). Mismatched term concept_ids must
        # raise without mutating state.
        for term in terms:
            if term.concept_id != concept.concept_id:
                raise ValueError(
                    f"Term {term.term_id!r} has concept_id={term.concept_id!r} "
                    f"but is being added under concept {concept.concept_id!r}"
                )
        self.concepts[concept.concept_id] = concept
        existing = {t.term_id: t for t in self.terms_by_concept.get(concept.concept_id, [])}
        for term in terms:
            existing[term.term_id] = term
        self.terms_by_concept[concept.concept_id] = list(existing.values())

    def add_domain(self, domain: Domain) -> None:
        self.domains[domain.domain_id] = domain

    def attach_concept_to_domain(self, concept_id: str, domain_id: str) -> None:
        attached = self.concept_to_domains.setdefault(concept_id, [])
        if domain_id not in attached:
            attached.append(domain_id)

    def add_persona(self, persona: Persona) -> None:
        self.personas[persona.persona_id] = persona

    # --- Termbase Protocol — read side ---

    def get_persona(self, persona_id: str) -> Persona | None:
        return self.personas.get(persona_id)

    def list_personas(self) -> tuple[Persona, ...]:
        return tuple(self.personas[pid] for pid in sorted(self.personas))

    def lookup_concepts_for(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
        domain_id: str | None = None,
        max_hits: int = 16,
    ) -> tuple[ConceptHit, ...]:
        # Not exercised by the importer / exporter cycle-3 tests; the
        # KuzuTermbase tests cover this surface end-to-end.
        return ()

    def stats(self) -> TermbaseStats:
        return TermbaseStats(
            concept_count=len(self.concepts),
            term_count_by_lang=(),
            domain_count=len(self.domains),
            persona_count=len(self.personas),
        )

    def iter_concept_entries(self, domain_id: str | None = None) -> Iterator[ConceptEntry]:
        for cid in sorted(self.concepts):
            if domain_id is not None and domain_id not in self.concept_to_domains.get(cid, []):
                continue
            terms = sorted(
                self.terms_by_concept.get(cid, []),
                key=lambda t: (t.lang, t.surface, t.term_id),
            )
            domain_ids = tuple(sorted(self.concept_to_domains.get(cid, [])))
            yield ConceptEntry(
                concept=self.concepts[cid],
                terms=tuple(terms),
                domain_ids=domain_ids,
            )

    # --- Test-only helper ---

    def all_terms(self) -> list[Term]:
        return [t for terms in self.terms_by_concept.values() for t in terms]


__all__ = ["RecordingTermbase"]
