"""Unit test for the deprecation-shim warning helper.

The helper :func:`ainemo._legacy.emit_legacy_shim_warning` is the single
source of truth for the warning text emitted by all four top-level
deprecation shims (``languages.py``, ``translation.py``,
``translation_request.py``, ``translation_service.py``). Each shim
collapses to two lines plus a module-name constant; the warning's
content lives here.

These tests pin the helper's contract so a refactor of the shim
boilerplate cannot silently change what users see when they import a
top-level legacy module.
"""

from __future__ import annotations

import warnings

import pytest

from ainemo._legacy import emit_legacy_shim_warning

# Names of the four real shims. Used both as test parameters and as the
# canonical list — if a fifth shim is added, register it here and a
# matching `<name>.py` shim file at the repo root.
_SHIM_MODULE_NAMES = (
    "languages",
    "translation",
    "translation_request",
    "translation_service",
)


@pytest.mark.parametrize("module_name", _SHIM_MODULE_NAMES)
def test_emits_deprecation_warning_with_module_name(module_name: str) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        emit_legacy_shim_warning(module_name)

    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 1, (
        f"Expected exactly one DeprecationWarning for shim {module_name!r}, "
        f"got {len(deprecation_warnings)}."
    )

    message = str(deprecation_warnings[0].message)
    # The warning must name the top-level module so users see "languages
    # is deprecated", not a generic "module is deprecated".
    assert f"`{module_name}`" in message
    # And it must point at the new import path so the user has somewhere
    # to migrate to.
    assert f"`ainemo._legacy.{module_name}`" in message


def test_warning_states_deletion_cycle() -> None:
    """The cycle-1 deletion deadline must surface in every emitted
    warning so users with old imports see the timeline."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        emit_legacy_shim_warning("languages")

    message = str(caught[0].message)
    assert "cycle 1" in message
    assert "removed at the end of" in message
