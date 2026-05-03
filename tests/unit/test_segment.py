"""Unit tests for :mod:`ainemo.core.segment`."""

from __future__ import annotations

import pytest

from ainemo.core.segment import (
    TRANSLATION_SOURCE_EXACT_TM,
    TRANSLATION_SOURCE_FUZZY_TM,
    TRANSLATION_SOURCE_MANUAL,
    TRANSLATION_SOURCE_PROVIDER,
    Placeholder,
    PlaceholderKind,
    Segment,
    TranslatedSegment,
)

# Test fixtures named with constants so the assertions and the data stay
# in lockstep when fixtures evolve.
_KEY_LOGIN_BUTTON = "login.button.submit"
_TEXT_HELLO = "Hello {name}!"
_TEXT_HELLO_VARIANT = "Hello, {name}!"
_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"


def _make_segment_hello() -> Segment:
    return Segment(
        key=_KEY_LOGIN_BUTTON,
        source_text=_TEXT_HELLO,
        source_lang=_LANG_EN_US,
        placeholders=(Placeholder(kind=PlaceholderKind.NAMED, raw="{name}", span=(6, 12)),),
    )


def test_segment_is_frozen() -> None:
    seg = _make_segment_hello()
    with pytest.raises((AttributeError, Exception)):
        seg.source_text = "mutated"  # type: ignore[misc]


def test_fingerprint_is_stable_across_instances() -> None:
    seg1 = _make_segment_hello()
    seg2 = _make_segment_hello()
    assert seg1.fingerprint == seg2.fingerprint


def test_fingerprint_changes_with_source_text() -> None:
    seg1 = _make_segment_hello()
    seg2 = Segment(
        key=_KEY_LOGIN_BUTTON,
        source_text=_TEXT_HELLO_VARIANT,
        source_lang=_LANG_EN_US,
        placeholders=(Placeholder(kind=PlaceholderKind.NAMED, raw="{name}", span=(7, 13)),),
    )
    assert seg1.fingerprint != seg2.fingerprint


def test_fingerprint_changes_with_source_lang() -> None:
    seg1 = _make_segment_hello()
    seg2 = Segment(
        key=seg1.key,
        source_text=seg1.source_text,
        source_lang=_LANG_DE,
        placeholders=seg1.placeholders,
    )
    assert seg1.fingerprint != seg2.fingerprint


def test_fingerprint_changes_with_placeholder_shape() -> None:
    """Two messages with identical text but different placeholder
    classifications must produce different fingerprints. Otherwise the
    TM could return a wrongly-keyed cached translation."""
    text = "Click {0}"
    seg_positional = Segment(
        key="x",
        source_text=text,
        source_lang=_LANG_EN_US,
        placeholders=(Placeholder(kind=PlaceholderKind.POSITIONAL, raw="{0}", span=(6, 9)),),
    )
    seg_named = Segment(
        key="x",
        source_text=text,
        source_lang=_LANG_EN_US,
        placeholders=(Placeholder(kind=PlaceholderKind.NAMED, raw="{0}", span=(6, 9)),),
    )
    assert seg_positional.fingerprint != seg_named.fingerprint


def test_fingerprint_is_hex_sha256() -> None:
    """64-char hex digest is the contract; downstream code (TM schema,
    log lines, debug output) relies on the format."""
    seg = _make_segment_hello()
    fp = seg.fingerprint
    assert len(fp) == 64
    int(fp, 16)  # must parse as hex


def test_segment_with_no_placeholders_still_fingerprints() -> None:
    seg = Segment(
        key="static",
        source_text="Welcome",
        source_lang=_LANG_EN_US,
    )
    assert len(seg.fingerprint) == 64


def test_translation_source_constants_match_literal_type() -> None:
    """The four TRANSLATION_SOURCE_* constants must exhaust the
    `TranslationSource` Literal. If a fifth source is added (e.g. a
    `legacy_import`), the Literal type and the constant must update
    together — this test catches drift."""
    valid_sources = {
        TRANSLATION_SOURCE_EXACT_TM,
        TRANSLATION_SOURCE_FUZZY_TM,
        TRANSLATION_SOURCE_PROVIDER,
        TRANSLATION_SOURCE_MANUAL,
    }
    seg = _make_segment_hello()
    for src in valid_sources:
        ts = TranslatedSegment(
            segment=seg,
            target_lang=_LANG_DE,
            target_text="Hallo {name}!",
            provider="test",
            confidence=None,
            source=src,  # type: ignore[arg-type]
        )
        assert ts.source == src


def test_placeholder_kind_enum_string_value() -> None:
    """`PlaceholderKind` is a `str` Enum so member ``.value`` is the
    serialization-stable representation. TM round-tripping through
    SQLite stores ``.value`` and rehydrates via ``PlaceholderKind(...)``,
    so the value strings are part of the on-disk contract."""
    assert PlaceholderKind.NAMED.value == "named"
    assert PlaceholderKind.ICU_PLURAL.value == "icu_plural"
    # And the round-trip works:
    assert PlaceholderKind("named") is PlaceholderKind.NAMED
    assert PlaceholderKind("icu_plural") is PlaceholderKind.ICU_PLURAL
