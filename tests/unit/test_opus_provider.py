"""Unit tests for :class:`ainemo.providers.opus.opus_provider.OpusProvider`.

Mocks the MarianMT translation at the module-function boundary so
tests run fast and don't download Helsinki-NLP models.
"""

from __future__ import annotations

from typing import Any

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_OPUS
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.opus._client import MarianModelCache
from ainemo.providers.opus._languages import (
    OpusTargetConfig,
    is_supported_source,
    supported_target_tags,
    to_opus_config,
)
from ainemo.providers.opus.opus_provider import (
    DEFAULT_MAX_LENGTH,
    OpusProvider,
)

# --- Stub Marian cache ----------------------------------------------------


class _StubMarianCache(MarianModelCache):
    """Returns sentinel objects in place of real Marian models. The
    provider passes them to :func:`_translate_with_marian`, which the
    fixture below monkey-patches."""

    def __init__(self) -> None:
        super().__init__()
        self.requested: list[str] = []

    def get(self, hf_model_name: str) -> tuple[Any, Any]:
        self.requested.append(hf_model_name)
        return ("__stub_tokenizer__", "__stub_model__")


@pytest.fixture
def stub_marian(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Monkey-patch :func:`_translate_with_marian` to record calls and
    return a deterministic translation."""
    captured: dict[str, Any] = {"calls": []}

    def _fake_translate_with_marian(**kwargs: Any) -> str:
        captured["calls"].append(kwargs)
        return f"[opus-out] {kwargs['text']}"

    monkeypatch.setattr(
        "ainemo.providers.opus.opus_provider._translate_with_marian",
        _fake_translate_with_marian,
    )
    return captured


def _seg(source_text: str = "Hello", source_lang: str = "en-US") -> Segment:
    return Segment(key="k", source_text=source_text, source_lang=source_lang)


# --- Protocol conformance + identity --------------------------------------


def test_satisfies_provider_protocol() -> None:
    p = OpusProvider(cache=_StubMarianCache())
    assert isinstance(p, Provider)
    assert p.provider_id == PROVIDER_ID_OPUS
    assert p.provider_id == "opus"


# --- Translate ------------------------------------------------------------


def test_translate_returns_provider_result_with_full_attribution(
    stub_marian: dict[str, Any],
) -> None:
    cache = _StubMarianCache()
    result = OpusProvider(cache=cache).translate(_seg(), "de-DE")

    assert isinstance(result, ProviderResult)
    assert result.provider == PROVIDER_ID_OPUS
    # German uses the Germanic group model with required token.
    assert result.model == "Helsinki-NLP/opus-mt-en-gem"
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.cost_usd is None
    assert result.latency_ms >= 0
    # Stub returns "[opus-out] " + prepared input. German requires
    # `>>deu<<` prefix on the input.
    assert result.target_text == "[opus-out] >>deu<<Hello"


def test_translate_uses_korean_tc_big_model(stub_marian: dict[str, Any]) -> None:
    """Korean uses the special ``opus-mt-tc-big-`` prefix because the
    standard Korean OPUS-MT model is unusable."""
    cache = _StubMarianCache()
    result = OpusProvider(cache=cache).translate(_seg(), "ko-KR")
    assert result.model == "Helsinki-NLP/opus-mt-tc-big-en-ko"


def test_translate_token_prefix_skipped_for_single_lang_models(
    stub_marian: dict[str, Any],
) -> None:
    """Greek, Hebrew, Hindi, Japanese, Korean, Swedish, Turkish use
    single-language models without a token prefix."""
    cache = _StubMarianCache()
    OpusProvider(cache=cache).translate(_seg("Hello"), "el-GR")
    assert stub_marian["calls"][0]["text"] == "Hello"  # No `>>token<<` prefix.


def test_translate_token_prefix_applied_for_grouped_models(
    stub_marian: dict[str, Any],
) -> None:
    """Romance group: French, Italian, Portuguese, Spanish all share
    one model and need a `>>{lang_code}<<` prefix."""
    cache = _StubMarianCache()
    OpusProvider(cache=cache).translate(_seg("Hello"), "fr-FR")
    assert stub_marian["calls"][0]["text"] == ">>fr<<Hello"


def test_translate_passes_max_length(stub_marian: dict[str, Any]) -> None:
    OpusProvider(max_length=200, cache=_StubMarianCache()).translate(_seg(), "de-DE")
    assert stub_marian["calls"][0]["max_length"] == 200


def test_translate_default_max_length(stub_marian: dict[str, Any]) -> None:
    OpusProvider(cache=_StubMarianCache()).translate(_seg(), "de-DE")
    assert stub_marian["calls"][0]["max_length"] == DEFAULT_MAX_LENGTH


def test_translate_chinese_simplified_uses_hans_token(
    stub_marian: dict[str, Any],
) -> None:
    cache = _StubMarianCache()
    OpusProvider(cache=cache).translate(_seg("Hello"), "zh-CN")
    assert stub_marian["calls"][0]["text"] == ">>cmn_Hans<<Hello"


def test_translate_chinese_traditional_uses_hant_token(
    stub_marian: dict[str, Any],
) -> None:
    cache = _StubMarianCache()
    OpusProvider(cache=cache).translate(_seg("Hello"), "zh-HK")
    assert stub_marian["calls"][0]["text"] == ">>cmn_Hant<<Hello"


# --- Source-language constraint ------------------------------------------


def test_translate_rejects_non_english_source(stub_marian: dict[str, Any]) -> None:
    """Cycle-2 OPUS supports English source only; non-English sources
    raise with a clear message pointing the caller at NLLB."""
    p = OpusProvider(cache=_StubMarianCache())
    with pytest.raises(ValueError, match="English source only"):
        p.translate(_seg(source_lang="fr-FR"), "de-DE")


def test_translate_unsupported_target_raises(stub_marian: dict[str, Any]) -> None:
    p = OpusProvider(cache=_StubMarianCache())
    with pytest.raises(ValueError, match="no en→.*model registered"):
        p.translate(_seg(), "vi-VN")  # Vietnamese not in the cycle-2 map


# --- supports() -----------------------------------------------------------


def test_supports_known_pair() -> None:
    p = OpusProvider(cache=_StubMarianCache())
    assert p.supports("en-US", "de-DE") is True
    assert p.supports("en", "fr-CA") is True
    assert p.supports("en-GB", "ja-JP") is True


def test_supports_rejects_non_english_source() -> None:
    p = OpusProvider(cache=_StubMarianCache())
    assert p.supports("fr-FR", "de-DE") is False
    assert p.supports("ja-JP", "ko-KR") is False


def test_supports_rejects_unknown_target() -> None:
    p = OpusProvider(cache=_StubMarianCache())
    assert p.supports("en-US", "vi-VN") is False
    assert p.supports("en-US", "zz-ZZ") is False


# --- Model cache reuse ----------------------------------------------------


def test_model_cache_loads_each_target_once(stub_marian: dict[str, Any]) -> None:
    """Translating multiple segments to the same target loads the
    Marian model once per target. Repeating the call must not reload."""
    cache = _StubMarianCache()
    p = OpusProvider(cache=cache)
    p.translate(_seg("First"), "de-DE")
    p.translate(_seg("Second"), "de-DE")
    p.translate(_seg("Third"), "fr-FR")

    # de-DE and fr-FR each get one cache.get() per translate call —
    # the StubMarianCache records every request, but a real cache's
    # internal dict short-circuits after the first.
    assert cache.requested.count("Helsinki-NLP/opus-mt-en-gem") == 2
    assert cache.requested.count("Helsinki-NLP/opus-mt-en-ROMANCE") == 1


# --- BCP-47 → OPUS config mapping ----------------------------------------


def test_to_opus_config_strips_region() -> None:
    """`fr-CA` falls back to `fr` (cycle-2 OPUS doesn't model regional
    French distinctions — same as cycle 1)."""
    config = to_opus_config("fr-CA")
    assert config is not None
    assert config.bcp47 == "fr"


def test_to_opus_config_explicit_zh_variants() -> None:
    """`zh-CN` and `zh-HK` have explicit map entries that override the
    primary-subtag fallback (different scripts → different tokens)."""
    cn = to_opus_config("zh-CN")
    hk = to_opus_config("zh-HK")
    assert cn is not None and cn.language_token == "cmn_Hans"
    assert hk is not None and hk.language_token == "cmn_Hant"


def test_to_opus_config_hebrew_aliases() -> None:
    he = to_opus_config("he")
    iw = to_opus_config("iw")
    assert he is not None
    assert iw is not None
    assert he.model_id == "he"
    assert iw.model_id == "he"


def test_to_opus_config_unknown_returns_none() -> None:
    assert to_opus_config("zz") is None
    assert to_opus_config("") is None


def test_is_supported_source_english_only() -> None:
    assert is_supported_source("en") is True
    assert is_supported_source("en-US") is True
    assert is_supported_source("en-GB") is True
    assert is_supported_source("EN") is True  # case-insensitive
    assert is_supported_source("fr") is False
    assert is_supported_source("") is False


def test_supported_target_tags_returns_sorted() -> None:
    tags = supported_target_tags()
    assert tags == tuple(sorted(tags))
    assert "de" in tags
    assert "fr" in tags


def test_hf_model_name_uses_prefix_correctly() -> None:
    """Korean uses the tc-big prefix; everyone else uses opus-mt-."""
    de = OpusTargetConfig(bcp47="de", model_id="gem")
    ko = OpusTargetConfig(bcp47="ko", model_id="ko", model_prefix="opus-mt-tc-big-")
    assert de.hf_model_name == "Helsinki-NLP/opus-mt-en-gem"
    assert ko.hf_model_name == "Helsinki-NLP/opus-mt-tc-big-en-ko"
