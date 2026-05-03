"""ICU MessageFormat syntax validator.

Catches malformed ICU constructs in the target text: unbalanced braces,
missing branches, malformed selectors. The cycle-1 ICU parser is
tolerant during parse (so a single malformed segment doesn't crash a
batch); this validator is where strictness lives.
"""

from __future__ import annotations

from typing import ClassVar

from ainemo.core.icu import parse_icu_branches, parse_placeholders
from ainemo.core.segment import PlaceholderKind, Segment, TranslatedSegment
from ainemo.core.validators.base import (
    VIOLATION_SEVERITY_ERROR,
    Violation,
    ViolationSeverity,
)

_VALIDATOR_NAME = "icu-syntax"

# Selector that ICU plural/select/selectordinal forms MUST include —
# the catch-all branch. Spec-required.
_REQUIRED_FALLBACK_SELECTOR = "other"

_ICU_KINDS = (
    PlaceholderKind.ICU_PLURAL,
    PlaceholderKind.ICU_SELECT,
    PlaceholderKind.ICU_SELECTORDINAL,
)


class IcuSyntaxValidator:
    """Verify ICU MessageFormat syntax in the target text."""

    name: ClassVar[str] = _VALIDATOR_NAME
    severity: ClassVar[ViolationSeverity] = VIOLATION_SEVERITY_ERROR

    def check(
        self,
        source: Segment,
        translated: TranslatedSegment,
    ) -> tuple[Violation, ...]:
        violations: list[Violation] = []

        # 1. Unbalanced braces.
        if not _braces_balanced(translated.target_text):
            violations.append(
                Violation(
                    validator=self.name,
                    severity=self.severity,
                    message="Target has unbalanced curly braces.",
                )
            )

        # 2. Each ICU placeholder in the target must have an `other`
        #    branch (spec-required catch-all).
        target_placeholders = parse_placeholders(translated.target_text)
        for placeholder in target_placeholders:
            if placeholder.kind not in _ICU_KINDS:
                continue
            try:
                branches = parse_icu_branches(placeholder)
            except ValueError:
                violations.append(
                    Violation(
                        validator=self.name,
                        severity=self.severity,
                        message=(
                            f"ICU placeholder {placeholder.raw!r} could not "
                            f"be decomposed into branches (malformed)."
                        ),
                        span=placeholder.span,
                    )
                )
                continue
            selectors = [branch.selector for branch in branches]
            if _REQUIRED_FALLBACK_SELECTOR not in selectors:
                violations.append(
                    Violation(
                        validator=self.name,
                        severity=self.severity,
                        message=(
                            f"ICU placeholder {placeholder.raw!r} is missing "
                            f"the required {_REQUIRED_FALLBACK_SELECTOR!r} "
                            f"fallback branch."
                        ),
                        span=placeholder.span,
                    )
                )
        return tuple(violations)


def _braces_balanced(text: str) -> bool:
    """Walk the text counting unescaped braces. ``True`` iff every
    open is matched."""
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "'" and i + 1 < n and text[i + 1] in "{}'":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


__all__ = ["IcuSyntaxValidator"]
