"""AI-NEMO command-line interface.

The `nemo` console-script entry point declared in `pyproject.toml`
resolves to :func:`main` below. Cycle 0 ships a stub; cycle 1 wires
real subcommands (`translate`, `tm stats`, `validate`).
"""
from __future__ import annotations

import sys


def main() -> int:
    """Stub entry point for the `nemo` CLI.

    Cycle 1 replaces this with an argparse/click dispatcher that routes
    `nemo translate`, `nemo tm`, `nemo validate`, etc. to their handlers.
    """
    sys.stderr.write(
        "nemo: AI-NEMO CLI is in cycle 0 (rebrand & stabilize).\n"
        "Real subcommands (translate, tm stats, validate) ship in cycle 1 — "
        "see specs/pitches/0001-foundation/pitch.md.\n"
    )
    return 0


__all__ = ["main"]
