"""Forbidden-terms validator.

Catches translations that contain text from a per-run forbidden list:
brand names that should be transliterated rather than translated,
trademarked terms with strict spellings, regulatory red flags. The
list is supplied at construction time; the validator is otherwise
config-free.
"""

from __future__ import annotations

import re
from typing import ClassVar

from ainemo.core.segment import Segment, TranslatedSegment
from ainemo.core.validators.base import (
    VIOLATION_SEVERITY_ERROR,
    Violation,
    ViolationSeverity,
)

_VALIDATOR_NAME = "forbidden-terms"


class ForbiddenTermsValidator:
    """Flag any occurrence of a forbidden term in the target text.

    Matching is case-insensitive by default and uses word boundaries so
    ``"AI"`` flags ``" AI "`` but not ``" Aimee"``. Both behaviors are
    constructor-tunable.
    """

    name: ClassVar[str] = _VALIDATOR_NAME
    severity: ClassVar[ViolationSeverity] = VIOLATION_SEVERITY_ERROR

    def __init__(
        self,
        forbidden_terms: tuple[str, ...],
        *,
        case_insensitive: bool = True,
        word_boundary: bool = True,
    ) -> None:
        self._forbidden_terms = forbidden_terms
        flags = re.IGNORECASE if case_insensitive else 0
        self._patterns: list[tuple[str, re.Pattern[str]]] = []
        for term in forbidden_terms:
            escaped = re.escape(term)
            if word_boundary:
                escaped = rf"\b{escaped}\b"
            self._patterns.append((term, re.compile(escaped, flags)))

    def check(
        self,
        source: Segment,
        translated: TranslatedSegment,
    ) -> tuple[Violation, ...]:
        violations: list[Violation] = []
        for term, pattern in self._patterns:
            for match in pattern.finditer(translated.target_text):
                violations.append(
                    Violation(
                        validator=self.name,
                        severity=self.severity,
                        message=f"Target contains forbidden term {term!r}.",
                        span=(match.start(), match.end()),
                    )
                )
        return tuple(violations)


__all__ = ["ForbiddenTermsValidator"]
