"""Unit + contract tests for
:class:`ainemo.core.adapters.java_properties.JavaPropertiesAdapter`.

These tests cover the cycle-1 scope-2 contract:

- Parse common ``.properties`` shapes into Segments.
- Round-trip identity: ``parse → serialize → parse`` is identity for a
  set of fixtures including pathological cases (Unicode, escape
  sequences, multi-line values, empty values, comments).
- ICU placeholders extracted correctly (delegating to ``core/icu.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.core.adapters.base import BundleAdapter
from ainemo.core.adapters.java_properties import (
    METADATA_KEY_COMMENT,
    JavaPropertiesAdapter,
)
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    PlaceholderKind,
    Segment,
    TranslatedSegment,
)

# Test-fixture constants — keep in lockstep with the assertions below.
_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"
_PROVIDER_TEST = "test"


# --- Protocol conformance --------------------------------------------------


def test_adapter_satisfies_bundle_adapter_protocol() -> None:
    adapter = JavaPropertiesAdapter()
    assert isinstance(adapter, BundleAdapter)
    assert adapter.format_id == "java-properties"
    assert adapter.file_extensions == (".properties",)


# --- Parsing — happy paths -------------------------------------------------


def test_parse_simple_key_value(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text("greeting=Hello world\n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert len(segments) == 1
    seg = segments[0]
    assert seg.key == "greeting"
    assert seg.source_text == "Hello world"
    assert seg.source_lang == _LANG_EN_US
    assert seg.placeholders == ()


def test_parse_preserves_key_order(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text("third=Third\nfirst=First\nsecond=Second\n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert [s.key for s in segments] == ["third", "first", "second"]


def test_parse_separator_variants(tmp_path: Path) -> None:
    """``=``, ``:``, and whitespace are all valid separators per the
    Properties spec; cycle-1 parser accepts all three."""
    fixture = tmp_path / "messages.properties"
    fixture.write_text(
        "with_equals=value1\nwith_colon:value2\nwith_whitespace value3\n",
        encoding="utf-8",
    )

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert {s.key: s.source_text for s in segments} == {
        "with_equals": "value1",
        "with_colon": "value2",
        "with_whitespace": "value3",
    }


def test_parse_strips_separator_whitespace(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text("  spaced  =  value with spaces  \n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].key == "spaced"
    # Trailing whitespace in value is part of value, not stripped (matches
    # java.util.Properties behavior — leading is stripped, trailing kept,
    # though some implementations differ).
    assert segments[0].source_text.startswith("value with spaces")


# --- Parsing — comments ---------------------------------------------------


def test_comments_attach_to_following_key(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text(
        "# This is the greeting\ngreeting=Hello\n! Another marker\nfarewell=Goodbye\n",
        encoding="utf-8",
    )

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].metadata.get(METADATA_KEY_COMMENT) == "This is the greeting"
    assert segments[1].metadata.get(METADATA_KEY_COMMENT) == "Another marker"


def test_multiple_consecutive_comments_join(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text(
        "# Line one of comment\n# Line two of comment\nkey=value\n",
        encoding="utf-8",
    )

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].metadata[METADATA_KEY_COMMENT] == (
        "Line one of comment\nLine two of comment"
    )


def test_blank_lines_dont_terminate_comments(tmp_path: Path) -> None:
    """Blank lines between comments and the key still let the comment
    attach. Mirrors common editor habits."""
    fixture = tmp_path / "messages.properties"
    fixture.write_text(
        "# Comment text\n\nkey=value\n",
        encoding="utf-8",
    )

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].metadata[METADATA_KEY_COMMENT] == "Comment text"


# --- Parsing — escape sequences -------------------------------------------


def test_parse_decodes_standard_escapes(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text(
        "newline=line1\\nline2\ntab=col1\\tcol2\nbackslash=one\\\\two\n",
        encoding="utf-8",
    )

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    text_by_key = {s.key: s.source_text for s in segments}
    assert text_by_key["newline"] == "line1\nline2"
    assert text_by_key["tab"] == "col1\tcol2"
    assert text_by_key["backslash"] == "one\\two"


def test_parse_decodes_unicode_escapes(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text("hebrew=\\u05E9\\u05DC\\u05D5\\u05DD\n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].source_text == "שלום"


def test_parse_handles_native_unicode(tmp_path: Path) -> None:
    """Modern .properties files frequently embed UTF-8 directly rather
    than \\u-escaping. Cycle-1 supports both."""
    fixture = tmp_path / "messages.properties"
    fixture.write_text("japanese=こんにちは\n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].source_text == "こんにちは"


# --- Parsing — multi-line / continuations --------------------------------


def test_parse_handles_line_continuation(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text(
        "long=part one \\\n    part two \\\n    part three\n",
        encoding="utf-8",
    )

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].source_text == "part one part two part three"


def test_parse_double_backslash_terminates_value(tmp_path: Path) -> None:
    """``\\\\`` is a literal backslash, not a continuation. The next
    line is a separate property."""
    fixture = tmp_path / "messages.properties"
    fixture.write_text("first=ends with backslash\\\\\nsecond=other\n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert {s.key: s.source_text for s in segments} == {
        "first": "ends with backslash\\",
        "second": "other",
    }


# --- Parsing — placeholders extracted via core/icu.py --------------------


def test_parse_extracts_placeholders(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text(
        "welcome=Hello {name}!\nitems={count, plural, one {1 item} other {# items}}\n",
        encoding="utf-8",
    )

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    welcome = next(s for s in segments if s.key == "welcome")
    items = next(s for s in segments if s.key == "items")
    assert len(welcome.placeholders) == 1
    assert welcome.placeholders[0].kind is PlaceholderKind.NAMED
    assert len(items.placeholders) == 1
    assert items.placeholders[0].kind is PlaceholderKind.ICU_PLURAL


# --- Parsing — empty values + edge cases ---------------------------------


def test_parse_empty_value(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text("empty=\nnotempty=value\n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].source_text == ""
    assert segments[1].source_text == "value"


def test_parse_empty_file(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text("", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments == ()


def test_parse_blank_lines_only(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.properties"
    fixture.write_text("\n\n\n", encoding="utf-8")

    segments = JavaPropertiesAdapter().parse(fixture, _LANG_EN_US)
    assert segments == ()


# --- Serialize ------------------------------------------------------------


def _ts(seg: Segment, target_text: str, target_lang: str = _LANG_DE) -> TranslatedSegment:
    return TranslatedSegment(
        segment=seg,
        target_lang=target_lang,
        target_text=target_text,
        provider=_PROVIDER_TEST,
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )


def test_serialize_writes_simple_key_values(tmp_path: Path) -> None:
    src = tmp_path / "messages.properties"
    src.write_text("greeting=Hello\nfarewell=Goodbye\n", encoding="utf-8")

    adapter = JavaPropertiesAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = tuple(_ts(seg, f"DE-{seg.source_text}") for seg in parsed)
    out = tmp_path / "messages_de.properties"
    adapter.serialize(out, translated, _LANG_DE)

    assert out.read_text(encoding="utf-8") == ("greeting=DE-Hello\nfarewell=DE-Goodbye\n")


def test_serialize_emits_comments(tmp_path: Path) -> None:
    src = tmp_path / "messages.properties"
    src.write_text("# Greet the user warmly\ngreeting=Hello\n", encoding="utf-8")

    adapter = JavaPropertiesAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = tuple(_ts(seg, "Hallo") for seg in parsed)
    out = tmp_path / "messages_de.properties"
    adapter.serialize(out, translated, _LANG_DE)

    assert out.read_text(encoding="utf-8") == ("# Greet the user warmly\ngreeting=Hallo\n")


def test_serialize_escapes_special_chars(tmp_path: Path) -> None:
    src = tmp_path / "messages.properties"
    src.write_text("k=v\n", encoding="utf-8")

    adapter = JavaPropertiesAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (_ts(parsed[0], "line1\nline2\twith\\back"),)
    out = tmp_path / "messages_de.properties"
    adapter.serialize(out, translated, _LANG_DE)

    assert out.read_text(encoding="utf-8") == ("k=line1\\nline2\\twith\\\\back\n")


def test_serialize_rejects_target_lang_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "messages.properties"
    src.write_text("k=v\n", encoding="utf-8")

    adapter = JavaPropertiesAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    wrong = (_ts(parsed[0], "x", target_lang="fr-FR"),)
    out = tmp_path / "messages_de.properties"
    with pytest.raises(ValueError):
        adapter.serialize(out, wrong, _LANG_DE)


# --- Round-trip identity --------------------------------------------------


@pytest.mark.parametrize(
    "fixture_text",
    [
        "simple=value\n",
        "k1=v1\nk2=v2\nk3=v3\n",
        "# A comment\nkey=value\n",
        "# multi\n# line\nkey=value\n",
        "with_newline=line1\\nline2\n",
        "with_unicode=שלום\n",
        "empty=\n",
        "with_braces=Hello {name}!\n",
        "with_icu={count, plural, one {1 item} other {# items}}\n",
        "key_with_equals_in_value=k=v\n",
    ],
    ids=[
        "simple",
        "multi-key",
        "single-comment",
        "multi-comment",
        "newline-escape",
        "unicode-native",
        "empty-value",
        "named-placeholder",
        "icu-plural",
        "value-with-equals",
    ],
)
def test_round_trip_identity(tmp_path: Path, fixture_text: str) -> None:
    """parse → serialize → parse must produce the same Segment list
    (modulo translation) for every cycle-1 fixture."""
    src = tmp_path / "messages.properties"
    src.write_text(fixture_text, encoding="utf-8")

    adapter = JavaPropertiesAdapter()
    first_parse = adapter.parse(src, _LANG_EN_US)
    translated = tuple(_ts(seg, seg.source_text) for seg in first_parse)
    out = tmp_path / "messages_de.properties"
    adapter.serialize(out, translated, _LANG_DE)
    second_parse = adapter.parse(out, _LANG_EN_US)

    assert len(first_parse) == len(second_parse)
    for first, second in zip(first_parse, second_parse, strict=True):
        assert first.key == second.key
        assert first.source_text == second.source_text
        assert first.metadata.get(METADATA_KEY_COMMENT) == second.metadata.get(METADATA_KEY_COMMENT)
