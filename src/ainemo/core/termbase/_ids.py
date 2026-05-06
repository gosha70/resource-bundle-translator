# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Stable identifiers + defaults for the termbase package.

Mirrors :mod:`ainemo.providers._ids` and the cycle-1 ``DEFAULT_*``
constants in :mod:`ainemo.core.tm.base` / :mod:`ainemo.core.tm.sqlite`:
every named string or numeric default that crosses a module boundary
becomes a ``Final`` constant here. AGENTS.md § Prohibited Patterns and
the project memory rule *No magic strings/numbers — named constants
always* both apply.

Q1 / Q2 from the pitch (resolved at /bet, 2026-05-05):

- Q1 — auto-promotion thresholds: take the proposed defaults
  (``DEFAULT_PROMOTION_FREQUENCY_MIN = 5``,
  ``DEFAULT_PROMOTION_CONSISTENCY_MIN = 0.9``). CLI flags override
  per run; cycle-3 cooldown re-tunes once real-world ``nemo termbase
  promote --review`` data is in.
- Q2 — persona schema: 4 of 5 optional fields kept; ``provider_hints``
  dropped in favor of the cycle-2 ``RoutingConfig`` ``persona`` /
  ``domain`` matchers.
"""

from __future__ import annotations

from typing import Final

# --- Kuzu node labels ---
NODE_LABEL_CONCEPT: Final = "Concept"
NODE_LABEL_TERM: Final = "Term"
NODE_LABEL_DOMAIN: Final = "Domain"
NODE_LABEL_PERSONA: Final = "Persona"
NODE_LABEL_SEGMENT: Final = "Segment"

# --- Kuzu relationship labels ---
REL_HAS_TERM: Final = "HAS_TERM"
REL_IN_DOMAIN: Final = "IN_DOMAIN"
REL_DERIVED_FROM_SEGMENT: Final = "DERIVED_FROM_SEGMENT"

# --- Term provenance tags ---
# Stored on `Term.source` so the reviewer surface (cycle 5) can
# distinguish a Weblate-imported term from an auto-promoted TM
# candidate from a cycle-4 domain pack.
TERM_SOURCE_TBX_IMPORT: Final = "tbx-import"
TERM_SOURCE_TM_PROMOTION: Final = "tm-promotion"
TERM_SOURCE_MANUAL: Final = "manual"
TERM_SOURCE_DOMAIN_PACK: Final = "domain-pack"

# --- Storage + persona conventions ---
# Per-project termbase under ./.ainemo/termbase.kuzu (Kuzu is a
# directory-shaped embedded DB). Excluded from git by the existing
# `.ainemo/` `.gitignore` line. Per-user override via a future
# `--termbase-path` CLI flag (deferred to cooldown per pitch Q5).
DEFAULT_TERMBASE_PATH: Final = ".ainemo/termbase.kuzu"
PERSONA_FILE_EXTENSION: Final = ".yaml"
DEFAULT_PERSONA_DIR: Final = "src/ainemo/personas"

# --- Auto-promotion thresholds (resolved at /bet — Q1) ---
# Frequency: an n-gram must appear in at least N distinct TM segments
# before it is even considered. Consistency: of those segments, at
# least this fraction must translate to the same target string.
# Both override-able per CLI run (S5).
DEFAULT_PROMOTION_FREQUENCY_MIN: Final = 5
DEFAULT_PROMOTION_CONSISTENCY_MIN: Final = 0.9


__all__ = [
    "NODE_LABEL_CONCEPT",
    "NODE_LABEL_TERM",
    "NODE_LABEL_DOMAIN",
    "NODE_LABEL_PERSONA",
    "NODE_LABEL_SEGMENT",
    "REL_HAS_TERM",
    "REL_IN_DOMAIN",
    "REL_DERIVED_FROM_SEGMENT",
    "TERM_SOURCE_TBX_IMPORT",
    "TERM_SOURCE_TM_PROMOTION",
    "TERM_SOURCE_MANUAL",
    "TERM_SOURCE_DOMAIN_PACK",
    "DEFAULT_TERMBASE_PATH",
    "PERSONA_FILE_EXTENSION",
    "DEFAULT_PERSONA_DIR",
    "DEFAULT_PROMOTION_FREQUENCY_MIN",
    "DEFAULT_PROMOTION_CONSISTENCY_MIN",
]
