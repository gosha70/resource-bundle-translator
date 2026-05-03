"""Length-budget validator.

Many UI strings have hard length limits — buttons, table headers,
mobile notification previews. The validator reads ``max_length`` from
:attr:`Segment.metadata` and warns when the target exceeds it.

This is a ``warning``-severity validator (not ``error``), since a
length overrun is a UX issue, not a correctness bug. The pipeline
still writes the translation; the reviewer UI flags it for human
attention.
"""

from __future__ import annotations

from typing import ClassVar

from ainemo.core.segment import Segment, TranslatedSegment
from ainemo.core.validators.base import (
    VIOLATION_SEVERITY_WARNING,
    Violation,
    ViolationSeverity,
)

_VALIDATOR_NAME = "length-budget"

# Metadata key carrying the max-length cap. Adapters that surface this
# (e.g. XLIFF's `<unit maxBytes="40">`) populate Segment.metadata with
# this key; cycle-1 adapters don't yet, but the contract is here ready.
METADATA_KEY_MAX_LENGTH = "max_length"


class LengthBudgetValidator:
    """Warn when the target text exceeds ``max_length``."""

    name: ClassVar[str] = _VALIDATOR_NAME
    severity: ClassVar[ViolationSeverity] = VIOLATION_SEVERITY_WARNING

    def check(
        self,
        source: Segment,
        translated: TranslatedSegment,
    ) -> tuple[Violation, ...]:
        max_length_str = source.metadata.get(METADATA_KEY_MAX_LENGTH)
        if max_length_str is None:
            return ()
        try:
            max_length = int(max_length_str)
        except ValueError:
            # Malformed metadata is not the validator's concern;
            # silent skip rather than raise.
            return ()
        actual_length = len(translated.target_text)
        if actual_length <= max_length:
            return ()
        return (
            Violation(
                validator=self.name,
                severity=self.severity,
                message=(
                    f"Target length {actual_length} exceeds budget "
                    f"{max_length} (over by {actual_length - max_length})."
                ),
            ),
        )


__all__ = ["LengthBudgetValidator", "METADATA_KEY_MAX_LENGTH"]
