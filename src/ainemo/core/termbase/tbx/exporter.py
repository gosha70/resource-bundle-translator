# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""TBX 3.0 (ISO 30042) exporter.

Cycle-3 S3 — writes a :class:`~ainemo.core.termbase.base.Termbase`
to a Weblate-compatible TBX 3.0 file.

Documented subset (mirrors the importer in
:mod:`ainemo.core.termbase.tbx.importer`):

================================  =======================================
Termbase field                    TBX element
================================  =======================================
``Concept.concept_id``            ``conceptEntry @id``
``ConceptEntry.domain_ids``       ``descrip type="domain"`` (one per id)
``Term.lang`` (group)             ``langSec @xml:lang``
``Term`` (one per termSec)        ``termSec`` ``<term>``
``Term.part_of_speech``           ``termNote type="partOfSpeech"``
``Term.register``                 ``termNote type="register"``
``Concept.definition``            ``definition`` (in source-lang
                                  ``langSec``'s first ``termSec``)
================================  =======================================

Determinism
-----------

The exporter writes byte-stable output across runs so the round-trip
test (``import → export → import → export = identical bytes``) is a
clean equality check rather than a canonical-XML diff. Determinism
comes from:

- :meth:`Termbase.iter_concept_entries` yields concepts in
  ``concept_id`` ascending order;
- :class:`ConceptEntry.terms` arrive pre-sorted by ``(lang, surface,
  term_id)``;
- :class:`ConceptEntry.domain_ids` are pre-sorted ascending;
- ``langSec`` groups are written in ``xml:lang`` ascending order;
- ``definition`` lands on the first ``termSec`` of the source-lang
  ``langSec`` (single-valued field on :class:`Concept`);
- ``etree.tostring(... pretty_print=True)`` writes consistent
  indentation; ``xml_declaration=True`` + ``encoding="UTF-8"`` pin
  the declaration shape.

Source language
---------------

The exporter writes the root ``@xml:lang`` from the constructor's
``source_lang`` argument (defaults to ``"en"``). Weblate's importer
uses this attribute to pick the "primary" language; getting it
wrong is the most common cause of round-trip drift, so it's a
required-with-default rather than auto-detected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from lxml import etree

from ainemo.core.termbase.base import ConceptEntry, Term, Termbase

# TBX 3.0 / ISO 30042 second-edition namespace, the only one Weblate
# emits and the only one we write. Mirrors the importer's `_TBX_NS`.
_TBX_NS: Final = "urn:iso:std:iso:30042:ed-2"
_XML_NS: Final = "http://www.w3.org/XML/1998/namespace"
_XML_LANG_KEY: Final = f"{{{_XML_NS}}}lang"

# Root element attributes Weblate writes; we mirror them so a Weblate
# user importing our export file lands on the same element shape.
_TBX_STYLE: Final = "dca"
_TBX_TYPE: Final = "TBX-Basic"

# Element local names (Weblate's TBX flow uses these — the importer's
# `_SUPPORTED_*` sets are the read-side mirror).
_TAG_TBX: Final = "tbx"
_TAG_HEADER: Final = "tbxHeader"
_TAG_FILE_DESC: Final = "fileDesc"
_TAG_TITLE_STMT: Final = "titleStmt"
_TAG_TITLE: Final = "title"
_TAG_SOURCE_DESC: Final = "sourceDesc"
_TAG_P: Final = "p"
_TAG_TEXT: Final = "text"
_TAG_BODY: Final = "body"
_TAG_CONCEPT_ENTRY: Final = "conceptEntry"
_TAG_DESCRIP: Final = "descrip"
_TAG_LANG_SEC: Final = "langSec"
_TAG_TERM_SEC: Final = "termSec"
_TAG_TERM: Final = "term"
_TAG_TERM_NOTE: Final = "termNote"
_TAG_DEFINITION: Final = "definition"

_DESCRIP_TYPE_DOMAIN: Final = "domain"
_TERM_NOTE_TYPE_POS: Final = "partOfSpeech"
_TERM_NOTE_TYPE_REGISTER: Final = "register"

_DEFAULT_SOURCE_LANG: Final = "en"
_DEFAULT_TITLE: Final = "ai-nemo-export"
_DEFAULT_PROVENANCE: Final = "AI-NEMO termbase export"


class TbxExporter:
    """Exports a :class:`Termbase` to a Weblate-compatible TBX 3.0 file.

    Construction is cheap; instances hold no state across calls.
    Output is deterministic — re-exporting an unchanged termbase
    produces byte-identical output, which is what the round-trip
    benchmark (``tests/integration/test_tbx_roundtrip.py``) asserts.
    """

    def __init__(
        self,
        tb: Termbase,
        *,
        source_lang: str = _DEFAULT_SOURCE_LANG,
        title: str = _DEFAULT_TITLE,
        provenance: str = _DEFAULT_PROVENANCE,
    ) -> None:
        self._tb = tb
        self._source_lang = source_lang
        self._title = title
        self._provenance = provenance

    def export_file(self, path: Path, *, domain_id: str | None = None) -> None:
        """Write the termbase contents to ``path`` as TBX 3.0.

        ``domain_id`` (when supplied) restricts the export to concepts
        attached to that domain. Cycle-3 S5 ``nemo termbase export
        --domain-id ...`` is the consumer.
        """
        payload = self.export_bytes(domain_id=domain_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def export_bytes(self, *, domain_id: str | None = None) -> bytes:
        """Render the TBX document to a UTF-8 ``bytes`` payload.

        Used by the round-trip test (avoids touching the filesystem)
        and by the cycle-5 reviewer UI's "preview export" surface.
        """
        root = self._build_root()
        body = self._find_body(root)
        for entry in self._tb.iter_concept_entries(domain_id):
            body.append(self._build_concept_entry(entry))
        payload = etree.tostring(
            root,
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=True,
        )
        # lxml's stubs type tostring() as Any; coerce so the public
        # signature is honest.
        return bytes(payload)

    # --- Internals ---

    def _build_root(self) -> etree._Element:
        # Use lxml's QName form so the namespace is declared once on
        # the root and inherited by every descendant — Weblate's
        # importer requires the default-namespace shape.
        nsmap = {None: _TBX_NS}
        root = etree.Element(
            etree.QName(_TBX_NS, _TAG_TBX),
            attrib={"style": _TBX_STYLE, "type": _TBX_TYPE},
            nsmap=nsmap,
        )
        root.set(_XML_LANG_KEY, self._source_lang)

        header = etree.SubElement(root, etree.QName(_TBX_NS, _TAG_HEADER))
        file_desc = etree.SubElement(header, etree.QName(_TBX_NS, _TAG_FILE_DESC))
        title_stmt = etree.SubElement(file_desc, etree.QName(_TBX_NS, _TAG_TITLE_STMT))
        title = etree.SubElement(title_stmt, etree.QName(_TBX_NS, _TAG_TITLE))
        title.text = self._title
        source_desc = etree.SubElement(file_desc, etree.QName(_TBX_NS, _TAG_SOURCE_DESC))
        provenance_p = etree.SubElement(source_desc, etree.QName(_TBX_NS, _TAG_P))
        provenance_p.text = self._provenance

        text = etree.SubElement(root, etree.QName(_TBX_NS, _TAG_TEXT))
        etree.SubElement(text, etree.QName(_TBX_NS, _TAG_BODY))
        return root

    def _find_body(self, root: etree._Element) -> etree._Element:
        body = root.find(f"{{{_TBX_NS}}}{_TAG_TEXT}/{{{_TBX_NS}}}{_TAG_BODY}")
        if body is None:
            raise RuntimeError("internal error: <body> not found in built root")
        return body

    def _build_concept_entry(self, entry: ConceptEntry) -> etree._Element:
        ce = etree.Element(etree.QName(_TBX_NS, _TAG_CONCEPT_ENTRY))
        ce.set("id", entry.concept.concept_id)

        # Multi-domain: one descrip per domain id, source-order
        # preserved (the Termbase Protocol contract gives them sorted
        # ascending; we don't re-sort here).
        for did in entry.domain_ids:
            descrip = etree.SubElement(ce, etree.QName(_TBX_NS, _TAG_DESCRIP))
            descrip.set("type", _DESCRIP_TYPE_DOMAIN)
            descrip.text = did

        # Group terms by language. Language order = ascending xml:lang
        # so output is deterministic regardless of how the termbase
        # internally returned them.
        terms_by_lang: dict[str, list[Term]] = {}
        for term in entry.terms:
            terms_by_lang.setdefault(term.lang, []).append(term)
        for lang in sorted(terms_by_lang):
            ce.append(
                self._build_lang_sec(
                    lang=lang,
                    terms=tuple(terms_by_lang[lang]),
                    definition=(entry.concept.definition if lang == self._source_lang else None),
                )
            )
        return ce

    def _build_lang_sec(
        self,
        *,
        lang: str,
        terms: tuple[Term, ...],
        definition: str | None,
    ) -> etree._Element:
        ls = etree.Element(etree.QName(_TBX_NS, _TAG_LANG_SEC))
        ls.set(_XML_LANG_KEY, lang)
        # Concept.definition lands on the first termSec of the
        # source-lang langSec — that's where the importer reads from
        # (see importer module docstring).
        for index, term in enumerate(terms):
            ls.append(
                self._build_term_sec(
                    term=term,
                    include_definition=(index == 0 and definition is not None),
                    definition=definition,
                )
            )
        return ls

    def _build_term_sec(
        self,
        *,
        term: Term,
        include_definition: bool,
        definition: str | None,
    ) -> etree._Element:
        ts = etree.Element(etree.QName(_TBX_NS, _TAG_TERM_SEC))
        term_el = etree.SubElement(ts, etree.QName(_TBX_NS, _TAG_TERM))
        term_el.text = term.surface
        if term.part_of_speech is not None:
            note = etree.SubElement(ts, etree.QName(_TBX_NS, _TAG_TERM_NOTE))
            note.set("type", _TERM_NOTE_TYPE_POS)
            note.text = term.part_of_speech
        if term.register is not None:
            note = etree.SubElement(ts, etree.QName(_TBX_NS, _TAG_TERM_NOTE))
            note.set("type", _TERM_NOTE_TYPE_REGISTER)
            note.text = term.register
        if include_definition and definition is not None:
            def_el = etree.SubElement(ts, etree.QName(_TBX_NS, _TAG_DEFINITION))
            def_el.text = definition
        return ts


__all__ = ["TbxExporter"]
