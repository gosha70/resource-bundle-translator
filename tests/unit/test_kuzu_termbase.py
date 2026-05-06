# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for :class:`ainemo.core.termbase.kuzu.store.KuzuTermbase`.

Cycle-3 S1 contract:

- Schema bootstrap is idempotent (open same DB twice → no DDL error,
  state preserved).
- CRUD round-trip for ``Concept`` + ``Term`` + ``Domain`` + ``Persona``
  (re-add same entity → no duplicate, properties refreshed).
- ``lookup_concepts_for`` precision/recall on a synthetic 200-concept
  fixture: known matches are found, near-misses (substring inside a
  larger word) are rejected, domain narrowing works.

The tests use a deterministic Kuzu DB on a tmp_path so they run on
the matrix without any setup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.termbase._ids import (
    DEFAULT_PROMOTION_CONSISTENCY_MIN,
    DEFAULT_PROMOTION_FREQUENCY_MIN,
    TERM_SOURCE_MANUAL,
    TERM_SOURCE_TBX_IMPORT,
)
from ainemo.core.termbase.base import (
    Concept,
    Domain,
    GlossaryOverride,
    Persona,
    Term,
    Termbase,
)
from ainemo.core.termbase.kuzu.store import KuzuTermbase

pytestmark = pytest.mark.unit


# --- Fixtures ---


@pytest.fixture
def tb(tmp_path: Path) -> KuzuTermbase:
    return KuzuTermbase(tmp_path / "termbase.kuzu")


def _concept(cid: str, *, qid: str | None = None, ts: int = 1) -> Concept:
    return Concept(concept_id=cid, qid=qid, definition=None, created_at=ts)


def _term(
    tid: str,
    *,
    concept_id: str,
    lang: str,
    surface: str,
    source: str = TERM_SOURCE_MANUAL,
) -> Term:
    return Term(
        term_id=tid,
        concept_id=concept_id,
        lang=lang,
        surface=surface,
        register=None,
        part_of_speech=None,
        source=source,
    )


# --- Constants discipline ---


def test_promotion_thresholds_match_q1_resolution() -> None:
    # Q1 from the pitch (resolved at /bet, 2026-05-05): take the
    # proposed defaults. Pin them in a test so an accidental edit to
    # _ids.py during cooldown re-tuning shows up as a contract change.
    assert DEFAULT_PROMOTION_FREQUENCY_MIN == 5
    assert DEFAULT_PROMOTION_CONSISTENCY_MIN == pytest.approx(0.9)


# --- Schema bootstrap idempotency ---


def test_open_twice_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "termbase.kuzu"
    first = KuzuTermbase(path)
    first.add_concept(
        _concept("c1", ts=1),
        [_term("t1", concept_id="c1", lang="en", surface="login")],
    )
    first.close()
    # Second open on the same directory must not re-error on
    # CREATE NODE TABLE — the IF NOT EXISTS guard is the contract.
    second = KuzuTermbase(path)
    stats = second.stats()
    assert stats.concept_count == 1
    assert stats.term_count_by_lang == (("en", 1),)


def test_protocol_runtime_check(tb: KuzuTermbase) -> None:
    # `Termbase` is `@runtime_checkable`; cycle-3 S6 pipeline accepts
    # `Termbase | None` and we want isinstance() to pass without
    # importing KuzuTermbase.
    assert isinstance(tb, Termbase)


# --- CRUD round-trip ---


def test_add_concept_round_trip(tb: KuzuTermbase) -> None:
    concept = Concept(concept_id="c1", qid="Q11460", definition="d", created_at=10)
    terms = [
        _term("t-en", concept_id="c1", lang="en", surface="login"),
        _term("t-de", concept_id="c1", lang="de", surface="Anmeldung"),
    ]
    tb.add_concept(concept, terms)

    hits = tb.lookup_concepts_for("login button", "en", "de")
    assert len(hits) == 1
    assert hits[0].concept.qid == "Q11460"
    assert hits[0].matched_source_term.surface == "login"
    assert tuple(t.surface for t in hits[0].target_terms) == ("Anmeldung",)


def test_add_concept_is_idempotent(tb: KuzuTermbase) -> None:
    concept = _concept("c1")
    term = _term("t1", concept_id="c1", lang="en", surface="login")
    tb.add_concept(concept, [term])
    # Re-add — must not duplicate the concept or term, and must
    # refresh properties (here we change `qid` and `surface`).
    refreshed = Concept(concept_id="c1", qid="Q-NEW", definition=None, created_at=20)
    refreshed_term = _term("t1", concept_id="c1", lang="en", surface="LOGIN")
    tb.add_concept(refreshed, [refreshed_term])
    stats = tb.stats()
    assert stats.concept_count == 1
    assert stats.term_count_by_lang == (("en", 1),)
    hits = tb.lookup_concepts_for("Login pane", "en", "de")
    assert len(hits) == 1
    assert hits[0].concept.qid == "Q-NEW"
    assert hits[0].concept.created_at == 20


def test_term_concept_id_must_match_concept(tb: KuzuTermbase) -> None:
    concept = _concept("c1")
    mismatched = _term("t1", concept_id="c-other", lang="en", surface="login")
    with pytest.raises(ValueError):
        tb.add_concept(concept, [mismatched])


def test_rejected_concept_insert_leaves_no_partial_state(tb: KuzuTermbase) -> None:
    # Regression: an earlier draft wrote the concept row before
    # validating the term list, so a ValueError raised mid-call left
    # an orphan Concept node and inflated `concept_count`. The
    # contract is "validate then write" — atomicity via input
    # validation, since Kuzu's embedded driver does not expose a
    # multi-statement transaction surface.
    concept = _concept("c1")
    valid = _term("t1", concept_id="c1", lang="en", surface="login")
    mismatched = _term("t2", concept_id="c-other", lang="en", surface="logout")
    with pytest.raises(ValueError):
        tb.add_concept(concept, [valid, mismatched])
    stats = tb.stats()
    assert stats.concept_count == 0
    assert stats.term_count_by_lang == ()


def test_add_domain_idempotent(tb: KuzuTermbase) -> None:
    tb.add_domain(Domain(domain_id="software", parent_id=None, name="Software"))
    tb.add_domain(Domain(domain_id="software", parent_id=None, name="Software (renamed)"))
    assert tb.stats().domain_count == 1


def test_persona_round_trip_with_overrides(tb: KuzuTermbase) -> None:
    overrides = (
        GlossaryOverride(source_term="cancel", target_lang="de", target_term="Abbrechen"),
        GlossaryOverride(source_term="ok", target_lang="fr", target_term="OK"),
    )
    persona = Persona(
        persona_id="software-ui",
        name="Software UI",
        forbidden_terms=("foo", "bar"),
        prompt_addendum="Translate UI strings.",
        domain_id="software",
        register="neutral",
        style_guide_url="https://example.invalid/sg",
        glossary_overrides=overrides,
    )
    tb.add_persona(persona)
    fetched = tb.get_persona("software-ui")
    assert fetched == persona

    assert tb.get_persona("does-not-exist") is None

    # Idempotent re-add with refreshed name + addendum.
    refreshed = Persona(
        persona_id="software-ui",
        name="Software UI v2",
        forbidden_terms=("baz",),
        prompt_addendum="Updated.",
        domain_id="software",
        register="formal",
        style_guide_url=None,
        glossary_overrides=(),
    )
    tb.add_persona(refreshed)
    assert tb.get_persona("software-ui") == refreshed
    assert tb.stats().persona_count == 1


def test_persona_provider_hints_field_does_not_exist() -> None:
    # Q2 from the pitch (resolved at /bet, 2026-05-05): the proposed
    # `provider_hints` optional field was dropped — persona-aware
    # routing lives in cycle-2's RoutingConfig, not on Persona.
    # Pin the dataclass shape so an accidental re-add during cooldown
    # surfaces as a failing test, not a silent contract violation.
    fields = {f for f in Persona.__dataclass_fields__}
    assert "provider_hints" not in fields
    assert fields == {
        "persona_id",
        "name",
        "forbidden_terms",
        "prompt_addendum",
        "domain_id",
        "register",
        "style_guide_url",
        "glossary_overrides",
    }


def test_list_personas_sorted(tb: KuzuTermbase) -> None:
    for pid in ("zulu", "alpha", "mike"):
        tb.add_persona(
            Persona(
                persona_id=pid,
                name=pid.title(),
                forbidden_terms=(),
                prompt_addendum="",
            )
        )
    ids = tuple(p.persona_id for p in tb.list_personas())
    assert ids == ("alpha", "mike", "zulu")


def test_stats_term_count_by_lang_sorted(tb: KuzuTermbase) -> None:
    tb.add_concept(
        _concept("c1"),
        [
            _term("t1", concept_id="c1", lang="en", surface="login"),
            _term("t2", concept_id="c1", lang="de", surface="Anmeldung"),
            _term("t3", concept_id="c1", lang="fr", surface="connexion"),
        ],
    )
    stats = tb.stats()
    langs = tuple(lang for lang, _ in stats.term_count_by_lang)
    assert langs == tuple(sorted(langs))


# --- N-gram lookup precision / recall on a 200-concept fixture ---


def _seed_synthetic_corpus(tb: KuzuTermbase, *, count: int = 200) -> dict[str, str]:
    """Seed a deterministic synthetic corpus with `count` concepts.

    Returns a dict of source-surface → target-surface so tests can
    assert lookup precision against known truth. Each concept gets an
    en + de term; concepts 0–9 also get IN_DOMAIN(software).
    """
    tb.add_domain(Domain(domain_id="software", parent_id=None, name="Software"))
    truth: dict[str, str] = {}
    for i in range(count):
        cid = f"c{i:04d}"
        en = f"widget{i:04d}"
        de = f"Widget{i:04d}DE"
        truth[en] = de
        tb.add_concept(
            _concept(cid, ts=i),
            [
                _term(f"{cid}-en", concept_id=cid, lang="en", surface=en),
                _term(f"{cid}-de", concept_id=cid, lang="de", surface=de),
            ],
        )
        if i < 10:
            tb.attach_concept_to_domain(cid, "software")
    return truth


def test_lookup_recall_on_synthetic_corpus(tb: KuzuTermbase) -> None:
    truth = _seed_synthetic_corpus(tb, count=200)
    # Pick a sample of source surfaces and embed each in a sentence.
    sample_keys = ["widget0000", "widget0042", "widget0099", "widget0150", "widget0199"]
    for key in sample_keys:
        sentence = f"please use the {key} now"
        hits = tb.lookup_concepts_for(sentence, "en", "de")
        assert len(hits) == 1, f"expected single hit for {key!r}, got {hits}"
        assert hits[0].matched_source_term.surface == key
        assert tuple(t.surface for t in hits[0].target_terms) == (truth[key],)
        assert 0.0 < hits[0].relevance <= 1.0


def test_lookup_precision_word_boundary(tb: KuzuTermbase) -> None:
    # A term `log` should match `please log in` but NOT match `logout`
    # or `prologue` — the word-bounded contains check is the
    # precision guard.
    tb.add_concept(
        _concept("c-log"),
        [
            _term("t-log-en", concept_id="c-log", lang="en", surface="log"),
            _term("t-log-de", concept_id="c-log", lang="de", surface="protokoll"),
        ],
    )
    assert tb.lookup_concepts_for("please log in to your account", "en", "de")
    assert not tb.lookup_concepts_for("clicked logout button", "en", "de")
    assert not tb.lookup_concepts_for("read the prologue chapter", "en", "de")


def test_lookup_relevance_ranks_longer_match_higher(tb: KuzuTermbase) -> None:
    tb.add_concept(
        _concept("c-short"),
        [_term("ts-en", concept_id="c-short", lang="en", surface="log")],
    )
    tb.add_concept(
        _concept("c-long"),
        [_term("tl-en", concept_id="c-long", lang="en", surface="log analyzer")],
    )
    hits = tb.lookup_concepts_for("the log analyzer reads the log", "en", "de")
    assert len(hits) == 2
    # Longer surface = higher relevance for cycle-3 v1's
    # len(surface)/len(source) score.
    assert hits[0].matched_source_term.surface == "log analyzer"
    assert hits[1].matched_source_term.surface == "log"
    assert hits[0].relevance > hits[1].relevance


def test_lookup_domain_filter(tb: KuzuTermbase) -> None:
    truth = _seed_synthetic_corpus(tb, count=20)
    assert "widget0001" in truth
    # Concept indexes 0–9 are IN_DOMAIN(software); 10+ are not.
    in_domain = tb.lookup_concepts_for(
        "the widget0001 and widget0015 buttons", "en", "de", domain_id="software"
    )
    assert tuple(h.matched_source_term.surface for h in in_domain) == ("widget0001",)
    no_filter = tb.lookup_concepts_for("the widget0001 and widget0015 buttons", "en", "de")
    surfaces = {h.matched_source_term.surface for h in no_filter}
    assert surfaces == {"widget0001", "widget0015"}


def test_lookup_max_hits_caps_results(tb: KuzuTermbase) -> None:
    _seed_synthetic_corpus(tb, count=20)
    sentence = " ".join(f"widget{i:04d}" for i in range(20))
    hits = tb.lookup_concepts_for(sentence, "en", "de", max_hits=5)
    assert len(hits) == 5


def test_lookup_target_lang_with_no_terms(tb: KuzuTermbase) -> None:
    # A concept may exist with an en term but no fr term yet — the
    # lookup still returns the hit; target_terms is empty so the
    # cycle-5 reviewer UI can flag it as a missing-translation
    # opportunity (per ConceptHit docstring).
    tb.add_concept(
        _concept("c-iso"),
        [_term("t-en", concept_id="c-iso", lang="en", surface="login")],
    )
    hits = tb.lookup_concepts_for("login screen", "en", "fr")
    assert len(hits) == 1
    assert hits[0].target_terms == ()


def test_lookup_empty_inputs_return_empty_tuple(tb: KuzuTermbase) -> None:
    tb.add_concept(
        _concept("c1"),
        [_term("t1", concept_id="c1", lang="en", surface="login")],
    )
    assert tb.lookup_concepts_for("", "en", "de") == ()
    assert tb.lookup_concepts_for("login", "en", "de", max_hits=0) == ()


def test_term_source_constants_round_trip(tb: KuzuTermbase) -> None:
    # The `source` field on Term is provenance — Weblate-imported vs
    # auto-promoted vs manual vs domain-pack. Pin round-trip so the
    # cycle-5 reviewer UI can rely on the exact tag values.
    tb.add_concept(
        _concept("c1"),
        [
            _term(
                "t1",
                concept_id="c1",
                lang="en",
                surface="login",
                source=TERM_SOURCE_TBX_IMPORT,
            )
        ],
    )
    hits = tb.lookup_concepts_for("login screen", "en", "de")
    assert hits[0].matched_source_term.source == TERM_SOURCE_TBX_IMPORT


def test_attach_concept_to_segment_creates_segment_node(tb: KuzuTermbase) -> None:
    tb.add_concept(
        _concept("c1"),
        [_term("t1", concept_id="c1", lang="en", surface="login")],
    )
    # S5 auto-promotion calls this. Idempotency contract: two calls
    # with the same (concept, fingerprint) leave one edge.
    tb.attach_concept_to_segment("c1", "fp-abc")
    tb.attach_concept_to_segment("c1", "fp-abc")
    # No assertion on edge count (the Protocol does not surface that)
    # — the test pins the no-error idempotency contract; S5 will
    # exercise the read side.
