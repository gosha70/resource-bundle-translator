"""Unit tests for :class:`ainemo.providers.nllb.nllb_provider.NllbProvider`.

Mocks the HuggingFace pipeline at the module-function boundary so
tests run fast and don't download the 2.5GB NLLB model. A separate
integration test (gated on a pre-cached HF cache) exercises the real
pipeline; that lives outside the cycle-2 unit suite.
"""

from __future__ import annotations

from typing import Any

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_NLLB
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.nllb._client import DEFAULT_MODEL, NllbModelHolder
from ainemo.providers.nllb._languages import (
    supported_bcp47_tags,
    to_nllb_code,
)
from ainemo.providers.nllb.nllb_provider import (
    DEFAULT_MAX_LENGTH,
    NllbProvider,
)

# --- Stub model holder ----------------------------------------------------


class _StubHolder(NllbModelHolder):
    """Holds sentinel objects in place of real HF tokenizer/model.
    The provider passes them to :func:`_translate_with_pipeline`,
    which we monkey-patch in the per-test fixture below."""

    def __init__(self, model_id: str = "test-nllb") -> None:
        super().__init__(model_id=model_id)
        self._loaded = ("__stub_tokenizer__", "__stub_model__")

    def load(self) -> tuple[Any, Any]:
        assert self._loaded is not None  # populated in __init__
        return self._loaded


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Monkey-patch :func:`_translate_with_pipeline` to record calls
    and return a deterministic translation."""
    captured: dict[str, Any] = {"calls": []}

    def _fake_translate_with_pipeline(**kwargs: Any) -> str:
        captured["calls"].append(kwargs)
        return f"[{kwargs['to_code']}] {kwargs['text']}"

    monkeypatch.setattr(
        "ainemo.providers.nllb.nllb_provider._translate_with_pipeline",
        _fake_translate_with_pipeline,
    )
    return captured


def _seg(source_text: str = "Hello", source_lang: str = "en-US") -> Segment:
    return Segment(key="k", source_text=source_text, source_lang=source_lang)


# --- Protocol conformance -------------------------------------------------


def test_satisfies_provider_protocol() -> None:
    p = NllbProvider(model_holder=_StubHolder())
    assert isinstance(p, Provider)
    assert p.provider_id == PROVIDER_ID_NLLB
    assert p.provider_id == "nllb"


def test_default_model_is_nllb_200_distilled() -> None:
    """Cycle-1 baseline carried into cycle 2."""
    assert DEFAULT_MODEL == "facebook/nllb-200-distilled-600M"


# --- Translate ------------------------------------------------------------


def test_translate_returns_provider_result_with_full_attribution(
    stub_pipeline: dict[str, Any],
) -> None:
    holder = _StubHolder(model_id="facebook/nllb-200-distilled-600M")
    result = NllbProvider(model_holder=holder).translate(_seg(), "de-DE")

    assert isinstance(result, ProviderResult)
    assert result.target_text == "[deu_Latn] Hello"
    assert result.provider == PROVIDER_ID_NLLB
    assert result.model == "facebook/nllb-200-distilled-600M"
    # Local model — no token counts and no cost.
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.cost_usd is None
    assert result.latency_ms >= 0


def test_translate_passes_correct_language_codes(
    stub_pipeline: dict[str, Any],
) -> None:
    NllbProvider(model_holder=_StubHolder()).translate(_seg(), "fr-FR")
    call = stub_pipeline["calls"][0]
    assert call["from_code"] == "eng_Latn"
    assert call["to_code"] == "fra_Latn"


def test_translate_passes_max_length(stub_pipeline: dict[str, Any]) -> None:
    NllbProvider(max_length=200, model_holder=_StubHolder()).translate(_seg(), "de-DE")
    assert stub_pipeline["calls"][0]["max_length"] == 200


def test_translate_default_max_length(stub_pipeline: dict[str, Any]) -> None:
    NllbProvider(model_holder=_StubHolder()).translate(_seg(), "de-DE")
    assert stub_pipeline["calls"][0]["max_length"] == DEFAULT_MAX_LENGTH


def test_translate_preserves_segment_text(stub_pipeline: dict[str, Any]) -> None:
    NllbProvider(model_holder=_StubHolder()).translate(_seg("Click {0} to confirm"), "de-DE")
    assert stub_pipeline["calls"][0]["text"] == "Click {0} to confirm"


def test_translate_unsupported_pair_raises(stub_pipeline: dict[str, Any]) -> None:
    """Unknown source or target language → ValueError, not silent
    fallback. The router uses ``supports()`` to gate before calling;
    a direct caller bypassing that check gets a clear error."""
    p = NllbProvider(model_holder=_StubHolder())
    with pytest.raises(ValueError, match="does not support"):
        p.translate(_seg(source_lang="zz-ZZ"), "de-DE")
    with pytest.raises(ValueError, match="does not support"):
        p.translate(_seg(), "zz-ZZ")


# --- supports() -----------------------------------------------------------


def test_supports_known_pair() -> None:
    p = NllbProvider(model_holder=_StubHolder())
    assert p.supports("en-US", "de-DE") is True
    assert p.supports("ja", "ar") is True
    assert p.supports("zh-CN", "zh-HK") is True


def test_supports_unknown_pair_returns_false() -> None:
    p = NllbProvider(model_holder=_StubHolder())
    assert p.supports("en-US", "zz-ZZ") is False
    assert p.supports("zz-ZZ", "de-DE") is False


# --- BCP-47 → NLLB code mapping ------------------------------------------


def test_to_nllb_code_strips_region() -> None:
    """Region tags are stripped — NLLB doesn't differentiate en-US
    from en-GB."""
    assert to_nllb_code("en-US") == "eng_Latn"
    assert to_nllb_code("en-GB") == "eng_Latn"
    assert to_nllb_code("en") == "eng_Latn"


def test_to_nllb_code_case_insensitive() -> None:
    assert to_nllb_code("EN-US") == "eng_Latn"
    assert to_nllb_code("zh-Hans") == "zho_Hans"


def test_to_nllb_code_unknown_returns_none() -> None:
    assert to_nllb_code("zz") is None
    assert to_nllb_code("") is None


def test_to_nllb_code_chinese_variants() -> None:
    """Simplified vs Traditional Chinese must produce different
    NLLB codes — they're different scripts to the model."""
    assert to_nllb_code("zh-CN") == "zho_Hans"
    assert to_nllb_code("zh-TW") == "zho_Hant"
    assert to_nllb_code("zh-HK") == "zho_Hant"


def test_to_nllb_code_hebrew_legacy_alias() -> None:
    """``"iw"`` is Java's Locale code for Hebrew; ``"he"`` is the
    modern ISO code. Both must map."""
    assert to_nllb_code("iw") == "heb_Hebr"
    assert to_nllb_code("he") == "heb_Hebr"


def test_supported_bcp47_tags_returns_sorted() -> None:
    tags = supported_bcp47_tags()
    assert tags == tuple(sorted(tags))
    assert "en" in tags
    assert "de" in tags
    assert "zh-cn" in tags
