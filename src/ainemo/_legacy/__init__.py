"""DEPRECATED — pre-cycle-1 data modules.

These modules (`languages`, `translation`, `translation_request`,
`translation_service`) carry the original prototype's data model and
orchestration forward into the AI-NEMO layout *unchanged in behavior*.
Cycle 1 replaces them with `ainemo.core.segment`, `ainemo.core.pipeline`,
and friends; this `_legacy` subpackage and its top-level deprecation
shims (at the repo root) **delete at the end of cycle 1**.

Do not import from here in new code.

This module also exposes the helper used by the four top-level
deprecation shims (`languages.py`, `translation.py`, etc.) to emit a
uniform `DeprecationWarning`. See :func:`emit_legacy_shim_warning`.
"""
from __future__ import annotations

import warnings

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Stacklevel for the deprecation warning. The shim files import this
# helper at module scope, so the call chain on `import <shim>` is:
#   1. the user's `import <shim>` statement
#   2. the shim module body executing `emit_legacy_shim_warning(...)`
#   3. this helper calling `warnings.warn(...)`
# stacklevel=3 surfaces the user's import line as the warning location.
_DEPRECATION_STACKLEVEL: int = 3

# Cycle that deletes both `_legacy/` and the top-level shims. Stamped
# into every emitted warning so the deletion deadline is visible at the
# call site.
_DELETION_CYCLE: str = "cycle 1"


def emit_legacy_shim_warning(top_level_module: str) -> None:
    """Emit a uniform `DeprecationWarning` for a top-level shim.

    Each shim at the repo root (e.g. ``languages.py``) calls this with
    its own module name. The single source of truth for the warning's
    text and its stack-level lives here, so renaming the deletion
    target or rewording the message touches one place.
    """
    message = (
        f"Top-level `{top_level_module}` module is deprecated; import "
        f"`ainemo._legacy.{top_level_module}` instead. This shim is "
        f"removed at the end of {_DELETION_CYCLE}."
    )
    warnings.warn(message, DeprecationWarning, stacklevel=_DEPRECATION_STACKLEVEL)


__all__ = ["emit_legacy_shim_warning"]
