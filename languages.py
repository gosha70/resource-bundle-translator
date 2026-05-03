"""DEPRECATED — re-export shim. Removed at the end of cycle 1.

The :class:`Language` enum has moved to :mod:`ainemo._legacy.languages`
during cycle 0's rebrand & stabilize work and will be replaced by the
cycle-1 segment data model (see ``specs/pitches/0001-foundation/``).
"""
from __future__ import annotations

from ainemo._legacy import emit_legacy_shim_warning as _warn

_SHIM_NAME = "languages"

_warn(_SHIM_NAME)

from ainemo._legacy.languages import Language  # noqa: E402, F401

__all__ = ["Language"]
