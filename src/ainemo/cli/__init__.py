"""AI-NEMO command-line interface.

The `nemo` console-script entry point declared in `pyproject.toml`
resolves to :func:`main` below. Cycle 0 ships a stub; cycle 1 wires
real subcommands (`translate`, `tm stats`, `validate`).
"""

from __future__ import annotations

import sys

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Path within the repo to the cycle-1 pitch where the real CLI shape is
# specified. Surfacing this in the stub message gives users a concrete
# place to follow up. Extracted as a constant so a future pitch rename
# breaks one place, not several.
_CYCLE_1_PITCH_PATH: str = "specs/pitches/0001-foundation/pitch.md"

# Human-facing message printed by the stub. Kept as a constant so a test
# can assert on its presence without re-typing the literal.
_STUB_MESSAGE: str = (
    "nemo: AI-NEMO CLI is in cycle 0 (rebrand & stabilize).\n"
    f"Real subcommands (translate, tm stats, validate) ship in cycle 1 — "
    f"see {_CYCLE_1_PITCH_PATH}.\n"
)


def main() -> int:
    """Stub entry point for the `nemo` CLI.

    Cycle 1 replaces this with an argparse/click dispatcher that routes
    `nemo translate`, `nemo tm`, `nemo validate`, etc. to their handlers.
    """
    sys.stderr.write(_STUB_MESSAGE)
    return 0


__all__ = ["main"]
