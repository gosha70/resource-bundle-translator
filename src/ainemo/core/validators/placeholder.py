"""Placeholder-parity validator.

Catches the most common LLM translation bug: dropping or inventing a
placeholder. ``Hello {name}!`` → ``Bonjour !`` (lost ``{name}``) and
``Click {0}`` → ``Cliquez {99}`` (invented ``{99}``) both make the
translation crash at runtime; the validator surfaces them at
translate-time so they never land in the output file.

The validator delegates to :func:`ainemo.core.icu.parse_placeholders`
on both the source and the target. Two placeholders are considered
equivalent when they have the same ``kind`` and ``raw`` text — the
position may shift in translation, that's fine.
"""

from __future__ import annotations

from collections import Counter
from typing import ClassVar

from ainemo.core.icu import parse_placeholders
from ainemo.core.segment import Placeholder, Segment, TranslatedSegment
from ainemo.core.validators.base import (
    VIOLATION_SEVERITY_ERROR,
    Violation,
    ViolationSeverity,
)

_VALIDATOR_NAME = "placeholder-parity"


class PlaceholderParityValidator:
    """Verify the target's placeholder set matches the source's."""

    name: ClassVar[str] = _VALIDATOR_NAME
    severity: ClassVar[ViolationSeverity] = VIOLATION_SEVERITY_ERROR

    def check(
        self,
        source: Segment,
        translated: TranslatedSegment,
    ) -> tuple[Violation, ...]:
        target_placeholders = parse_placeholders(translated.target_text)
        source_counts = _signature_counts(source.placeholders)
        target_counts = _signature_counts(target_placeholders)
        violations: list[Violation] = []

        for signature, source_count in source_counts.items():
            target_count = target_counts.get(signature, 0)
            if target_count < source_count:
                violations.append(
                    Violation(
                        validator=self.name,
                        severity=self.severity,
                        message=(
                            f"Source placeholder {signature[1]!r} appears "
                            f"{source_count}× in source but "
                            f"{target_count}× in target."
                        ),
                    )
                )
        for signature, target_count in target_counts.items():
            source_count = source_counts.get(signature, 0)
            if target_count > source_count:
                violations.append(
                    Violation(
                        validator=self.name,
                        severity=self.severity,
                        message=(
                            f"Target has {target_count - source_count} "
                            f"extra occurrence(s) of placeholder "
                            f"{signature[1]!r} not in source."
                        ),
                    )
                )
        return tuple(violations)


def _signature_counts(
    placeholders: tuple[Placeholder, ...],
) -> Counter[tuple[str, str]]:
    """Bag of (kind, raw) tuples — order-independent comparison."""
    return Counter((ph.kind.value, ph.raw) for ph in placeholders)


__all__ = ["PlaceholderParityValidator"]
