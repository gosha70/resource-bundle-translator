# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""TermbaseSource Protocol + import value types.

The :class:`TermbaseSource` Protocol is the only thing
:mod:`ainemo.core.termbase` consumers (cycle-4 S2/S3 concrete
sources, the cycle-4 S2 loader bridge, the cycle-4 S4/S5 CLI)
import. Concrete impls live in their own modules under
:mod:`ainemo.core.termbase.sources` and bring whatever parser
deps they need (``csv`` stdlib, ``json`` stdlib).

Mirrors the cycle-3 ``Termbase`` Protocol-first convention: the
core package depends only on Protocols + dataclasses; concrete
backends import their drivers privately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterator, Protocol, runtime_checkable


@dataclass(frozen=True)
class ImportRecord:
    """One conceptual row read from a source file.

    Carries a source-language term plus zero-or-more target-language
    renderings plus optional metadata. The loader bridge
    (:func:`ainemo.core.termbase.sources.loader.load_into_termbase`,
    cycle-4 S2) turns each :class:`ImportRecord` into a
    :class:`~ainemo.core.termbase.base.Concept` plus its
    :class:`~ainemo.core.termbase.base.Term` rows plus an optional
    :class:`~ainemo.core.termbase.base.Domain` attachment.
    """

    source_term: str
    source_lang: str

    target_terms: tuple[tuple[str, str], ...]
    """``((target_lang, surface), ...)`` — pairs rather than a dict
    so the type stays hashable + frozen-dataclass-compatible. The
    loader handles deduplication if a source row redundantly lists
    the same ``target_lang`` twice."""

    domain_id: str | None
    """Per-row domain id read from
    :attr:`FieldMapping.domain_column`, or ``None`` when the mapping
    omits ``domain_column`` or the row's domain cell is blank.

    Participates in concept-id derivation as the highest-precedence
    namespace component (see § Solution shape in the pitch). When
    set, two rows sharing ``(source_lang, source_term)`` but
    different ``domain_id`` produce *different* concepts."""

    definition: str | None
    """Optional source-language definition. Lands on
    :attr:`Concept.definition` when set; the cycle-3 termbase
    treats this as a single-valued field per concept."""


@dataclass(frozen=True)
class SkippedRow:
    """One source-file row the importer could not turn into a valid
    :class:`ImportRecord`.

    Yielded inline by :meth:`TermbaseSource.iter_concepts` alongside
    successful :class:`ImportRecord` rows so the loader bridge can
    accumulate skip reasons into :class:`ImportReport.skipped_details`
    without a side channel — the Protocol contract is "every input
    row produces exactly one output item, either an ImportRecord or
    a SkippedRow." Callers pattern-match on the yielded item.

    The cycle-4 P1 review fix: the cycle-3 ``TbxImporter`` returned
    skip details on its return value because it was a single-shot
    parse; cycle-4 sources are streaming, so skip details must travel
    through the iterator itself.

    Cycle-5 S3 additive extension: four optional fields with ``None``
    defaults let the cycle-5 ``ImportSkipStore`` preserve the original
    row payload for retry.  Existing callers that construct
    ``SkippedRow(reason=...)`` positionally stay byte-stable — the new
    fields default to ``None`` and existing consumers read only
    ``reason``.
    """

    reason: str
    """Human-readable line, format ``"row N: <reason>"`` (e.g.
    ``"row 12: blank source_term"``, ``"row 47: malformed JSON"``).
    Lands verbatim in :attr:`ImportReport.skipped_details`."""

    row_payload: str | None = None
    """JSON-serialised original row from the source file.

    For ``CsvSource`` rows this is ``json.dumps`` of the
    ``csv.DictReader`` row dict (including any ``None``-valued extras
    key from over-wide rows).  For ``JsonLinesSource`` rows this is
    the original raw line string — lossless round-trip without any
    re-serialisation overhead, and simpler than re-encoding a parsed
    dict.  ``None`` when the source did not populate the field (e.g.
    cycle-4 callers that construct ``SkippedRow(reason=...)`` only).
    """

    row_index: int | None = None
    """1-based row index matching the ``"row N:"`` prefix in
    :attr:`reason`.  Used by :class:`~ainemo.app.store.import_skips.ImportSkipStore`
    as a component of the content-addressed ``skip_id``.  ``None``
    when the source did not populate the field."""

    source_path: str | None = None
    """Absolute or relative path of the source file as a plain string.

    Preserved so the ``ImportSkipStore`` can group skip rows by
    source file without access to the original ``Path`` object.
    ``None`` when the source did not populate the field."""

    source_format: str | None = None
    """Source-file format token — ``"csv"`` or ``"jsonl"``.

    Values are the :data:`~ainemo.core.termbase.sources._ids.SOURCE_FORMAT_CSV`
    and :data:`~ainemo.core.termbase.sources._ids.SOURCE_FORMAT_JSONL`
    constants.  The ``single_row_source`` retry factory reads this
    field to select the correct ``TermbaseSource`` adapter.  ``None``
    when the source did not populate the field."""


@dataclass(frozen=True)
class ImportReport:
    """Outcome of one ``load_into_termbase`` call.

    Surfaces both the success counts and the per-row reasons for
    skipped rows so the CLI can print a useful summary without
    callers having to log inside the loader.
    """

    concepts_added: int
    """Concepts processed by this import — counts every row that
    successfully turned into an :class:`ImportRecord`, regardless
    of whether the underlying upsert created a new row or refreshed
    an existing one. Same shape as cycle-3's
    :class:`TbxImportReport.concepts_added`. To distinguish new vs
    refreshed, compare :meth:`Termbase.stats` before and after the
    import."""

    terms_added: int
    """Term rows processed by this import — counts every (concept,
    lang, surface) triple emitted, regardless of whether the
    underlying upsert created a new term or refreshed an existing
    one. Same convention as ``concepts_added``."""

    domains_added: int
    """Distinct new ``Domain`` rows created during the import.
    Pre-existing domains referenced by the source data do not count
    here — only first-touch creations."""

    rows_skipped: int
    """Number of source rows the importer could not turn into a
    valid :class:`ImportRecord` (e.g. blank source_term, malformed
    JSON line, missing required column value)."""

    skipped_details: tuple[str, ...]
    """One human-readable line per skipped row, format
    ``"row N: <reason>"``. Empty when every row imported cleanly.
    The CLI prints these so an operator dogfooding a real glossary
    can see *why* particular rows were dropped."""


@runtime_checkable
class TermbaseSource(Protocol):
    """Read-side surface for any structured terminology data file.

    Cycle-4 ships :class:`~ainemo.core.termbase.sources.csv_source.CsvSource`
    (S2) and :class:`~ainemo.core.termbase.sources.jsonl_source.JsonLinesSource`
    (S3). Cycle-7+ may add SkosRdfSource / Wikidata-enricher if
    real demand surfaces (per the pitch's no-go list, cycle 4
    explicitly defers RDF/SKOS / Wikidata SPARQL).
    """

    provenance: ClassVar[str]
    """Stable provenance tag from
    :mod:`ainemo.core.termbase.sources._ids` (e.g.
    ``TERM_SOURCE_CSV_IMPORT``). The loader bridge stamps it on
    every :attr:`Term.source` it writes so the cycle-5 reviewer UI
    can audit imported-from-CSV terms separately from imported-
    from-JSONL / imported-from-TBX (cycle 3) / auto-promoted-from-TM
    (cycle 3 S5) terms. Mirrors the cycle-2 ``Provider.provider_id``
    ClassVar pattern."""

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]:
        """Yield one item per source-file row — either an
        :class:`ImportRecord` (parsed cleanly) or a
        :class:`SkippedRow` (parse / mapping failure with a
        human-readable reason).

        Implementations MAY yield in any order; consumers must not
        rely on iteration order. The return type is an iterator
        rather than a tuple so backends can stream large files
        without materializing them — same contract as cycle-3's
        :meth:`TranslationMemory.iter_translations`.

        Implementations MUST NOT raise for row-level parse /
        mapping errors — surface them as :class:`SkippedRow`
        items so the loader bridge can accumulate them into
        :class:`ImportReport.skipped_details`. A single malformed
        row aborting the import would force the user to clean
        their source file before any subset of it can land, which
        defeats the cycle-4 audience use case (i18n teams loading
        their own ad-hoc glossaries). Implementations MAY raise
        for file-level errors that no caller could recover from —
        e.g. file does not exist, malformed CSV header row.
        """
        ...


__all__ = [
    "ImportRecord",
    "ImportReport",
    "SkippedRow",
    "TermbaseSource",
]
