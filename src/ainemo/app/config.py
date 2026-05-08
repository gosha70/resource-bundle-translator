# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Pydantic configuration model for the Flask reviewer app.

``AppConfig`` is constructed once in ``cli/app_commands.py`` (from CLI
flags or defaults) and injected into :func:`~ainemo.app.create_app`.
Using ``extra="forbid"`` catches typos in programmatic construction
early — the same lesson applied to the cycle-3 persona schema (S4).

``secret_key`` left ``None`` by default: Flask auto-generates a random
session secret per process. For a single-user-localhost reviewer this
is sufficient; cycle-6+ basic-auth would pin a stable key.  Callers
that need stable sessions across restarts (tests, future multi-user
mode) must supply an explicit key.

Port range validation (1–65535) follows RFC 6335.  Path fields reject
blank strings so the CLI cannot pass ``--tm-path ""``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

from ainemo.app._ids import DEFAULT_HOST, DEFAULT_IMPORT_SKIPS_PATH, DEFAULT_PORT


class AppConfig(BaseModel, extra="forbid"):
    """Runtime configuration for the Flask reviewer app.

    All fields have project-convention defaults so constructing
    ``AppConfig()`` (no arguments) is always valid.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    debug: bool = False
    secret_key: str | None = None
    """Flask session secret.

    ``None`` (default) → Flask generates a per-process random secret,
    which is fine for single-user-localhost.  Supply a stable value if
    you need sessions that survive server restarts.
    """
    termbase_path: Path = Path(".ainemo/termbase.kuzu")
    tm_path: Path = Path(".ainemo/tm.sqlite")
    import_skips_path: Path = Path(DEFAULT_IMPORT_SKIPS_PATH)

    @field_validator("port")
    @classmethod
    def _validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port must be in 1–65535, got {v}")
        return v

    @field_validator("termbase_path", "tm_path", "import_skips_path", mode="before")
    @classmethod
    def _validate_path_non_blank(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            raise ValueError("path must not be blank")
        return v

    @model_validator(mode="after")
    def _validate_host_non_blank(self) -> AppConfig:
        if not self.host.strip():
            raise ValueError("host must not be blank")
        return self


__all__ = ["AppConfig"]
