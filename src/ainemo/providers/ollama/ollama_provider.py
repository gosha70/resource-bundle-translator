"""Ollama local-LLM provider — cycle-2 Provider Protocol.

Implements :class:`ainemo.providers.base.Provider` against the
official Ollama Python SDK (``ollama.Client.chat``). Ollama is the
local-first answer for users who want LLM-quality translation without
a HuggingFace download or a cloud API bill.

Per cycle-2 pitch open-question 5: default model is **``llama3.2``**.
Users override via routes.yaml for ``qwen``, ``gemma``, etc.

``cost_usd`` is always ``None`` — local execution has no per-call
billable cost. Token counts come from ``prompt_eval_count`` /
``eval_count`` in the chat response when the underlying Ollama model
populates them; older or modified models may not, in which case both
are ``None`` (the UsageLog distinguishes "not measured" from zero).
"""

from __future__ import annotations

import time
from typing import ClassVar, Final

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_OLLAMA
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.ollama._client import build_client
from ainemo.providers.ollama._prompts import (
    GLOSSARY_PREFIX,
    SYSTEM_PROMPT,
    USER_MESSAGE_TEMPLATE,
)

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Default model. Per cycle-2 pitch open-question 5: ``llama3.2`` —
# the current Ollama default. Override via constructor or routes.yaml.
DEFAULT_MODEL: Final = "llama3.2"

# Per-call decoding parameters. Per AGENTS.md § Architecture Rules:
# "Reproducibility by default: temperature 0 across all providers
# unless explicitly overridden." Ollama exposes options via the
# ``options=`` kwarg on ``chat()``.
_TEMPERATURE: Final = 0.0
_OPTION_KEY_TEMPERATURE: Final = "temperature"

# Chat-message role constants.
_ROLE_SYSTEM: Final = "system"
_ROLE_USER: Final = "user"


class OllamaProvider:
    """:class:`ainemo.providers.base.Provider` over a local Ollama
    daemon."""

    provider_id: ClassVar[str] = PROVIDER_ID_OLLAMA

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        host: str | None = None,
        client: object | None = None,
    ) -> None:
        self._model = model
        self._host = host
        # `client` is injectable so unit tests pass a fake without
        # hitting any HTTP daemon. Production leaves it None and the
        # provider lazily builds a real client on the first translate
        # call.
        self._client = client

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        client = self._get_client()
        user_message = USER_MESSAGE_TEMPLATE.format(
            from_lang=segment.source_lang,
            to_lang=target_lang,
            text=segment.source_text,
        )
        messages = [
            {"role": _ROLE_SYSTEM, "content": SYSTEM_PROMPT},
            {"role": _ROLE_USER, "content": user_message},
        ]

        started = time.perf_counter()
        response = client.chat(  # type: ignore[attr-defined]
            model=self._model,
            messages=messages,
            options={_OPTION_KEY_TEMPERATURE: _TEMPERATURE},
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        target_text = _extract_target_text(response, segment.source_text)
        input_tokens, output_tokens = _extract_usage(response)

        return ProviderResult(
            target_text=target_text,
            provider=self.provider_id,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            cost_usd=None,  # Local execution; no per-call billable cost.
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        # The supported pair set depends on the locally-pulled model
        # (llama3.2 covers most BCP-47 pairs we'd realistically use
        # for software i18n). The SDK doesn't expose a per-model
        # capability check; cycle-3+ may add one once benchmark data
        # tells us which pairs are unsafe.
        return True

    # --- Internals ---

    def _get_client(self) -> object:
        if self._client is None:
            self._client = build_client(self._host)
        return self._client


def _build_glossary_message(forbidden_terms: tuple[str, ...]) -> str:
    """Compose the glossary-injection suffix. Cycle 3 termbase work
    plugs this into the routing layer; kept here so the full prompt
    template lives next to the provider."""
    if not forbidden_terms:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + GLOSSARY_PREFIX + ", ".join(forbidden_terms)


def _extract_target_text(response: object, source_text: str) -> str:
    """Pull the assistant's reply out of an Ollama chat response.

    Ollama's ``ChatResponse`` is a Pydantic model with
    ``response.message.content`` carrying the body. Same conditional-
    unwrap and trailing-newline rules as the OpenAI / Anthropic
    providers so cross-provider behavior is uniform.
    """
    message = getattr(response, "message", None)
    if message is None:
        raise RuntimeError("Ollama response had no message field.")
    content = getattr(message, "content", None)
    if content is None:
        raise RuntimeError("Ollama response message had no content.")
    raw = str(content)
    if raw.endswith("\n"):
        raw = raw[:-1]
    return _conditionally_unwrap_quotes(raw, source_text)


def _conditionally_unwrap_quotes(text: str, source_text: str) -> str:
    """Strip ``'`` or ``"`` wrapper added by the model only when the
    source text was not itself wrapped in the same quote character.
    Identical contract to the OpenAI / Anthropic providers' helpers."""
    for quote in ('"', "'"):
        wrapped = len(text) >= 2 and text[0] == quote and text[-1] == quote
        source_wrapped = (
            len(source_text) >= 2 and source_text[0] == quote and source_text[-1] == quote
        )
        if wrapped and not source_wrapped:
            return text[1:-1]
    return text


def _extract_usage(response: object) -> tuple[int | None, int | None]:
    """Pull token-usage figures out of the chat response. Ollama
    populates ``prompt_eval_count`` (input) and ``eval_count`` (output)
    on most models; older or modified models may omit either, in
    which case the missing field becomes ``None`` so the UsageLog
    records "not measured" rather than zero."""
    prompt = getattr(response, "prompt_eval_count", None)
    completion = getattr(response, "eval_count", None)
    return (
        int(prompt) if prompt is not None else None,
        int(completion) if completion is not None else None,
    )


# Provider Protocol satisfaction is enforced via runtime_checkable; the
# below assertion documents the cycle-2 contract at module-load time.
_: type[Provider] = OllamaProvider


__all__ = ["DEFAULT_MODEL", "OllamaProvider"]
