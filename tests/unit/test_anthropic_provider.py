"""Unit tests for :class:`ainemo.providers.anthropic.anthropic_provider.AnthropicProvider`.

Mirrors the OpenAI provider's contract suite so cross-provider behavior
stays uniform — placeholder preservation, conditional quote unwrap,
trailing-newline strip, temperature-0 reproducibility, lazy SDK
construction, defensive empty-response handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_ANTHROPIC
from ainemo.providers.anthropic._client import (
    ENV_VAR_API_KEY,
    MissingAnthropicApiKey,
)
from ainemo.providers.anthropic.anthropic_provider import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    AnthropicProvider,
)
from ainemo.providers.base import Provider, ProviderResult

# --- Fake SDK client (Anthropic Messages API shape) -----------------------


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeResponse:
    content: list[_FakeTextBlock]
    usage: _FakeUsage | None = None


@dataclass
class _FakeMessages:
    response: _FakeResponse
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self.response


@dataclass
class _FakeClient:
    messages: _FakeMessages

    @classmethod
    def with_response(
        cls,
        text: str,
        input_tokens: int = 100,
        output_tokens: int = 50,
        usage: bool = True,
    ) -> "_FakeClient":
        usage_obj = (
            _FakeUsage(input_tokens=input_tokens, output_tokens=output_tokens) if usage else None
        )
        response = _FakeResponse(
            content=[_FakeTextBlock(text=text)],
            usage=usage_obj,
        )
        return cls(messages=_FakeMessages(response=response))

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls


def _seg(text: str = "Hello, {name}!") -> Segment:
    return Segment(key="k", source_text=text, source_lang="en-US")


# --- Protocol conformance + identity --------------------------------------


def test_satisfies_provider_protocol() -> None:
    p = AnthropicProvider(client=_FakeClient.with_response("Hallo"))
    assert isinstance(p, Provider)
    assert p.provider_id == PROVIDER_ID_ANTHROPIC
    assert p.provider_id == "anthropic"


def test_default_model_is_dated_sonnet_4_5() -> None:
    """Per cycle-2 pitch open-question 4: dated ID, Sonnet 4.5."""
    assert DEFAULT_MODEL == "claude-sonnet-4-5-20250929"


# --- Translate ------------------------------------------------------------


def test_translate_returns_provider_result_with_full_attribution() -> None:
    client = _FakeClient.with_response("Hallo, {name}!", input_tokens=120, output_tokens=8)
    provider = AnthropicProvider(client=client)

    result = provider.translate(_seg(), "de-DE")

    assert isinstance(result, ProviderResult)
    assert result.target_text == "Hallo, {name}!"
    assert result.provider == PROVIDER_ID_ANTHROPIC
    assert result.model == DEFAULT_MODEL
    assert result.input_tokens == 120
    assert result.output_tokens == 8
    assert result.latency_ms >= 0
    # claude-sonnet-4-5-20250929: $3.00/M input + $15.00/M output
    expected_cost = (120 * 3.00 + 8 * 15.00) / 1_000_000
    assert result.cost_usd is not None
    assert abs(result.cost_usd - expected_cost) < 1e-12


def test_translate_uses_temperature_zero_for_reproducibility() -> None:
    """Per AGENTS.md § Architecture Rules: temperature 0 by default."""
    client = _FakeClient.with_response("x")
    AnthropicProvider(client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["temperature"] == 0.0


def test_translate_passes_system_at_top_level_not_in_messages() -> None:
    """Anthropic Messages API takes the system prompt as a top-level
    kwarg (unlike OpenAI's chat-completions where it's a message)."""
    client = _FakeClient.with_response("x")
    AnthropicProvider(client=client).translate(_seg(), "de-DE")
    call = client.calls[0]
    assert "system" in call
    assert isinstance(call["system"], str) and call["system"]
    # And no system-role message in the messages array.
    for msg in call["messages"]:
        assert msg["role"] != "system"


def test_translate_includes_source_and_target_lang_in_user_message() -> None:
    client = _FakeClient.with_response("x")
    AnthropicProvider(client=client).translate(_seg("Hello"), "fr-FR")
    user_msg = client.calls[0]["messages"][0]["content"]
    assert "en-US" in user_msg
    assert "fr-FR" in user_msg
    assert "Hello" in user_msg


def test_translate_passes_custom_model() -> None:
    client = _FakeClient.with_response("x")
    AnthropicProvider(model="claude-3-5-haiku-20241022", client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["model"] == "claude-3-5-haiku-20241022"


def test_translate_passes_max_tokens() -> None:
    client = _FakeClient.with_response("x")
    AnthropicProvider(max_tokens=500, client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["max_tokens"] == 500


def test_translate_default_max_tokens() -> None:
    client = _FakeClient.with_response("x")
    AnthropicProvider(client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["max_tokens"] == DEFAULT_MAX_TOKENS


# --- Quote / whitespace handling (mirrors OpenAI provider contract) -------


def test_translate_unwraps_stray_quotes_when_source_unquoted() -> None:
    client = _FakeClient.with_response('"Hallo, {name}!"')
    result = AnthropicProvider(client=client).translate(_seg(), "de-DE")
    assert result.target_text == "Hallo, {name}!"


def test_translate_unwraps_single_quotes_when_source_unquoted() -> None:
    client = _FakeClient.with_response("'Hallo'")
    result = AnthropicProvider(client=client).translate(_seg(), "de-DE")
    assert result.target_text == "Hallo"


def test_translate_preserves_quoted_source_translation() -> None:
    """Cross-provider contract pin: ``"OK"`` whose source is already
    quoted must round-trip with the quotes intact."""
    client = _FakeClient.with_response('"OK"')
    result = AnthropicProvider(client=client).translate(_seg('"OK"'), "de-DE")
    assert result.target_text == '"OK"'


def test_translate_preserves_apostrophe_wrapped_source() -> None:
    client = _FakeClient.with_response("'OK'")
    result = AnthropicProvider(client=client).translate(_seg("'OK'"), "de-DE")
    assert result.target_text == "'OK'"


def test_translate_preserves_internal_quotes() -> None:
    client = _FakeClient.with_response('Er sagte "Hallo" zu mir.')
    result = AnthropicProvider(client=client).translate(_seg('He said "Hi" to me.'), "de-DE")
    assert result.target_text == 'Er sagte "Hallo" zu mir.'


def test_translate_preserves_leading_and_trailing_spaces() -> None:
    client = _FakeClient.with_response("  Hallo  ")
    result = AnthropicProvider(client=client).translate(_seg("  Hello  "), "de-DE")
    assert result.target_text == "  Hallo  "


def test_translate_strips_only_trailing_newline() -> None:
    client = _FakeClient.with_response("Hallo\n")
    result = AnthropicProvider(client=client).translate(_seg("Hello"), "de-DE")
    assert result.target_text == "Hallo"


def test_translate_preserves_internal_newlines() -> None:
    client = _FakeClient.with_response("Zeile 1\nZeile 2")
    result = AnthropicProvider(client=client).translate(_seg("Line 1\nLine 2"), "de-DE")
    assert result.target_text == "Zeile 1\nZeile 2"


def test_translate_preserves_apostrophe_in_body() -> None:
    client = _FakeClient.with_response("C'est cassé")
    result = AnthropicProvider(client=client).translate(_seg("It's broken"), "fr-FR")
    assert result.target_text == "C'est cassé"


# --- Pricing edge cases ---------------------------------------------------


def test_translate_unknown_model_returns_no_cost() -> None:
    """Models not in the pricing table get cost_usd=None."""
    client = _FakeClient.with_response("x")
    result = AnthropicProvider(model="claude-future-9000-preview", client=client).translate(
        _seg(), "de-DE"
    )
    assert result.cost_usd is None


def test_translate_no_usage_field_returns_no_cost() -> None:
    client = _FakeClient.with_response("Hallo", usage=False)
    result = AnthropicProvider(client=client).translate(_seg(), "de-DE")
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.cost_usd is None


# --- supports() -----------------------------------------------------------


def test_supports_returns_true_for_any_pair() -> None:
    p = AnthropicProvider(client=_FakeClient.with_response("x"))
    assert p.supports("en-US", "de-DE") is True
    assert p.supports("ja-JP", "ar-EG") is True


# --- API-key handling -----------------------------------------------------


def test_missing_api_key_raises_on_first_translate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-import is free; first ``translate()`` builds the real
    client which reads the env var. Without it,
    :class:`MissingAnthropicApiKey` propagates with a clear message."""
    monkeypatch.delenv(ENV_VAR_API_KEY, raising=False)
    p = AnthropicProvider()  # no injected client → lazy build
    with pytest.raises(MissingAnthropicApiKey):
        p.translate(_seg(), "de-DE")


def test_module_import_does_not_require_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-import with the env var unset must succeed — keeps test
    collection and ``nemo --help`` env-free."""
    import importlib
    import sys

    monkeypatch.delenv(ENV_VAR_API_KEY, raising=False)
    sys.modules.pop("ainemo.providers.anthropic.anthropic_provider", None)
    importlib.import_module("ainemo.providers.anthropic.anthropic_provider")


# --- Empty / malformed responses ------------------------------------------


def test_translate_raises_on_empty_content() -> None:
    response = _FakeResponse(content=[])
    client = _FakeClient(messages=_FakeMessages(response=response))
    with pytest.raises(RuntimeError, match="no content"):
        AnthropicProvider(client=client).translate(_seg(), "de-DE")


def test_translate_raises_when_no_text_block() -> None:
    """A non-text block (e.g. tool_use) without any text block should
    surface a clear error rather than silently returning an empty
    string."""

    @dataclass
    class _NonText:
        type: str = "tool_use"

    response = _FakeResponse(content=[_NonText()])  # type: ignore[list-item]
    client = _FakeClient(messages=_FakeMessages(response=response))
    with pytest.raises(RuntimeError, match="no text content"):
        AnthropicProvider(client=client).translate(_seg(), "de-DE")
