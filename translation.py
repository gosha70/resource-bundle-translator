"""DEPRECATED — re-export shim. Removed at the end of cycle 1.

:class:`Translation` and :data:`MISSING_TRANSLATION` have moved to
:mod:`ainemo._legacy.translation` and will be replaced by cycle 1's
:class:`ainemo.core.segment.Segment` / ``TranslatedSegment`` types.
"""
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "Top-level `translation` module is deprecated; import from "
    "`ainemo._legacy.translation` instead. This shim is removed at the "
    "end of cycle 1.",
    DeprecationWarning,
    stacklevel=2,
)

from ainemo._legacy.translation import (  # noqa: E402, F401
    MISSING_TRANSLATION,
    Translation,
)

__all__ = ["MISSING_TRANSLATION", "Translation"]
