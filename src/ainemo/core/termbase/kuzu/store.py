# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Kuzu-backed :class:`~ainemo.core.termbase.base.Termbase`.

Cycle-3 S1 — schema bootstrap (idempotent), CRUD for concepts /
terms / domains / personas, and ``lookup_concepts_for`` via literal
n-gram match.

Design choices
--------------

- **Directory-shaped DB.** Kuzu is an embedded graph database whose
  on-disk format is a directory, not a single file. Default location
  is ``./.ainemo/termbase.kuzu/`` (the trailing slash is implicit;
  Kuzu manages the directory contents). Excluded from git via the
  existing ``.ainemo/`` ``.gitignore`` line.
- **``CREATE ... IF NOT EXISTS`` everywhere.** Schema bootstrap is
  idempotent: opening the same database twice in a row creates the
  database the first time and is a no-op the second.
- **``MERGE`` for upserts.** ``add_concept`` / ``add_domain`` /
  ``add_persona`` use Kuzu ``MERGE`` so re-adding the same entity
  refreshes properties without duplicating the row. Mirrors the
  cycle-1 SQLite TM's ``INSERT OR REPLACE`` idempotency contract.
- **JSON-encoded list properties.** Kuzu's typed columns work fine
  for scalars; ``forbidden_terms`` and ``glossary_overrides`` are
  encoded as JSON strings on the ``Persona`` node. Cheap, portable,
  and avoids mapping nested ``LIST`` types whose API surface differs
  across Kuzu minor versions.
- **Literal n-gram match.** ``lookup_concepts_for`` walks every term
  in ``source_lang`` (optionally narrowed to a domain), case-folds
  surface + source-text, and looks for whitespace-bounded substring
  hits. Per-pitch rabbit-hole rule: *Don't introduce vector
  embeddings for term lookup yet*. Linear scan is fine up to the
  cycle-3 benchmark target (5k concepts, p95 < 25 ms).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, Iterator, Sequence

import kuzu

from ainemo.core.termbase._ids import (
    NODE_LABEL_CONCEPT,
    NODE_LABEL_DOMAIN,
    NODE_LABEL_PERSONA,
    NODE_LABEL_SEGMENT,
    NODE_LABEL_TERM,
    REL_DERIVED_FROM_SEGMENT,
    REL_HAS_TERM,
    REL_IN_DOMAIN,
)
from ainemo.core.termbase.base import (
    _UNSET,
    Concept,
    ConceptEntry,
    ConceptHit,
    Domain,
    GlossaryOverride,
    Persona,
    Term,
    TermbaseStats,
    _UnsetType,
)

# Whitespace + punctuation chars that bound an n-gram. Used by
# `_word_bounded_contains` so a term "log" doesn't match "logout"
# but does match "please log in".
_WORD_BOUNDARIES: Final = " \t\n\r.,;:!?\"'()[]{}<>/\\|*+-_="

_DEFAULT_MAX_HITS: Final = 16


class TermbaseLockedError(RuntimeError):
    """Raised when Kuzu's single-writer lock blocks termbase construction.

    Cycle-5 cooldown polish: Kuzu surfaces a generic ``RuntimeError``
    ("Could not set lock on file") when another process already holds
    the termbase. The reviewer app (``nemo app run``) is the most
    common lock-holder; this wrapper names that explicitly so the
    operator doesn't have to read Kuzu's concurrency docs to diagnose.
    """


class KuzuTermbase:
    """Concrete Kuzu-backed :class:`~ainemo.core.termbase.base.Termbase`.

    See module docstring for design notes. Implements the full
    Protocol surface; instances are not thread-safe (Kuzu's connection
    object is single-threaded — wrap with a lock at the caller if
    cross-thread access is needed; cycle-3 S6 pipeline is
    single-threaded).
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Kuzu Database accepts str; the type stubs (when present)
        # may type the arg loosely so we coerce explicitly.
        self._path = path
        try:
            self._db = kuzu.Database(str(path))
        except RuntimeError as exc:
            # Cycle-5 cooldown polish: Kuzu raises a generic RuntimeError
            # ("Could not set lock on file") when another process already
            # holds the termbase's single-writer lock — most commonly the
            # `nemo app run` reviewer app from a separate terminal. Wrap
            # with an operator-friendly hint so the user doesn't have to
            # read https://docs.kuzudb.com/concurrency to diagnose.
            if "Could not set lock" in str(exc) or "lock" in str(exc).lower():
                raise TermbaseLockedError(
                    f"Termbase at {path} is locked by another process. "
                    f"If `nemo app run` is running in another terminal, "
                    f"stop it first (Kuzu allows one writer at a time). "
                    f"Original error: {exc}"
                ) from exc
            raise
        self._conn = kuzu.Connection(self._db)
        self._init_schema()

    def close(self) -> None:
        # Kuzu releases resources when the Connection / Database are
        # GC'd; explicit close is provided so tests can drop refs
        # deterministically before tmpdir cleanup on Windows.
        self._conn = None  # type: ignore[assignment]
        self._db = None  # type: ignore[assignment]

    # --- Termbase Protocol ---

    def lookup_concepts_for(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
        domain_id: str | None = None,
        max_hits: int = _DEFAULT_MAX_HITS,
    ) -> tuple[ConceptHit, ...]:
        if not source_text or max_hits <= 0:
            return ()
        candidates = self._fetch_source_terms(source_lang, domain_id)
        if not candidates:
            return ()
        source_lower = source_text.lower()
        source_len = len(source_text)
        scored: list[tuple[float, Term]] = []
        for term in candidates:
            surface_lower = term.surface.lower()
            if not surface_lower:
                continue
            if not _word_bounded_contains(source_lower, surface_lower):
                continue
            relevance = min(1.0, len(term.surface) / max(source_len, 1))
            scored.append((relevance, term))
        if not scored:
            return ()
        scored.sort(key=lambda item: (-item[0], item[1].term_id))
        scored = scored[:max_hits]
        # Group by concept; one ConceptHit per concept, with the
        # highest-relevance source-term as the matched_source_term.
        seen: dict[str, ConceptHit] = {}
        for relevance, term in scored:
            if term.concept_id in seen:
                continue
            concept = self._get_concept(term.concept_id)
            if concept is None:
                continue
            target_terms = self._fetch_terms_for_concept(term.concept_id, target_lang)
            seen[term.concept_id] = ConceptHit(
                concept=concept,
                matched_source_term=term,
                target_terms=target_terms,
                relevance=relevance,
            )
        return tuple(seen.values())

    def add_concept(self, concept: Concept, terms: Sequence[Term]) -> None:
        # Validate every term *before* the first Kuzu write so a
        # mismatched-concept_id term doesn't leave an orphan concept
        # row behind. Kuzu's Python driver does not expose multi-
        # statement transactions in the embedded API, so atomicity has
        # to come from input validation rather than rollback.
        for term in terms:
            if term.concept_id != concept.concept_id:
                raise ValueError(
                    f"Term {term.term_id!r} has concept_id={term.concept_id!r} "
                    f"but is being added under concept {concept.concept_id!r}"
                )
        self._conn.execute(
            f"MERGE (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}}) "
            "ON CREATE SET c.qid = $qid, c.definition = $defn, "
            "              c.created_at = $ts "
            "ON MATCH  SET c.qid = $qid, c.definition = $defn, "
            "              c.created_at = $ts",
            {
                "cid": concept.concept_id,
                "qid": concept.qid,
                "defn": concept.definition,
                "ts": int(concept.created_at),
            },
        )
        for term in terms:
            self._upsert_term(term)

    def add_domain(self, domain: Domain) -> None:
        self._conn.execute(
            f"MERGE (d:{NODE_LABEL_DOMAIN} {{domain_id: $did}}) "
            "ON CREATE SET d.parent_id = $pid, d.name = $name "
            "ON MATCH  SET d.parent_id = $pid, d.name = $name",
            {
                "did": domain.domain_id,
                "pid": domain.parent_id,
                "name": domain.name,
            },
        )

    def add_persona(self, persona: Persona) -> None:
        forbidden_json = json.dumps(list(persona.forbidden_terms))
        overrides_json = json.dumps(
            [
                {
                    "source_term": override.source_term,
                    "target_lang": override.target_lang,
                    "target_term": override.target_term,
                }
                for override in persona.glossary_overrides
            ]
        )
        self._conn.execute(
            f"MERGE (p:{NODE_LABEL_PERSONA} {{persona_id: $pid}}) "
            "ON CREATE SET p.domain_id = $did, p.name = $name, "
            "              p.register = $reg, "
            "              p.forbidden_terms_json = $fbt, "
            "              p.prompt_addendum = $addendum, "
            "              p.style_guide_url = $sgu, "
            "              p.glossary_overrides_json = $ovr "
            "ON MATCH  SET p.domain_id = $did, p.name = $name, "
            "              p.register = $reg, "
            "              p.forbidden_terms_json = $fbt, "
            "              p.prompt_addendum = $addendum, "
            "              p.style_guide_url = $sgu, "
            "              p.glossary_overrides_json = $ovr",
            {
                "pid": persona.persona_id,
                "did": persona.domain_id,
                "name": persona.name,
                "reg": persona.register,
                "fbt": forbidden_json,
                "addendum": persona.prompt_addendum,
                "sgu": persona.style_guide_url,
                "ovr": overrides_json,
            },
        )

    def get_persona(self, persona_id: str) -> Persona | None:
        result = self._conn.execute(
            f"MATCH (p:{NODE_LABEL_PERSONA} {{persona_id: $pid}}) "
            "RETURN p.persona_id, p.domain_id, p.name, p.register, "
            "       p.forbidden_terms_json, p.prompt_addendum, "
            "       p.style_guide_url, p.glossary_overrides_json",
            {"pid": persona_id},
        )
        row = _next_row(result)
        if row is None:
            return None
        return _row_to_persona(row)

    def list_personas(self) -> tuple[Persona, ...]:
        result = self._conn.execute(
            f"MATCH (p:{NODE_LABEL_PERSONA}) "
            "RETURN p.persona_id, p.domain_id, p.name, p.register, "
            "       p.forbidden_terms_json, p.prompt_addendum, "
            "       p.style_guide_url, p.glossary_overrides_json "
            "ORDER BY p.persona_id"
        )
        personas: list[Persona] = []
        for row in _all_rows(result):
            personas.append(_row_to_persona(row))
        return tuple(personas)

    def stats(self) -> TermbaseStats:
        concept_count = _scalar_int(
            self._conn.execute(f"MATCH (c:{NODE_LABEL_CONCEPT}) RETURN COUNT(c)")
        )
        domain_count = _scalar_int(
            self._conn.execute(f"MATCH (d:{NODE_LABEL_DOMAIN}) RETURN COUNT(d)")
        )
        persona_count = _scalar_int(
            self._conn.execute(f"MATCH (p:{NODE_LABEL_PERSONA}) RETURN COUNT(p)")
        )
        result = self._conn.execute(
            f"MATCH (t:{NODE_LABEL_TERM}) RETURN t.lang, COUNT(t) ORDER BY t.lang"
        )
        per_lang: list[tuple[str, int]] = []
        for row in _all_rows(result):
            per_lang.append((str(row[0]), int(row[1])))
        return TermbaseStats(
            concept_count=concept_count,
            term_count_by_lang=tuple(per_lang),
            domain_count=domain_count,
            persona_count=persona_count,
        )

    def iter_concept_entries(self, domain_id: str | None = None) -> Iterator[ConceptEntry]:
        # Cycle-3 S3 (TBX exporter) is the first consumer. Yields in
        # `concept_id` ascending order so re-export is byte-stable
        # (canonical-XML round-trip is a hard contract). Implementation:
        # one MATCH per concept fetches concept row + terms + domain
        # ids; in-memory sorts keep the SQL simple at cycle-3 scale
        # (5k concepts upper bound per pitch § Test strategy).
        if domain_id is None:
            concept_rows = _all_rows(
                self._conn.execute(
                    f"MATCH (c:{NODE_LABEL_CONCEPT}) "
                    "RETURN c.concept_id, c.qid, c.definition, c.created_at "
                    "ORDER BY c.concept_id"
                )
            )
        else:
            concept_rows = _all_rows(
                self._conn.execute(
                    f"MATCH (c:{NODE_LABEL_CONCEPT})"
                    f"-[:{REL_IN_DOMAIN}]->(d:{NODE_LABEL_DOMAIN} "
                    f"     {{domain_id: $did}}) "
                    "RETURN c.concept_id, c.qid, c.definition, c.created_at "
                    "ORDER BY c.concept_id",
                    {"did": domain_id},
                )
            )
        for row in concept_rows:
            concept = Concept(
                concept_id=str(row[0]),
                qid=None if row[1] is None else str(row[1]),
                definition=None if row[2] is None else str(row[2]),
                created_at=int(row[3]),
            )
            terms = self._fetch_all_terms_for_concept(concept.concept_id)
            domain_ids = self._fetch_domain_ids_for_concept(concept.concept_id)
            yield ConceptEntry(
                concept=concept,
                terms=terms,
                domain_ids=domain_ids,
            )

    def update_term(
        self,
        term_id: str,
        *,
        surface: str | _UnsetType = _UNSET,
        register: str | None | _UnsetType = _UNSET,
        part_of_speech: str | None | _UnsetType = _UNSET,
    ) -> bool:
        set_clauses: list[str] = []
        params: dict[str, Any] = {"tid": term_id}
        if not isinstance(surface, _UnsetType):
            if not surface.strip():
                raise ValueError("surface must be non-blank")
            set_clauses.append("t.surface = $surf")
            set_clauses.append("t.surface_lower = $surf_lower")
            params["surf"] = surface
            params["surf_lower"] = surface.lower()
        if not isinstance(register, _UnsetType):
            set_clauses.append("t.register = $reg")
            params["reg"] = register
        if not isinstance(part_of_speech, _UnsetType):
            set_clauses.append("t.part_of_speech = $pos")
            params["pos"] = part_of_speech

        if not set_clauses:
            result = self._conn.execute(
                f"MATCH (t:{NODE_LABEL_TERM} {{term_id: $tid}}) RETURN count(t)",
                params,
            )
            return _scalar_int(result) > 0

        result = self._conn.execute(
            f"MATCH (t:{NODE_LABEL_TERM} {{term_id: $tid}}) "
            f"SET {', '.join(set_clauses)} "
            "RETURN count(t)",
            params,
        )
        return _scalar_int(result) > 0

    # --- Convenience methods (not part of the Protocol but used by
    #     tests and by S6 pipeline integration; the Protocol surface
    #     intentionally stays narrow). ---

    def attach_concept_to_domain(self, concept_id: str, domain_id: str) -> None:
        """Idempotent ``(concept)-[:IN_DOMAIN]->(domain)`` edge."""
        self._conn.execute(
            f"MATCH (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}}), "
            f"      (d:{NODE_LABEL_DOMAIN}  {{domain_id:  $did}}) "
            f"MERGE (c)-[:{REL_IN_DOMAIN}]->(d)",
            {"cid": concept_id, "did": domain_id},
        )

    def attach_concept_to_segment(self, concept_id: str, fingerprint: str) -> None:
        """Idempotent ``(concept)-[:DERIVED_FROM_SEGMENT]->(segment)``.

        Auto-promotion (S5) calls this so the reviewer UI can audit
        which TM rows produced which concept. The Segment node is
        a stub here — the cycle-1 SQLite TM owns the real segment
        data; this graph just stores the fingerprint key.
        """
        self._conn.execute(
            f"MERGE (s:{NODE_LABEL_SEGMENT} {{fingerprint: $fp}})",
            {"fp": fingerprint},
        )
        self._conn.execute(
            f"MATCH (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}}), "
            f"      (s:{NODE_LABEL_SEGMENT} {{fingerprint: $fp}}) "
            f"MERGE (c)-[:{REL_DERIVED_FROM_SEGMENT}]->(s)",
            {"cid": concept_id, "fp": fingerprint},
        )

    # --- Internals ---

    def _init_schema(self) -> None:
        # Nodes
        self._conn.execute(
            f"CREATE NODE TABLE IF NOT EXISTS {NODE_LABEL_CONCEPT} ("
            "  concept_id STRING, "
            "  qid STRING, "
            "  definition STRING, "
            "  created_at INT64, "
            "  PRIMARY KEY (concept_id))"
        )
        self._conn.execute(
            f"CREATE NODE TABLE IF NOT EXISTS {NODE_LABEL_TERM} ("
            "  term_id STRING, "
            "  concept_id STRING, "
            "  lang STRING, "
            "  surface STRING, "
            "  surface_lower STRING, "
            "  register STRING, "
            "  part_of_speech STRING, "
            "  source STRING, "
            "  PRIMARY KEY (term_id))"
        )
        self._conn.execute(
            f"CREATE NODE TABLE IF NOT EXISTS {NODE_LABEL_DOMAIN} ("
            "  domain_id STRING, "
            "  parent_id STRING, "
            "  name STRING, "
            "  PRIMARY KEY (domain_id))"
        )
        self._conn.execute(
            f"CREATE NODE TABLE IF NOT EXISTS {NODE_LABEL_PERSONA} ("
            "  persona_id STRING, "
            "  domain_id STRING, "
            "  name STRING, "
            "  register STRING, "
            "  forbidden_terms_json STRING, "
            "  prompt_addendum STRING, "
            "  style_guide_url STRING, "
            "  glossary_overrides_json STRING, "
            "  PRIMARY KEY (persona_id))"
        )
        self._conn.execute(
            f"CREATE NODE TABLE IF NOT EXISTS {NODE_LABEL_SEGMENT} ("
            "  fingerprint STRING, "
            "  PRIMARY KEY (fingerprint))"
        )
        # Relationships
        self._conn.execute(
            f"CREATE REL TABLE IF NOT EXISTS {REL_HAS_TERM} "
            f"(FROM {NODE_LABEL_CONCEPT} TO {NODE_LABEL_TERM})"
        )
        self._conn.execute(
            f"CREATE REL TABLE IF NOT EXISTS {REL_IN_DOMAIN} "
            f"(FROM {NODE_LABEL_CONCEPT} TO {NODE_LABEL_DOMAIN})"
        )
        self._conn.execute(
            f"CREATE REL TABLE IF NOT EXISTS {REL_DERIVED_FROM_SEGMENT} "
            f"(FROM {NODE_LABEL_CONCEPT} TO {NODE_LABEL_SEGMENT})"
        )

    def _upsert_term(self, term: Term) -> None:
        self._conn.execute(
            f"MERGE (t:{NODE_LABEL_TERM} {{term_id: $tid}}) "
            "ON CREATE SET t.concept_id = $cid, t.lang = $lang, "
            "              t.surface = $surf, t.surface_lower = $surf_lower, "
            "              t.register = $reg, t.part_of_speech = $pos, "
            "              t.source = $src "
            "ON MATCH  SET t.concept_id = $cid, t.lang = $lang, "
            "              t.surface = $surf, t.surface_lower = $surf_lower, "
            "              t.register = $reg, t.part_of_speech = $pos, "
            "              t.source = $src",
            {
                "tid": term.term_id,
                "cid": term.concept_id,
                "lang": term.lang,
                "surf": term.surface,
                "surf_lower": term.surface.lower(),
                "reg": term.register,
                "pos": term.part_of_speech,
                "src": term.source,
            },
        )
        self._conn.execute(
            f"MATCH (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}}), "
            f"      (t:{NODE_LABEL_TERM}    {{term_id:    $tid}}) "
            f"MERGE (c)-[:{REL_HAS_TERM}]->(t)",
            {"cid": term.concept_id, "tid": term.term_id},
        )

    def _get_concept(self, concept_id: str) -> Concept | None:
        result = self._conn.execute(
            f"MATCH (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}}) "
            "RETURN c.concept_id, c.qid, c.definition, c.created_at",
            {"cid": concept_id},
        )
        row = _next_row(result)
        if row is None:
            return None
        return Concept(
            concept_id=str(row[0]),
            qid=None if row[1] is None else str(row[1]),
            definition=None if row[2] is None else str(row[2]),
            created_at=int(row[3]),
        )

    def _fetch_source_terms(self, source_lang: str, domain_id: str | None) -> tuple[Term, ...]:
        if domain_id is None:
            result = self._conn.execute(
                f"MATCH (c:{NODE_LABEL_CONCEPT})-[:{REL_HAS_TERM}]->(t:{NODE_LABEL_TERM}) "
                "WHERE t.lang = $lang "
                "RETURN t.term_id, t.concept_id, t.lang, t.surface, "
                "       t.register, t.part_of_speech, t.source",
                {"lang": source_lang},
            )
        else:
            result = self._conn.execute(
                f"MATCH (c:{NODE_LABEL_CONCEPT})-[:{REL_HAS_TERM}]->(t:{NODE_LABEL_TERM}), "
                f"      (c)-[:{REL_IN_DOMAIN}]->(d:{NODE_LABEL_DOMAIN} "
                f"            {{domain_id: $did}}) "
                "WHERE t.lang = $lang "
                "RETURN t.term_id, t.concept_id, t.lang, t.surface, "
                "       t.register, t.part_of_speech, t.source",
                {"lang": source_lang, "did": domain_id},
            )
        return tuple(_row_to_term(row) for row in _all_rows(result))

    def _fetch_terms_for_concept(self, concept_id: str, lang: str) -> tuple[Term, ...]:
        result = self._conn.execute(
            f"MATCH (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}})"
            f"-[:{REL_HAS_TERM}]->(t:{NODE_LABEL_TERM}) "
            "WHERE t.lang = $lang "
            "RETURN t.term_id, t.concept_id, t.lang, t.surface, "
            "       t.register, t.part_of_speech, t.source "
            "ORDER BY t.term_id",
            {"cid": concept_id, "lang": lang},
        )
        return tuple(_row_to_term(row) for row in _all_rows(result))

    def _fetch_all_terms_for_concept(self, concept_id: str) -> tuple[Term, ...]:
        # Used by iter_concept_entries — returns all terms for a
        # concept across every language, sorted (lang, surface,
        # term_id) ascending so the TBX exporter's <langSec> /
        # <termSec> output is byte-stable across runs.
        result = self._conn.execute(
            f"MATCH (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}})"
            f"-[:{REL_HAS_TERM}]->(t:{NODE_LABEL_TERM}) "
            "RETURN t.term_id, t.concept_id, t.lang, t.surface, "
            "       t.register, t.part_of_speech, t.source "
            "ORDER BY t.lang, t.surface, t.term_id",
            {"cid": concept_id},
        )
        return tuple(_row_to_term(row) for row in _all_rows(result))

    def _fetch_domain_ids_for_concept(self, concept_id: str) -> tuple[str, ...]:
        result = self._conn.execute(
            f"MATCH (c:{NODE_LABEL_CONCEPT} {{concept_id: $cid}})"
            f"-[:{REL_IN_DOMAIN}]->(d:{NODE_LABEL_DOMAIN}) "
            "RETURN d.domain_id ORDER BY d.domain_id",
            {"cid": concept_id},
        )
        return tuple(str(row[0]) for row in _all_rows(result))


# --- Module-level helpers ---


def _word_bounded_contains(haystack: str, needle: str) -> bool:
    """Case-folded, whitespace/punctuation-bounded substring check.

    Both inputs are expected to already be lowercased. A bare
    ``str.__contains__`` would match ``"log"`` inside ``"logout"``,
    inflating recall. We require the surrounding characters in
    ``haystack`` to be word boundaries (or string edges) so n-gram
    matches are word-level, not character-level.
    """
    if not needle:
        return False
    start = 0
    haystack_len = len(haystack)
    needle_len = len(needle)
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            return False
        before_ok = idx == 0 or haystack[idx - 1] in _WORD_BOUNDARIES
        end = idx + needle_len
        after_ok = end == haystack_len or haystack[end] in _WORD_BOUNDARIES
        if before_ok and after_ok:
            return True
        start = idx + 1


def _row_to_term(row: list[Any]) -> Term:
    return Term(
        term_id=str(row[0]),
        concept_id=str(row[1]),
        lang=str(row[2]),
        surface=str(row[3]),
        register=None if row[4] is None else str(row[4]),
        part_of_speech=None if row[5] is None else str(row[5]),
        source=str(row[6]),
    )


def _row_to_persona(row: list[Any]) -> Persona:
    forbidden_terms_raw = row[4]
    overrides_raw = row[7]
    forbidden_terms = (
        tuple(json.loads(forbidden_terms_raw)) if forbidden_terms_raw is not None else ()
    )
    overrides_list: list[GlossaryOverride] = []
    if overrides_raw is not None:
        for entry in json.loads(overrides_raw):
            overrides_list.append(
                GlossaryOverride(
                    source_term=str(entry["source_term"]),
                    target_lang=str(entry["target_lang"]),
                    target_term=str(entry["target_term"]),
                )
            )
    return Persona(
        persona_id=str(row[0]),
        name=str(row[2]),
        forbidden_terms=forbidden_terms,
        prompt_addendum=str(row[5]) if row[5] is not None else "",
        domain_id=None if row[1] is None else str(row[1]),
        register=None if row[3] is None else str(row[3]),
        style_guide_url=None if row[6] is None else str(row[6]),
        glossary_overrides=tuple(overrides_list),
    )


def _next_row(result: Any) -> list[Any] | None:
    if not result.has_next():
        return None
    raw = result.get_next()
    return list(raw)


def _all_rows(result: Any) -> list[list[Any]]:
    rows: list[list[Any]] = []
    while result.has_next():
        rows.append(list(result.get_next()))
    return rows


def _scalar_int(result: Any) -> int:
    row = _next_row(result)
    if row is None:
        return 0
    return int(row[0])


def make_default_termbase(path: Path | None = None) -> KuzuTermbase:
    """Convenience constructor used by S5 CLI + S6 pipeline.

    Defaults the path to :data:`DEFAULT_TERMBASE_PATH` if ``None``.
    Kept here (not in S4/S5/S6) so the cycle-3 S1 surface is
    self-contained for testing.
    """
    from ainemo.core.termbase._ids import DEFAULT_TERMBASE_PATH

    return KuzuTermbase(path or Path(DEFAULT_TERMBASE_PATH))


__all__ = ["KuzuTermbase", "TermbaseLockedError", "make_default_termbase"]
