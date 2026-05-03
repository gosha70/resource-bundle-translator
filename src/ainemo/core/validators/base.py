"""Validator Protocol + result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, Literal, Protocol, runtime_checkable

from ainemo.core.segment import Segment, TranslatedSegment

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Severity tags. `error` blocks the write; `warning` is logged.
VIOLATION_SEVERITY_ERROR: Final = "error"
VIOLATION_SEVERITY_WARNING: Final = "warning"

ViolationSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class Violation:
    """One issue raised by one validator on one translation."""

    validator: str
    """The :attr:`Validator.name` of the validator that fired."""

    severity: ViolationSeverity

    message: str
    """Human-readable description. Reviewer UI surfaces this verbatim."""

    span: tuple[int, int] | None = None
    """Optional offset range in the *target* text where the issue lies.
    ``None`` when the violation is whole-segment (e.g. length budget)."""


@runtime_checkable
class Validator(Protocol):
    """Inspect a translation; return violations."""

    name: ClassVar[str]
    """Stable identifier (e.g. ``"placeholder-parity"``). Used in
    ``Violation.validator`` so reviewers and logs name the source."""

    severity: ClassVar[ViolationSeverity]
    """Default severity for violations this validator raises. Concrete
    validators may override per-violation when they have finer-grained
    information."""

    def check(
        self,
        source: Segment,
        translated: TranslatedSegment,
    ) -> tuple[Violation, ...]:
        """Return zero or more violations.

        Implementations must be pure: same inputs → same outputs, no
        side effects. The pipeline runs validators in arbitrary order
        and may parallelize them in cycle-2+.
        """
        ...


__all__ = [
    "Violation",
    "ViolationSeverity",
    "Validator",
    "VIOLATION_SEVERITY_ERROR",
    "VIOLATION_SEVERITY_WARNING",
]
