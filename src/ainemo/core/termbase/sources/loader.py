# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Loader bridge from :class:`TermbaseSource` to cycle-3
:class:`Termbase`.

Cycle-4 S2 — drains a :class:`TermbaseSource` (CsvSource for now;
JsonLinesSource in S3) into the cycle-3 termbase via the
:meth:`Termbase.add_concept` /
:meth:`Termbase.add_domain` /
:meth:`Termbase.attach_concept_to_domain` Protocol surface.

Concept identity
----------------

Concept ids are content-addressed over a
**(source_lang, source_term, namespace)** triple:

::

    import-<sha256(source_lang || U+001F || source_term || U+001F || namespace)[:16]>

where ``namespace`` resolves first non-empty of:

1. The :class:`ImportRecord`'s ``domain_id`` (from
   :attr:`FieldMapping.domain_column` when set per-row).
2. The per-import ``namespace`` argument the CLI's
   ``--namespace TAG`` flag forwards.
3. The empty string — global namespace.

This is the cycle-4 S1 P2 fix that keeps
same-source-term-different-domain rows from collapsing onto one
concept (see pitch § Solution shape). Re-running an import with
unchanged source data + unchanged namespace upserts onto the same
rows; changing any identity field produces a new concept and orphans
the previous one (documented orphan behavior per pitch § Risks).

Term identity
-------------

Each concept's source-language and target-language terms get
deterministic ids of the form ``<concept_id>-<lang>``. With the
concept_id already content-addressed, term ids are stable across
re-imports without an extra hash.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Final

from ainemo.core.termbase.base import Concept, Domain, Term, Termbase
from ainemo.core.termbase.sources.base import (
    ImportRecord,
    ImportReport,
    SkippedRow,
    TermbaseSource,
)

_CONCEPT_ID_PREFIX: Final = "import-"
_CONCEPT_ID_HASH_LENGTH: Final = 16
"""sha256 truncation length. 16 hex chars = 64 bits — same length
as the cycle-3 S2 (TBX termSec) and S5 (promotion concept) ids."""

_HASH_SEPARATOR: Final = "\x1f"
"""ASCII unit separator. Cannot appear in normal text inputs, so
the three identity fields cannot collide via delimiter ambiguity.
Same convention as the cycle-3 fixes."""


def load_into_termbase(
    tb: Termbase,
    source: TermbaseSource,
    *,
    namespace: str | None = None,
    skip_store: Any | None = None,
) -> ImportReport:
    """Drain ``source`` into ``tb``, returning the aggregate
    :class:`ImportReport`.

    See module docstring for the concept-identity contract. ``tb`` is
    consumed via the Protocol surface only; both
    :class:`KuzuTermbase` (production) and the test stub
    :class:`tests.termbase_stub.RecordingTermbase` work.

    Parameters
    ----------
    skip_store:
        Optional cycle-5 S3 ``ImportSkipStore`` implementation.  When
        supplied, every :class:`SkippedRow` is also written to the store
        (in addition to being accumulated in
        :attr:`ImportReport.skipped_details`) so the reviewer UI can
        triage and retry skipped rows without re-editing the source
        file.  When ``None`` (the default), behaviour is identical to
        cycle 4 — the print path and ``skipped_details`` are unaffected.
        Typed ``Any`` to avoid importing the app-layer Protocol at
        core-module import time (ports-and-adapters boundary).
    """
    concepts_added = 0
    terms_added = 0
    domains_added = 0
    rows_skipped = 0
    skipped_details: list[str] = []
    seen_domains: set[str] = set()
    now = int(time.time())

    for item in source.iter_concepts():
        if isinstance(item, SkippedRow):
            rows_skipped += 1
            skipped_details.append(item.reason)
            if skip_store is not None:
                _write_to_skip_store(skip_store, item, now)
            continue
        # item is ImportRecord
        record = item
        effective_namespace = _resolve_namespace(record.domain_id, namespace)
        concept_id = _derive_import_concept_id(
            source_lang=record.source_lang,
            source_term=record.source_term,
            namespace=effective_namespace,
        )
        concept = Concept(
            concept_id=concept_id,
            qid=None,
            definition=record.definition,
            created_at=now,
        )
        terms = _build_terms_for_record(record, concept_id, source.provenance)
        tb.add_concept(concept, terms)
        concepts_added += 1
        terms_added += len(terms)

        if record.domain_id:
            if record.domain_id not in seen_domains:
                tb.add_domain(
                    Domain(
                        domain_id=record.domain_id,
                        parent_id=None,
                        name=record.domain_id,
                    )
                )
                seen_domains.add(record.domain_id)
                domains_added += 1
            tb.attach_concept_to_domain(concept_id, record.domain_id)

    return ImportReport(
        concepts_added=concepts_added,
        terms_added=terms_added,
        domains_added=domains_added,
        rows_skipped=rows_skipped,
        skipped_details=tuple(skipped_details),
    )


def _derive_import_concept_id(
    *,
    source_lang: str,
    source_term: str,
    namespace: str,
) -> str:
    """Stable, content-addressed concept id for an imported row.

    Internal helper — kept underscored so future cycles can change
    the derivation (e.g. lengthen the hash, change the separator)
    without a deprecation cycle. The ``test_loader_concept_ids.py``
    contract suite imports it directly to pin the format; that
    test access is the only consumer outside this module. S3+ source
    impls should NOT call this — build :class:`ImportRecord` rows
    and let :func:`load_into_termbase` derive ids internally.
    Pass ``namespace=""`` for the global-namespace case.
    """
    payload = _HASH_SEPARATOR.join((source_lang, source_term, namespace))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{_CONCEPT_ID_PREFIX}{digest[:_CONCEPT_ID_HASH_LENGTH]}"


# --- Internals ---


def _resolve_namespace(record_domain_id: str | None, per_import_namespace: str | None) -> str:
    """Apply the cycle-4 namespace resolution chain: row's
    ``domain_id`` wins if set; otherwise per-import ``--namespace``
    flag value; otherwise empty (global namespace).

    Per pitch § Solution shape — and explicitly tested in the
    namespace-collision contract that pinned the cycle-4 S1 P2 fix.
    """
    if record_domain_id:
        return record_domain_id
    if per_import_namespace:
        return per_import_namespace
    return ""


def _build_terms_for_record(record: ImportRecord, concept_id: str, provenance: str) -> list[Term]:
    """One source-language Term + one target-language Term per
    ``record.target_terms`` entry. Term ids derived from
    ``<concept_id>-<lang>`` — content-addressed on the concept side
    so the term ids are stable across re-imports without extra
    hashing. The ``provenance`` argument is the source's
    :attr:`TermbaseSource.provenance` ClassVar (e.g.
    ``TERM_SOURCE_CSV_IMPORT``)."""
    terms: list[Term] = [
        Term(
            term_id=f"{concept_id}-{record.source_lang}",
            concept_id=concept_id,
            lang=record.source_lang,
            surface=record.source_term,
            register=None,
            part_of_speech=None,
            source=provenance,
        )
    ]
    for target_lang, surface in record.target_terms:
        terms.append(
            Term(
                term_id=f"{concept_id}-{target_lang}",
                concept_id=concept_id,
                lang=target_lang,
                surface=surface,
                register=None,
                part_of_speech=None,
                source=provenance,
            )
        )
    return terms


def _write_to_skip_store(skip_store: Any, skipped: SkippedRow, now: int) -> None:
    """Write a :class:`SkippedRow` to the cycle-5 ``ImportSkipStore``.

    Called only when ``skip_store is not None``.  Late-imports the
    store dataclass to avoid pulling the app-layer module into the
    core import graph at module load time — the import happens inside
    this function body so it is deferred until first use.

    If ``SkippedRow`` is missing any of the four cycle-5 optional
    fields (e.g. a cycle-4 caller that constructs ``SkippedRow(reason=…)``
    only), this helper silently skips the store write rather than
    raising — the byte-stability invariant means old callers must not
    break when ``skip_store`` is accidentally passed.
    """
    if (
        skipped.row_payload is None
        or skipped.row_index is None
        or skipped.source_path is None
        or skipped.source_format is None
    ):
        return

    # Deferred import — keeps core independent of the app layer at
    # module-load time while still giving a concrete call path at
    # runtime when the store is supplied.
    from ainemo.app.store.import_skips import ImportSkipRow, _derive_skip_id  # noqa: PLC0415

    skip_row = ImportSkipRow(
        skip_id=_derive_skip_id(
            source_path=skipped.source_path,
            row_index=skipped.row_index,
            row_payload=skipped.row_payload,
        ),
        source_path=skipped.source_path,
        source_format=skipped.source_format,
        row_index=skipped.row_index,
        row_payload=skipped.row_payload,
        skip_reason=skipped.reason,
        created_at=now,
        last_retried_at=None,
    )
    skip_store.add(skip_row)


__all__ = ["load_into_termbase"]
