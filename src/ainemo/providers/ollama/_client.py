"""Lazy client construction for the Ollama provider.

Ollama is a local HTTP daemon (defaults to ``http://localhost:11434``);
the official ``ollama`` Python SDK wraps it. There is no API key to
read, but the host can be overridden via the ``OLLAMA_HOST`` env var
or the constructor — same shape as the other providers' lazy clients
so the cycle-2 ProviderRouter doesn't need to special-case Ollama.
"""

from __future__ import annotations

import os
from typing import Final

from ollama import Client

# Env var name for an alternate Ollama daemon host. Per AGENTS.md §
# Translation-Domain Conventions: external endpoints via env var, not
# hardcoded.
ENV_VAR_HOST: Final = "OLLAMA_HOST"

# Default daemon URL — matches the upstream ``ollama serve`` default.
DEFAULT_HOST: Final = "http://localhost:11434"


def build_client(host: str | None = None) -> Client:
    """Construct an Ollama SDK client. ``host`` overrides the env var
    which overrides the default daemon URL.

    Module-import remains side-effect free — building the client is
    cheap (no network call) but is still deferred so a misconfigured
    host shows up as a clear error from the first ``translate()``
    rather than swallowing the whole package import.
    """
    target_host = host or os.getenv(ENV_VAR_HOST) or DEFAULT_HOST
    return Client(host=target_host)


__all__ = ["DEFAULT_HOST", "ENV_VAR_HOST", "build_client"]
