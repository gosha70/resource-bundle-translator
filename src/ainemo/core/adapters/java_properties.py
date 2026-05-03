"""Java ``.properties`` bundle adapter.

Implements :class:`ainemo.core.adapters.base.BundleAdapter` for the
Java ``Properties`` file format used by Spring Boot, JVM resource
bundles, and many enterprise i18n setups.

Cycle-1 scope: parse + serialize with round-trip identity for the
common case (key=value, key:value, comments, blank lines, line
continuations, standard escapes). Edge cases not covered:

- Trailing comments after the last key (lost during round-trip; the
  Segment-based abstraction does not have a place to attach them).
- Mixed `=`/`:`/whitespace separators per key — serialize always emits
  ``=`` regardless of the source separator.
- ISO-8859-1 input with embedded non-ASCII ``\\uXXXX`` escapes:
  parse decodes ``\\uXXXX``; serialize emits UTF-8 directly without
  re-encoding to ``\\uXXXX``. The cycle-1 design choice is "UTF-8
  source, UTF-8 sink" (matching the pre-cycle-0 prototype).

These limitations are documented in ``docs/adapters.md`` (scope 12).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from ainemo.core.icu import parse_placeholders
from ainemo.core.segment import Segment, TranslatedSegment

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

_FORMAT_ID = "java-properties"
_FILE_EXTENSIONS = (".properties",)

# File encoding. Java 9+ accepts UTF-8 natively; older JVMs require
# ISO-8859-1 with `\uXXXX` escapes for non-ASCII. AI-NEMO targets
# modern JVMs and the pre-cycle-0 prototype's behavior.
_ENCODING = "utf-8"

# Comment-line markers, per java.util.Properties spec.
_COMMENT_PREFIXES: tuple[str, ...] = ("#", "!")

# Key/value separator characters. The first occurrence (not in an
# escape sequence) splits key from value.
_SEPARATOR_CHARS: tuple[str, ...] = ("=", ":")

# Whitespace counts as a separator if no = or : is found first.
_WHITESPACE_PATTERN = re.compile(r"\s")

# Metadata key carrying the comment(s) that preceded the property in
# the source file. Comments round-trip through serialize.
METADATA_KEY_COMMENT = "comment"

# Canonical separator emitted by ``serialize``.
_OUTPUT_SEPARATOR = "="

# Output line terminator. ``\n`` matches the prototype and is portable
# across modern editors; cycle 1 does not preserve the source file's
# line-ending convention.
_OUTPUT_LINE_TERMINATOR = "\n"


class JavaPropertiesAdapter:
    """Adapter for ``.properties`` resource bundles."""

    format_id: ClassVar[str] = _FORMAT_ID
    file_extensions: ClassVar[tuple[str, ...]] = _FILE_EXTENSIONS

    def parse(self, path: Path, source_lang: str) -> tuple[Segment, ...]:
        text = path.read_text(encoding=_ENCODING)
        segments: list[Segment] = []
        pending_comments: list[str] = []
        for record in _read_logical_lines(text):
            stripped = record.lstrip()
            if not stripped:
                # Blank logical line — flush pending comments? No:
                # leave them attached to the next key. Mirrors common
                # editor behavior where blank lines separate paragraphs
                # but comments still belong to the next entry.
                continue
            if stripped[0] in _COMMENT_PREFIXES:
                pending_comments.append(stripped[1:].lstrip())
                continue
            key, value = _split_key_value(record)
            decoded_key = _decode_escapes(key)
            decoded_value = _decode_escapes(value)
            metadata: dict[str, str] = {}
            if pending_comments:
                metadata[METADATA_KEY_COMMENT] = "\n".join(pending_comments)
                pending_comments = []
            segments.append(
                Segment(
                    key=decoded_key,
                    source_text=decoded_value,
                    source_lang=source_lang,
                    placeholders=parse_placeholders(decoded_value),
                    metadata=metadata,
                )
            )
        return tuple(segments)

    def serialize(
        self,
        path: Path,
        translated: tuple[TranslatedSegment, ...],
        target_lang: str,
    ) -> None:
        for ts in translated:
            if ts.target_lang != target_lang:
                raise ValueError(
                    f"TranslatedSegment for key {ts.segment.key!r} has "
                    f"target_lang={ts.target_lang!r} but serialize was "
                    f"called with target_lang={target_lang!r}."
                )
        lines: list[str] = []
        for ts in translated:
            comment = ts.segment.metadata.get(METADATA_KEY_COMMENT)
            if comment:
                for comment_line in comment.split("\n"):
                    lines.append(f"# {comment_line}")
            lines.append(
                f"{_encode_key(ts.segment.key)}{_OUTPUT_SEPARATOR}{_encode_value(ts.target_text)}"
            )
        body = _OUTPUT_LINE_TERMINATOR.join(lines)
        if body:
            body += _OUTPUT_LINE_TERMINATOR
        path.write_text(body, encoding=_ENCODING)


# --- Internals ---


def _read_logical_lines(text: str) -> list[str]:
    """Split ``text`` into logical lines, joining ``\\``-continuations.

    A trailing single backslash on a line means "join with the next";
    a doubled backslash is a literal `\\`. Comment lines are returned
    as-is and are NOT subject to continuation, per the Properties spec.
    """
    raw_lines = text.splitlines()
    logical: list[str] = []
    buffer = ""
    in_continuation = False
    for raw in raw_lines:
        if in_continuation:
            buffer += raw.lstrip()
        else:
            buffer = raw
        # Comment lines never continue
        stripped = buffer.lstrip()
        if stripped[:1] in _COMMENT_PREFIXES and not in_continuation:
            logical.append(buffer)
            buffer = ""
            in_continuation = False
            continue
        # Count trailing unescaped backslashes
        trailing_bs = 0
        i = len(buffer) - 1
        while i >= 0 and buffer[i] == "\\":
            trailing_bs += 1
            i -= 1
        if trailing_bs % 2 == 1:
            # Odd number of trailing backslashes — line continues
            buffer = buffer[:-1]  # drop the continuation backslash
            in_continuation = True
            continue
        logical.append(buffer)
        buffer = ""
        in_continuation = False
    if buffer:
        logical.append(buffer)
    return logical


def _split_key_value(line: str) -> tuple[str, str]:
    """Split a property line into ``(key, value)``.

    The split point is the first unescaped ``=``, ``:``, or
    whitespace, whichever appears first (with ``=``/``:`` taking
    priority if surrounded by whitespace).
    """
    line = line.lstrip()
    # Find first unescaped separator
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch in _SEPARATOR_CHARS:
            key = line[:i].rstrip()
            value = line[i + 1 :].lstrip()
            return key, value
        if _WHITESPACE_PATTERN.match(ch):
            # Whitespace as separator — but only if no = or : appears
            # later on this logical line. Look ahead.
            rest = line[i:]
            sep_match = re.search(r"(?<!\\)[=:]", rest)
            if sep_match:
                # =/: takes priority; advance i to consume whitespace
                i += 1
                continue
            key = line[:i]
            value = line[i:].lstrip()
            return key, value
        i += 1
    # Whole line is a key with no value
    return line, ""


# Standard Java .properties escape table (parse direction: literal -> char).
_PARSE_ESCAPES: dict[str, str] = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "f": "\f",
    "\\": "\\",
    "=": "=",
    ":": ":",
    "#": "#",
    "!": "!",
    " ": " ",
}


def _decode_escapes(text: str) -> str:
    """Decode the standard ``.properties`` escape sequences."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1]
        if nxt == "u" and i + 5 < n:
            hex_part = text[i + 2 : i + 6]
            try:
                out.append(chr(int(hex_part, 16)))
                i += 6
                continue
            except ValueError:
                # Malformed \u escape — emit the literal backslash and
                # continue. Tolerant-parse keeps malformed input from
                # crashing the pipeline; validators surface it later.
                out.append(ch)
                i += 1
                continue
        out.append(_PARSE_ESCAPES.get(nxt, nxt))
        i += 2
    return "".join(out)


# Characters that need escaping in serialized output. Order matters —
# backslash first so subsequent escapes don't double-escape.
_OUTPUT_ESCAPES: tuple[tuple[str, str], ...] = (
    ("\\", "\\\\"),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\t", "\\t"),
    ("\f", "\\f"),
)


def _encode_value(text: str) -> str:
    """Escape a value for ``.properties`` output.

    Properties keys and values use the same escape set; the difference
    is that keys also escape spaces and the separator characters
    (``=``, ``:``). Values do not need that — see :func:`_encode_key`.
    """
    out = text
    for src, dst in _OUTPUT_ESCAPES:
        out = out.replace(src, dst)
    return out


def _encode_key(text: str) -> str:
    """Escape a key for ``.properties`` output.

    Adds escaping for whitespace, ``=``, ``:``, ``#``, and ``!`` since
    they would otherwise terminate the key.
    """
    out = _encode_value(text)
    out = (
        out.replace("=", "\\=")
        .replace(":", "\\:")
        .replace("#", "\\#")
        .replace("!", "\\!")
        .replace(" ", "\\ ")
    )
    return out


__all__ = ["JavaPropertiesAdapter", "METADATA_KEY_COMMENT"]
