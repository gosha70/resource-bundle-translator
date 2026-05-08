# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Stable identifiers + defaults for the Flask reviewer app.

Mirrors :mod:`ainemo.core.termbase._ids` and
:mod:`ainemo.core.termbase.sources._ids`: every named string or numeric
default that crosses a module boundary is a ``Final`` constant here.
AGENTS.md § Prohibited Patterns and the project memory rule
*No magic strings/numbers — named constants always* both apply.

HTMX vendoring note (cycle-5 S1, pre-resolved Q1):
    The reviewer app ships ``htmx.min.js`` as a **vendored static file**
    under ``src/ainemo/app/static/``. No CDN script tag is used —
    local-first / no-phone-home per CLAUDE.md § Architecture Rules.
    ``HTMX_VENDORED_SHA256`` is the sha256 of the bundled file; the S1
    smoke test asserts it matches so a CDN regression is caught
    immediately on CI.

Default bind (cycle-5 S1, pre-resolved Q3):
    ``127.0.0.1:5050`` — single-user-localhost. ``--host 0.0.0.0``
    is allowed via the CLI flag but the help text notes the user
    accepts responsibility for any auth layer in front of it.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Route names — used in url_for() + template hrefs; never inline strings.
# ---------------------------------------------------------------------------

ROUTE_INDEX: Final = "index"
ROUTE_PROMOTE_QUEUE: Final = "promote_queue"
ROUTE_PROMOTE_DECIDE: Final = "promote_decide"
ROUTE_IMPORT_SKIPS: Final = "import_skips"
ROUTE_IMPORT_REPLAY: Final = "import_replay"
ROUTE_TERMBASE_LIST: Final = "termbase_list"
ROUTE_TERMBASE_EDIT: Final = "termbase_edit"
ROUTE_PERSONA_LIST: Final = "persona_list"
ROUTE_PERSONA_PREVIEW: Final = "persona_preview"
ROUTE_QA_CONFIDENCE: Final = "qa_confidence"
ROUTE_QA_BACK_TRANSLATE: Final = "qa_back_translate"

# ---------------------------------------------------------------------------
# Decision tokens — form values for the promote-queue accept/reject/edit flow.
# ---------------------------------------------------------------------------

DECISION_ACCEPT: Final = "accept"
DECISION_REJECT: Final = "reject"
DECISION_EDIT: Final = "edit"

# ---------------------------------------------------------------------------
# Default storage paths (no magic strings; mirrors cycle-3/4 defaults).
# ---------------------------------------------------------------------------

DEFAULT_IMPORT_SKIPS_PATH: Final = ".ainemo/import_skips.db"

# ---------------------------------------------------------------------------
# Confidence-signal weights.
# Cycle-5 cooldown candidate: re-tune from real reviewer-decision data.
# Initial values are reasoned defaults — termbase + placeholder weighted
# equally, length is a softer signal, back-translation dominates when
# opted in. Per pitch § Open questions Q9.
# ---------------------------------------------------------------------------

WEIGHT_TERMBASE_COSINE: Final = 0.4
WEIGHT_PLACEHOLDER_PARITY: Final = 0.4
WEIGHT_LENGTH_BUDGET: Final = 0.2
WEIGHT_BACK_TRANSLATION_COSINE: Final = 1.0  # only when opted in per segment

# ---------------------------------------------------------------------------
# Vendored HTMX (cycle-5 S1, pre-resolved Q1 — no CDN, no Node toolchain).
# Version: 2.0.4  Source: https://github.com/bigskysoftware/htmx/releases
# SHA-256 covers the exact bytes in src/ainemo/app/static/htmx.min.js.
# The S1 smoke test asserts GET /static/htmx.min.js content matches this
# hash — CDN regression test per pitch § S1 acceptance criteria.
# ---------------------------------------------------------------------------

HTMX_VENDORED_VERSION: Final = "2.0.4"
HTMX_VENDORED_SHA256: Final = "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447"

# ---------------------------------------------------------------------------
# Flask server defaults (single-user-localhost; pre-resolved Q3).
# ---------------------------------------------------------------------------

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 5050


__all__ = [
    "DECISION_ACCEPT",
    "DECISION_EDIT",
    "DECISION_REJECT",
    "DEFAULT_HOST",
    "DEFAULT_IMPORT_SKIPS_PATH",
    "DEFAULT_PORT",
    "HTMX_VENDORED_SHA256",
    "HTMX_VENDORED_VERSION",
    "ROUTE_INDEX",
    "ROUTE_IMPORT_REPLAY",
    "ROUTE_IMPORT_SKIPS",
    "ROUTE_PERSONA_LIST",
    "ROUTE_PERSONA_PREVIEW",
    "ROUTE_PROMOTE_DECIDE",
    "ROUTE_PROMOTE_QUEUE",
    "ROUTE_QA_BACK_TRANSLATE",
    "ROUTE_QA_CONFIDENCE",
    "ROUTE_TERMBASE_EDIT",
    "ROUTE_TERMBASE_LIST",
    "WEIGHT_BACK_TRANSLATION_COSINE",
    "WEIGHT_LENGTH_BUDGET",
    "WEIGHT_PLACEHOLDER_PARITY",
    "WEIGHT_TERMBASE_COSINE",
]
