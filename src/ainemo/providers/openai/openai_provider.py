"""OpenAI managed-translation provider — cycle-2 Protocol.

Implements :class:`ainemo.providers.base.Provider` against the OpenAI
chat-completions API. Per the cycle-2 pitch's open-question 4
resolution: default model is ``gpt-4o-2024-11-20``; configurable via
constructor or routes.yaml.
"""

from __future__ import annotations

import time
from typing import ClassVar, Final, Mapping

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_OPENAI
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.openai._client import build_client
from ainemo.providers.openai._prompts import (
    GLOSSARY_PREFIX,
    SYSTEM_PROMPT,
    USER_MESSAGE_TEMPLATE,
)

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Default model. Per cycle-2 pitch open-question 4: dated ID per
# Anthropic/OpenAI docs convention; ``gpt-4o-2024-11-20`` was the
# current GPT-4o snapshot at build time. Override via constructor.
DEFAULT_MODEL: Final = "gpt-4o-2024-11-20"

# Per-call decoding parameters. Per AGENTS.md § Architecture Rules:
# "Reproducibility by default: temperature 0 across all providers
# unless explicitly overridden."
_TEMPERATURE: Final = 0.0
_TOP_P: Final = 1.0
_FREQUENCY_PENALTY: Final = 0.0
_PRESENCE_PENALTY: Final = 0.0

# Maximum tokens for the translation response. Resource-bundle
# strings are short; 2000 is comfortable headroom for any single
# segment including ICU plurals with multiple branches.
DEFAULT_MAX_TOKENS: Final = 2000

# USD pricing per 1M tokens, by model id. Keys are dated model IDs
# only — undated aliases (e.g. "gpt-4o") shift behind the scenes
# and would make cost surveillance non-deterministic. Models not in
# this table get cost_usd=None on their ProviderResult; the cycle-3+
# upgrade adds entries as new models ship.
_PRICING_USD_PER_M_TOKENS: Mapping[str, tuple[float, float]] = {
    # (input_per_M, output_per_M) — verify in
    # https://platform.openai.com/docs/pricing before touching.
    "gpt-4o-2024-11-20": (2.50, 10.00),
    "gpt-4o-2024-08-06": (2.50, 10.00),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "gpt-4-turbo-2024-04-09": (10.00, 30.00),
}


class OpenAIProvider:
    """:class:`ainemo.providers.base.Provider` over OpenAI chat
    completions."""

    provider_id: ClassVar[str] = PROVIDER_ID_OPENAI

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
        # hitting the network or needing OPENAI_API_KEY. Production
        # leaves it None and the provider lazily builds a real client
        # on the first translate call (also keeps __init__ cheap and
        # env-var-free at import time).
        self._client = client

    def translate(
        self,
        segment: Segment,
        target_lang: str,
        *,
        system_prompt_addendum: str | None = None,
    ) -> ProviderResult:
        client = self._get_client()
        # Cycle-3 S6: persona + termbase glossary block lands as a
        # system-prompt addendum when the pipeline is wired with a
        # termbase / persona. None preserves cycle-2 behavior.
        system_prompt = (
            SYSTEM_PROMPT
            if not system_prompt_addendum
            else f"{SYSTEM_PROMPT}\n\n{system_prompt_addendum}"
        )
        user_message = USER_MESSAGE_TEMPLATE.format(
            from_lang=segment.source_lang,
            to_lang=target_lang,
            text=segment.source_text,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        started = time.perf_counter()
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=self._model,
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=_TEMPERATURE,
            top_p=_TOP_P,
            frequency_penalty=_FREQUENCY_PENALTY,
            presence_penalty=_PRESENCE_PENALTY,
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
        # GPT-4o handles every BCP-47 pair we'd realistically translate
        # for software i18n; the SDK doesn't expose a per-pair
        # capability check. Cycle-3+ may add per-language quality
        # gating as benchmark data lands.
        return True

    # --- Internals ---

    def _get_client(self) -> object:
        if self._client is None:
            self._client = build_client()
        return self._client


def _build_glossary_message(forbidden_terms: tuple[str, ...]) -> str:
    """Helper to compose the glossary-injection suffix. Not yet wired
    into the cycle-2 router — kept here for cycle 3's termbase
    integration so the prompt template lives next to the provider."""
    if not forbidden_terms:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + GLOSSARY_PREFIX + ", ".join(forbidden_terms)


def _extract_target_text(response: object, source_text: str) -> str:
    """Pull the assistant's reply out of an OpenAI chat-completion
    response.

    The model output is preserved **verbatim** with two narrow
    transport-level cleanups:

    1. A single trailing ``"\\n"`` is stripped — many SDKs append a
       terminator that isn't part of the translation. Internal
       whitespace and other trailing whitespace (a literal trailing
       space the source had) is always preserved.
    2. **Conditional** quote unwrap: if the model wrapped the entire
       response in matching ``'`` or ``"`` and the source text was
       NOT itself wrapped in the same quote character, the wrapper
       is removed. This handles the LLM-misbehaves-despite-prompt
       case without corrupting legitimately-quoted bundle strings
       — button labels like ``"OK"`` and UI text the source author
       intentionally quoted are preserved.

    Internal whitespace, leading whitespace, and apostrophes inside
    the body are all preserved verbatim.
    """
    choices = response.choices  # type: ignore[attr-defined]
    if not choices:
        raise RuntimeError("OpenAI response had no choices.")
    content = choices[0].message.content
    if content is None:
        raise RuntimeError("OpenAI response choice had no content.")
    raw = str(content)
    if raw.endswith("\n"):
        raw = raw[:-1]
    return _conditionally_unwrap_quotes(raw, source_text)


def _conditionally_unwrap_quotes(text: str, source_text: str) -> str:
    """Strip ``'`` or ``"`` wrapper added by the model only when the
    source text wasn't itself wrapped in the same quote character."""
    for quote in ('"', "'"):
        wrapped = len(text) >= 2 and text[0] == quote and text[-1] == quote
        source_wrapped = (
            len(source_text) >= 2 and source_text[0] == quote and source_text[-1] == quote
        )
        if wrapped and not source_wrapped:
            return text[1:-1]
    return text


def _extract_usage(response: object) -> tuple[int | None, int | None]:
    """Pull token-usage figures out of the response. Returns
    ``(None, None)`` when the SDK didn't populate ``usage`` (rare,
    but defensive)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    return (
        int(prompt) if prompt is not None else None,
        int(completion) if completion is not None else None,
    )


def _estimate_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Multiply the per-1M-token rate by the actual token count.
    Returns None for unpriced models or when token counts are missing
    (which is what the UsageLog records — None rather than zero so the
    "not measured" case is distinguishable)."""
    if input_tokens is None or output_tokens is None:
        return None
    rate = _PRICING_USD_PER_M_TOKENS.get(model)
    if rate is None:
        return None
    input_rate, output_rate = rate
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


# Provider Protocol satisfaction is enforced via runtime_checkable; the
# below assertion documents the cycle-2 contract at module-load time.
_: type[Provider] = OpenAIProvider


__all__ = ["DEFAULT_MODEL", "DEFAULT_MAX_TOKENS", "OpenAIProvider"]
