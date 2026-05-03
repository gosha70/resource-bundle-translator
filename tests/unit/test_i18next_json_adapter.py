"""Unit + contract tests for
:class:`ainemo.core.adapters.i18next_json.I18NextJsonAdapter`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainemo.core.adapters.base import BundleAdapter
from ainemo.core.adapters.i18next_json import I18NextJsonAdapter
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    PlaceholderKind,
    Segment,
    TranslatedSegment,
)

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"
_PROVIDER_TEST = "test"


def _ts(seg: Segment, target_text: str, target_lang: str = _LANG_DE) -> TranslatedSegment:
    return TranslatedSegment(
        segment=seg,
        target_lang=target_lang,
        target_text=target_text,
        provider=_PROVIDER_TEST,
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )


def test_adapter_satisfies_protocol() -> None:
    adapter = I18NextJsonAdapter()
    assert isinstance(adapter, BundleAdapter)
    assert adapter.format_id == "i18next-json"
    assert adapter.file_extensions == (".json",)


def test_parse_flat_json(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.json"
    fixture.write_text(
        json.dumps({"login.button.submit": "Submit", "login.button.cancel": "Cancel"}),
        encoding="utf-8",
    )

    segments = I18NextJsonAdapter().parse(fixture, _LANG_EN_US)
    assert {s.key: s.source_text for s in segments} == {
        "login.button.submit": "Submit",
        "login.button.cancel": "Cancel",
    }


def test_parse_nested_json_flattens_to_dot_keys(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.json"
    fixture.write_text(
        json.dumps({"login": {"button": {"submit": "Submit", "cancel": "Cancel"}}}),
        encoding="utf-8",
    )

    segments = I18NextJsonAdapter().parse(fixture, _LANG_EN_US)
    assert {s.key: s.source_text for s in segments} == {
        "login.button.submit": "Submit",
        "login.button.cancel": "Cancel",
    }


def test_parse_extracts_placeholders(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.json"
    fixture.write_text(
        json.dumps(
            {
                "welcome": "Hello {name}!",
                "items": "{count, plural, one {1 item} other {# items}}",
            }
        ),
        encoding="utf-8",
    )

    segments = I18NextJsonAdapter().parse(fixture, _LANG_EN_US)
    by_key = {s.key: s for s in segments}
    assert by_key["welcome"].placeholders[0].kind is PlaceholderKind.NAMED
    assert by_key["items"].placeholders[0].kind is PlaceholderKind.ICU_PLURAL


def test_parse_unicode_native(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.json"
    fixture.write_text(
        json.dumps({"greeting": "こんにちは"}, ensure_ascii=False),
        encoding="utf-8",
    )

    segments = I18NextJsonAdapter().parse(fixture, _LANG_EN_US)
    assert segments[0].source_text == "こんにちは"


def test_parse_rejects_non_object_top_level(tmp_path: Path) -> None:
    fixture = tmp_path / "messages.json"
    fixture.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a JSON object"):
        I18NextJsonAdapter().parse(fixture, _LANG_EN_US)


def test_parse_handles_i18next_plural_suffixes(tmp_path: Path) -> None:
    """i18next's per-suffix plural style. Each suffix is its own
    Segment for cycle 1 — branch-aware decomposition is cycle-2+."""
    fixture = tmp_path / "messages.json"
    fixture.write_text(
        json.dumps(
            {
                "items_one": "1 item",
                "items_other": "{{count}} items",
            }
        ),
        encoding="utf-8",
    )

    segments = I18NextJsonAdapter().parse(fixture, _LANG_EN_US)
    assert {s.key for s in segments} == {"items_one", "items_other"}


def test_serialize_emits_nested_json(tmp_path: Path) -> None:
    src = tmp_path / "en.json"
    src.write_text(
        json.dumps({"login": {"button": {"submit": "Submit"}}}),
        encoding="utf-8",
    )

    adapter = I18NextJsonAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = tuple(_ts(seg, f"DE-{seg.source_text}") for seg in parsed)
    out = tmp_path / "de.json"
    adapter.serialize(out, translated, _LANG_DE)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == {"login": {"button": {"submit": "DE-Submit"}}}


def test_serialize_preserves_unicode_natively(tmp_path: Path) -> None:
    src = tmp_path / "en.json"
    src.write_text(json.dumps({"greeting": "Hello"}), encoding="utf-8")

    adapter = I18NextJsonAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (_ts(parsed[0], "こんにちは", target_lang="ja-JP"),)
    out = tmp_path / "ja.json"
    adapter.serialize(out, translated, "ja-JP")

    raw_text = out.read_text(encoding="utf-8")
    assert "こんにちは" in raw_text
    # And no \u escapes for it:
    assert "\\u" not in raw_text


def test_serialize_rejects_target_lang_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "en.json"
    src.write_text(json.dumps({"k": "v"}), encoding="utf-8")

    adapter = I18NextJsonAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    wrong = (_ts(parsed[0], "x", target_lang="fr-FR"),)
    out = tmp_path / "de.json"
    with pytest.raises(ValueError):
        adapter.serialize(out, wrong, _LANG_DE)


@pytest.mark.parametrize(
    "fixture_payload",
    [
        {"simple": "value"},
        {"k1": "v1", "k2": "v2"},
        {"login": {"button": {"submit": "Submit"}}},
        {"welcome": "Hello {name}!"},
        {"items": "{count, plural, one {1 item} other {# items}}"},
        {"greeting": "こんにちは"},
        {"empty": ""},
        {"deep": {"a": {"b": {"c": {"d": "deep value"}}}}},
        {"items_one": "1 item", "items_other": "{count} items"},
        {"mixed": "Top-level", "nested": {"inner": "Inner value"}},
    ],
    ids=[
        "simple",
        "multi-key-flat",
        "deeply-nested",
        "named-placeholder",
        "icu-plural",
        "unicode",
        "empty-value",
        "very-deep",
        "i18next-suffix-plural",
        "mixed-flat-and-nested",
    ],
)
def test_round_trip_identity(tmp_path: Path, fixture_payload: dict[str, object]) -> None:
    src = tmp_path / "messages.json"
    src.write_text(json.dumps(fixture_payload), encoding="utf-8")

    adapter = I18NextJsonAdapter()
    first_parse = adapter.parse(src, _LANG_EN_US)
    translated = tuple(_ts(seg, seg.source_text) for seg in first_parse)
    out = tmp_path / "messages_de.json"
    adapter.serialize(out, translated, _LANG_DE)
    second_parse = adapter.parse(out, _LANG_EN_US)

    # Round-trip is segment-list-level identity (same flat keys, same
    # values), not file-level byte identity (the source might have
    # been flat but serialize always emits nested).
    assert {s.key: s.source_text for s in first_parse} == {
        s.key: s.source_text for s in second_parse
    }
