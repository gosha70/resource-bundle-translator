"""i18next JSON bundle adapter.

Implements :class:`ainemo.core.adapters.base.BundleAdapter` for the
JSON format used by `i18next <https://www.i18next.com/>`_, the dominant
JavaScript i18n library.

i18next supports two equivalent key shapes:

- **Flat** with dot-separated keys: ``{"login.button.submit": "Submit"}``
- **Nested** with object levels: ``{"login": {"button": {"submit": "Submit"}}}``

Cycle-1 design choice: the adapter normalizes both shapes to flat
dot-keys internally, and **serialize always emits nested JSON**. The
nested form is the i18next convention and round-trips through
i18next's loader to the same flat lookup keys. Round-trip identity
therefore holds at the *segment-list level* (same flat keys, same
values, same placeholders) regardless of whether the source was flat
or nested.

i18next plural suffixes (``_zero``, ``_one``, ``_two``, ``_few``,
``_many``, ``_other``, ``_plural``) are treated as ordinary keys for
cycle 1 — each suffix variant is its own translatable Segment. The
ICU plural form (``{count, plural, ...}``) is the canonical
plural-handling path; teams that prefer the suffix style get correct
per-key translations without branch-aware logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar, Mapping

from ainemo.core.icu import parse_placeholders
from ainemo.core.segment import Segment, TranslatedSegment

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

_FORMAT_ID = "i18next-json"
_FILE_EXTENSIONS = (".json",)

_ENCODING = "utf-8"

# Separator used to flatten nested JSON paths into a single Segment.key.
# i18next defaults to "." but the project doesn't override it for
# cycle 1 — see docs/adapters.md for how to extend.
_KEY_SEPARATOR = "."

# JSON serialization shape. ``indent=2`` matches the conventional
# checked-in i18next file layout; ``ensure_ascii=False`` preserves
# native UTF-8 characters rather than escaping them, matching modern
# tooling (i18next-parser, react-i18next examples).
_JSON_INDENT = 2
_JSON_ENSURE_ASCII = False


class I18NextJsonAdapter:
    """Adapter for i18next JSON resource bundles."""

    format_id: ClassVar[str] = _FORMAT_ID
    file_extensions: ClassVar[tuple[str, ...]] = _FILE_EXTENSIONS

    def parse(self, path: Path, source_lang: str) -> tuple[Segment, ...]:
        raw = json.loads(path.read_text(encoding=_ENCODING))
        if not isinstance(raw, dict):
            raise ValueError(
                f"i18next bundle at {path!s} must be a JSON object at the "
                f"top level; got {type(raw).__name__}."
            )
        flat = _flatten(raw, prefix="")
        segments: list[Segment] = []
        for key, value in flat.items():
            segments.append(
                Segment(
                    key=key,
                    source_text=value,
                    source_lang=source_lang,
                    placeholders=parse_placeholders(value),
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
        nested: dict[str, Any] = {}
        for ts in translated:
            _set_nested(nested, ts.segment.key.split(_KEY_SEPARATOR), ts.target_text)
        text = json.dumps(
            nested,
            indent=_JSON_INDENT,
            ensure_ascii=_JSON_ENSURE_ASCII,
            sort_keys=False,
        )
        path.write_text(text + "\n", encoding=_ENCODING)


# --- Internals ---


def _flatten(node: Mapping[str, Any], prefix: str) -> dict[str, str]:
    """Recursively flatten a nested JSON object into dot-keyed leaves."""
    out: dict[str, str] = {}
    for key, value in node.items():
        path_key = f"{prefix}{_KEY_SEPARATOR}{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path_key))
        elif isinstance(value, str):
            out[path_key] = value
        else:
            # Non-string leaves (numbers, booleans, null, arrays) are
            # outside cycle-1 scope. Coerce to string so the bundle
            # round-trips, but warn callers via the converted form.
            out[path_key] = json.dumps(value, ensure_ascii=_JSON_ENSURE_ASCII)
    return out


def _set_nested(target: dict[str, Any], path: list[str], value: str) -> None:
    """Insert ``value`` at the dot-keyed ``path`` in ``target``,
    creating intermediate dicts as needed."""
    cursor = target
    for segment in path[:-1]:
        existing = cursor.get(segment)
        if not isinstance(existing, dict):
            new_dict: dict[str, Any] = {}
            cursor[segment] = new_dict
            cursor = new_dict
        else:
            cursor = existing
    cursor[path[-1]] = value


__all__ = ["I18NextJsonAdapter"]
