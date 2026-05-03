"""Unit tests for the cycle-1 validator suite."""

from __future__ import annotations

from ainemo.core.icu import parse_placeholders
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    Segment,
    TranslatedSegment,
)
from ainemo.core.validators.base import (
    VIOLATION_SEVERITY_ERROR,
    VIOLATION_SEVERITY_WARNING,
    Validator,
)
from ainemo.core.validators.forbidden import ForbiddenTermsValidator
from ainemo.core.validators.icu import IcuSyntaxValidator
from ainemo.core.validators.length import (
    METADATA_KEY_MAX_LENGTH,
    LengthBudgetValidator,
)
from ainemo.core.validators.placeholder import PlaceholderParityValidator

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"


def _seg(source_text: str, *, metadata: dict[str, str] | None = None) -> Segment:
    return Segment(
        key="k",
        source_text=source_text,
        source_lang=_LANG_EN_US,
        placeholders=parse_placeholders(source_text),
        metadata=metadata or {},
    )


def _ts(source: Segment, target_text: str) -> TranslatedSegment:
    return TranslatedSegment(
        segment=source,
        target_lang=_LANG_DE,
        target_text=target_text,
        provider="test",
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )


# --- PlaceholderParityValidator -------------------------------------------


def test_placeholder_parity_passes_when_set_matches() -> None:
    v = PlaceholderParityValidator()
    assert isinstance(v, Validator)
    seg = _seg("Hello {name}!")
    assert v.check(seg, _ts(seg, "Hallo {name}!")) == ()


def test_placeholder_parity_passes_when_order_differs() -> None:
    """Position can shift between languages; only counts matter."""
    v = PlaceholderParityValidator()
    seg = _seg("{greeting}, {name}!")
    assert v.check(seg, _ts(seg, "{name}, {greeting}!")) == ()


def test_placeholder_parity_flags_dropped_placeholder() -> None:
    v = PlaceholderParityValidator()
    seg = _seg("Hello {name}!")
    violations = v.check(seg, _ts(seg, "Hallo!"))
    assert len(violations) == 1
    assert violations[0].validator == "placeholder-parity"
    assert violations[0].severity == VIOLATION_SEVERITY_ERROR
    assert "{name}" in violations[0].message


def test_placeholder_parity_flags_invented_placeholder() -> None:
    v = PlaceholderParityValidator()
    seg = _seg("Hello!")
    violations = v.check(seg, _ts(seg, "Hallo {name}!"))
    assert len(violations) == 1
    assert "{name}" in violations[0].message


def test_placeholder_parity_flags_count_mismatch() -> None:
    v = PlaceholderParityValidator()
    seg = _seg("{name} and {name}")
    violations = v.check(seg, _ts(seg, "{name}"))
    assert len(violations) == 1


def test_placeholder_parity_distinguishes_positional_from_named() -> None:
    v = PlaceholderParityValidator()
    seg = _seg("Hello {0}")
    violations = v.check(seg, _ts(seg, "Hallo {name}"))
    # Different placeholder kinds → both a missing and an extra
    assert len(violations) == 2


# --- IcuSyntaxValidator ---------------------------------------------------


def test_icu_syntax_passes_on_valid_plural() -> None:
    v = IcuSyntaxValidator()
    seg = _seg("{count, plural, one {1 item} other {# items}}")
    target = "{count, plural, one {1 Eintrag} other {# Einträge}}"
    assert v.check(seg, _ts(seg, target)) == ()


def test_icu_syntax_flags_unbalanced_braces() -> None:
    v = IcuSyntaxValidator()
    seg = _seg("Hello")
    violations = v.check(seg, _ts(seg, "Hallo {oops"))
    assert len(violations) == 1
    assert "unbalanced" in violations[0].message.lower()


def test_icu_syntax_flags_missing_other_branch() -> None:
    v = IcuSyntaxValidator()
    seg = _seg("Hello")
    target = "{count, plural, one {one item} few {few items}}"
    violations = v.check(seg, _ts(seg, target))
    # Missing 'other' branch
    assert any("other" in v_.message for v_ in violations)


def test_icu_syntax_passes_on_select_with_other() -> None:
    v = IcuSyntaxValidator()
    seg = _seg("{gender, select, male {he} female {she} other {they}}")
    target = "{gender, select, male {er} female {sie} other {sie}}"
    assert v.check(seg, _ts(seg, target)) == ()


# --- LengthBudgetValidator ------------------------------------------------


def test_length_budget_no_metadata_passes() -> None:
    v = LengthBudgetValidator()
    seg = _seg("Hello world", metadata={})
    assert v.check(seg, _ts(seg, "Hallo Welt das hier ist viel zu lang")) == ()


def test_length_budget_within_passes() -> None:
    v = LengthBudgetValidator()
    seg = _seg("Hello", metadata={METADATA_KEY_MAX_LENGTH: "20"})
    assert v.check(seg, _ts(seg, "Hallo")) == ()


def test_length_budget_exceeded_warns() -> None:
    v = LengthBudgetValidator()
    seg = _seg("Hi", metadata={METADATA_KEY_MAX_LENGTH: "5"})
    violations = v.check(seg, _ts(seg, "Hallo Welt"))
    assert len(violations) == 1
    assert violations[0].severity == VIOLATION_SEVERITY_WARNING
    assert "exceeds budget" in violations[0].message


def test_length_budget_malformed_metadata_skips() -> None:
    """Non-int max_length is the adapter's bug; validator silently
    declines to fire rather than crash the run."""
    v = LengthBudgetValidator()
    seg = _seg("Hi", metadata={METADATA_KEY_MAX_LENGTH: "many"})
    assert v.check(seg, _ts(seg, "Hallo Welt das ist sehr lang")) == ()


def test_length_budget_severity_is_warning() -> None:
    """Length is a UX concern, not correctness — warning, not error.
    Pipeline does not block writes on warnings."""
    v = LengthBudgetValidator()
    assert v.severity == VIOLATION_SEVERITY_WARNING


# --- ForbiddenTermsValidator ----------------------------------------------


def test_forbidden_terms_passes_when_clean() -> None:
    v = ForbiddenTermsValidator(forbidden_terms=("Coca-Cola", "Microsoft"))
    seg = _seg("Hello")
    assert v.check(seg, _ts(seg, "Hallo Welt")) == ()


def test_forbidden_terms_flags_match_case_insensitive() -> None:
    v = ForbiddenTermsValidator(forbidden_terms=("Coca-Cola",))
    seg = _seg("Hello")
    violations = v.check(seg, _ts(seg, "We sell coca-cola here."))
    assert len(violations) == 1
    assert violations[0].severity == VIOLATION_SEVERITY_ERROR


def test_forbidden_terms_word_boundary_default() -> None:
    """Default `word_boundary=True`: ``"AI"`` flags ``" AI "`` but
    not ``"Aimee"``."""
    v = ForbiddenTermsValidator(forbidden_terms=("AI",))
    seg = _seg("test")
    assert v.check(seg, _ts(seg, "Aimee said hi")) == ()
    assert len(v.check(seg, _ts(seg, "We use AI heavily"))) == 1


def test_forbidden_terms_word_boundary_disabled() -> None:
    """With word_boundary=False, the term matches as a substring
    anywhere — useful when the forbidden term is a brand stem that
    should not appear in any compound."""
    v = ForbiddenTermsValidator(forbidden_terms=("CocaCola",), word_boundary=False)
    seg = _seg("test")
    violations = v.check(seg, _ts(seg, "We sell CocaColalike drinks"))
    assert len(violations) == 1


def test_forbidden_terms_flags_each_occurrence() -> None:
    v = ForbiddenTermsValidator(forbidden_terms=("foo",))
    seg = _seg("test")
    violations = v.check(seg, _ts(seg, "foo bar foo baz foo"))
    assert len(violations) == 3
    spans = [v_.span for v_ in violations]
    assert all(span is not None for span in spans)


def test_forbidden_terms_case_sensitive_mode() -> None:
    v = ForbiddenTermsValidator(forbidden_terms=("API",), case_insensitive=False)
    seg = _seg("test")
    assert v.check(seg, _ts(seg, "Use the api carefully")) == ()
    assert len(v.check(seg, _ts(seg, "Use the API carefully"))) == 1
