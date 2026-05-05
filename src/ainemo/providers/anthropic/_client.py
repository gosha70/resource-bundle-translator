"""Lazy SDK-client construction for the Anthropic provider.

Mirrors the OpenAI provider's :mod:`ainemo.providers.openai._client`
shape: import-time cheap, env-var read on first call, custom error
type so unhappy-path remediation lives in one place.

Per AGENTS.md § Translation-Domain Conventions: API keys via env vars
only, never in config files.
"""

from __future__ import annotations

import os
from typing import Final

from anthropic import Anthropic

ENV_VAR_API_KEY: Final = "ANTHROPIC_API_KEY"


class MissingAnthropicApiKey(Exception):
    """Raised when ``ANTHROPIC_API_KEY`` is unset at provider call
    time. The user-facing remediation is to ``export
    ANTHROPIC_API_KEY=…``; the message includes the env var name
    verbatim so the error is self-explanatory."""

    def __init__(self) -> None:
        super().__init__(
            f"Required environment variable {ENV_VAR_API_KEY!r} is not "
            f"set. The Anthropic provider needs an API key — set the env "
            f"var or route around the Anthropic provider via routes.yaml."
        )


def build_client() -> Anthropic:
    """Read the API key from the env and construct an SDK client.

    Raises :class:`MissingAnthropicApiKey` when the env var is unset
    so cleanup of the unhappy path lives in one place rather than at
    every provider call site.
    """
    api_key = os.getenv(ENV_VAR_API_KEY)
    if not api_key:
        raise MissingAnthropicApiKey()
    return Anthropic(api_key=api_key)


__all__ = ["ENV_VAR_API_KEY", "MissingAnthropicApiKey", "build_client"]
