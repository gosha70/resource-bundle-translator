# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-2 :class:`Provider` Protocol + :class:`ProviderResult`.

The pitch (specs/pitches/0002-providers-gradle/pitch.md) calls for a
single Protocol that every concrete backend (NLLB/OPUS/OpenAI/Anthropic/
Ollama) implements, with a richer result type than cycle-1's
``str`` return so the cycle-2 router can record per-call cost/latency/
token usage to ``~/.ainemo/usage.jsonl``.

The legacy :class:`TranslatorModel` ABC stays in this module for
backward compat with the cycle-1 NoOp CLI surface; cycle-2 scope 5
deletes it once every concrete backend has been migrated to the new
Protocol.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Dict, List, Protocol, Tuple, runtime_checkable

from ainemo._legacy.translation_request import TranslationRequest
from ainemo.core.segment import Segment

logger = logging.getLogger(__name__)

# Legacy constant — cycle-1 used this in marian / nllb token-budgeting.
# Kept here until scope 5 deletes the legacy ABC and the providers that
# rely on it migrate to the new Protocol's per-provider configuration.
TRANSLATION_MAX_LENGTH = 2000


@dataclass(frozen=True, kw_only=True)
class ProviderResult:
    """One provider call's outcome.

    The router (scope 4) records every ProviderResult to
    ``~/.ainemo/usage.jsonl`` and uses ``cost_usd`` / ``latency_ms``
    for cost surveillance. The pipeline unwraps ``target_text`` for
    the TM and validators.

    All fields are keyword-only — same defense-in-depth rationale as
    :class:`~ainemo.core.segment.TranslatedSegment` (kw-only protects
    callers from silent corruption when fields are added).
    """

    target_text: str
    """The translated text. Placeholders restored to source form
    (the provider is responsible for tokenize/restore if needed)."""

    provider: str
    """Concrete provider id that produced this result — e.g.
    ``"openai"``, ``"anthropic"``, ``"nllb"``. Required even when the
    call goes through :class:`~ainemo.providers.router.ProviderRouter`,
    because the router's ``provider_id`` is the façade ``"router"``;
    only the concrete backend can name itself authoritatively. The
    pipeline persists this onto :class:`TranslatedSegment.provider` so
    TM rows attribute correctly when the router is in use."""

    model: str
    """Provider-specific model id used for this call. Example values:
    ``"nllb-200-distilled-600M"``, ``"claude-sonnet-4-5-20250929"``,
    ``"gpt-4o-2024-11-20"``, ``"llama3.2"``. Recorded verbatim so the
    UsageLog can disambiguate between models for the same provider."""

    input_tokens: int | None = None
    """``None`` for non-LLM providers (NLLB, OPUS) where token counts
    are not exposed by the underlying library."""

    output_tokens: int | None = None
    """Same shape as ``input_tokens``."""

    latency_ms: int = 0
    """Wall-clock duration of the provider call in milliseconds.
    Always populated; defaults to 0 only when the result is synthesized
    from a cache hit (cycle 2 router will not call providers for those)."""

    cost_usd: float | None = None
    """Estimated USD cost of this call. ``None`` for local providers
    (NLLB / OPUS / Ollama) and any cloud provider whose pricing the
    router does not yet model. Cycle-2 ships pricing tables for
    OpenAI and Anthropic; other providers add theirs as they land."""

    confidence: float | None = None
    """Optional 0..1 confidence score the provider exposes."""


@runtime_checkable
class Provider(Protocol):
    """Single :class:`Segment`-shaped translation provider Protocol.

    Cycle 2 finalizes this surface. Every concrete backend implements
    ``translate`` and ``supports``; the router calls only these two
    methods. Cycle-2 scope 5 migrates the existing
    NLLB/OPUS/OpenAI providers; scopes 6+7 add Anthropic and Ollama.
    """

    provider_id: ClassVar[str]
    """Stable identifier from :mod:`ainemo.providers._ids` (e.g.
    ``PROVIDER_ID_NLLB``). The TM stores this on every TranslatedSegment
    so caching keys on (segment, target_lang, provider)."""

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        """Translate ``segment`` to ``target_lang``.

        Implementations are responsible for placeholder preservation
        if the underlying model needs it. Errors propagate as
        exceptions; the router (scope 4) wraps with retry+backoff via
        :func:`ainemo.providers._retry.with_retry`.
        """
        ...

    def supports(self, source_lang: str, target_lang: str) -> bool:
        """Return ``True`` iff this provider can translate the given
        language pair. The router consults this before invoking
        ``translate`` so unsupported pairs surface as clean
        ``ProviderRouteNotFound`` errors rather than mid-call failures
        from the underlying SDK."""
        ...


class TranslatorModel(ABC):
    """LEGACY (cycle-1 carryover). Will be deleted by cycle-2 scope 5
    once every concrete backend (NLLB/OPUS/OpenAI) has been migrated
    to the new :class:`Provider` Protocol. Do not write new providers
    against this ABC.
    """

    def __init__(self, cache_dir=None, logging=None):
        """Initializes TranslatorModel with optional Logging."""
        self.logging = logging
        self.cache_dir = cache_dir

    @abstractmethod
    def translate(self, translation_request: TranslationRequest):
        """Legacy translate signature — see :class:`Provider` for the
        cycle-2 replacement."""
        pass

    def preserve_glossary_words(
        self, text: str, glossary: List[Tuple[str, str]], preserved_words: Dict[str, str]
    ) -> str:
        pass

    def encode_placeholders(self, text: str, preserved_words: Dict[str, str]) -> str:
        pass

    def restore_preserved_words(self, text: str, preserved_words: Dict[str, str]) -> str:
        for token, placeholder in preserved_words.items():
            text = text.replace(token, placeholder)
        return text

    def log_info(self, message: str):
        if self.logging is None:
            logger.info(message)
        else:
            self.logging.info(message)

    def log_error(self, message: str):
        if self.logging is None:
            logger.error(message)
        else:
            self.logging.error(message)


__all__ = [
    "Provider",
    "ProviderResult",
    "TranslatorModel",
    "TRANSLATION_MAX_LENGTH",
]
