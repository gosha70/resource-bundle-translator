"""DEPRECATED — re-export shim. Removed at the end of cycle 1.

:class:`TranslationService` has moved to
:mod:`ainemo._legacy.translation_service` and will be replaced by cycle
1's :class:`ainemo.core.pipeline.TranslationPipeline`.
"""
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "Top-level `translation_service` module is deprecated; import "
    "`ainemo._legacy.translation_service.TranslationService` instead. "
    "This shim is removed at the end of cycle 1.",
    DeprecationWarning,
    stacklevel=2,
)

from ainemo._legacy.translation_service import TranslationService  # noqa: E402, F401

__all__ = ["TranslationService"]
