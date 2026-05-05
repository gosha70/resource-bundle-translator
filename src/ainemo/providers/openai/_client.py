"""Lazy SDK-client construction for the OpenAI provider.

The OpenAI SDK reads ``OPENAI_API_KEY`` from the env at client
construction. Building the client at module-import time would require
the env var for every code path that touches ``ainemo.providers``
(test collection, the NLLB CLI, etc.) — the cycle-0 audit-bug fix
moved construction into ``OpenAITranslatorModel.__init__``; cycle 2
keeps that pattern but lifts it into its own helper module.
"""

from __future__ import annotations

import os
from typing import Final

from openai import OpenAI

# Env var name. Per AGENTS.md § Translation-Domain Conventions: API
# keys via env vars only, never in config files.
ENV_VAR_API_KEY: Final = "OPENAI_API_KEY"


class MissingOpenAiApiKey(Exception):
    """Raised when ``OPENAI_API_KEY`` is unset at provider-construction
    time. The user-facing remediation is to ``export OPENAI_API_KEY=…``;
    the message includes the env var name verbatim so the error is
    self-explanatory."""

    def __init__(self) -> None:
        super().__init__(
            f"Required environment variable {ENV_VAR_API_KEY!r} is not "
            f"set. The OpenAI provider needs an API key — set the env "
            f"var or route around the OpenAI provider via routes.yaml."
        )


def build_client() -> OpenAI:
    """Read the API key from the env and construct an SDK client.

    Raises :class:`MissingOpenAiApiKey` when the env var is unset, so
    cleanup of the unhappy path lives in one place rather than at
    every provider call site.
    """
    api_key = os.getenv(ENV_VAR_API_KEY)
    if not api_key:
        raise MissingOpenAiApiKey()
    return OpenAI(api_key=api_key)


__all__ = ["ENV_VAR_API_KEY", "MissingOpenAiApiKey", "build_client"]
