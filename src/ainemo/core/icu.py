"""ICU MessageFormat-aware placeholder parser.

This module is the single source of truth for placeholder identification
across all bundle adapters. Adapters delegate to :func:`parse_placeholders`
to walk a source string and produce the
:class:`ainemo.core.segment.Placeholder` list that goes onto a
:class:`ainemo.core.segment.Segment`.

Cycle 1 ships a pure-Python implementation: lighter dependency footprint,
predictable behavior, no native build step. If real-world ICU corner
cases (deeply nested numbered branches, exotic locale plural categories
beyond the CLDR baseline) hit a wall, the migration path is to swap the
parser body for a `pyicu` call while keeping the public API.

Recognized shapes
-----------------

Simple placeholders:
    - ``{0}``, ``{1}`` — positional
    - ``{name}``, ``{user_id}`` — named

Complex placeholders (ICU MessageFormat):
    - ``{count, plural, =0 {none} one {one item} other {# items}}``
    - ``{gender, select, male {he} female {she} other {they}}``
    - ``{place, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}``

ICU placeholders may nest other placeholders inside their branches; the
parser walks the structure with brace-depth tracking and returns the
top-level placeholder span. Inner placeholders are exposed via
:func:`parse_icu_branches` for adapters that need branch-level access
(e.g., for translating branch text individually).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ainemo.core.segment import Placeholder, PlaceholderKind

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# ICU type keywords introducing complex placeholder shapes. Must match
# CLDR-defined names exactly.
_ICU_TYPE_PLURAL = "plural"
_ICU_TYPE_SELECT = "select"
_ICU_TYPE_SELECTORDINAL = "selectordinal"

_ICU_TYPE_TO_KIND: dict[str, PlaceholderKind] = {
    _ICU_TYPE_PLURAL: PlaceholderKind.ICU_PLURAL,
    _ICU_TYPE_SELECT: PlaceholderKind.ICU_SELECT,
    _ICU_TYPE_SELECTORDINAL: PlaceholderKind.ICU_SELECTORDINAL,
}

# Identifier pattern for placeholder argNames. ICU permits letters,
# digits, and underscores; cannot start with a digit (that would be a
# positional placeholder).
_NAMED_ARG_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Positional argName: one or more digits.
_POSITIONAL_ARG_PATTERN = re.compile(r"^\d+$")

# ICU escape sequence — single quote followed by `{`, `}`, or another `'`.
# Inside an ICU message, `'{'` is a literal `{`, `''` is a literal `'`.
# Cycle-1 parser respects this minimally; full ICU quoting state machine
# (apostrophe-as-mode-toggle) is more than the cycle needs.
_ICU_ESCAPE_OPEN = "'{"
_ICU_ESCAPE_CLOSE = "'}"
_ICU_ESCAPE_QUOTE = "''"


@dataclass(frozen=True)
class IcuBranch:
    """One branch of an ICU plural/select/selectordinal block.

    ``selector`` is the branch key (e.g. ``"one"``, ``"other"``,
    ``"=0"``, ``"male"``). ``text`` is the branch body — the inner
    text between the branch's braces, with placeholders left inline.
    """

    selector: str
    text: str
    span: tuple[int, int]
    """``(start, end)`` offsets of the branch body within the original
    source string (i.e. positions of the characters between the
    braces)."""


def parse_placeholders(text: str) -> tuple[Placeholder, ...]:
    """Walk ``text`` and return placeholders in left-to-right order.

    Top-level placeholders only; placeholders nested inside ICU branches
    are not returned (they live within the parent's span). Adapters that
    need branch-level access call :func:`parse_icu_branches` on the
    parent placeholder.
    """
    placeholders: list[Placeholder] = []
    cursor = 0
    n = len(text)
    while cursor < n:
        char = text[cursor]
        # Honor ICU escape sequences: '{ '} '' don't open placeholders.
        if char == "'" and cursor + 1 < n and text[cursor + 1] in "{}'":
            cursor += 2
            continue
        if char != "{":
            cursor += 1
            continue
        end = _find_matching_brace(text, cursor)
        if end is None:
            # Unbalanced opening brace — leave it as plain text. Cycle-1
            # design choice: be tolerant of malformed input rather than
            # raise during parse. The IcuSyntaxValidator (scope 8)
            # surfaces this at validate-time with a clear message.
            cursor += 1
            continue
        raw = text[cursor : end + 1]
        kind = _classify_placeholder(raw)
        if kind is not None:
            placeholders.append(Placeholder(kind=kind, raw=raw, span=(cursor, end + 1)))
        cursor = end + 1
    return tuple(placeholders)


def parse_icu_branches(placeholder: Placeholder) -> tuple[IcuBranch, ...]:
    """Decompose an ICU placeholder into its branches.

    Raises ``ValueError`` if the placeholder is not an ICU type
    (plural/select/selectordinal). Branch ``span`` offsets are relative
    to the placeholder's ``raw`` string, not the parent source.
    """
    if placeholder.kind not in (
        PlaceholderKind.ICU_PLURAL,
        PlaceholderKind.ICU_SELECT,
        PlaceholderKind.ICU_SELECTORDINAL,
    ):
        raise ValueError(
            f"parse_icu_branches expects an ICU placeholder kind, got {placeholder.kind.value}"
        )
    raw = placeholder.raw
    body_open = raw.index(",", raw.index(",") + 1) + 1  # past second comma
    body = raw[body_open:-1].lstrip()
    body_offset = (
        len(raw) - len(raw[body_open:].lstrip()) - 1
    )  # offset of body in raw, -1 for closing brace
    # The body offset above is approximate; recompute precisely:
    body_offset = body_open + (len(raw[body_open:]) - len(raw[body_open:].lstrip()))
    branches: list[IcuBranch] = []
    cursor = 0
    while cursor < len(body):
        # Skip whitespace
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor >= len(body):
            break
        # Read selector (up to first whitespace or '{')
        selector_start = cursor
        while cursor < len(body) and not body[cursor].isspace() and body[cursor] != "{":
            cursor += 1
        selector = body[selector_start:cursor]
        # Skip whitespace before the brace
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor >= len(body) or body[cursor] != "{":
            break  # malformed; bail
        body_brace_open = cursor
        body_brace_close = _find_matching_brace(body, body_brace_open)
        if body_brace_close is None:
            break
        branch_text = body[body_brace_open + 1 : body_brace_close]
        branches.append(
            IcuBranch(
                selector=selector,
                text=branch_text,
                span=(
                    body_offset + body_brace_open + 1,
                    body_offset + body_brace_close,
                ),
            )
        )
        cursor = body_brace_close + 1
    return tuple(branches)


# --- Internals ---


def _find_matching_brace(text: str, open_index: int) -> int | None:
    """Return the index of the `}` matching `text[open_index] == '{'`.

    Honors ICU `'{'` and `'}'` escape sequences inside the body — those
    don't change brace depth. Returns ``None`` on unbalanced input.
    """
    depth = 1
    i = open_index + 1
    n = len(text)
    while i < n:
        char = text[i]
        if char == "'" and i + 1 < n and text[i + 1] in "{}'":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _classify_placeholder(raw: str) -> PlaceholderKind | None:
    """Decide the ``PlaceholderKind`` for a `{...}` substring.

    Returns ``None`` for substrings that look like braces but aren't
    valid placeholders — e.g. literal `{}` blocks in non-ICU text.
    """
    if not (raw.startswith("{") and raw.endswith("}") and len(raw) >= 2):
        return None
    inner = raw[1:-1].strip()
    if not inner:
        return None
    # Complex (ICU) placeholder?
    parts = [part.strip() for part in _split_top_level(inner, ",", limit=2)]
    if len(parts) >= 2:
        arg_name = parts[0]
        type_keyword = parts[1]
        if not (_NAMED_ARG_PATTERN.match(arg_name) or _POSITIONAL_ARG_PATTERN.match(arg_name)):
            return None
        kind = _ICU_TYPE_TO_KIND.get(type_keyword)
        if kind is not None:
            return kind
        # `{x, number, ...}`-style ICU types other than plural/select/
        # selectordinal are out of scope for cycle 1 (date/time/number
        # formatters preserve verbatim through translation; cycle 1
        # treats them as named placeholders for parity validation).
        if _NAMED_ARG_PATTERN.match(arg_name):
            return PlaceholderKind.NAMED
        return PlaceholderKind.POSITIONAL
    # Simple placeholder: {arg}
    if _POSITIONAL_ARG_PATTERN.match(inner):
        return PlaceholderKind.POSITIONAL
    if _NAMED_ARG_PATTERN.match(inner):
        return PlaceholderKind.NAMED
    return None


def _split_top_level(text: str, separator: str, limit: int) -> list[str]:
    """Split ``text`` on ``separator`` only at brace depth 0, up to
    ``limit`` splits."""
    parts: list[str] = []
    depth = 0
    last = 0
    i = 0
    n = len(text)
    while i < n and len(parts) < limit:
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[last:i])
            last = i + 1
        i += 1
    parts.append(text[last:])
    return parts


__all__ = ["IcuBranch", "parse_placeholders", "parse_icu_branches"]
