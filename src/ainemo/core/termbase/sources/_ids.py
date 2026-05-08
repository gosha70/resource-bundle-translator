# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Stable identifiers + defaults for the termbase importer sources.

Mirrors :mod:`ainemo.core.termbase._ids` and the cycle-3 ``Final``
constant convention. AGENTS.md § Prohibited Patterns and the project
memory rule *No magic strings/numbers — named constants always* both
apply: every named string or numeric default that crosses a module
boundary lives here.
"""

from __future__ import annotations

from typing import Final

# --- Term provenance tags ---
# Stored on `Term.source` so the cycle-5 reviewer UI can audit
# imported-from-CSV separately from imported-from-TBX (cycle-3) /
# auto-promoted-from-TM (cycle-3 S5) / pack-supplied (cycle-7+).
TERM_SOURCE_CSV_IMPORT: Final = "csv-import"
TERM_SOURCE_JSONL_IMPORT: Final = "jsonl-import"

# --- Source-format tokens (cycle-5 S3) ---
# Stored on ``SkippedRow.source_format`` so the ``ImportSkipStore``
# and the ``single_row_source`` factory can reconstruct the correct
# ``TermbaseSource`` adapter at retry time.
SOURCE_FORMAT_CSV: Final = "csv"
SOURCE_FORMAT_JSONL: Final = "jsonl"

# --- CSV dialect defaults (RFC 4180) ---
# Override-able per CLI run via `--encoding` / `--delimiter` flags.
# No `chardet`-style auto-detection — that's a 5+ MB dep for a
# problem the user can solve with one flag (per pitch § Risks).
DEFAULT_CSV_DELIMITER: Final = ","
DEFAULT_CSV_QUOTECHAR: Final = '"'
DEFAULT_CSV_ENCODING: Final = "utf-8"

# --- FieldMapping YAML schema keys ---
# The loader reads these from the user's `--map-config` file.
# Pinned as constants so the Pydantic schema, the loader, and any
# future tooling all agree on the wire shape.
MAP_KEY_SOURCE_LANG: Final = "source_lang"
MAP_KEY_SOURCE_COLUMN: Final = "source_column"
MAP_KEY_TARGET_COLUMNS: Final = "target_columns"
MAP_KEY_DOMAIN_COLUMN: Final = "domain_column"
MAP_KEY_DEFINITION_COLUMN: Final = "definition_column"


__all__ = [
    "TERM_SOURCE_CSV_IMPORT",
    "TERM_SOURCE_JSONL_IMPORT",
    "SOURCE_FORMAT_CSV",
    "SOURCE_FORMAT_JSONL",
    "DEFAULT_CSV_DELIMITER",
    "DEFAULT_CSV_QUOTECHAR",
    "DEFAULT_CSV_ENCODING",
    "MAP_KEY_SOURCE_LANG",
    "MAP_KEY_SOURCE_COLUMN",
    "MAP_KEY_TARGET_COLUMNS",
    "MAP_KEY_DOMAIN_COLUMN",
    "MAP_KEY_DEFINITION_COLUMN",
]
