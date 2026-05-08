# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""``nemo app`` subcommand — cycle-5 Flask reviewer app entry points.

One sub-subcommand in S1:

- ``nemo app run`` — start the Flask reviewer app on localhost.

The ``register_*`` / ``run_*`` split mirrors :mod:`ainemo.cli.commands`
and :mod:`ainemo.cli.termbase_commands` so the dispatcher in
:mod:`ainemo.cli` stays consistent.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Final, TextIO

from ainemo.app._ids import DEFAULT_HOST, DEFAULT_IMPORT_SKIPS_PATH, DEFAULT_PORT
from ainemo.core.termbase._ids import DEFAULT_TERMBASE_PATH
from ainemo.core.tm.sqlite import DEFAULT_TM_PATH

logger = logging.getLogger(__name__)

# --- Subcommand / sub-subcommand names (no magic strings) ------------------

CMD_NAME_APP: Final = "app"
_APP_SUBCMD_RUN: Final = "run"

# --- Flag destination names (no magic strings) -----------------------------

_FLAG_HOST: Final = "host"
_FLAG_PORT: Final = "port"
_FLAG_DEBUG: Final = "debug"
_FLAG_TERMBASE_PATH: Final = "termbase_path"
_FLAG_TM_PATH: Final = "tm_path"

# --- Exit codes ------------------------------------------------------------

_EXIT_OK: Final = 0
_EXIT_USAGE: Final = 2


def register_app(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``nemo app`` subcommand tree with *subparsers*."""
    parser = subparsers.add_parser(
        CMD_NAME_APP,
        help="Start or manage the Flask reviewer app.",
    )
    app_sub = parser.add_subparsers(dest="app_subcommand")
    _register_run(app_sub)


def _register_run(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    parser = subparsers.add_parser(
        _APP_SUBCMD_RUN,
        help=(
            "Start the AI-NEMO reviewer app. "
            f"Binds to {DEFAULT_HOST}:{DEFAULT_PORT} by default "
            "(single-user-localhost). "
            "Pass --host 0.0.0.0 only if you have an auth layer in front."
        ),
    )
    parser.add_argument(
        "--host",
        dest=_FLAG_HOST,
        default=DEFAULT_HOST,
        help=(
            f"Host to bind to (default: {DEFAULT_HOST}). "
            "You accept full responsibility for any auth layer when "
            "using 0.0.0.0 or any non-loopback address."
        ),
    )
    parser.add_argument(
        "--port",
        dest=_FLAG_PORT,
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT}, range 1–65535).",
    )
    parser.add_argument(
        "--debug",
        dest=_FLAG_DEBUG,
        action="store_true",
        default=False,
        help="Enable Flask debug mode (reloader + verbose errors). Do not use in production.",
    )
    parser.add_argument(
        "--termbase-path",
        dest=_FLAG_TERMBASE_PATH,
        type=Path,
        default=Path(DEFAULT_TERMBASE_PATH),
        help=f"Path to the Kuzu termbase directory (default: {DEFAULT_TERMBASE_PATH}).",
    )
    parser.add_argument(
        "--tm-path",
        dest=_FLAG_TM_PATH,
        type=Path,
        default=Path(DEFAULT_TM_PATH),
        help=f"Path to the SQLite translation memory (default: {DEFAULT_TM_PATH}).",
    )


def register_app_cmd(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Alias kept for symmetry with the ``register_*`` naming convention."""
    register_app(subparsers)


def run_app(args: argparse.Namespace, *, err: TextIO | None = None) -> int:
    """Dispatch ``nemo app <subcommand>``."""
    err_io: TextIO = err if err is not None else sys.stderr
    if args.app_subcommand == _APP_SUBCMD_RUN:
        return _run_app_run(args, err=err_io)
    # No sub-subcommand supplied — print help.
    logger.error("No sub-subcommand for 'nemo app'. Try 'nemo app run --help'.")
    return _EXIT_USAGE


def _run_app_run(args: argparse.Namespace, *, err: TextIO) -> int:
    """Execute ``nemo app run``.

    Constructs concrete dependencies (KuzuTermbase, SqliteTranslationMemory,
    ProviderRouter with noop default) and passes them to the DI factory.
    The factory (create_app) depends only on Protocols — the concrete
    types live here per the Library-first / CLI-second rule.
    """
    from typing import ClassVar

    from ainemo.app import create_app
    from ainemo.app.config import AppConfig
    from ainemo.app.store.import_skips import SqliteImportSkipStore
    from ainemo.core.segment import Segment
    from ainemo.core.termbase.kuzu.store import KuzuTermbase
    from ainemo.core.tm.sqlite import SqliteTranslationMemory
    from ainemo.providers._ids import PROVIDER_ID_NOOP
    from ainemo.providers._usage_log import DEFAULT_USAGE_LOG_PATH, UsageLog
    from ainemo.providers.base import Provider, ProviderResult
    from ainemo.providers.router import ProviderRouter, RoutingConfig

    class _NoOpProvider:
        """Minimal no-op provider so the app starts without any provider configured."""

        provider_id: ClassVar[str] = PROVIDER_ID_NOOP

        def translate(
            self,
            segment: Segment,
            target_lang: str,
            *,
            system_prompt_addendum: str | None = None,
        ) -> ProviderResult:
            del system_prompt_addendum
            return ProviderResult(
                target_text=segment.source_text,
                provider=PROVIDER_ID_NOOP,
                model=PROVIDER_ID_NOOP,
                input_tokens=None,
                output_tokens=None,
                latency_ms=0,
                cost_usd=None,
                confidence=None,
            )

        def supports(self, source_lang: str, target_lang: str) -> bool:
            return True

    from pydantic import ValidationError

    termbase_path: Path = args.termbase_path
    tm_path: Path = args.tm_path
    host: str = args.host
    port: int = args.port
    debug: bool = args.debug

    try:
        config = AppConfig(
            host=host,
            port=port,
            debug=debug,
            termbase_path=termbase_path,
            tm_path=tm_path,
            import_skips_path=Path(DEFAULT_IMPORT_SKIPS_PATH),
        )
    except (ValueError, ValidationError) as exc:
        err.write(f"Invalid `nemo app run` configuration: {exc}\n")
        return _EXIT_USAGE

    termbase = KuzuTermbase(termbase_path)
    tm = SqliteTranslationMemory(tm_path)
    import_skips = SqliteImportSkipStore(config.import_skips_path)
    noop: Provider = _NoOpProvider()
    router = ProviderRouter(
        providers={PROVIDER_ID_NOOP: noop},
        routing_config=RoutingConfig(default_provider=PROVIDER_ID_NOOP),
        usage_log=UsageLog(Path(DEFAULT_USAGE_LOG_PATH)),
    )

    app = create_app(
        termbase=termbase,
        tm=tm,
        router=router,
        import_skips=import_skips,
        config=config,
    )
    try:
        app.run(host=host, port=port, debug=debug)
    finally:
        termbase.close()
        tm.close()
        import_skips.close()
    return _EXIT_OK


__all__ = ["CMD_NAME_APP", "register_app", "run_app"]
