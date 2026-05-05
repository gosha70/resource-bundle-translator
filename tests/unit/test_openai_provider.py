"""Unit tests for :class:`ainemo.providers.openai.openai_provider.OpenAIProvider`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_OPENAI
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.openai._client import ENV_VAR_API_KEY, MissingOpenAiApiKey
from ainemo.providers.openai.openai_provider import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    OpenAIProvider,
)

# --- Fake SDK client ------------------------------------------------------


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _FakeMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage | None = None


@dataclass
class _FakeCompletions:
    response: _FakeResponse
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self.response


@dataclass
class _FakeChat:
    completions: _FakeCompletions


@dataclass
class _FakeClient:
    chat: _FakeChat

    @classmethod
    def with_response(
        cls,
        text: str,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
        usage: bool = True,
    ) -> "_FakeClient":
        usage_obj = (
            _FakeUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
            if usage
            else None
        )
        response = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=text))],
            usage=usage_obj,
        )
        return cls(chat=_FakeChat(completions=_FakeCompletions(response=response)))

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.chat.completions.calls


def _seg(text: str = "Hello, {name}!") -> Segment:
    return Segment(key="k", source_text=text, source_lang="en-US")


# --- Protocol conformance + identity --------------------------------------


def test_satisfies_provider_protocol() -> None:
    p = OpenAIProvider(client=_FakeClient.with_response("Hallo"))
    assert isinstance(p, Provider)
    assert p.provider_id == PROVIDER_ID_OPENAI
    assert p.provider_id == "openai"


def test_default_model_is_dated_gpt_4o() -> None:
    """Per cycle-2 pitch open-question 4: default is the dated
    ``gpt-4o-2024-11-20`` ID, not an undated alias."""
    assert DEFAULT_MODEL == "gpt-4o-2024-11-20"


# --- Translate ------------------------------------------------------------


def test_translate_returns_provider_result_with_full_attribution() -> None:
    client = _FakeClient.with_response("Hallo, {name}!", prompt_tokens=120, completion_tokens=8)
    provider = OpenAIProvider(client=client)

    result = provider.translate(_seg(), "de-DE")

    assert isinstance(result, ProviderResult)
    assert result.target_text == "Hallo, {name}!"
    assert result.provider == PROVIDER_ID_OPENAI
    assert result.model == DEFAULT_MODEL
    assert result.input_tokens == 120
    assert result.output_tokens == 8
    assert result.latency_ms >= 0
    # gpt-4o-2024-11-20: $2.50/M input + $10.00/M output
    expected_cost = (120 * 2.50 + 8 * 10.00) / 1_000_000
    assert result.cost_usd is not None
    assert abs(result.cost_usd - expected_cost) < 1e-12


def test_translate_unwraps_stray_quotes_when_source_unquoted() -> None:
    """LLMs occasionally wrap output in quotes despite the prompt
    saying not to. When the source was NOT itself quoted, the wrapper
    is stripped."""
    client = _FakeClient.with_response('"Hallo, {name}!"')
    result = OpenAIProvider(client=client).translate(_seg(), "de-DE")
    assert result.target_text == "Hallo, {name}!"


def test_translate_unwraps_single_quotes_when_source_unquoted() -> None:
    client = _FakeClient.with_response("'Hallo'")
    result = OpenAIProvider(client=client).translate(_seg(), "de-DE")
    assert result.target_text == "Hallo"


def test_translate_preserves_quoted_source_translation() -> None:
    """Cycle-2 contract pin: a button label like ``"OK"`` whose source
    text is itself wrapped in quotes must round-trip with the quotes
    intact. The cycle-1 unconditional `.strip("'\\"")` would have
    corrupted the bundle; cycle 2 only unwraps when the source was
    unquoted."""
    client = _FakeClient.with_response('"OK"')
    result = OpenAIProvider(client=client).translate(_seg('"OK"'), "de-DE")
    assert result.target_text == '"OK"'


def test_translate_preserves_apostrophe_wrapped_source() -> None:
    client = _FakeClient.with_response("'OK'")
    result = OpenAIProvider(client=client).translate(_seg("'OK'"), "de-DE")
    assert result.target_text == "'OK'"


def test_translate_preserves_internal_quotes() -> None:
    """Quotes inside the body — not at the edges — are always
    preserved, regardless of source shape."""
    client = _FakeClient.with_response('Er sagte "Hallo" zu mir.')
    result = OpenAIProvider(client=client).translate(_seg('He said "Hi" to me.'), "de-DE")
    assert result.target_text == 'Er sagte "Hallo" zu mir.'


def test_translate_preserves_leading_and_trailing_spaces() -> None:
    """Bundle strings sometimes carry intentional padding for UI
    alignment (e.g. ``" Submit "``). The provider must not strip it."""
    client = _FakeClient.with_response("  Hallo  ")
    result = OpenAIProvider(client=client).translate(_seg("  Hello  "), "de-DE")
    assert result.target_text == "  Hallo  "


def test_translate_strips_only_trailing_newline() -> None:
    """Many SDKs append a terminating newline that isn't part of the
    translation; the provider strips exactly one trailing ``\\n`` and
    nothing else."""
    client = _FakeClient.with_response("Hallo\n")
    result = OpenAIProvider(client=client).translate(_seg("Hello"), "de-DE")
    assert result.target_text == "Hallo"


def test_translate_preserves_internal_newlines() -> None:
    """Multi-line bundle values (rare but legal) must round-trip their
    internal newlines."""
    client = _FakeClient.with_response("Zeile 1\nZeile 2")
    result = OpenAIProvider(client=client).translate(_seg("Line 1\nLine 2"), "de-DE")
    assert result.target_text == "Zeile 1\nZeile 2"


def test_translate_preserves_apostrophe_in_body() -> None:
    """Apostrophes inside the body — possessives, contractions —
    are never stripped."""
    client = _FakeClient.with_response("C'est cassé")
    result = OpenAIProvider(client=client).translate(_seg("It's broken"), "fr-FR")
    assert result.target_text == "C'est cassé"


def test_translate_uses_temperature_zero_for_reproducibility() -> None:
    """Per AGENTS.md § Architecture Rules: temperature 0 by default."""
    client = _FakeClient.with_response("x")
    OpenAIProvider(client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["temperature"] == 0.0


def test_translate_passes_custom_model() -> None:
    client = _FakeClient.with_response("x")
    OpenAIProvider(model="gpt-4o-mini-2024-07-18", client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["model"] == "gpt-4o-mini-2024-07-18"


def test_translate_passes_max_tokens() -> None:
    client = _FakeClient.with_response("x")
    OpenAIProvider(max_tokens=500, client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["max_tokens"] == 500


def test_translate_default_max_tokens() -> None:
    client = _FakeClient.with_response("x")
    OpenAIProvider(client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["max_tokens"] == DEFAULT_MAX_TOKENS


def test_translate_includes_source_and_target_lang_in_user_message() -> None:
    client = _FakeClient.with_response("x")
    OpenAIProvider(client=client).translate(_seg("Hello"), "fr-FR")
    user_msg = client.calls[0]["messages"][1]["content"]
    assert "en-US" in user_msg
    assert "fr-FR" in user_msg
    assert "Hello" in user_msg


def test_translate_emits_system_prompt_first() -> None:
    client = _FakeClient.with_response("x")
    OpenAIProvider(client=client).translate(_seg(), "de-DE")
    messages = client.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


# --- Pricing edge cases ---------------------------------------------------


def test_translate_unknown_model_returns_no_cost() -> None:
    """Models not in the pricing table get cost_usd=None — the
    UsageLog distinguishes "not priced" from zero cost."""
    client = _FakeClient.with_response("x")
    result = OpenAIProvider(model="gpt-future-9000-preview", client=client).translate(
        _seg(), "de-DE"
    )
    assert result.cost_usd is None


def test_translate_no_usage_field_returns_no_cost() -> None:
    """Defensive: SDK responses without the usage field still produce
    a valid ProviderResult — tokens and cost are None."""
    client = _FakeClient.with_response("Hallo", usage=False)
    result = OpenAIProvider(client=client).translate(_seg(), "de-DE")
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.cost_usd is None


# --- supports() -----------------------------------------------------------


def test_supports_returns_true_for_any_pair() -> None:
    """GPT-4o handles every BCP-47 pair we'd realistically translate
    for software i18n; no per-pair gating in cycle 2."""
    p = OpenAIProvider(client=_FakeClient.with_response("x"))
    assert p.supports("en-US", "de-DE") is True
    assert p.supports("ja-JP", "ar-EG") is True


# --- API-key handling -----------------------------------------------------


def test_missing_api_key_raises_on_first_translate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-import is free; first ``translate()`` builds the real
    client, which reads the env var. Without it, MissingOpenAiApiKey
    propagates with a clear remediation message."""
    monkeypatch.delenv(ENV_VAR_API_KEY, raising=False)
    p = OpenAIProvider()  # no injected client → lazy build
    with pytest.raises(MissingOpenAiApiKey):
        p.translate(_seg(), "de-DE")


def test_module_import_does_not_require_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-import with the env var unset must succeed — the fix from
    cycle 0 P1 stays intact in cycle 2."""
    import importlib
    import sys

    monkeypatch.delenv(ENV_VAR_API_KEY, raising=False)
    sys.modules.pop("ainemo.providers.openai.openai_provider", None)
    importlib.import_module("ainemo.providers.openai.openai_provider")


# --- Empty / malformed responses ------------------------------------------


def test_translate_raises_on_empty_choices() -> None:
    """Defensive: an empty ``choices`` array would otherwise cause an
    IndexError. Surface a clear message instead."""
    response = _FakeResponse(choices=[])
    client = _FakeClient(chat=_FakeChat(completions=_FakeCompletions(response=response)))
    with pytest.raises(RuntimeError, match="no choices"):
        OpenAIProvider(client=client).translate(_seg(), "de-DE")


def test_translate_raises_on_none_content() -> None:
    response = _FakeResponse(choices=[_FakeChoice(message=_FakeMessage(content=None))])
    client = _FakeClient(chat=_FakeChat(completions=_FakeCompletions(response=response)))
    with pytest.raises(RuntimeError, match="no content"):
        OpenAIProvider(client=client).translate(_seg(), "de-DE")
