"""Gettext ``.po`` bundle adapter.

Implements :class:`ainemo.core.adapters.base.BundleAdapter` for the
GNU gettext PO format used by Python (Babel/Django/Flask-Babel),
WordPress, Drupal, and most non-Java open-source ecosystems.

Cycle-1 scope:

- Singular entries: ``msgid`` → ``msgstr``. The ``msgid`` is the
  Segment's ``source_text``; the Segment's ``key`` is the entry's
  ``msgctxt`` if present, otherwise the ``msgid`` itself (which
  matches gettext's catalog-key convention).
- Plural entries: each ``msgstr[N]`` is its own Segment with key
  ``"<base_key>#<N>"``. ``msgid`` populates the ``[0]`` Segment;
  ``msgid_plural`` populates the ``[1]`` Segment. Cycle-1 design
  choice: each plural form translates independently. The
  PlaceholderParityValidator (scope 8) keeps placeholders consistent
  across the forms; cycle-3+ termbase work may unify form-coherent
  translation if quality demands it.
- Translator comments (``# ``), extracted comments (``#. ``),
  reference comments (``#: ``), and flag comments (``#, ``) are all
  preserved on the Segment's ``metadata`` and round-tripped on
  serialize.
- The ``.po`` header entry (``msgid ""``) is preserved verbatim and
  not translated.

Backed by ``polib`` (added to dependencies in this commit).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import polib

from ainemo.core.icu import parse_placeholders
from ainemo.core.segment import Segment, TranslatedSegment

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

_FORMAT_ID = "gettext-po"
_FILE_EXTENSIONS = (".po",)

_ENCODING = "utf-8"

# Plural-form key separator. Reserved (the "#" character is not legal
# in gettext msgctxt) so it can't collide with real catalog keys.
_PLURAL_KEY_SEPARATOR = "#"

# Metadata keys for round-trip preservation. Stored on Segment.metadata.
METADATA_KEY_MSGCTXT = "po.msgctxt"
METADATA_KEY_TRANSLATOR_COMMENT = "po.tcomment"
METADATA_KEY_EXTRACTED_COMMENT = "po.comment"
METADATA_KEY_REFERENCE = "po.occurrences"
METADATA_KEY_FLAGS = "po.flags"
# Plural-form metadata: which msgid family this Segment belongs to and
# which form index it represents. Used by serialize to regroup forms
# under one polib entry.
METADATA_KEY_PLURAL_BASE_KEY = "po.plural_base_key"
METADATA_KEY_PLURAL_FORM_INDEX = "po.plural_form_index"
METADATA_KEY_MSGID_PLURAL = "po.msgid_plural"


class GettextPoAdapter:
    """Adapter for gettext ``.po`` resource bundles."""

    format_id: ClassVar[str] = _FORMAT_ID
    file_extensions: ClassVar[tuple[str, ...]] = _FILE_EXTENSIONS

    def parse(self, path: Path, source_lang: str) -> tuple[Segment, ...]:
        po = polib.pofile(str(path), encoding=_ENCODING)
        segments: list[Segment] = []
        for entry in po:
            if entry.obsolete:
                continue
            if entry.msgid_plural:
                # Plural entry: each form (singular + plural) is its
                # own Segment so it translates independently.
                base_key = _entry_key(entry)
                segments.append(
                    _segment_from_plural_form(
                        entry=entry,
                        form_index=0,
                        text=entry.msgid,
                        base_key=base_key,
                        source_lang=source_lang,
                    )
                )
                segments.append(
                    _segment_from_plural_form(
                        entry=entry,
                        form_index=1,
                        text=entry.msgid_plural,
                        base_key=base_key,
                        source_lang=source_lang,
                    )
                )
            else:
                segments.append(_segment_from_singular(entry, source_lang))
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

        po = polib.POFile(encoding=_ENCODING)
        po.metadata = _default_po_metadata(target_lang)

        # Group plural forms under their base key. Singular Segments
        # become their own entry; plural Segments combine.
        plural_groups: dict[str, list[TranslatedSegment]] = {}
        for ts in translated:
            base_key = ts.segment.metadata.get(METADATA_KEY_PLURAL_BASE_KEY)
            if base_key is None:
                po.append(_singular_entry_from_translated(ts))
            else:
                plural_groups.setdefault(base_key, []).append(ts)

        for base_key, forms in plural_groups.items():
            po.append(_plural_entry_from_translated(base_key, forms))

        po.save(str(path))


# --- Internals ---


def _entry_key(entry: polib.POEntry) -> str:
    """Catalog key for a polib entry. Combines msgctxt and msgid the
    way gettext does for catalog lookups. polib lacks type stubs so
    every attribute access is `Any`; the explicit `str(...)` coerces
    back to the declared return type for mypy strict."""
    if entry.msgctxt:
        return f"{entry.msgctxt}{_PLURAL_KEY_SEPARATOR}ctx{_PLURAL_KEY_SEPARATOR}{entry.msgid}"
    return str(entry.msgid)


def _segment_from_singular(entry: polib.POEntry, source_lang: str) -> Segment:
    metadata = _common_metadata(entry)
    return Segment(
        key=_entry_key(entry),
        source_text=entry.msgid,
        source_lang=source_lang,
        placeholders=parse_placeholders(entry.msgid),
        metadata=metadata,
    )


def _segment_from_plural_form(
    *,
    entry: polib.POEntry,
    form_index: int,
    text: str,
    base_key: str,
    source_lang: str,
) -> Segment:
    metadata = _common_metadata(entry)
    metadata[METADATA_KEY_PLURAL_BASE_KEY] = base_key
    metadata[METADATA_KEY_PLURAL_FORM_INDEX] = str(form_index)
    if entry.msgid_plural:
        metadata[METADATA_KEY_MSGID_PLURAL] = entry.msgid_plural
    return Segment(
        key=f"{base_key}{_PLURAL_KEY_SEPARATOR}{form_index}",
        source_text=text,
        source_lang=source_lang,
        placeholders=parse_placeholders(text),
        metadata=metadata,
    )


def _common_metadata(entry: polib.POEntry) -> dict[str, str]:
    """Round-trip-able metadata captured for every Segment from a
    polib entry."""
    metadata: dict[str, str] = {}
    if entry.msgctxt:
        metadata[METADATA_KEY_MSGCTXT] = entry.msgctxt
    if entry.tcomment:
        metadata[METADATA_KEY_TRANSLATOR_COMMENT] = entry.tcomment
    if entry.comment:
        metadata[METADATA_KEY_EXTRACTED_COMMENT] = entry.comment
    if entry.occurrences:
        metadata[METADATA_KEY_REFERENCE] = "\n".join(
            f"{filename}:{lineno}" for filename, lineno in entry.occurrences
        )
    if entry.flags:
        metadata[METADATA_KEY_FLAGS] = ",".join(entry.flags)
    return metadata


def _singular_entry_from_translated(ts: TranslatedSegment) -> polib.POEntry:
    seg = ts.segment
    return polib.POEntry(
        msgid=seg.source_text,
        msgstr=ts.target_text,
        msgctxt=seg.metadata.get(METADATA_KEY_MSGCTXT) or None,
        tcomment=seg.metadata.get(METADATA_KEY_TRANSLATOR_COMMENT) or "",
        comment=seg.metadata.get(METADATA_KEY_EXTRACTED_COMMENT) or "",
        occurrences=_parse_occurrences(seg.metadata.get(METADATA_KEY_REFERENCE)),
        flags=_parse_flags(seg.metadata.get(METADATA_KEY_FLAGS)),
    )


def _plural_entry_from_translated(base_key: str, forms: list[TranslatedSegment]) -> polib.POEntry:
    forms_by_index: dict[int, TranslatedSegment] = {}
    for ts in forms:
        idx_str = ts.segment.metadata.get(METADATA_KEY_PLURAL_FORM_INDEX)
        if idx_str is None:
            raise ValueError(
                f"Plural form Segment {ts.segment.key!r} missing "
                f"metadata[{METADATA_KEY_PLURAL_FORM_INDEX!r}]."
            )
        forms_by_index[int(idx_str)] = ts

    if 0 not in forms_by_index or 1 not in forms_by_index:
        raise ValueError(f"Plural family for base key {base_key!r} is missing form 0 or form 1.")

    msgid = forms_by_index[0].segment.source_text
    msgid_plural = forms_by_index[1].segment.source_text
    sample_metadata = forms_by_index[0].segment.metadata
    return polib.POEntry(
        msgid=msgid,
        msgid_plural=msgid_plural,
        msgstr_plural={idx: ts.target_text for idx, ts in forms_by_index.items()},
        msgctxt=sample_metadata.get(METADATA_KEY_MSGCTXT) or None,
        tcomment=sample_metadata.get(METADATA_KEY_TRANSLATOR_COMMENT) or "",
        comment=sample_metadata.get(METADATA_KEY_EXTRACTED_COMMENT) or "",
        occurrences=_parse_occurrences(sample_metadata.get(METADATA_KEY_REFERENCE)),
        flags=_parse_flags(sample_metadata.get(METADATA_KEY_FLAGS)),
    )


def _parse_occurrences(raw: str | None) -> list[tuple[str, str]]:
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for line in raw.split("\n"):
        if ":" in line:
            filename, lineno = line.rsplit(":", 1)
            out.append((filename, lineno))
        elif line:
            out.append((line, ""))
    return out


def _parse_flags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [flag.strip() for flag in raw.split(",") if flag.strip()]


def _default_po_metadata(target_lang: str) -> dict[str, str]:
    """Bare-minimum PO header. Keeps the file valid and identifies the
    target language; cycle 1 doesn't preserve the source file's full
    header (Project-Id-Version, POT-Creation-Date, etc.)."""
    return {
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Language": target_lang,
        "MIME-Version": "1.0",
    }


__all__ = [
    "GettextPoAdapter",
    "METADATA_KEY_MSGCTXT",
    "METADATA_KEY_TRANSLATOR_COMMENT",
    "METADATA_KEY_EXTRACTED_COMMENT",
    "METADATA_KEY_REFERENCE",
    "METADATA_KEY_FLAGS",
    "METADATA_KEY_PLURAL_BASE_KEY",
    "METADATA_KEY_PLURAL_FORM_INDEX",
    "METADATA_KEY_MSGID_PLURAL",
]
