"""DEPRECATED — re-export shim. Removed at the end of cycle 1.

:class:`TranslationRequest` has moved to
:mod:`ainemo._legacy.translation_request` and will be subsumed by cycle
1's :class:`ainemo.core.pipeline.TranslationPipeline`.
"""
from __future__ import annotations

from ainemo._legacy import emit_legacy_shim_warning as _warn

_SHIM_NAME = "translation_request"

_warn(_SHIM_NAME)

from ainemo._legacy.translation_request import TranslationRequest  # noqa: E402, F401

__all__ = ["TranslationRequest"]
