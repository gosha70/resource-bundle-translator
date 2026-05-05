"""Anthropic Claude provider — cycle-2 Provider Protocol.

Implements :class:`ainemo.providers.base.Provider` against the
Anthropic Messages API (``client.messages.create``). Per the cycle-2
pitch's open-question 4 resolution, the default model is the
**Sonnet 4.5** dated ID — Sonnet is the price/quality sweet spot for
translation; the dated form pins behavior so cost surveillance stays
reproducible.

Quote / whitespace handling mirrors :class:`OpenAIProvider`'s
reviewer-validated logic (cycle-2 P2 follow-up): conditional unwrap
of stray model-emitted quotes only when the source was unquoted; a
single trailing newline is stripped, internal whitespace preserved
verbatim.
"""

from __future__ import annotations

import time
from typing import ClassVar, Final, Mapping

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_ANTHROPIC
from ainemo.providers.anthropic._client import build_client
from ainemo.providers.anthropic._prompts import (
    GLOSSARY_PREFIX,
    SYSTEM_PROMPT,
    USER_MESSAGE_TEMPLATE,
)
from ainemo.providers.base import Provider, ProviderResult

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Default model. Per cycle-2 pitch open-question 4 resolution: dated
# ID per Anthropic docs convention; Sonnet 4.5 (claude-sonnet-4-5-
# 20250929) is the cycle-2 sweet spot for translation cost vs quality.
# Override via constructor or routes.yaml.
DEFAULT_MODEL: Final = "claude-sonnet-4-5-20250929"

# Per-call decoding parameters. Per AGENTS.md § Architecture Rules:
# "Reproducibility by default: temperature 0 across all providers
# unless explicitly overridden."
_TEMPERATURE: Final = 0.0

# Maximum output tokens. Resource-bundle strings are short; 2000
# matches the OpenAI provider headroom and is well under Sonnet 4.5's
# context limit.
DEFAULT_MAX_TOKENS: Final = 2000

# Anthropic Messages API content-block types.
_CONTENT_BLOCK_TYPE_TEXT: Final = "text"
_USER_ROLE: Final = "user"

# USD pricing per 1M tokens, by model id. Keys are dated model IDs
# only — undated aliases shift behind the scenes and would make cost
# surveillance non-deterministic. Models not in this table get
# cost_usd=None on their ProviderResult.
_PRICING_USD_PER_M_TOKENS: Mapping[str, tuple[float, float]] = {
    # (input_per_M, output_per_M) — verify in
    # https://docs.anthropic.com/en/docs/about-claude/pricing before
    # touching.
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-opus-4-1-20250805": (15.00, 75.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
}


class AnthropicProvider:
    """:class:`ainemo.providers.base.Provider` over Anthropic Messages."""

    provider_id: ClassVar[str] = PROVIDER_ID_ANTHROPIC

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: object | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        # `client` is injectable so unit tests pass a mock without
        # hitting the network or needing ANTHROPIC_API_KEY. Production
        # leaves it None and the provider lazily builds a real client
        # on the first translate call.
        self._client = client

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        client = self._get_client()
        user_message = USER_MESSAGE_TEMPLATE.format(
            from_lang=segment.source_lang,
            to_lang=target_lang,
            text=segment.source_text,
        )

        started = time.perf_counter()
        # The Anthropic Messages API takes the system prompt as a
        # top-level kwarg (not as a message), unlike the OpenAI chat
        # API; everything else is the user message.
        response = client.messages.create(  # type: ignore[attr-defined]
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{"role": _USER_ROLE, "content": user_message}],
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        target_text = _extract_target_text(response, segment.source_text)
        input_tokens, output_tokens = _extract_usage(response)
        cost_usd = _estimate_cost(self._model, input_tokens, output_tokens)

        return ProviderResult(
            target_text=target_text,
            provider=self.provider_id,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            cost_usd=cost_usd,
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        # Claude handles every BCP-47 pair we'd realistically translate
        # for software i18n; the SDK doesn't expose a per-pair
        # capability check. Cycle-3+ may add per-language quality
        # gating once benchmark data lands.
        return True

    # --- Internals ---

    def _get_client(self) -> object:
        if self._client is None:
            self._client = build_client()
        return self._client


def _build_glossary_message(forbidden_terms: tuple[str, ...]) -> str:
    """Compose the glossary-injection suffix. Not yet wired into the
    cycle-2 router — kept here for cycle 3's termbase integration so
    the prompt template lives next to the provider."""
    if not forbidden_terms:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + GLOSSARY_PREFIX + ", ".join(forbidden_terms)


def _extract_target_text(response: object, source_text: str) -> str:
    """Pull the assistant's reply out of an Anthropic Messages
    response.

    Anthropic returns ``response.content`` as a list of content blocks
    (TextBlock, ToolUseBlock, etc). For cycle-2 translation we only
    expect text blocks; the first text block's ``text`` field is the
    translation. Same conditional-unwrap and trailing-newline rules
    as the OpenAI provider so cross-provider behavior is uniform.
    """
    content = getattr(response, "content", None)
    if not content:
        raise RuntimeError("Anthropic response had no content blocks.")
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == _CONTENT_BLOCK_TYPE_TEXT:
            text = getattr(block, "text", None)
            if text is None:
                raise RuntimeError("Anthropic text block had no text field.")
            raw = str(text)
            if raw.endswith("\n"):
                raw = raw[:-1]
            return _conditionally_unwrap_quotes(raw, source_text)
    raise RuntimeError("Anthropic response had no text content block.")


def _conditionally_unwrap_quotes(text: str, source_text: str) -> str:
    """Strip ``'`` or ``"`` wrapper added by the model only when the
    source text was not itself wrapped in the same quote character.
    Identical contract to the OpenAI provider's helper — cycle-2
    cross-provider tests pin both."""
    for quote in ('"', "'"):
        wrapped = len(text) >= 2 and text[0] == quote and text[-1] == quote
        source_wrapped = (
            len(source_text) >= 2 and source_text[0] == quote and source_text[-1] == quote
        )
        if wrapped and not source_wrapped:
            return text[1:-1]
    return text


def _extract_usage(response: object) -> tuple[int | None, int | None]:
    """Pull token-usage figures out of the Messages response. Returns
    ``(None, None)`` when the SDK didn't populate ``usage``."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    inp = getattr(usage, "input_tokens", None)
    out = getattr(usage, "output_tokens", None)
    return (
        int(inp) if inp is not None else None,
        int(out) if out is not None else None,
    )


def _estimate_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Multiply the per-1M-token rate by the actual token count.
    Returns ``None`` for unpriced models or when token counts are
    missing — None rather than zero so the "not measured" case stays
    distinguishable in the UsageLog."""
    if input_tokens is None or output_tokens is None:
        return None
    rate = _PRICING_USD_PER_M_TOKENS.get(model)
    if rate is None:
        return None
    input_rate, output_rate = rate
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


# Provider Protocol satisfaction is enforced via runtime_checkable; the
# below assertion documents the cycle-2 contract at module-load time.
_: type[Provider] = AnthropicProvider


__all__ = ["DEFAULT_MODEL", "DEFAULT_MAX_TOKENS", "AnthropicProvider"]
