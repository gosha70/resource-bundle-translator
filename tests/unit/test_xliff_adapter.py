"""Unit + contract tests for
:class:`ainemo.core.adapters.xliff.XliffAdapter`."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from ainemo.core.adapters.base import BundleAdapter
from ainemo.core.adapters.xliff import (
    METADATA_KEY_FILE_ID,
    METADATA_KEY_GROUP_ID,
    METADATA_KEY_NOTE_PREFIX,
    METADATA_KEY_UNIT_ID,
    XliffAdapter,
)
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    PlaceholderKind,
    Segment,
    TranslatedSegment,
)

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"
_PROVIDER_TEST = "test"
_NS = "urn:oasis:names:tc:xliff:document:2.0"


def _ts(seg: Segment, target_text: str, target_lang: str = _LANG_DE) -> TranslatedSegment:
    return TranslatedSegment(
        segment=seg,
        target_lang=target_lang,
        target_text=target_text,
        provider=_PROVIDER_TEST,
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )


def _write_xliff(path: Path, body: str, target_lang: str = _LANG_DE) -> None:
    """Write a minimal XLIFF 2.0 envelope around ``body``."""
    full = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<xliff version="2.0" srcLang="{_LANG_EN_US}" trgLang="{target_lang}" '
        f'xmlns="{_NS}">\n'
        f'  <file id="f1">\n{body}\n  </file>\n'
        "</xliff>\n"
    )
    path.write_text(full, encoding="utf-8")


# --- Protocol conformance --------------------------------------------------


def test_adapter_satisfies_protocol() -> None:
    adapter = XliffAdapter()
    assert isinstance(adapter, BundleAdapter)
    assert adapter.format_id == "xliff-2"
    assert adapter.file_extensions == (".xlf", ".xliff")


# --- Parsing ---------------------------------------------------------------


def test_parse_single_unit_single_segment(tmp_path: Path) -> None:
    src = tmp_path / "messages.xlf"
    _write_xliff(
        src,
        '    <unit id="welcome">\n'
        '      <segment id="s1">\n'
        "        <source>Hello world</source>\n"
        "        <target></target>\n"
        "      </segment>\n"
        "    </unit>",
    )

    segments = XliffAdapter().parse(src, _LANG_EN_US)
    assert len(segments) == 1
    assert segments[0].source_text == "Hello world"
    assert segments[0].key == "welcome#s1"
    assert segments[0].metadata[METADATA_KEY_UNIT_ID] == "welcome"


def test_parse_extracts_placeholders(tmp_path: Path) -> None:
    src = tmp_path / "messages.xlf"
    _write_xliff(
        src,
        '    <unit id="greeting">\n'
        '      <segment id="s1">\n'
        "        <source>Hello {name}!</source>\n"
        "      </segment>\n"
        "    </unit>",
    )

    segments = XliffAdapter().parse(src, _LANG_EN_US)
    assert len(segments[0].placeholders) == 1
    assert segments[0].placeholders[0].kind is PlaceholderKind.NAMED


def test_parse_multiple_units(tmp_path: Path) -> None:
    src = tmp_path / "messages.xlf"
    _write_xliff(
        src,
        '    <unit id="u1"><segment id="s1"><source>One</source></segment></unit>\n'
        '    <unit id="u2"><segment id="s1"><source>Two</source></segment></unit>',
    )

    segments = XliffAdapter().parse(src, _LANG_EN_US)
    assert [s.source_text for s in segments] == ["One", "Two"]
    assert [s.key for s in segments] == ["u1#s1", "u2#s1"]


def test_parse_with_group(tmp_path: Path) -> None:
    src = tmp_path / "messages.xlf"
    _write_xliff(
        src,
        '    <group id="login">\n'
        '      <unit id="u1"><segment id="s1"><source>Sign in</source></segment></unit>\n'
        "    </group>",
    )

    segments = XliffAdapter().parse(src, _LANG_EN_US)
    assert segments[0].metadata[METADATA_KEY_GROUP_ID] == "login"
    assert segments[0].metadata[METADATA_KEY_FILE_ID] == "f1"


def test_parse_preserves_notes(tmp_path: Path) -> None:
    src = tmp_path / "messages.xlf"
    _write_xliff(
        src,
        '    <unit id="welcome">\n'
        "      <notes>\n"
        '        <note category="extracted">UI label for greeting</note>\n'
        '        <note category="reference">src/ui.py:42</note>\n'
        "      </notes>\n"
        '      <segment id="s1"><source>Welcome</source></segment>\n'
        "    </unit>",
    )

    segments = XliffAdapter().parse(src, _LANG_EN_US)
    seg = segments[0]
    assert seg.metadata[f"{METADATA_KEY_NOTE_PREFIX}extracted"] == "UI label for greeting"
    assert seg.metadata[f"{METADATA_KEY_NOTE_PREFIX}reference"] == "src/ui.py:42"


def test_parse_rejects_wrong_root_element(tmp_path: Path) -> None:
    src = tmp_path / "messages.xlf"
    src.write_text('<?xml version="1.0"?>\n<not_xliff/>\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Expected root element"):
        XliffAdapter().parse(src, _LANG_EN_US)


# --- Serialize -------------------------------------------------------------


def test_serialize_basic(tmp_path: Path) -> None:
    src = tmp_path / "en.xlf"
    _write_xliff(
        src,
        '    <unit id="welcome">\n'
        '      <segment id="s1"><source>Welcome</source></segment>\n'
        "    </unit>",
    )

    adapter = XliffAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (_ts(parsed[0], "Willkommen"),)
    out = tmp_path / "de.xlf"
    adapter.serialize(out, translated, _LANG_DE)

    written = etree.parse(str(out))
    root = written.getroot()
    assert root.get("srcLang") == _LANG_EN_US
    assert root.get("trgLang") == _LANG_DE
    target_el = root.find(f".//{{{_NS}}}target")
    assert target_el is not None
    assert target_el.text == "Willkommen"


def test_serialize_preserves_unit_hierarchy(tmp_path: Path) -> None:
    src = tmp_path / "en.xlf"
    _write_xliff(
        src,
        '    <group id="login">\n'
        '      <unit id="u1"><segment id="s1"><source>Sign in</source></segment></unit>\n'
        "    </group>",
    )

    adapter = XliffAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (_ts(parsed[0], "Anmelden"),)
    out = tmp_path / "de.xlf"
    adapter.serialize(out, translated, _LANG_DE)

    written = etree.parse(str(out))
    group_el = written.find(f".//{{{_NS}}}group")
    assert group_el is not None
    assert group_el.get("id") == "login"


def test_serialize_preserves_notes(tmp_path: Path) -> None:
    src = tmp_path / "en.xlf"
    _write_xliff(
        src,
        '    <unit id="welcome">\n'
        "      <notes>\n"
        '        <note category="extracted">UI label</note>\n'
        "      </notes>\n"
        '      <segment id="s1"><source>Welcome</source></segment>\n'
        "    </unit>",
    )

    adapter = XliffAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (_ts(parsed[0], "Willkommen"),)
    out = tmp_path / "de.xlf"
    adapter.serialize(out, translated, _LANG_DE)

    written = etree.parse(str(out))
    note_el = written.find(f".//{{{_NS}}}note")
    assert note_el is not None
    assert note_el.text == "UI label"
    assert note_el.get("category") == "extracted"


def test_serialize_rejects_target_lang_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "en.xlf"
    _write_xliff(
        src,
        '    <unit id="u1">\n      <segment id="s1"><source>k</source></segment>\n    </unit>',
    )

    adapter = XliffAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    wrong = (_ts(parsed[0], "x", target_lang="fr-FR"),)
    out = tmp_path / "de.xlf"
    with pytest.raises(ValueError):
        adapter.serialize(out, wrong, _LANG_DE)


def test_serialize_empty_bundle(tmp_path: Path) -> None:
    """An empty translated tuple still produces a valid XLIFF skeleton
    so downstream tooling does not choke on a missing file."""
    out = tmp_path / "de.xlf"
    XliffAdapter().serialize(out, (), _LANG_DE)
    written = etree.parse(str(out))
    assert written.getroot().get("trgLang") == _LANG_DE


# --- Round-trip identity --------------------------------------------------


@pytest.mark.parametrize(
    "fixture_body",
    [
        '<unit id="u1"><segment id="s1"><source>Hello</source></segment></unit>',
        '<unit id="u1"><segment id="s1"><source>Hello {name}!</source></segment></unit>',
        (
            '<unit id="u1"><segment id="s1"><source>'
            "{count, plural, one {1 item} other {# items}}"
            "</source></segment></unit>"
        ),
        '<unit id="u1"><segment id="s1"><source>こんにちは</source></segment></unit>',
        (
            '<unit id="u1">\n'
            '  <notes><note category="extracted">label</note></notes>\n'
            '  <segment id="s1"><source>Welcome</source></segment>\n'
            "</unit>"
        ),
        (
            '<group id="login">\n'
            '  <unit id="u1"><segment id="s1"><source>Sign in</source></segment></unit>\n'
            '  <unit id="u2"><segment id="s1"><source>Sign out</source></segment></unit>\n'
            "</group>"
        ),
        (
            '<unit id="u1"><segment id="s1"><source>One</source></segment></unit>\n'
            '<unit id="u2"><segment id="s1"><source>Two</source></segment></unit>'
        ),
        '<unit id="u1"><segment id="s1"><source></source></segment></unit>',
        '<unit id="u-with-dashes"><segment id="s1"><source>Dashes ok</source></segment></unit>',
        (
            '<unit id="multi">'
            '<segment id="s1"><source>First</source></segment>'
            '<segment id="s2"><source>Second</source></segment>'
            "</unit>"
        ),
    ],
    ids=[
        "simple",
        "with-named-placeholder",
        "with-icu-plural",
        "unicode",
        "with-notes",
        "in-group-multi-unit",
        "two-units",
        "empty-source",
        "dashed-unit-id",
        "multi-segment-unit",
    ],
)
def test_round_trip_identity(tmp_path: Path, fixture_body: str) -> None:
    indented = "\n".join("    " + line for line in fixture_body.split("\n"))
    src = tmp_path / "messages.xlf"
    _write_xliff(src, indented)

    adapter = XliffAdapter()
    first_parse = adapter.parse(src, _LANG_EN_US)
    translated = tuple(_ts(seg, seg.source_text) for seg in first_parse)
    out = tmp_path / "messages.de.xlf"
    adapter.serialize(out, translated, _LANG_DE)
    second_parse = adapter.parse(out, _LANG_EN_US)

    assert len(first_parse) == len(second_parse)
    for first, second in zip(first_parse, second_parse, strict=True):
        assert first.source_text == second.source_text
        assert first.key == second.key
