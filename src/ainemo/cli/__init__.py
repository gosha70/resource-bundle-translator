"""AI-NEMO command-line interface.

The ``nemo`` console-script entry point declared in ``pyproject.toml``
resolves to :func:`main`. The dispatcher routes to the cycle-1
subcommands:

- ``nemo translate`` — translate a single bundle file
- ``nemo tm stats`` — report TM statistics
- ``nemo validate`` — re-run validators on an existing translation

Cycle 2 expands this surface with provider management
(``nemo provider list/stats``) and daemon mode (``nemo daemon``).
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from ainemo.cli.commands import (
    CMD_NAME_PROVIDER,
    CMD_NAME_TM,
    CMD_NAME_TRANSLATE,
    CMD_NAME_VALIDATE,
    register_provider,
    register_tm,
    register_translate,
    register_validate,
)
from ainemo.cli.daemon import CMD_NAME_DAEMON, register_daemon


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nemo",
        description=(
            "AI-NEMO — knowledge-graph-grounded localization CLI. "
            "Translate resource bundles, query the translation memory, "
            "and re-run validators on existing output."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand")
    register_translate(subparsers)
    register_tm(subparsers)
    register_validate(subparsers)
    register_provider(subparsers)
    register_daemon(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch to the cycle-1 subcommands.

    Returns the subcommand's exit code (0 on success, non-zero on
    failure or validation errors).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2
    if args.subcommand == CMD_NAME_TRANSLATE:
        from ainemo.cli.commands import run_translate

        return run_translate(args)
    if args.subcommand == CMD_NAME_TM:
        from ainemo.cli.commands import run_tm

        return run_tm(args)
    if args.subcommand == CMD_NAME_VALIDATE:
        from ainemo.cli.commands import run_validate

        return run_validate(args)
    if args.subcommand == CMD_NAME_PROVIDER:
        from ainemo.cli.commands import run_provider

        return run_provider(args)
    if args.subcommand == CMD_NAME_DAEMON:
        from ainemo.cli.daemon import run_daemon

        return run_daemon(args)
    parser.print_help(sys.stderr)
    return 2


__all__ = ["main"]
