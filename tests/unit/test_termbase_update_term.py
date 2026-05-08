# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for ``Termbase.update_term`` — cycle-5 S4.

Covers both :class:`~ainemo.core.termbase.kuzu.store.KuzuTermbase`
(concrete impl) and :class:`~tests.termbase_stub.RecordingTermbase`
(test double) to ensure both honour the Protocol contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.termbase._ids import TERM_SOURCE_MANUAL
from ainemo.core.termbase.base import Concept, Term, Termbase
from ainemo.core.termbase.kuzu.store import KuzuTermbase

pytestmark = pytest.mark.unit


@pytest.fixture()
def tb(tmp_path: Path) -> KuzuTermbase:
    return KuzuTermbase(tmp_path / "termbase.kuzu")


def _add_simple(tb: KuzuTermbase) -> tuple[str, str]:
    concept_id = "c-update-test"
    term_id = "t-update-test"
    tb.add_concept(
        Concept(concept_id=concept_id, qid=None, definition=None, created_at=1),
        [
            Term(
                term_id=term_id,
                concept_id=concept_id,
                lang="en",
                surface="login",
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            )
        ],
    )
    return concept_id, term_id


def _lookup_term(tb: KuzuTermbase, term_id: str) -> Term | None:
    for entry in tb.iter_concept_entries():
        for term in entry.terms:
            if term.term_id == term_id:
                return term
    return None


def test_update_term_surface(tb: KuzuTermbase) -> None:
    concept_id, term_id = _add_simple(tb)
    result = tb.update_term(term_id, surface="sign in", register=None, part_of_speech=None)
    assert result is True
    updated = _lookup_term(tb, term_id)
    assert updated is not None
    assert updated.surface == "sign in"


def test_update_term_register(tb: KuzuTermbase) -> None:
    concept_id, term_id = _add_simple(tb)
    tb.update_term(term_id, surface="login", register="formal", part_of_speech=None)
    updated = _lookup_term(tb, term_id)
    assert updated is not None
    assert updated.register == "formal"


def test_update_term_part_of_speech(tb: KuzuTermbase) -> None:
    concept_id, term_id = _add_simple(tb)
    tb.update_term(term_id, surface="login", register=None, part_of_speech="verb")
    updated = _lookup_term(tb, term_id)
    assert updated is not None
    assert updated.part_of_speech == "verb"


def test_update_term_unknown_returns_false(tb: KuzuTermbase) -> None:
    result = tb.update_term("no-such-term", surface="x", register=None, part_of_speech=None)
    assert result is False


def test_update_term_blank_surface_raises(tb: KuzuTermbase) -> None:
    concept_id, term_id = _add_simple(tb)
    with pytest.raises(ValueError, match="non-blank"):
        tb.update_term(term_id, surface="   ", register=None, part_of_speech=None)
    with pytest.raises(ValueError, match="non-blank"):
        tb.update_term(term_id, surface="", register=None, part_of_speech=None)


def test_update_term_identity_fields_unchanged(tb: KuzuTermbase) -> None:
    concept_id, term_id = _add_simple(tb)
    before = _lookup_term(tb, term_id)
    assert before is not None
    tb.update_term(term_id, surface="updated surface", register="casual", part_of_speech="noun")
    after = _lookup_term(tb, term_id)
    assert after is not None
    assert after.term_id == before.term_id
    assert after.concept_id == before.concept_id
    assert after.lang == before.lang
    assert after.source == before.source


def test_protocol_runtime_check(tb: KuzuTermbase) -> None:
    assert isinstance(tb, Termbase)


def test_recording_termbase_update_term_implements_protocol() -> None:
    from tests.termbase_stub import RecordingTermbase

    stub = RecordingTermbase()
    assert isinstance(stub, Termbase)
    stub.add_concept(
        Concept(concept_id="c1", qid=None, definition=None, created_at=1),
        [
            Term(
                term_id="t1",
                concept_id="c1",
                lang="en",
                surface="login",
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            )
        ],
    )
    result = stub.update_term("t1", surface="sign in", register="formal", part_of_speech="verb")
    assert result is True
    updated = next(t for t in stub.all_terms() if t.term_id == "t1")
    assert updated.surface == "sign in"
    assert updated.register == "formal"
    assert updated.part_of_speech == "verb"
    assert (
        stub.update_term("no-such-term", surface="x", register=None, part_of_speech=None) is False
    )


def test_recording_termbase_update_term_blank_surface_raises() -> None:
    from tests.termbase_stub import RecordingTermbase

    stub = RecordingTermbase()
    stub.add_concept(
        Concept(concept_id="c1", qid=None, definition=None, created_at=1),
        [
            Term(
                term_id="t1",
                concept_id="c1",
                lang="en",
                surface="login",
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            )
        ],
    )
    with pytest.raises(ValueError, match="non-blank"):
        stub.update_term("t1", surface="  ", register=None, part_of_speech=None)


def test_partial_update_register_only_preserves_surface(tb: KuzuTermbase) -> None:
    """Cycle-5 S4 P2 regression — partial update must NOT corrupt unspecified
    columns. Before the _UNSET sentinel landed, this call wrote NULL to
    surface and surface_lower because the impl SET every column unconditionally.
    """
    concept_id, term_id = _add_simple(tb)
    before = _lookup_term(tb, term_id)
    assert before is not None
    assert before.surface == "login"

    tb.update_term(term_id, register="formal")

    after = _lookup_term(tb, term_id)
    assert after is not None
    assert after.surface == "login", (
        f"partial update corrupted surface: expected 'login', got {after.surface!r}"
    )
    assert after.register == "formal"
    assert after.part_of_speech is None


def test_partial_update_surface_only_preserves_register(tb: KuzuTermbase) -> None:
    """Cycle-5 S4 P2 regression — partial update must NOT clear other columns.
    Set register first, then update only surface; register must stay."""
    concept_id, term_id = _add_simple(tb)
    tb.update_term(term_id, register="casual", part_of_speech="verb")

    tb.update_term(term_id, surface="sign in")

    after = _lookup_term(tb, term_id)
    assert after is not None
    assert after.surface == "sign in"
    assert after.register == "casual"
    assert after.part_of_speech == "verb"


def test_explicit_none_clears_register(tb: KuzuTermbase) -> None:
    """Passing ``register=None`` explicitly MUST clear the column.
    The _UNSET sentinel distinguishes "leave alone" from "clear to NULL"."""
    concept_id, term_id = _add_simple(tb)
    tb.update_term(term_id, register="formal")

    tb.update_term(term_id, register=None)

    after = _lookup_term(tb, term_id)
    assert after is not None
    assert after.register is None


def test_recording_termbase_partial_update_preserves_surface() -> None:
    """Same regression on the test double — both impls share the contract."""
    from tests.termbase_stub import RecordingTermbase

    stub = RecordingTermbase()
    stub.add_concept(
        Concept(concept_id="c1", qid=None, definition=None, created_at=1),
        [
            Term(
                term_id="t1",
                concept_id="c1",
                lang="en",
                surface="login",
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            )
        ],
    )
    stub.update_term("t1", register="formal")
    updated = next(t for t in stub.all_terms() if t.term_id == "t1")
    assert updated.surface == "login"
    assert updated.register == "formal"
