"""DEPRECATED — re-export shim. Removed at the end of cycle 1.

:class:`TranslationService` has moved to
:mod:`ainemo._legacy.translation_service` and will be replaced by cycle
1's :class:`ainemo.core.pipeline.TranslationPipeline`.
"""
from __future__ import annotations

from ainemo._legacy import emit_legacy_shim_warning as _warn

_SHIM_NAME = "translation_service"

_warn(_SHIM_NAME)

from ainemo._legacy.translation_service import TranslationService  # noqa: E402, F401

__all__ = ["TranslationService"]
