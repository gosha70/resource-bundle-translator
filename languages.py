"""DEPRECATED — re-export shim. Removed at the end of cycle 1.

The :class:`Language` enum has moved to :mod:`ainemo._legacy.languages`
during cycle 0's rebrand & stabilize work and will be replaced by the
cycle-1 segment data model (see ``specs/pitches/0001-foundation/``).

This shim exists to keep pre-cycle-0 callers (`from languages import
Language`) working for one release while migration happens.
"""
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "Top-level `languages` module is deprecated; import "
    "`ainemo._legacy.languages.Language` instead. This shim is removed "
    "at the end of cycle 1.",
    DeprecationWarning,
    stacklevel=2,
)

from ainemo._legacy.languages import Language  # noqa: E402, F401

__all__ = ["Language"]
