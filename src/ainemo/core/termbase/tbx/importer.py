# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""TBX 3.0 (ISO 30042) importer.

Cycle-3 S2 — reads a Weblate-style TBX export and writes its
``<conceptEntry>`` rows into a :class:`~ainemo.core.termbase.base.Termbase`.

Documented subset (per pitch § Solution shape and § Open questions Q6):

================================  ==================================
Element                           Maps to
================================  ==================================
``<conceptEntry id="...">``       :class:`Concept` (id preserved)
``<descrip type="domain">``       :class:`Domain` + IN_DOMAIN edge
``<langSec xml:lang="...">``      Language scope for child terms
``<termSec>``                     :class:`Term` (one per termSec)
``<term>``                        ``Term.surface``
``<termNote type="partOfSpeech">``  ``Term.part_of_speech``
``<termNote type="register">``    ``Term.register``
``<definition>``                  ``Concept.definition`` (first
                                  source-lang definition wins)
================================  ==================================

Anything else inside a ``<conceptEntry>`` is recorded in
:class:`TbxImportReport.skipped_unsupported` as ``"name @ xpath"``,
where ``xpath`` is a 1-indexed positional path so the cycle-3
retro can locate the element in the source file.

Design choices
--------------

- **lxml only.** Already a project dep (XLIFF adapter). The
  ``etree.iterparse`` streaming API is overkill for the cycle-3
  appetite; ``etree.parse`` materializes the whole tree, which is
  fine for the largest realistic Weblate export (≪10 MB).
- **Protocol-only writes.** The importer takes a
  :class:`Termbase`, not a :class:`KuzuTermbase`. Cycle-5's
  ``MemoryTermbase`` test double will work transparently.
- **Source language = root ``@xml:lang``** (TBX 3.0 convention).
  ``Concept.definition`` is the first ``<definition>`` found in
  the source-lang ``<langSec>``; non-source-lang definitions are
  ignored on import (the field is single-valued on
  :class:`Concept`). Definitions in *other* langSec entries do
  not land in ``skipped_unsupported`` — they're a documented
  element, just not used for ``Concept.definition``.
- **Empty/whitespace-only ``<term>`` is skipped.** A termSec with
  no surface is recorded as skipped — Weblate's UI prevents these
  but hand-edited TBX files can produce them.
- **Idempotent re-import.** Re-importing the same TBX twice is a
  no-op — the underlying termbase upserts on PK and every id the
  importer produces is stable across runs:

  * ``concept_id`` is taken from ``conceptEntry @id`` when present
    (Weblate always writes it). Absent ``@id`` falls back to a
    UUID4 — that path is non-idempotent and is the *only* path
    that reflects in ``synthesized_id_count`` as a duplicate-risk
    warning. Real Weblate exports never trigger it.
  * ``term_id`` is taken from ``termSec @id`` when present.
    Absent ``@id`` (Weblate's normal shape) falls back to a stable
    content-addressed hash of ``(concept_id, lang, surface)`` —
    see :func:`_derive_term_id`. Re-importing the same termSec
    therefore upserts onto the same row.

  ``synthesized_id_count`` reports how many ``@id`` attributes
  were absent in total so the caller can surface "your TBX
  omits @id" without implying duplicate-on-reimport risk for the
  termSec-level case.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final

from lxml import etree

from ainemo.core.termbase._ids import TERM_SOURCE_TBX_IMPORT
from ainemo.core.termbase.base import Concept, Domain, Term, Termbase

# TBX 3.0 / ISO 30042 second-edition namespace, the only one Weblate
# emits in its export flow. We accept files without a default
# namespace too (some hand-edited fixtures omit it) — see
# `_TBX_NAMESPACES` below.
_TBX_NS: Final = "urn:iso:std:iso:30042:ed-2"
_XML_NS: Final = "http://www.w3.org/XML/1998/namespace"
_XML_LANG_KEY: Final = f"{{{_XML_NS}}}lang"

# --- Documented subset (anything else lands in skipped_unsupported) ---

# Children of <conceptEntry> we extract.
_CONCEPT_DESCRIP_TYPE_DOMAIN: Final = "domain"
# termNote @type values we extract (the rest hit skipped_unsupported).
_TERMNOTE_TYPE_POS: Final = "partOfSpeech"
_TERMNOTE_TYPE_REGISTER: Final = "register"

# Element local-names that are part of the cycle-3 documented subset.
_SUPPORTED_CONCEPT_CHILDREN: Final = frozenset({"descrip", "langSec"})
_SUPPORTED_LANGSEC_CHILDREN: Final = frozenset({"termSec"})
_SUPPORTED_TERMSEC_CHILDREN: Final = frozenset({"term", "termNote", "definition"})
_SUPPORTED_TERMNOTE_TYPES: Final = frozenset({_TERMNOTE_TYPE_POS, _TERMNOTE_TYPE_REGISTER})
_SUPPORTED_DESCRIP_TYPES: Final = frozenset({_CONCEPT_DESCRIP_TYPE_DOMAIN})


@dataclass(frozen=True)
class TbxImportReport:
    """Outcome of one ``import_file`` call.

    ``skipped_unsupported`` entries are formatted as
    ``"<localname>[@type=<value>] @ <xpath>"`` so a human reading
    the cycle-3 retro can map each entry back to a source line.
    A Weblate-export round-trip should produce an empty tuple.
    """

    concepts_added: int
    terms_added: int
    domains_added: int
    skipped_unsupported: tuple[str, ...]
    synthesized_id_count: int
    """Number of conceptEntry / termSec elements that did not carry
    an ``@id`` and got a derived id from the importer.

    termSec rows without ``@id`` use a stable
    ``(concept_id, lang, surface)`` hash (see
    :func:`_derive_term_id`), so re-import is idempotent at the
    term level. conceptEntry rows without ``@id`` still fall back
    to UUID4 and re-import would duplicate them — but Weblate's
    export always writes ``conceptEntry @id``, so that path does
    not trigger in practice. Surface this count so the caller can
    note "your TBX omits @id" rather than as a strict
    duplicate-risk warning."""


class TbxImporter:
    """Imports TBX 3.0 files into a :class:`Termbase`.

    Construction is cheap; instances hold no state across calls. The
    optional ``new_id`` and ``now`` callables are injected so tests
    can produce deterministic IDs and timestamps without monkeypatching
    ``uuid.uuid4`` / ``time.time`` at module scope.
    """

    def __init__(
        self,
        tb: Termbase,
        *,
        new_id: Callable[[], str] | None = None,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._tb = tb
        self._new_id = new_id if new_id is not None else _default_new_id
        self._now = now if now is not None else _default_now

    def import_file(self, path: Path) -> TbxImportReport:
        tree = etree.parse(str(path))
        return self._import_tree(tree)

    def import_bytes(self, payload: bytes) -> TbxImportReport:
        # Tests prefer this — no temp file needed.
        root = etree.fromstring(payload)
        # ``etree.fromstring`` returns the root element directly; wrap
        # in an ElementTree so the same _import_tree path handles both
        # entry points (and getroottree() on a synthesized root works).
        return self._import_tree(root.getroottree())

    # --- Internals ---

    def _import_tree(self, tree: etree._ElementTree) -> TbxImportReport:
        root = tree.getroot()
        source_lang = root.get(_XML_LANG_KEY)
        skipped: list[str] = []
        concepts_added = 0
        terms_added = 0
        domains_added = 0
        synthesized_id_count = 0
        seen_domains: set[str] = set()

        for entry in _findall_local(root, "conceptEntry"):
            outcome = self._import_concept_entry(
                entry,
                source_lang=source_lang,
                seen_domains=seen_domains,
            )
            concepts_added += 1
            terms_added += outcome.terms_added
            domains_added += outcome.domains_added
            synthesized_id_count += outcome.synthesized_ids
            skipped.extend(outcome.skipped)

        return TbxImportReport(
            concepts_added=concepts_added,
            terms_added=terms_added,
            domains_added=domains_added,
            skipped_unsupported=tuple(skipped),
            synthesized_id_count=synthesized_id_count,
        )

    def _import_concept_entry(
        self,
        entry: etree._Element,
        *,
        source_lang: str | None,
        seen_domains: set[str],
    ) -> _ConceptOutcome:
        skipped: list[str] = []
        concept_id_attr = entry.get("id")
        if concept_id_attr is None:
            concept_id = self._new_id()
            synthesized_ids = 1
        else:
            concept_id = concept_id_attr
            synthesized_ids = 0

        domain_ids: list[str] = []
        terms: list[Term] = []
        definition: str | None = None

        for child in entry:
            local = etree.QName(child).localname
            if local not in _SUPPORTED_CONCEPT_CHILDREN:
                skipped.append(_skip_marker(child))
                continue
            if local == "descrip":
                descrip_type = child.get("type")
                if descrip_type not in _SUPPORTED_DESCRIP_TYPES:
                    skipped.append(_skip_marker(child))
                    continue
                domain_id = (child.text or "").strip()
                if domain_id:
                    domain_ids.append(domain_id)
            elif local == "langSec":
                lang = child.get(_XML_LANG_KEY)
                if not lang:
                    skipped.append(_skip_marker(child))
                    continue
                outcome = self._import_lang_sec(
                    child,
                    concept_id=concept_id,
                    lang=lang,
                )
                terms.extend(outcome.terms)
                synthesized_ids += outcome.synthesized_ids
                skipped.extend(outcome.skipped)
                if (
                    definition is None
                    and source_lang is not None
                    and lang == source_lang
                    and outcome.definition is not None
                ):
                    definition = outcome.definition

        concept = Concept(
            concept_id=concept_id,
            qid=None,
            definition=definition,
            created_at=self._now(),
        )
        self._tb.add_concept(concept, terms)

        domains_added = 0
        for domain_id in domain_ids:
            if domain_id not in seen_domains:
                self._tb.add_domain(Domain(domain_id=domain_id, parent_id=None, name=domain_id))
                seen_domains.add(domain_id)
                domains_added += 1
            self._tb.attach_concept_to_domain(concept_id, domain_id)

        return _ConceptOutcome(
            terms_added=len(terms),
            domains_added=domains_added,
            synthesized_ids=synthesized_ids,
            skipped=skipped,
        )

    def _import_lang_sec(
        self,
        lang_sec: etree._Element,
        *,
        concept_id: str,
        lang: str,
    ) -> _LangSecOutcome:
        terms: list[Term] = []
        skipped: list[str] = []
        synthesized_ids = 0
        definition: str | None = None

        for child in lang_sec:
            local = etree.QName(child).localname
            if local not in _SUPPORTED_LANGSEC_CHILDREN:
                skipped.append(_skip_marker(child))
                continue
            term_outcome = self._import_term_sec(
                child,
                concept_id=concept_id,
                lang=lang,
            )
            if term_outcome.term is not None:
                terms.append(term_outcome.term)
            synthesized_ids += term_outcome.synthesized_ids
            skipped.extend(term_outcome.skipped)
            if definition is None and term_outcome.definition is not None:
                definition = term_outcome.definition

        return _LangSecOutcome(
            terms=terms,
            definition=definition,
            synthesized_ids=synthesized_ids,
            skipped=skipped,
        )

    def _import_term_sec(
        self,
        term_sec: etree._Element,
        *,
        concept_id: str,
        lang: str,
    ) -> _TermSecOutcome:
        skipped: list[str] = []
        surface: str | None = None
        register: str | None = None
        part_of_speech: str | None = None
        definition: str | None = None

        for child in term_sec:
            local = etree.QName(child).localname
            if local not in _SUPPORTED_TERMSEC_CHILDREN:
                skipped.append(_skip_marker(child))
                continue
            if local == "term":
                text = (child.text or "").strip()
                if text:
                    surface = text
            elif local == "termNote":
                note_type = child.get("type")
                if note_type not in _SUPPORTED_TERMNOTE_TYPES:
                    skipped.append(_skip_marker(child))
                    continue
                text = (child.text or "").strip()
                if not text:
                    continue
                if note_type == _TERMNOTE_TYPE_POS:
                    part_of_speech = text
                elif note_type == _TERMNOTE_TYPE_REGISTER:
                    register = text
            elif local == "definition":
                text = (child.text or "").strip()
                if text:
                    definition = text

        if surface is None:
            # A termSec with no extractable surface is itself unsupported
            # data — emit a single skip marker rather than swallowing it.
            skipped.append(_skip_marker(term_sec, suffix="[no-term]"))
            return _TermSecOutcome(
                term=None,
                definition=definition,
                synthesized_ids=0,
                skipped=skipped,
            )

        term_id_attr = term_sec.get("id")
        if term_id_attr is None:
            # Weblate's TBX export never sets @id on termSec, so the
            # original UUID4 fallback duplicated every term on
            # re-import. Derive a stable id from (concept_id, lang,
            # surface) instead — that's the natural-key triple Kuzu's
            # PK upsert needs to make re-import truly idempotent.
            # Surfaces with the same text under the same concept+lang
            # collapse to one row (a duplicate in the source TBX is
            # always a user error; Weblate's UI prevents it).
            term_id = _derive_term_id(concept_id, lang, surface)
            synthesized_ids = 1
        else:
            term_id = term_id_attr
            synthesized_ids = 0

        term = Term(
            term_id=term_id,
            concept_id=concept_id,
            lang=lang,
            surface=surface,
            register=register,
            part_of_speech=part_of_speech,
            source=TERM_SOURCE_TBX_IMPORT,
        )
        return _TermSecOutcome(
            term=term,
            definition=definition,
            synthesized_ids=synthesized_ids,
            skipped=skipped,
        )


# --- Internal value objects (not exported) ---


@dataclass(frozen=True)
class _ConceptOutcome:
    terms_added: int
    domains_added: int
    synthesized_ids: int
    skipped: list[str]


@dataclass(frozen=True)
class _LangSecOutcome:
    terms: list[Term]
    definition: str | None
    synthesized_ids: int
    skipped: list[str]


@dataclass(frozen=True)
class _TermSecOutcome:
    term: Term | None
    definition: str | None
    synthesized_ids: int
    skipped: list[str]


# --- Helpers ---


def _findall_local(root: etree._Element, localname: str) -> list[etree._Element]:
    """Find every descendant element with the given local name,
    namespace-agnostic.

    Weblate emits TBX 3.0 with the ``urn:iso:std:iso:30042:ed-2``
    default namespace; some hand-edited fixtures omit it. Using the
    local-name() XPath function lets us accept both shapes from one
    code path.
    """
    namespaced = list(root.iter(f"{{{_TBX_NS}}}{localname}"))
    bare = list(root.iter(localname))
    return namespaced + bare


def _skip_marker(element: etree._Element, *, suffix: str = "") -> str:
    """Format a ``skipped_unsupported`` entry.

    Format: ``"<localname>[@type=<value>] @ <xpath>[ <suffix>]"``.
    The XPath uses lxml's ``getpath`` which produces a 1-indexed
    positional path (e.g. ``/tbx/text/body/conceptEntry[1]/transacGrp[1]``)
    so a human can locate the element in the source file even when
    @id is absent.
    """
    local = etree.QName(element).localname
    type_attr = element.get("type")
    type_part = f"[@type={type_attr!r}]" if type_attr is not None else ""
    tree = element.getroottree()
    xpath = tree.getpath(element) if tree is not None else ""
    suffix_part = f" {suffix}" if suffix else ""
    return f"{local}{type_part} @ {xpath}{suffix_part}"


def _derive_term_id(concept_id: str, lang: str, surface: str) -> str:
    """Stable, content-addressed term id for Weblate-style termSec
    rows that omit ``@id``.

    Hash of ``(concept_id, lang, surface)`` joined by the ASCII unit
    separator (``\\x1f``) so the three fields cannot collide via
    delimiter ambiguity. Truncated to 16 hex chars (64 bits) — more
    than enough for the cycle-3 termbase scale (5k concepts × ~5
    langs).
    """
    digest = hashlib.sha256(f"{concept_id}\x1f{lang}\x1f{surface}".encode("utf-8")).hexdigest()
    return f"tbx-{digest[:16]}"


def _default_new_id() -> str:
    return str(uuid.uuid4())


def _default_now() -> int:
    import time

    return int(time.time())


__all__ = ["TbxImporter", "TbxImportReport"]
