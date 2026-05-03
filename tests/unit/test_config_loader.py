"""Regression tests for cycle-0 P1 fixes in
:mod:`ainemo.config.config_loader`.

Two bugs surfaced during PR review of commit ``a2176d8``:

1. ``ConfigLoader.__init__`` declared ``config_file`` as a positional-
   required parameter, but ``translator_app`` (and the spirit of the
   "default config" comment) calls ``ConfigLoader()`` with no args.
   Result: TypeError at module-import time on the Flask app.
2. ``DEFAULT_CONFIG`` pointed at the pre-cycle-0 path
   ``'config/translation_config.json'``. After the layout reorg, the
   file lives at ``src/ainemo/config/translation_config.json`` — only
   accessible via package-relative resolution. Result: FileNotFoundError
   on every default-arg ConfigLoader instantiation.

These tests pin both fixes.
"""

from __future__ import annotations

import os

import pytest

from ainemo._legacy.languages import Language
from ainemo.config.config_loader import (
    CONFIG_FILENAME,
    CONFIG_PACKAGE,
    DEFAULT_CONFIG,
    ConfigLoader,
    _default_config_path,
)

# Legacy relative path the cycle-0 fix replaced; pinned here as a literal
# so the regression test stays explicit about what NOT to fall back to.
_LEGACY_RELATIVE_PATH = "config/translation_config.json"


def test_config_loader_accepts_no_args() -> None:
    """`ConfigLoader()` must not raise TypeError. The Flask app calls
    this exact form at module-level."""
    cfg = ConfigLoader()
    assert cfg is not None


def test_default_config_path_resolves_to_packaged_resource() -> None:
    """The default config must be discoverable via package resources,
    not relative-to-CWD."""
    path = _default_config_path()
    assert os.path.exists(path), (
        f"Default config path {path!r} does not exist. The cycle-0 fix "
        "uses importlib.resources to point at the bundled "
        f"{CONFIG_PACKAGE.replace('.', '/')}/{CONFIG_FILENAME}."
    )
    assert path.endswith(CONFIG_FILENAME)
    # The path must end up inside the ainemo.config package, not at the
    # legacy top-level `config/` location.
    package_segments = CONFIG_PACKAGE.split(".")
    assert all(segment in path for segment in package_segments)


def test_default_config_constant_is_resolved_path() -> None:
    """`DEFAULT_CONFIG` must be the resolved package-resource path, not
    the legacy relative string."""
    assert DEFAULT_CONFIG == _default_config_path()
    assert DEFAULT_CONFIG != _LEGACY_RELATIVE_PATH


def test_config_loader_default_loads_from_packaged_config() -> None:
    """With no args, ConfigLoader populates from the bundled JSON."""
    cfg = ConfigLoader()
    assert cfg.get_from_language() == Language.EN_US
    assert cfg.get_to_languages() is not None
    assert len(cfg.get_to_languages()) > 0
    assert cfg.get_glossary() == ["EGOGE", "Ltd."]


def test_config_loader_explicit_none_still_works() -> None:
    """`ConfigLoader(config_file=None)` is the form the legacy CLIs use;
    keep it working."""
    cfg = ConfigLoader(config_file=None)
    assert cfg.get_from_language() == Language.EN_US


def test_config_loader_raises_on_missing_explicit_path(tmp_path) -> None:
    """An explicit non-default path that doesn't exist must surface a
    real error, not silently fall back."""
    bogus = tmp_path / "no_such_config.json"
    with pytest.raises(FileNotFoundError):
        ConfigLoader(config_file=str(bogus))
