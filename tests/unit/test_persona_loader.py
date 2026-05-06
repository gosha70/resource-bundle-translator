# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for :mod:`ainemo.core.termbase.persona_loader`.

Cycle-3 S4 contract:

- The three starter YAMLs (``software-ui``, ``formal``, ``casual``)
  load cleanly and produce the expected :class:`Persona` shape.
- Schema enforcement: missing mandatory fields raise; unknown fields
  (notably the dropped ``provider_hints``) raise; filename stem
  mismatch with ``persona_id`` raises.
- ``sync_personas_into_termbase`` is idempotent on re-call.
- :meth:`ForbiddenTermsValidator.from_persona` produces a validator
  equivalent to the legacy constructor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    Segment,
    TranslatedSegment,
)
from ainemo.core.termbase.base import Persona
from ainemo.core.termbase.persona_loader import (
    PersonaLoadError,
    load_personas,
    sync_personas_into_termbase,
)
from ainemo.core.validators.forbidden import ForbiddenTermsValidator
from tests.termbase_stub import RecordingTermbase

pytestmark = pytest.mark.unit


_PACKAGE_PERSONA_DIR = Path(__file__).parent.parent.parent / "src" / "ainemo" / "personas"


# --- Starter YAMLs ---


def test_starter_personas_load() -> None:
    personas = load_personas(_PACKAGE_PERSONA_DIR)
    by_id = {p.persona_id: p for p in personas}
    assert set(by_id) == {"software-ui", "formal", "casual"}


def test_software_ui_persona_shape() -> None:
    personas = {p.persona_id: p for p in load_personas(_PACKAGE_PERSONA_DIR)}
    sw = personas["software-ui"]
    assert sw.name == "Software UI"
    assert sw.domain_id == "software"
    assert sw.register == "neutral"
    assert sw.forbidden_terms == ()
    assert "Preserve every" in sw.prompt_addendum
    assert sw.glossary_overrides == ()


def test_formal_persona_shape() -> None:
    personas = {p.persona_id: p for p in load_personas(_PACKAGE_PERSONA_DIR)}
    formal = personas["formal"]
    assert formal.register == "formal"
    assert formal.domain_id is None
    assert "formal, professional register" in formal.prompt_addendum


def test_casual_persona_shape() -> None:
    personas = {p.persona_id: p for p in load_personas(_PACKAGE_PERSONA_DIR)}
    casual = personas["casual"]
    assert casual.register == "casual"
    assert casual.domain_id is None
    assert "conversational register" in casual.prompt_addendum


def test_load_personas_returns_in_filename_order() -> None:
    # Filenames sort to (casual, formal, software-ui); confirm
    # deterministic startup order (sync_personas_into_termbase
    # relies on this for reproducible add_persona call sequences).
    personas = load_personas(_PACKAGE_PERSONA_DIR)
    assert tuple(p.persona_id for p in personas) == (
        "casual",
        "formal",
        "software-ui",
    )


# --- Schema enforcement ---


def test_missing_mandatory_field_raises(tmp_path: Path) -> None:
    # Drop `prompt_addendum` (mandatory).
    (tmp_path / "broken.yaml").write_text(
        "persona_id: broken\nname: Broken\nforbidden_terms: []\n",
        encoding="utf-8",
    )
    with pytest.raises(PersonaLoadError) as excinfo:
        load_personas(tmp_path)
    assert "broken.yaml" in str(excinfo.value)


def test_missing_forbidden_terms_field_raises(tmp_path: Path) -> None:
    # Regression for the P2 finding: `forbidden_terms` is one of the
    # four mandatory persona YAML fields per the pitch. An *empty*
    # list is explicit and accepted; an *omitted* field is a malformed
    # persona and must surface as a load error rather than silently
    # default to ().
    (tmp_path / "no-fbt.yaml").write_text(
        'persona_id: no-fbt\nname: No Forbidden Terms\nprompt_addendum: "x"\n',
        encoding="utf-8",
    )
    with pytest.raises(PersonaLoadError) as excinfo:
        load_personas(tmp_path)
    assert "forbidden_terms" in str(excinfo.value)


def test_invalid_register_value_is_rejected(tmp_path: Path) -> None:
    # Regression for the P2 finding: register is constrained to
    # ``formal | casual | neutral | null`` per pitch Q2. Any other
    # value (here ``pirate``) must fail at load time rather than
    # land on Persona.register and silently break downstream prompt
    # injection / routing.
    (tmp_path / "bad-register.yaml").write_text(
        "persona_id: bad-register\n"
        "name: Bad Register\n"
        "forbidden_terms: []\n"
        'prompt_addendum: "x"\n'
        "register: pirate\n",
        encoding="utf-8",
    )
    with pytest.raises(PersonaLoadError) as excinfo:
        load_personas(tmp_path)
    msg = str(excinfo.value)
    assert "register" in msg
    assert "pirate" in msg


def test_register_accepts_documented_values(tmp_path: Path) -> None:
    for register in ("formal", "casual", "neutral"):
        path = tmp_path / f"r-{register}.yaml"
        path.write_text(
            f"persona_id: r-{register}\n"
            f'name: "R-{register}"\n'
            "forbidden_terms: []\n"
            'prompt_addendum: "x"\n'
            f"register: {register}\n",
            encoding="utf-8",
        )
    personas = {p.persona_id: p for p in load_personas(tmp_path)}
    assert personas["r-formal"].register == "formal"
    assert personas["r-casual"].register == "casual"
    assert personas["r-neutral"].register == "neutral"


def test_provider_hints_field_is_rejected(tmp_path: Path) -> None:
    # Q2 from /bet: `provider_hints` was dropped. A YAML carrying it
    # must fail loud rather than silently lose data.
    (tmp_path / "rogue.yaml").write_text(
        "persona_id: rogue\n"
        "name: Rogue\n"
        "forbidden_terms: []\n"
        'prompt_addendum: "test"\n'
        "provider_hints:\n"
        "  - openai\n",
        encoding="utf-8",
    )
    with pytest.raises(PersonaLoadError) as excinfo:
        load_personas(tmp_path)
    assert "provider_hints" in str(excinfo.value)


def test_filename_stem_must_match_persona_id(tmp_path: Path) -> None:
    (tmp_path / "alpha.yaml").write_text(
        'persona_id: zulu\nname: Zulu\nforbidden_terms: []\nprompt_addendum: "x"\n',
        encoding="utf-8",
    )
    with pytest.raises(PersonaLoadError) as excinfo:
        load_personas(tmp_path)
    msg = str(excinfo.value)
    assert "alpha" in msg and "zulu" in msg


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    (tmp_path / "scalar.yaml").write_text("just a string\n", encoding="utf-8")
    with pytest.raises(PersonaLoadError) as excinfo:
        load_personas(tmp_path)
    assert "mapping" in str(excinfo.value)


def test_missing_persona_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(PersonaLoadError):
        load_personas(tmp_path / "does-not-exist")


def test_glossary_overrides_load_with_full_schema(tmp_path: Path) -> None:
    (tmp_path / "with-overrides.yaml").write_text(
        "persona_id: with-overrides\n"
        "name: With Overrides\n"
        "forbidden_terms: []\n"
        'prompt_addendum: "x"\n'
        "glossary_overrides:\n"
        "  - source_term: cancel\n"
        "    target_lang: de\n"
        "    target_term: Abbrechen\n"
        "  - source_term: ok\n"
        "    target_lang: fr\n"
        "    target_term: OK\n",
        encoding="utf-8",
    )
    personas = load_personas(tmp_path)
    assert len(personas) == 1
    overrides = personas[0].glossary_overrides
    assert len(overrides) == 2
    assert overrides[0].source_term == "cancel"
    assert overrides[0].target_lang == "de"
    assert overrides[0].target_term == "Abbrechen"


# --- Sync into termbase ---


def test_sync_writes_to_termbase() -> None:
    stub = RecordingTermbase()
    n = sync_personas_into_termbase(stub, _PACKAGE_PERSONA_DIR)
    assert n == 3
    assert set(stub.personas) == {"software-ui", "formal", "casual"}


def test_sync_is_idempotent() -> None:
    stub = RecordingTermbase()
    sync_personas_into_termbase(stub, _PACKAGE_PERSONA_DIR)
    snapshot = {pid: stub.personas[pid] for pid in stub.personas}
    sync_personas_into_termbase(stub, _PACKAGE_PERSONA_DIR)
    assert snapshot == stub.personas
    assert len(stub.personas) == 3


# --- ForbiddenTermsValidator.from_persona ---


def test_forbidden_validator_from_persona_matches_direct_construction() -> None:
    persona = Persona(
        persona_id="brand",
        name="Brand-protected",
        forbidden_terms=("Foo", "Bar"),
        prompt_addendum="x",
    )
    persona_validator = ForbiddenTermsValidator.from_persona(persona)
    direct_validator = ForbiddenTermsValidator(persona.forbidden_terms)

    seg = Segment(key="k", source_text="please use Foo", source_lang="en")
    translated = TranslatedSegment(
        segment=seg,
        target_lang="de",
        target_text="Bitte Foo verwenden",
        provider="noop",
        model="",
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )

    persona_violations = persona_validator.check(seg, translated)
    direct_violations = direct_validator.check(seg, translated)
    assert len(persona_violations) == 1
    assert tuple(v.span for v in persona_violations) == tuple(v.span for v in direct_violations)


def test_forbidden_validator_from_persona_with_empty_terms_list() -> None:
    persona = Persona(
        persona_id="empty",
        name="Empty",
        forbidden_terms=(),
        prompt_addendum="x",
    )
    validator = ForbiddenTermsValidator.from_persona(persona)
    seg = Segment(key="k", source_text="anything", source_lang="en")
    translated = TranslatedSegment(
        segment=seg,
        target_lang="de",
        target_text="anything goes here",
        provider="noop",
        model="",
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )
    assert validator.check(seg, translated) == ()


def test_forbidden_validator_from_persona_respects_match_flags() -> None:
    persona = Persona(
        persona_id="brand",
        name="Brand",
        forbidden_terms=("AI",),
        prompt_addendum="x",
    )
    validator = ForbiddenTermsValidator.from_persona(
        persona, case_insensitive=False, word_boundary=True
    )
    seg = Segment(key="k", source_text="x", source_lang="en")
    # Lowercase "ai" must not match when case_insensitive=False.
    translated = TranslatedSegment(
        segment=seg,
        target_lang="en",
        target_text="this is ai-driven",
        provider="noop",
        model="",
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )
    assert validator.check(seg, translated) == ()
