# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Termbase importer sources.

Cycle-4 surface (per ``specs/pitches/0004-termbase-importer-pipeline/pitch.md``).
The package extends cycle-3's TBX importer with general-purpose
read paths for the data shapes i18n teams actually have on hand:
spreadsheets, Google Sheets exports, ad-hoc JSON dumps. The cycle-3
``Termbase`` Protocol is the write target; concrete sources here
produce :class:`ImportRecord` rows that the loader bridge writes
into the termbase via the cycle-3 ``add_concept`` surface.

S1 ships:

- :class:`ainemo.core.termbase.sources.base.TermbaseSource` Protocol +
  :class:`ImportRecord` + :class:`ImportReport` dataclasses.
- :class:`ainemo.core.termbase.sources.mapping.FieldMapping` —
  Pydantic-strict YAML schema with ``extra="forbid"`` per the cycle-3
  S4 cooldown lesson.
- :mod:`ainemo.core.termbase.sources._ids` — ``Final`` constants
  (provenance tags, CSV defaults, YAML mapping keys).

S2 (CsvSource), S3 (JsonLinesSource), S4 (CSV CLI), S5 (JSONL CLI),
and S6 (docs) build on this surface.
"""
