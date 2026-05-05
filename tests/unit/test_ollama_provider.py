"""Unit tests for :class:`ainemo.providers.ollama.ollama_provider.OllamaProvider`.

Mocks the Ollama Client at the SDK boundary so tests run fast and
don't require a running local daemon. A separate integration test
(gated on a reachable Ollama daemon) exercises the real client; that
lives outside the cycle-2 unit suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_OLLAMA
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.ollama._client import DEFAULT_HOST, ENV_VAR_HOST
from ainemo.providers.ollama.ollama_provider import (
    DEFAULT_MODEL,
    OllamaProvider,
)

# --- Fake SDK client ------------------------------------------------------


@dataclass
class _FakeMessage:
    content: str | None
    role: str = "assistant"


@dataclass
class _FakeChatResponse:
    message: _FakeMessage
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    model: str | None = None


@dataclass
class _FakeOllamaClient:
    response: _FakeChatResponse
    calls: list[dict[str, Any]] = field(default_factory=list)

    def chat(self, **kwargs: Any) -> _FakeChatResponse:
        self.calls.append(kwargs)
        return self.response

    @classmethod
    def with_response(
        cls,
        text: str,
        prompt_eval_count: int | None = 80,
        eval_count: int | None = 40,
    ) -> "_FakeOllamaClient":
        return cls(
            response=_FakeChatResponse(
                message=_FakeMessage(content=text),
                prompt_eval_count=prompt_eval_count,
                eval_count=eval_count,
            )
        )


def _seg(text: str = "Hello, {name}!") -> Segment:
    return Segment(key="k", source_text=text, source_lang="en-US")


# --- Protocol conformance + identity --------------------------------------


def test_satisfies_provider_protocol() -> None:
    p = OllamaProvider(client=_FakeOllamaClient.with_response("Hallo"))
    assert isinstance(p, Provider)
    assert p.provider_id == PROVIDER_ID_OLLAMA
    assert p.provider_id == "ollama"


def test_default_model_is_llama32() -> None:
    """Per cycle-2 pitch open-question 5: ``llama3.2`` default."""
    assert DEFAULT_MODEL == "llama3.2"


def test_default_host_is_localhost_11434() -> None:
    """Matches upstream ``ollama serve`` default."""
    assert DEFAULT_HOST == "http://localhost:11434"


# --- Translate ------------------------------------------------------------


def test_translate_returns_provider_result_with_full_attribution() -> None:
    client = _FakeOllamaClient.with_response("Hallo, {name}!", prompt_eval_count=120, eval_count=8)
    provider = OllamaProvider(client=client)

    result = provider.translate(_seg(), "de-DE")

    assert isinstance(result, ProviderResult)
    assert result.target_text == "Hallo, {name}!"
    assert result.provider == PROVIDER_ID_OLLAMA
    assert result.model == DEFAULT_MODEL
    assert result.input_tokens == 120
    assert result.output_tokens == 8
    assert result.latency_ms >= 0
    # Local execution = no per-call cost.
    assert result.cost_usd is None


def test_translate_uses_temperature_zero_for_reproducibility() -> None:
    """Per AGENTS.md § Architecture Rules: temperature 0 by default.
    Ollama exposes options via ``options=`` kwarg on chat()."""
    client = _FakeOllamaClient.with_response("x")
    OllamaProvider(client=client).translate(_seg(), "de-DE")
    options = client.calls[0]["options"]
    assert options["temperature"] == 0.0


def test_translate_emits_system_prompt_first() -> None:
    """Ollama (unlike Anthropic) takes system prompt as a chat message
    in the messages array — same as OpenAI chat-completions shape."""
    client = _FakeOllamaClient.with_response("x")
    OllamaProvider(client=client).translate(_seg(), "de-DE")
    messages = client.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_translate_includes_source_and_target_lang_in_user_message() -> None:
    client = _FakeOllamaClient.with_response("x")
    OllamaProvider(client=client).translate(_seg("Hello"), "fr-FR")
    user_msg = client.calls[0]["messages"][1]["content"]
    assert "en-US" in user_msg
    assert "fr-FR" in user_msg
    assert "Hello" in user_msg


def test_translate_passes_custom_model() -> None:
    client = _FakeOllamaClient.with_response("x")
    OllamaProvider(model="qwen2.5", client=client).translate(_seg(), "de-DE")
    assert client.calls[0]["model"] == "qwen2.5"


# --- Quote / whitespace handling (mirrors OpenAI/Anthropic contract) ------


def test_translate_unwraps_stray_quotes_when_source_unquoted() -> None:
    client = _FakeOllamaClient.with_response('"Hallo, {name}!"')
    result = OllamaProvider(client=client).translate(_seg(), "de-DE")
    assert result.target_text == "Hallo, {name}!"


def test_translate_unwraps_single_quotes_when_source_unquoted() -> None:
    client = _FakeOllamaClient.with_response("'Hallo'")
    result = OllamaProvider(client=client).translate(_seg(), "de-DE")
    assert result.target_text == "Hallo"


def test_translate_preserves_quoted_source_translation() -> None:
    client = _FakeOllamaClient.with_response('"OK"')
    result = OllamaProvider(client=client).translate(_seg('"OK"'), "de-DE")
    assert result.target_text == '"OK"'


def test_translate_preserves_apostrophe_wrapped_source() -> None:
    client = _FakeOllamaClient.with_response("'OK'")
    result = OllamaProvider(client=client).translate(_seg("'OK'"), "de-DE")
    assert result.target_text == "'OK'"


def test_translate_preserves_internal_quotes() -> None:
    client = _FakeOllamaClient.with_response('Er sagte "Hallo" zu mir.')
    result = OllamaProvider(client=client).translate(_seg('He said "Hi" to me.'), "de-DE")
    assert result.target_text == 'Er sagte "Hallo" zu mir.'


def test_translate_preserves_leading_and_trailing_spaces() -> None:
    client = _FakeOllamaClient.with_response("  Hallo  ")
    result = OllamaProvider(client=client).translate(_seg("  Hello  "), "de-DE")
    assert result.target_text == "  Hallo  "


def test_translate_strips_only_trailing_newline() -> None:
    client = _FakeOllamaClient.with_response("Hallo\n")
    result = OllamaProvider(client=client).translate(_seg("Hello"), "de-DE")
    assert result.target_text == "Hallo"


def test_translate_preserves_internal_newlines() -> None:
    client = _FakeOllamaClient.with_response("Zeile 1\nZeile 2")
    result = OllamaProvider(client=client).translate(_seg("Line 1\nLine 2"), "de-DE")
    assert result.target_text == "Zeile 1\nZeile 2"


def test_translate_preserves_apostrophe_in_body() -> None:
    client = _FakeOllamaClient.with_response("C'est cassé")
    result = OllamaProvider(client=client).translate(_seg("It's broken"), "fr-FR")
    assert result.target_text == "C'est cassé"


# --- Token counts --------------------------------------------------------


def test_translate_missing_token_counts_returns_none() -> None:
    """Some Ollama models / older daemon versions don't populate
    ``prompt_eval_count`` / ``eval_count`` — both fields become None
    so the UsageLog records "not measured" rather than zero."""
    client = _FakeOllamaClient.with_response("Hallo", prompt_eval_count=None, eval_count=None)
    result = OllamaProvider(client=client).translate(_seg(), "de-DE")
    assert result.input_tokens is None
    assert result.output_tokens is None
    # cost_usd is always None for Ollama, regardless of token counts.
    assert result.cost_usd is None


def test_translate_partial_token_counts() -> None:
    """One field populated, the other missing — record what we have."""
    client = _FakeOllamaClient.with_response("Hallo", prompt_eval_count=50, eval_count=None)
    result = OllamaProvider(client=client).translate(_seg(), "de-DE")
    assert result.input_tokens == 50
    assert result.output_tokens is None


# --- supports() -----------------------------------------------------------


def test_supports_returns_true_for_any_pair() -> None:
    """Per-model pair gating lands cycle-3+ once benchmark data tells
    us which pairs are unsafe; for now the local model handles
    whatever it handles."""
    p = OllamaProvider(client=_FakeOllamaClient.with_response("x"))
    assert p.supports("en-US", "de-DE") is True
    assert p.supports("ja-JP", "ar-EG") is True


# --- Empty / malformed responses ------------------------------------------


def test_translate_raises_on_no_message() -> None:
    response = _FakeChatResponse(message=None)  # type: ignore[arg-type]
    client = _FakeOllamaClient(response=response)
    with pytest.raises(RuntimeError, match="no message"):
        OllamaProvider(client=client).translate(_seg(), "de-DE")


def test_translate_raises_on_none_content() -> None:
    response = _FakeChatResponse(message=_FakeMessage(content=None))
    client = _FakeOllamaClient(response=response)
    with pytest.raises(RuntimeError, match="no content"):
        OllamaProvider(client=client).translate(_seg(), "de-DE")


# --- Host configuration ---------------------------------------------------


def test_module_import_does_not_require_running_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-importing the module with neither OLLAMA_HOST nor a daemon
    must succeed — keeps test collection and ``nemo --help`` env-free
    (no network call at module import)."""
    import importlib
    import sys

    monkeypatch.delenv(ENV_VAR_HOST, raising=False)
    sys.modules.pop("ainemo.providers.ollama.ollama_provider", None)
    importlib.import_module("ainemo.providers.ollama.ollama_provider")
