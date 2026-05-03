"""Unit tests for :mod:`ainemo.core.icu`.

The parser is the single source of truth for placeholder identification
across all bundle adapters (cycle-1 invariant). These tests pin its
contract: which substrings count as which kind, where the spans land,
and how the corner cases (escapes, nested ICU, malformed input) are
handled.
"""

from __future__ import annotations

import pytest

from ainemo.core.icu import parse_icu_branches, parse_placeholders
from ainemo.core.segment import PlaceholderKind

# --- Simple placeholders ---------------------------------------------------


def test_no_placeholders_in_plain_text() -> None:
    assert parse_placeholders("Hello world") == ()


def test_single_named_placeholder() -> None:
    placeholders = parse_placeholders("Hello {name}!")
    assert len(placeholders) == 1
    ph = placeholders[0]
    assert ph.kind is PlaceholderKind.NAMED
    assert ph.raw == "{name}"
    assert ph.span == (6, 12)


def test_single_positional_placeholder() -> None:
    placeholders = parse_placeholders("Click {0} to continue")
    assert len(placeholders) == 1
    ph = placeholders[0]
    assert ph.kind is PlaceholderKind.POSITIONAL
    assert ph.raw == "{0}"
    assert ph.span == (6, 9)


def test_multiple_placeholders_left_to_right() -> None:
    placeholders = parse_placeholders("{greeting} {name}, you have {0} messages")
    assert [(ph.kind, ph.raw) for ph in placeholders] == [
        (PlaceholderKind.NAMED, "{greeting}"),
        (PlaceholderKind.NAMED, "{name}"),
        (PlaceholderKind.POSITIONAL, "{0}"),
    ]


def test_underscore_named_placeholder() -> None:
    placeholders = parse_placeholders("Hi {user_name}")
    assert placeholders[0].kind is PlaceholderKind.NAMED
    assert placeholders[0].raw == "{user_name}"


def test_multi_digit_positional() -> None:
    placeholders = parse_placeholders("Param {42}")
    assert placeholders[0].kind is PlaceholderKind.POSITIONAL


# --- ICU placeholders ------------------------------------------------------


def test_icu_plural_placeholder() -> None:
    text = "{count, plural, one {1 item} other {# items}}"
    placeholders = parse_placeholders(text)
    assert len(placeholders) == 1
    ph = placeholders[0]
    assert ph.kind is PlaceholderKind.ICU_PLURAL
    assert ph.raw == text
    assert ph.span == (0, len(text))


def test_icu_select_placeholder() -> None:
    text = "{gender, select, male {he} female {she} other {they}}"
    placeholders = parse_placeholders(text)
    assert len(placeholders) == 1
    assert placeholders[0].kind is PlaceholderKind.ICU_SELECT


def test_icu_selectordinal_placeholder() -> None:
    text = "{place, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
    placeholders = parse_placeholders(text)
    assert len(placeholders) == 1
    assert placeholders[0].kind is PlaceholderKind.ICU_SELECTORDINAL


def test_icu_with_text_around_it() -> None:
    text = "You have {count, plural, one {one new message} other {# new messages}} today."
    placeholders = parse_placeholders(text)
    assert len(placeholders) == 1
    ph = placeholders[0]
    assert ph.kind is PlaceholderKind.ICU_PLURAL
    # span covers exactly the placeholder, not the surrounding text
    assert text[ph.span[0] : ph.span[1]] == ph.raw


def test_icu_nested_placeholder_inside_branch() -> None:
    """Nested placeholders are inside the parent's span; only the
    top-level placeholder is returned. Adapters that need branch-level
    access call `parse_icu_branches`."""
    text = "{count, plural, one {{name} has 1 item} other {{name} has # items}}"
    placeholders = parse_placeholders(text)
    assert len(placeholders) == 1
    assert placeholders[0].kind is PlaceholderKind.ICU_PLURAL


# --- ICU `number`/`date`/etc. — treated as named for cycle 1 ---------------


def test_icu_number_treated_as_named() -> None:
    """ICU `{x, number, ...}` and similar formatter types are not
    plural/select/selectordinal; cycle 1 classifies them as named so
    they participate in placeholder parity validation without needing
    branch decomposition."""
    placeholders = parse_placeholders("Total: {price, number, currency}")
    assert len(placeholders) == 1
    assert placeholders[0].kind is PlaceholderKind.NAMED
    assert placeholders[0].raw == "{price, number, currency}"


# --- Escaping --------------------------------------------------------------


def test_escaped_braces_are_not_placeholders() -> None:
    """ICU's `'{'` and `'}'` escape sequences must not be picked up as
    placeholders."""
    assert parse_placeholders("Literal '{not a placeholder'}") == ()


def test_escape_does_not_break_subsequent_placeholders() -> None:
    placeholders = parse_placeholders("Literal '{escaped'} then {real}")
    assert len(placeholders) == 1
    assert placeholders[0].raw == "{real}"


# --- Malformed input -------------------------------------------------------


def test_unbalanced_open_brace_is_ignored() -> None:
    """Cycle-1 design choice: be tolerant of unbalanced braces during
    parse; surface them via the IcuSyntaxValidator at validate-time."""
    placeholders = parse_placeholders("Broken {not closed")
    assert placeholders == ()


def test_empty_braces_are_not_placeholders() -> None:
    assert parse_placeholders("Just {} braces") == ()


def test_invalid_argname_is_skipped() -> None:
    """`{1abc}` — neither pure-positional nor a valid identifier — is
    not a placeholder."""
    assert parse_placeholders("Bad {1abc} here") == ()


# --- Branch decomposition --------------------------------------------------


def test_parse_icu_branches_plural() -> None:
    text = "{count, plural, one {1 item} other {# items}}"
    placeholders = parse_placeholders(text)
    branches = parse_icu_branches(placeholders[0])
    assert [b.selector for b in branches] == ["one", "other"]
    assert [b.text for b in branches] == ["1 item", "# items"]


def test_parse_icu_branches_select() -> None:
    text = "{gender, select, male {he} female {she} other {they}}"
    placeholders = parse_placeholders(text)
    branches = parse_icu_branches(placeholders[0])
    assert [b.selector for b in branches] == ["male", "female", "other"]


def test_parse_icu_branches_with_explicit_numeric_selector() -> None:
    text = "{count, plural, =0 {nothing} =1 {one} other {many}}"
    placeholders = parse_placeholders(text)
    branches = parse_icu_branches(placeholders[0])
    assert [b.selector for b in branches] == ["=0", "=1", "other"]


def test_parse_icu_branches_rejects_non_icu_kind() -> None:
    placeholders = parse_placeholders("Hello {name}")
    with pytest.raises(ValueError):
        parse_icu_branches(placeholders[0])


def test_parse_icu_branches_handles_nested_braces() -> None:
    """A branch body containing a nested placeholder must round-trip
    its braces correctly — the branch's span ends at the matching
    closing brace, not the first inner one."""
    text = "{count, plural, one {{name}'s item} other {{name}'s # items}}"
    placeholders = parse_placeholders(text)
    branches = parse_icu_branches(placeholders[0])
    assert len(branches) == 2
    assert branches[0].text == "{name}'s item"
    assert branches[1].text == "{name}'s # items"
