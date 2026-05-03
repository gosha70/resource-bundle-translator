"""DEPRECATED — re-export shim. Removed at the end of cycle 1.

:class:`Translation` and :data:`MISSING_TRANSLATION` have moved to
:mod:`ainemo._legacy.translation` and will be replaced by cycle 1's
:class:`ainemo.core.segment.Segment` / ``TranslatedSegment`` types.
"""
from __future__ import annotations

from ainemo._legacy import emit_legacy_shim_warning as _warn

_SHIM_NAME = "translation"

_warn(_SHIM_NAME)

from ainemo._legacy.translation import (  # noqa: E402, F401
    MISSING_TRANSLATION,
    Translation,
)

__all__ = ["MISSING_TRANSLATION", "Translation"]
