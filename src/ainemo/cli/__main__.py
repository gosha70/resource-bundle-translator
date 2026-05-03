"""Allow `python -m ainemo.cli` to invoke the CLI stub.

The console-script entry-point declared in ``pyproject.toml``
(``nemo = "ainemo.cli:main"``) is the supported way to invoke the CLI
once the package is installed; this module-execution path is provided
as a convenience for callers who want to run the CLI without relying on
``$PATH`` resolution.
"""
from __future__ import annotations

import sys

from ainemo.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
