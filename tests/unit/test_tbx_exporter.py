# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for :class:`ainemo.core.termbase.tbx.exporter.TbxExporter`.

Cycle-3 S3 contract:

- Output is byte-stable across runs (re-export of an unchanged
  termbase produces identical bytes).
- ``conceptEntry`` rows ordered by ``concept_id`` ascending.
- ``langSec`` groups ordered by ``xml:lang`` ascending.
- ``termSec`` rows ordered by ``(surface, term_id)`` ascending
  (delivered pre-sorted by the Termbase Protocol).
- Empty/None fields are omitted, not written as empty elements.
- ``Concept.definition`` lands on the first ``termSec`` of the
  source-language ``langSec``.
- ``domain_id`` filter restricts export to attached concepts.

The full Weblate-export → import → export round-trip is covered
in the integration test suite; this file pins the per-feature
contract in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from ainemo.core.termbase._ids import TERM_SOURCE_MANUAL
from ainemo.core.termbase.base import Concept, Domain, Term
from ainemo.core.termbase.tbx.exporter import TbxExporter
from tests.termbase_stub import RecordingTermbase

pytestmark = pytest.mark.unit


_TBX_NS = "urn:iso:std:iso:30042:ed-2"
_NSMAP = {"t": _TBX_NS}


# --- Builders ---


def _seed_two_concepts(stub: RecordingTermbase) -> None:
    stub.add_domain(Domain(domain_id="software", parent_id=None, name="Software"))
    stub.add_concept(
        Concept(concept_id="c-cancel", qid=None, definition=None, created_at=1),
        [
            Term(
                term_id="t-cancel-en",
                concept_id="c-cancel",
                lang="en",
                surface="cancel",
                register=None,
                part_of_speech="verb",
                source=TERM_SOURCE_MANUAL,
            ),
            Term(
                term_id="t-cancel-de",
                concept_id="c-cancel",
                lang="de",
                surface="abbrechen",
                register=None,
                part_of_speech="verb",
                source=TERM_SOURCE_MANUAL,
            ),
        ],
    )
    stub.add_concept(
        Concept(
            concept_id="c-login",
            qid="Q11460",
            definition="The act of authenticating.",
            created_at=2,
        ),
        [
            Term(
                term_id="t-login-en",
                concept_id="c-login",
                lang="en",
                surface="login",
                register="neutral",
                part_of_speech="noun",
                source=TERM_SOURCE_MANUAL,
            ),
            Term(
                term_id="t-login-de",
                concept_id="c-login",
                lang="de",
                surface="Anmeldung",
                register=None,
                part_of_speech="noun",
                source=TERM_SOURCE_MANUAL,
            ),
        ],
    )
    stub.attach_concept_to_domain("c-cancel", "software")
    stub.attach_concept_to_domain("c-login", "software")


@pytest.fixture
def stub() -> RecordingTermbase:
    return RecordingTermbase()


# --- Output structure ---


def test_export_is_well_formed_tbx_3(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    assert etree.QName(root).namespace == _TBX_NS
    assert etree.QName(root).localname == "tbx"
    assert root.get("style") == "dca"
    assert root.get("type") == "TBX-Basic"
    assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "en"


def test_export_concept_entries_ordered_by_id(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    ids = [ce.get("id") for ce in root.findall(".//t:conceptEntry", _NSMAP)]
    assert ids == ["c-cancel", "c-login"]


def test_export_lang_secs_ordered_alphabetically(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    login = root.find(".//t:conceptEntry[@id='c-login']", _NSMAP)
    assert login is not None
    langs = [
        ls.get("{http://www.w3.org/XML/1998/namespace}lang")
        for ls in login.findall("t:langSec", _NSMAP)
    ]
    assert langs == ["de", "en"]


def test_export_emits_pos_and_register_term_notes(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    en_login = root.find(
        ".//t:conceptEntry[@id='c-login']/t:langSec[@xml:lang='en']/t:termSec",
        {**_NSMAP, "xml": "http://www.w3.org/XML/1998/namespace"},
    )
    assert en_login is not None
    note_types = [n.get("type") for n in en_login.findall("t:termNote", _NSMAP)]
    assert note_types == ["partOfSpeech", "register"]
    pos = en_login.find("t:termNote[@type='partOfSpeech']", _NSMAP)
    reg = en_login.find("t:termNote[@type='register']", _NSMAP)
    assert pos is not None and pos.text == "noun"
    assert reg is not None and reg.text == "neutral"


def test_export_omits_term_notes_when_field_is_none(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    de_login = root.find(
        ".//t:conceptEntry[@id='c-login']/t:langSec[@xml:lang='de']/t:termSec",
        {**_NSMAP, "xml": "http://www.w3.org/XML/1998/namespace"},
    )
    assert de_login is not None
    # Term has POS but no register on the de side; verify only POS
    # element is emitted and no empty register element.
    note_types = [n.get("type") for n in de_login.findall("t:termNote", _NSMAP)]
    assert note_types == ["partOfSpeech"]


def test_definition_lands_on_source_lang_first_termsec(
    stub: RecordingTermbase,
) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    # Source-lang (en) langSec for c-login: definition present.
    en_def = root.find(
        ".//t:conceptEntry[@id='c-login']/t:langSec[@xml:lang='en']/t:termSec/t:definition",
        {**_NSMAP, "xml": "http://www.w3.org/XML/1998/namespace"},
    )
    assert en_def is not None
    assert en_def.text == "The act of authenticating."
    # Non-source-lang (de) langSec must NOT carry the definition.
    de_def = root.find(
        ".//t:conceptEntry[@id='c-login']/t:langSec[@xml:lang='de']/t:termSec/t:definition",
        {**_NSMAP, "xml": "http://www.w3.org/XML/1998/namespace"},
    )
    assert de_def is None


def test_concept_without_definition_emits_no_definition_element(
    stub: RecordingTermbase,
) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    # c-cancel has no definition.
    defs = root.findall(".//t:conceptEntry[@id='c-cancel']//t:definition", _NSMAP)
    assert defs == []


def test_domain_descrip_one_per_domain_id(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    # Add a second domain to c-login so we can verify multi-domain
    # output.
    stub.add_domain(Domain(domain_id="legal", parent_id=None, name="Legal"))
    stub.attach_concept_to_domain("c-login", "legal")
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    descrips = root.findall(".//t:conceptEntry[@id='c-login']/t:descrip[@type='domain']", _NSMAP)
    # RecordingTermbase sorts domain ids ascending in iter_concept_entries.
    assert [d.text for d in descrips] == ["legal", "software"]


def test_domain_id_filter_narrows_export(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    stub.add_domain(Domain(domain_id="legal", parent_id=None, name="Legal"))
    # Attach c-login to BOTH; c-cancel only to software.
    stub.attach_concept_to_domain("c-login", "legal")
    payload = TbxExporter(stub).export_bytes(domain_id="legal")
    root = etree.fromstring(payload)
    ids = [ce.get("id") for ce in root.findall(".//t:conceptEntry", _NSMAP)]
    assert ids == ["c-login"]


# --- Determinism ---


def test_export_is_byte_stable_across_calls(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    exporter = TbxExporter(stub)
    payload_a = exporter.export_bytes()
    payload_b = exporter.export_bytes()
    assert payload_a == payload_b


def test_export_terms_within_lang_sorted_by_surface(
    stub: RecordingTermbase,
) -> None:
    # Seed three synonyms in en — they should appear in surface order.
    stub.add_concept(
        Concept(concept_id="c-syn", qid=None, definition=None, created_at=1),
        [
            Term(
                term_id=f"t-syn-{i}",
                concept_id="c-syn",
                lang="en",
                surface=surface,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            )
            for i, surface in enumerate(["zebra", "alpha", "mike"])
        ],
    )
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    surfaces = [
        t.text
        for t in root.findall(
            ".//t:conceptEntry[@id='c-syn']/t:langSec/t:termSec/t:term",
            _NSMAP,
        )
    ]
    assert surfaces == ["alpha", "mike", "zebra"]


# --- File entry point ---


def test_export_file_creates_parent_dirs(stub: RecordingTermbase, tmp_path: Path) -> None:
    _seed_two_concepts(stub)
    target = tmp_path / "nested" / "deeper" / "out.tbx"
    TbxExporter(stub).export_file(target)
    assert target.exists()
    payload = target.read_bytes()
    # Sanity: emitted file has the expected XML declaration shape.
    assert payload.startswith(b"<?xml")


def test_export_with_custom_title_and_provenance(stub: RecordingTermbase) -> None:
    _seed_two_concepts(stub)
    exporter = TbxExporter(
        stub,
        title="my-glossary",
        provenance="Cycle-3 round-trip benchmark",
    )
    payload = exporter.export_bytes()
    root = etree.fromstring(payload)
    title_el = root.find(".//t:title", _NSMAP)
    p_el = root.find(".//t:sourceDesc/t:p", _NSMAP)
    assert title_el is not None and title_el.text == "my-glossary"
    assert p_el is not None and p_el.text == "Cycle-3 round-trip benchmark"


def test_export_root_xml_lang_follows_constructor_argument(
    stub: RecordingTermbase,
) -> None:
    _seed_two_concepts(stub)
    payload = TbxExporter(stub, source_lang="de").export_bytes()
    root = etree.fromstring(payload)
    assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "de"
    # Definition would now be expected on the de langSec, not en.
    de_def = root.find(
        ".//t:conceptEntry[@id='c-login']/t:langSec[@xml:lang='de']/t:termSec/t:definition",
        {**_NSMAP, "xml": "http://www.w3.org/XML/1998/namespace"},
    )
    assert de_def is not None
    assert de_def.text == "The act of authenticating."


# --- Empty termbase ---


def test_export_empty_termbase_yields_well_formed_document(
    stub: RecordingTermbase,
) -> None:
    payload = TbxExporter(stub).export_bytes()
    root = etree.fromstring(payload)
    assert root.findall(".//t:conceptEntry", _NSMAP) == []
    body = root.find(".//t:body", _NSMAP)
    assert body is not None
    assert len(list(body)) == 0
