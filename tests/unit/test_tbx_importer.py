# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for :class:`ainemo.core.termbase.tbx.importer.TbxImporter`.

Cycle-3 S2 contract:

- Documented subset (``<conceptEntry>``, ``<descrip type="domain">``,
  ``<langSec>``, ``<termSec>``, ``<term>``, ``<termNote
  type="partOfSpeech"|"register">``, ``<definition>``) is extracted
  into ``Concept`` + ``Term`` rows on the supplied :class:`Termbase`.
- Anything outside the subset is recorded in
  ``TbxImportReport.skipped_unsupported`` as ``"name @ xpath"``.
- Weblate-style fixtures produce an empty ``skipped_unsupported``;
  the pathological-unsupported-elements fixture surfaces every
  out-of-subset element it contains.
- ``synthesized_id_count`` tracks termSec / conceptEntry elements
  that lacked ``@id`` and got a derived id from the importer
  (deterministic ``(concept_id, lang, surface)`` hash for termSec;
  UUID4 fallback for conceptEntry — the latter never triggers on
  Weblate exports).

Tests use both the on-disk Kuzu termbase (covered transitively via
the S1 unit test) and an in-process recording stub so the importer's
write path is exercised without paying Kuzu setup cost on every case.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Sequence

import pytest

from ainemo.core.termbase._ids import TERM_SOURCE_TBX_IMPORT
from ainemo.core.termbase.base import (
    Concept,
    ConceptHit,
    Domain,
    Persona,
    Term,
    Termbase,
    TermbaseStats,
)
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.termbase.tbx.importer import TbxImporter, TbxImportReport

pytestmark = pytest.mark.unit


_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tbx"


# --- Recording stub: implements the Termbase Protocol with an
#     in-memory dict so tests can assert exactly what the importer
#     wrote without spinning up Kuzu. The on-disk path is covered by
#     `test_importer_into_kuzu_round_trip`. ---


class _RecordingTermbase:
    """In-process Termbase test double — records every call."""

    def __init__(self) -> None:
        self.concepts: dict[str, Concept] = {}
        self.terms_by_concept: dict[str, list[Term]] = {}
        self.domains: dict[str, Domain] = {}
        self.concept_to_domains: dict[str, list[str]] = {}
        self.personas: dict[str, Persona] = {}

    def add_concept(self, concept: Concept, terms: Sequence[Term]) -> None:
        for term in terms:
            if term.concept_id != concept.concept_id:
                raise ValueError(
                    f"Term {term.term_id!r} has concept_id={term.concept_id!r} "
                    f"but is being added under concept {concept.concept_id!r}"
                )
        self.concepts[concept.concept_id] = concept
        self.terms_by_concept.setdefault(concept.concept_id, []).extend(terms)

    def add_domain(self, domain: Domain) -> None:
        self.domains[domain.domain_id] = domain

    def attach_concept_to_domain(self, concept_id: str, domain_id: str) -> None:
        attached = self.concept_to_domains.setdefault(concept_id, [])
        if domain_id not in attached:
            attached.append(domain_id)

    def add_persona(self, persona: Persona) -> None:
        self.personas[persona.persona_id] = persona

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
        return ()  # not exercised by the importer

    def stats(self) -> TermbaseStats:
        return TermbaseStats(
            concept_count=len(self.concepts),
            term_count_by_lang=(),
            domain_count=len(self.domains),
            persona_count=len(self.personas),
        )

    def all_terms(self) -> list[Term]:
        return [t for terms in self.terms_by_concept.values() for t in terms]


@pytest.fixture
def stub() -> _RecordingTermbase:
    return _RecordingTermbase()


@pytest.fixture
def importer(stub: _RecordingTermbase) -> TbxImporter:
    counter = itertools.count()
    return TbxImporter(
        stub,
        new_id=lambda: f"gen-{next(counter)}",
        now=lambda: 1234567890,
    )


def _import(importer: TbxImporter, fixture_name: str) -> TbxImportReport:
    return importer.import_file(_FIXTURE_DIR / fixture_name)


# --- Protocol contract ---


def test_recording_stub_satisfies_protocol(stub: _RecordingTermbase) -> None:
    # Pin that the test double fully implements `Termbase` so it can
    # stand in for `KuzuTermbase` in cycle-3 S6 pipeline tests too.
    assert isinstance(stub, Termbase)


# --- Weblate-style fixtures: skipped_unsupported must be empty ---


@pytest.mark.parametrize(
    "fixture",
    [
        "weblate-software-en-de.tbx",
        "weblate-multi-lang.tbx",
        "weblate-with-pos-register.tbx",
        "weblate-multi-term-per-lang.tbx",
        "weblate-with-definitions.tbx",
    ],
)
def test_weblate_fixtures_have_no_skipped_elements(importer: TbxImporter, fixture: str) -> None:
    report = _import(importer, fixture)
    assert report.skipped_unsupported == (), (
        f"{fixture}: unexpected skipped elements {report.skipped_unsupported}"
    )
    assert report.concepts_added > 0
    assert report.terms_added > 0


# --- Per-fixture content assertions ---


def test_software_en_de_extracts_terms_and_domain(
    importer: TbxImporter, stub: _RecordingTermbase
) -> None:
    report = _import(importer, "weblate-software-en-de.tbx")
    assert report.concepts_added == 3
    assert report.terms_added == 6  # 3 concepts × 2 langs
    assert report.domains_added == 1

    # Concept ids preserved from @id attribute.
    assert set(stub.concepts) == {"c-login", "c-logout", "c-cancel"}

    # Source-lang definition lifted onto Concept.
    login = stub.concepts["c-login"]
    assert login.definition == "The act of authenticating into a system."

    # Domain attached.
    assert stub.concept_to_domains["c-login"] == ["software"]
    assert "software" in stub.domains

    # Term provenance + register/POS extracted.
    login_terms = stub.terms_by_concept["c-login"]
    by_lang = {t.lang: t for t in login_terms}
    assert by_lang["en"].surface == "login"
    assert by_lang["en"].part_of_speech == "noun"
    assert by_lang["en"].register == "neutral"
    assert by_lang["en"].source == TERM_SOURCE_TBX_IMPORT
    assert by_lang["de"].surface == "Anmeldung"
    assert by_lang["de"].register is None  # not present in the fixture


def test_multi_lang_fixture(importer: TbxImporter, stub: _RecordingTermbase) -> None:
    report = _import(importer, "weblate-multi-lang.tbx")
    assert report.concepts_added == 2
    assert report.terms_added == 8  # 2 concepts × 4 langs
    settings_terms = stub.terms_by_concept["c-settings"]
    surfaces_by_lang = {t.lang: t.surface for t in settings_terms}
    assert surfaces_by_lang == {
        "en": "settings",
        "de": "Einstellungen",
        "fr": "paramètres",
        "es": "configuración",
    }


def test_pos_and_register_fixture(importer: TbxImporter, stub: _RecordingTermbase) -> None:
    _import(importer, "weblate-with-pos-register.tbx")
    greet_terms = stub.terms_by_concept["c-greet"]
    by_lang = {t.lang: t for t in greet_terms}
    assert by_lang["en"].register == "neutral"
    assert by_lang["de"].register == "formal"
    assert by_lang["fr"].register == "casual"
    assert all(t.part_of_speech == "interjection" for t in greet_terms)


def test_multi_term_per_lang_fixture(importer: TbxImporter, stub: _RecordingTermbase) -> None:
    report = _import(importer, "weblate-multi-term-per-lang.tbx")
    assert report.concepts_added == 1
    assert report.terms_added == 5  # 3 en synonyms + 2 de synonyms
    en_terms = sorted((t.surface for t in stub.terms_by_concept["c-quick"] if t.lang == "en"))
    assert en_terms == ["fast", "quick", "rapid"]


def test_with_definitions_fixture(importer: TbxImporter, stub: _RecordingTermbase) -> None:
    _import(importer, "weblate-with-definitions.tbx")
    db = stub.concepts["c-database"]
    cache = stub.concepts["c-cache"]
    assert db.definition == "An organized collection of structured data."
    assert cache.definition is not None
    assert "transient" in cache.definition


# --- Pathological fixtures ---


def test_mixed_langsec_order_attributes_terms_correctly(
    importer: TbxImporter, stub: _RecordingTermbase
) -> None:
    # de + fr appear before en in the conceptEntry; the importer
    # must still tag each term with its langSec's @xml:lang and
    # lift the en definition onto Concept.definition.
    report = _import(importer, "pathological-mixed-langsec-order.tbx")
    assert report.skipped_unsupported == ()
    save_terms = {t.lang: t.surface for t in stub.terms_by_concept["c-save"]}
    assert save_terms == {"en": "save", "de": "speichern", "fr": "enregistrer"}
    save = stub.concepts["c-save"]
    assert save.definition == "Persist the current state to storage."


def test_missing_definitions_leaves_concept_definition_none(
    importer: TbxImporter, stub: _RecordingTermbase
) -> None:
    report = _import(importer, "pathological-missing-definitions.tbx")
    assert report.skipped_unsupported == ()
    for cid in ("c-search", "c-filter"):
        assert stub.concepts[cid].definition is None


def test_multi_domain_concept_attaches_to_each_domain(
    importer: TbxImporter, stub: _RecordingTermbase
) -> None:
    report = _import(importer, "pathological-multi-domain.tbx")
    assert report.skipped_unsupported == ()
    assert report.domains_added == 2
    # Order matches source-file order: legal first, then software.
    assert stub.concept_to_domains["c-license"] == ["legal", "software"]
    assert {"legal", "software"} <= set(stub.domains)


def test_unsupported_elements_recorded_with_name_and_xpath(
    importer: TbxImporter, stub: _RecordingTermbase
) -> None:
    report = _import(importer, "pathological-unsupported-elements.tbx")
    skipped = report.skipped_unsupported

    # Five out-of-subset items: descrip type=context, transacGrp,
    # termNote type=usageStatus, xref, ref.
    assert len(skipped) == 5
    joined = "\n".join(skipped)

    # Names + their distinguishing @type when present.
    assert "descrip[@type='context']" in joined
    assert "transacGrp" in joined
    assert "termNote[@type='usageStatus']" in joined
    assert "xref[@type='externalCrossReference']" in joined
    assert "ref[@type='seeAlso']" in joined

    # Every entry must include " @ /" — the XPath separator. lxml's
    # getpath emits positional XPath expressions usable verbatim
    # against the source file with `tree.xpath(...)`.
    for entry in skipped:
        assert " @ /" in entry

    # The supported parts of the same conceptEntry still landed.
    assert "c-export" in stub.concepts
    export_terms = {t.lang: t.surface for t in stub.terms_by_concept["c-export"]}
    assert export_terms == {"en": "export", "de": "exportieren"}


# --- ID synthesis + idempotency ---


def test_termsec_without_id_synthesizes_deterministically_and_reports_count(
    importer: TbxImporter,
) -> None:
    # Weblate exports never set @id on termSec; the importer must
    # derive a stable id from (concept_id, lang, surface) so re-import
    # is genuinely idempotent. synthesized_id_count tracks how many
    # @id attributes were absent — useful for the caller to surface
    # "your TBX export omits @id" without implying duplicate risk.
    report = _import(importer, "weblate-software-en-de.tbx")
    assert report.synthesized_id_count == report.terms_added


def test_termsec_synthesized_ids_are_stable_across_calls(
    importer: TbxImporter, stub: _RecordingTermbase
) -> None:
    # Importing the same fixture twice into the same termbase must
    # produce identical term ids, so the upsert layer collapses the
    # second import onto the first instead of duplicating rows.
    _import(importer, "weblate-software-en-de.tbx")
    first_pass_ids = {(t.concept_id, t.lang, t.surface): t.term_id for t in stub.all_terms()}
    _import(importer, "weblate-software-en-de.tbx")
    second_pass_ids = {(t.concept_id, t.lang, t.surface): t.term_id for t in stub.all_terms()}
    assert first_pass_ids == second_pass_ids


def test_concept_with_explicit_id_is_idempotent_on_reimport(
    stub: _RecordingTermbase,
) -> None:
    # Re-import on the same stub must not grow the concept count.
    # `new_id` only fires for conceptEntry without @id (Weblate always
    # writes it); the term-level fallback is deterministic so it does
    # not need a counter override.
    imp1 = TbxImporter(stub, now=lambda: 1)
    imp2 = TbxImporter(stub, now=lambda: 2)

    imp1.import_file(_FIXTURE_DIR / "weblate-software-en-de.tbx")
    concept_count_after_first = len(stub.concepts)
    imp2.import_file(_FIXTURE_DIR / "weblate-software-en-de.tbx")
    assert len(stub.concepts) == concept_count_after_first
    # Concept.created_at refreshes on re-import (upsert semantics).
    assert stub.concepts["c-login"].created_at == 2


# --- Construction defaults ---


def test_default_constructors_run_without_injection(
    stub: _RecordingTermbase,
) -> None:
    # Smoke: TbxImporter without new_id/now overrides falls back to
    # uuid.uuid4 + time.time. Verify on a tiny fixture so the test
    # is fast and does not depend on a clock value.
    imp = TbxImporter(stub)
    report = imp.import_file(_FIXTURE_DIR / "pathological-missing-definitions.tbx")
    assert report.concepts_added == 2


# --- End-to-end on the real Kuzu backend ---


def test_importer_into_kuzu_round_trip(tmp_path: Path) -> None:
    tb = KuzuTermbase(tmp_path / "termbase.kuzu")
    counter = itertools.count()
    imp = TbxImporter(tb, new_id=lambda: f"gen-{next(counter)}", now=lambda: 100)
    report = imp.import_file(_FIXTURE_DIR / "weblate-software-en-de.tbx")
    assert report.skipped_unsupported == ()
    stats = tb.stats()
    assert stats.concept_count == 3
    assert dict(stats.term_count_by_lang) == {"en": 3, "de": 3}
    assert stats.domain_count == 1

    # The imported termbase is queryable via the Termbase Protocol.
    hits = tb.lookup_concepts_for("please login now", "en", "de")
    assert len(hits) == 1
    assert hits[0].matched_source_term.surface == "login"
    assert tuple(t.surface for t in hits[0].target_terms) == ("Anmeldung",)


def test_importer_kuzu_re_import_does_not_duplicate(tmp_path: Path) -> None:
    # Regression for the P2 finding: an earlier UUID4 fallback for
    # termSec without @id duplicated every term on re-import,
    # inflating en/de from 3→6 each and surfacing duplicate
    # target_terms in lookup. The deterministic
    # (concept_id, lang, surface) hash makes re-import a true no-op.
    tb = KuzuTermbase(tmp_path / "termbase.kuzu")
    imp = TbxImporter(tb, now=lambda: 100)
    imp.import_file(_FIXTURE_DIR / "weblate-software-en-de.tbx")
    stats_after_first = tb.stats()
    imp.import_file(_FIXTURE_DIR / "weblate-software-en-de.tbx")
    stats_after_second = tb.stats()

    assert stats_after_second.concept_count == stats_after_first.concept_count
    assert stats_after_second.term_count_by_lang == stats_after_first.term_count_by_lang
    assert dict(stats_after_second.term_count_by_lang) == {"en": 3, "de": 3}

    # Lookup must not return duplicate target_terms.
    hits = tb.lookup_concepts_for("please login now", "en", "de")
    assert len(hits) == 1
    target_surfaces = tuple(t.surface for t in hits[0].target_terms)
    assert target_surfaces == ("Anmeldung",)


# --- import_bytes entry point ---


def test_import_bytes_supports_namespace_free_documents(
    stub: _RecordingTermbase, importer: TbxImporter
) -> None:
    # Hand-edited TBX-ish documents sometimes omit the namespace.
    # The `_findall_local` helper accepts both shapes; pin it.
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<tbx style="dca" type="TBX-Basic" xml:lang="en">
  <text><body>
    <conceptEntry id="c-bare">
      <langSec xml:lang="en">
        <termSec><term>bare</term></termSec>
      </langSec>
    </conceptEntry>
  </body></text>
</tbx>"""
    report = importer.import_bytes(payload)
    assert report.concepts_added == 1
    assert "c-bare" in stub.concepts
