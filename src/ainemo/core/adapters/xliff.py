"""XLIFF 2.0 bundle adapter.

Implements :class:`ainemo.core.adapters.base.BundleAdapter` for XLIFF
2.0 (OASIS Standard, 2018). XLIFF 1.2 is intentionally out of scope —
the formats differ enough that a single adapter would be a tangle of
version branches; if real demand surfaces, a sibling
``XliffOneTwoAdapter`` is the right shape.

XLIFF 2.0 structure (cycle-1 subset):

::

    <xliff version="2.0" srcLang="en-US" trgLang="de-DE"
           xmlns="urn:oasis:names:tc:xliff:document:2.0">
      <file id="f1">
        <unit id="welcome">
          <notes>
            <note category="extracted">UI label</note>
          </notes>
          <segment id="1">
            <source>Hello {name}!</source>
            <target>Hallo {name}!</target>
          </segment>
        </unit>
      </file>
    </xliff>

Cycle-1 mapping:

- Each ``<segment>`` becomes one Segment. ``key`` =
  ``"{unit_id}#{segment_id}"`` (segment_id defaults to ``"1"`` when
  absent — XLIFF allows omitting it for single-segment units).
- ``<source>`` text becomes ``Segment.source_text``.
- ``<note>`` elements within the parent ``<unit>`` are preserved on
  ``Segment.metadata`` (one note per metadata key, joined by newlines
  if multiple notes share a category).
- ``<file id>`` and ``<group id>`` are preserved on metadata so the
  unit hierarchy round-trips.
- Inline markup (``<mrk>``, ``<ph>``, ``<sc>``, ``<ec>``) inside
  ``<source>`` is **NOT supported in cycle 1**. The cycle-1 parser
  collects only the text content of ``<source>``/``<target>``
  elements; any inline child tags are dropped on parse with a
  ``DEBUG``-level log entry naming the affected unit. Files that
  rely on inline codes for placeholder/format preservation (CAT
  tools exporting from translation memories, formatted-string
  segments) lose that markup through the cycle-1 round-trip.

  Why drop instead of preserve? An earlier cycle-1 attempt
  serialized inline children as XML strings into Segment.source_text;
  on serialize, lxml's ``Element.text = ...`` escapes those strings,
  emitting ``&lt;ph id="x"/&gt;`` instead of ``<ph id="x"/>``. That
  is silently broken XLIFF — worse than dropping the markup
  outright. Cycle 2+ rebuilds inline children as real XML nodes on
  serialize and adds a placeholder shape to the cycle-1 ICU parser
  for them.

Backed by ``lxml`` (added to dependencies in this commit's predecessor).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from lxml import etree

from ainemo.core.icu import parse_placeholders
from ainemo.core.segment import Segment, TranslatedSegment

_logger = logging.getLogger(__name__)

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

_FORMAT_ID = "xliff-2"
_FILE_EXTENSIONS = (".xlf", ".xliff")

_ENCODING = "utf-8"

# XLIFF 2.0 namespace + version + element/attribute names. All declared
# as constants so the parser, the serializer, and any future tooling
# share one canonical spelling.
_XLIFF_NS = "urn:oasis:names:tc:xliff:document:2.0"
_XLIFF_VERSION = "2.0"

_TAG_XLIFF = f"{{{_XLIFF_NS}}}xliff"
_TAG_FILE = f"{{{_XLIFF_NS}}}file"
_TAG_GROUP = f"{{{_XLIFF_NS}}}group"
_TAG_UNIT = f"{{{_XLIFF_NS}}}unit"
_TAG_SEGMENT = f"{{{_XLIFF_NS}}}segment"
_TAG_SOURCE = f"{{{_XLIFF_NS}}}source"
_TAG_TARGET = f"{{{_XLIFF_NS}}}target"
_TAG_NOTES = f"{{{_XLIFF_NS}}}notes"
_TAG_NOTE = f"{{{_XLIFF_NS}}}note"

_ATTR_VERSION = "version"
_ATTR_SRC_LANG = "srcLang"
_ATTR_TRG_LANG = "trgLang"
_ATTR_ID = "id"
_ATTR_CATEGORY = "category"

# Default segment id per XLIFF 2.0 — units with a single segment may
# omit the id; the spec recommends "s1" when serialization needs one.
_DEFAULT_SEGMENT_ID = "s1"
_DEFAULT_FILE_ID = "f1"

# Metadata keys for round-trip preservation.
METADATA_KEY_FILE_ID = "xliff.file_id"
METADATA_KEY_GROUP_ID = "xliff.group_id"
METADATA_KEY_UNIT_ID = "xliff.unit_id"
METADATA_KEY_SEGMENT_ID = "xliff.segment_id"
METADATA_KEY_NOTE_PREFIX = "xliff.note."  # appended with category name


class XliffAdapter:
    """Adapter for XLIFF 2.0 bilingual interchange files."""

    format_id: ClassVar[str] = _FORMAT_ID
    file_extensions: ClassVar[tuple[str, ...]] = _FILE_EXTENSIONS

    def parse(self, path: Path, source_lang: str) -> tuple[Segment, ...]:
        tree = etree.parse(str(path))  # noqa: S320 (caller-controlled input)
        root = tree.getroot()
        if root.tag != _TAG_XLIFF:
            raise ValueError(
                f"Expected root element {{{_XLIFF_NS}}}xliff at {path!s}; got {root.tag}."
            )
        # We trust the caller's source_lang over the file's srcLang
        # attribute. Mismatches are not necessarily errors — a user
        # may translate from a non-canonical source — but log via
        # validators downstream rather than raise here.
        segments: list[Segment] = []
        for file_element in root.iter(_TAG_FILE):
            file_id = file_element.get(_ATTR_ID, _DEFAULT_FILE_ID)
            for unit_element, group_id in _walk_units(file_element):
                segments.extend(
                    _segments_from_unit(
                        unit_element=unit_element,
                        file_id=file_id,
                        group_id=group_id,
                        source_lang=source_lang,
                    )
                )
        return tuple(segments)

    def serialize(
        self,
        path: Path,
        translated: tuple[TranslatedSegment, ...],
        target_lang: str,
    ) -> None:
        if not translated:
            # Even an empty bundle gets a valid XLIFF skeleton so
            # downstream tooling doesn't choke on a missing file.
            _write_xml(path, _build_empty_skeleton(target_lang))
            return

        for ts in translated:
            if ts.target_lang != target_lang:
                raise ValueError(
                    f"TranslatedSegment for key {ts.segment.key!r} has "
                    f"target_lang={ts.target_lang!r} but serialize was "
                    f"called with target_lang={target_lang!r}."
                )

        # Source language: take from the first Segment. All Segments
        # in a single bundle share a source language by construction.
        source_lang = translated[0].segment.source_lang

        nsmap = {None: _XLIFF_NS}
        root = etree.Element(_TAG_XLIFF, nsmap=nsmap)
        root.set(_ATTR_VERSION, _XLIFF_VERSION)
        root.set(_ATTR_SRC_LANG, source_lang)
        root.set(_ATTR_TRG_LANG, target_lang)

        # Group by file_id → group_id → unit_id so the original
        # hierarchy round-trips.
        by_file: dict[str, dict[str | None, dict[str, list[TranslatedSegment]]]] = {}
        for ts in translated:
            file_id = ts.segment.metadata.get(METADATA_KEY_FILE_ID, _DEFAULT_FILE_ID)
            group_id = ts.segment.metadata.get(METADATA_KEY_GROUP_ID)
            unit_id = ts.segment.metadata.get(METADATA_KEY_UNIT_ID, ts.segment.key)
            by_file.setdefault(file_id, {}).setdefault(group_id, {}).setdefault(unit_id, []).append(
                ts
            )

        for file_id, groups in by_file.items():
            file_el = etree.SubElement(root, _TAG_FILE)
            file_el.set(_ATTR_ID, file_id)
            for group_id, units in groups.items():
                container = file_el
                if group_id is not None:
                    group_el = etree.SubElement(file_el, _TAG_GROUP)
                    group_el.set(_ATTR_ID, group_id)
                    container = group_el
                for unit_id, unit_translations in units.items():
                    _append_unit(container, unit_id, unit_translations)

        _write_xml(path, root)


# --- Internals ---


def _walk_units(file_element: etree._Element) -> list[tuple[etree._Element, str | None]]:
    """Yield ``(unit, group_id)`` pairs for every unit reachable from
    ``file_element``, walking through ``<group>`` containers if any."""
    out: list[tuple[etree._Element, str | None]] = []
    for child in file_element:
        if child.tag == _TAG_UNIT:
            out.append((child, None))
        elif child.tag == _TAG_GROUP:
            group_id = child.get(_ATTR_ID)
            for unit in child.iter(_TAG_UNIT):
                out.append((unit, group_id))
    return out


def _segments_from_unit(
    *,
    unit_element: etree._Element,
    file_id: str,
    group_id: str | None,
    source_lang: str,
) -> list[Segment]:
    unit_id = unit_element.get(_ATTR_ID, "")
    notes_metadata = _collect_notes(unit_element)

    segments: list[Segment] = []
    for segment_element in unit_element.iter(_TAG_SEGMENT):
        segment_id = segment_element.get(_ATTR_ID, _DEFAULT_SEGMENT_ID)
        source_element = segment_element.find(_TAG_SOURCE)
        if source_element is None:
            continue
        source_text = _serialize_inline(source_element)
        metadata = dict(notes_metadata)
        metadata[METADATA_KEY_FILE_ID] = file_id
        metadata[METADATA_KEY_UNIT_ID] = unit_id
        metadata[METADATA_KEY_SEGMENT_ID] = segment_id
        if group_id is not None:
            metadata[METADATA_KEY_GROUP_ID] = group_id
        segments.append(
            Segment(
                key=f"{unit_id}#{segment_id}",
                source_text=source_text,
                source_lang=source_lang,
                placeholders=parse_placeholders(source_text),
                metadata=metadata,
            )
        )
    return segments


def _collect_notes(unit_element: etree._Element) -> dict[str, str]:
    """Read ``<notes>`` children; return one metadata key per category
    (multiple notes in the same category join with newlines)."""
    notes_container = unit_element.find(_TAG_NOTES)
    if notes_container is None:
        return {}
    by_category: dict[str, list[str]] = {}
    for note in notes_container.iter(_TAG_NOTE):
        category = note.get(_ATTR_CATEGORY, "general")
        text = note.text or ""
        by_category.setdefault(category, []).append(text)
    return {
        f"{METADATA_KEY_NOTE_PREFIX}{category}": "\n".join(notes)
        for category, notes in by_category.items()
    }


def _serialize_inline(element: etree._Element) -> str:
    """Extract the text content of ``element``, dropping any inline
    children.

    **Cycle-1 limitation.** XLIFF 2.0 allows inline elements
    (``<mrk>``, ``<ph>``, ``<sc>``, ``<ec>``) inside ``<source>`` and
    ``<target>``. Cycle 1 does not preserve those — the parser keeps
    only the element's surrounding text. An earlier cycle-1 design
    serialized inline children as XML strings (e.g.
    ``'Hello <ph id="x"/>'``) into ``Segment.source_text``; on
    serialize, ``Element.text = ...`` would escape those strings into
    ``&lt;ph id="x"/&gt;``, emitting silently broken XLIFF. Dropping
    is the cycle-1-honest choice. Cycle 2+ rebuilds inline children
    as real XML nodes on serialize and exposes them through a new
    ``Placeholder.kind`` value to the parser.

    Files that rely on inline codes lose that information through the
    cycle-1 round-trip; the ``DEBUG`` log line below names every
    affected element so users can audit.
    """
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        # Inline children are dropped (see docstring); their tail text
        # — the text immediately after the closing tag, before the
        # next child or end of parent — is preserved.
        _logger.debug(
            "XLIFF inline element %s dropped from %s (cycle-1 limitation)",
            etree.QName(child).localname,
            etree.QName(element).localname,
        )
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _append_unit(
    container: etree._Element,
    unit_id: str,
    translations: list[TranslatedSegment],
) -> None:
    """Build a ``<unit>`` subtree and append it to ``container``."""
    unit_el = etree.SubElement(container, _TAG_UNIT)
    unit_el.set(_ATTR_ID, unit_id)

    # Notes: take from the first segment's metadata (all segments in
    # a unit share unit-level notes).
    sample_metadata = translations[0].segment.metadata
    note_keys = sorted(k for k in sample_metadata if k.startswith(METADATA_KEY_NOTE_PREFIX))
    if note_keys:
        notes_el = etree.SubElement(unit_el, _TAG_NOTES)
        for note_key in note_keys:
            category = note_key[len(METADATA_KEY_NOTE_PREFIX) :]
            for text in sample_metadata[note_key].split("\n"):
                note_el = etree.SubElement(notes_el, _TAG_NOTE)
                note_el.set(_ATTR_CATEGORY, category)
                note_el.text = text

    for ts in translations:
        seg_el = etree.SubElement(unit_el, _TAG_SEGMENT)
        seg_id = ts.segment.metadata.get(METADATA_KEY_SEGMENT_ID, _DEFAULT_SEGMENT_ID)
        seg_el.set(_ATTR_ID, seg_id)
        source_el = etree.SubElement(seg_el, _TAG_SOURCE)
        source_el.text = ts.segment.source_text
        target_el = etree.SubElement(seg_el, _TAG_TARGET)
        target_el.text = ts.target_text


def _build_empty_skeleton(target_lang: str) -> etree._Element:
    nsmap = {None: _XLIFF_NS}
    root = etree.Element(_TAG_XLIFF, nsmap=nsmap)
    root.set(_ATTR_VERSION, _XLIFF_VERSION)
    root.set(_ATTR_SRC_LANG, "en-US")
    root.set(_ATTR_TRG_LANG, target_lang)
    file_el = etree.SubElement(root, _TAG_FILE)
    file_el.set(_ATTR_ID, _DEFAULT_FILE_ID)
    return root


def _write_xml(path: Path, root: etree._Element) -> None:
    tree = etree.ElementTree(root)
    tree.write(
        str(path),
        encoding=_ENCODING,
        xml_declaration=True,
        pretty_print=True,
    )


__all__ = [
    "XliffAdapter",
    "METADATA_KEY_FILE_ID",
    "METADATA_KEY_GROUP_ID",
    "METADATA_KEY_UNIT_ID",
    "METADATA_KEY_SEGMENT_ID",
    "METADATA_KEY_NOTE_PREFIX",
]
