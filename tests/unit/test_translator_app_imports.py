"""Regression test for cycle-0 P1: Flask app module-import must not
TypeError.

The pre-fix ``translator_app.py`` had ``app_config = ConfigLoader()`` at
module top level while ``ConfigLoader.__init__`` required a positional
``config_file`` argument. ``python -m ainemo.app.translator_app`` raised
``TypeError`` before the app could start.

This test imports the module (which executes its top-level statements)
and asserts the import succeeds.
"""

from __future__ import annotations

import importlib

import pytest


def test_translator_app_module_imports_cleanly() -> None:
    """Module-level statements (`app_config = ConfigLoader()`,
    `app = Flask(__name__)`) must execute without exception."""
    flask = pytest.importorskip("flask")  # CI installs flask; locally maybe not.
    del flask

    module = importlib.import_module("ainemo.app.translator_app")
    assert module.app is not None  # Flask app exists at module scope
    assert module.app_config is not None  # ConfigLoader instantiated
