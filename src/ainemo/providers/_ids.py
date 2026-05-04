"""Stable provider identifiers used across the providers package and
the TM. The `provider_id` on a :class:`TranslatedSegment` references one
of these strings, the routing config matches on them, and the
`UsageLog` records them per call.

Defined as ``Final`` so each is its own Literal type — callers can
pass them directly to ``ProviderResult(provider_id=...)`` and the
typechecker narrows correctly under mypy strict.
"""

from __future__ import annotations

from typing import Final

PROVIDER_ID_NLLB: Final = "nllb"
PROVIDER_ID_OPUS: Final = "opus"
PROVIDER_ID_OPENAI: Final = "openai"
PROVIDER_ID_ANTHROPIC: Final = "anthropic"
PROVIDER_ID_OLLAMA: Final = "ollama"

# Pipeline-internal IDs — the no-op stub used in cycle-1 pipeline tests
# (and the cycle-2 CLI's default while real providers are unconfigured)
# and the manual-edit identifier the validator CLI uses.
PROVIDER_ID_NOOP: Final = "noop"
PROVIDER_ID_MANUAL: Final = "manual"


__all__ = [
    "PROVIDER_ID_NLLB",
    "PROVIDER_ID_OPUS",
    "PROVIDER_ID_OPENAI",
    "PROVIDER_ID_ANTHROPIC",
    "PROVIDER_ID_OLLAMA",
    "PROVIDER_ID_NOOP",
    "PROVIDER_ID_MANUAL",
]
