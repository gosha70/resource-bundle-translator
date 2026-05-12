---
pitch_id: 0005-reviewer-ui-qa-layer
title: "Cycle 5 — Reviewer Web UI + QA Layer"
appetite: 6w
bet_status: shipped
cycle: "05"
circuit_breaker: "If the QA Layer (S5 — back-translation behind opt-in flag + cheap-signal confidence scoring) is still uphill at week 4, ship the reviewer UI without back-translation: the auto-promotion queue (S2), import-skip queue (S3), termbase curation (S4), persona inspector (S6), and cheap-signal confidence display (subset of S5) are core; back-translation moves to cycle-5 cooldown or cycle-6. The reviewer UI is the moat-builder for cycle 5; back-translation is a nice-to-have."
shaped_by: gosha70
shaped_date: 2026-05-07
---

<!-- AI-NEMO Shape-Up pitch template. Companion to plan.md / spec.md / tasks.md. -->
<!-- See specs/README.md for the full SDD + Shape-Up workflow. -->

# Cycle 5 — Reviewer Web UI + QA Layer

<!-- Human-readable header. Authoritative status / dates live in the YAML
     frontmatter above; this list is for at-a-glance reference and is what the
     README + ROADMAP cross-link to. Keep them in sync when bet_status flips. -->

- **ID**: 0005
- **Appetite**: 6w (wall-clock ceiling; actual session execution measured in hours per project memory rule *Calibrate estimates for Claude Code, not human-days*)
- **Status**: building (cycle 05 open for execution as of 2026-05-07)
- **Owner**: gosha70

## Problem

Cycle 3 shipped the concept-oriented termbase + the auto-promotion algorithm. Cycle 4 shipped the importer pipeline. Both cycles produce **reviewer-shaped queues** that today live in CLI-only surfaces and force the reviewer to make decisions one terminal prompt at a time:

1. **Auto-promotion candidates** (cycle-3 S5). `nemo termbase promote --review` is a stdin loop (`y` / `n` / `q` per candidate, see [`src/ainemo/cli/termbase_commands.py:581-611`](../../../src/ainemo/cli/termbase_commands.py)). The reviewer sees the n-gram, frequency, and consistency — but nothing else. They cannot see *which TM segments* the n-gram came from, *which provider/model* produced each translation, *whether existing termbase concepts already cover the candidate*, or *what the persona-filtered glossary block would look like* with the candidate added. Decisions get rushed because the context isn't in the surface.
2. **Import-skip rows** (cycle-4 S2/S3). `ImportReport.skipped_details` is a `tuple[str, ...]` of human-readable lines printed once at the end of `nemo termbase import-from-csv` / `import-from-jsonl` (see [`cli/termbase_commands.py:516-520, 571-575`](../../../src/ainemo/cli/termbase_commands.py)). The reviewer sees what failed; they cannot fix-and-re-import incrementally without re-editing the source CSV/JSONL by hand. The original row is gone — only the skip reason is preserved.

Plus two surfaces that today have no reviewer UI at all and limit the substrate's usefulness:

3. **Termbase curation**. To list, search, edit, or attach Concepts and Terms today the reviewer has to either run `nemo termbase export some.tbx` and hand-edit XML, or call the `Termbase` Protocol from a Python REPL. Weblate's glossary admin is the closest comparable surface; AI-NEMO's local-first equivalent does not exist yet.
4. **Persona inspector**. The three starter personas + any user-authored ones are YAML files under `src/ainemo/personas/`. The reviewer cannot see *for a given segment, which concepts the persona's domain filter would actually surface* without running a translation and reading the daemon log. The cycle-3 persona system shipped the contract; the inspection surface to build trust in it did not.

CLAUDE.md § Agent Team explicitly names a **UI Engineer** role for cycle 5+ owning `app/` and `app/templates/`. The cycle-3 cooldown carryforward item #5 (CLI-loop UX observations from `nemo termbase promote --review`) and cycle-4's S6 fixes (#7 + #8 — surface honest error text in the right place) directly inform what a reviewer UI should expose. The cooldown-after-04 report names this as the headline shaping target: "natural consumer of cycle-3 auto-promotion candidate queue and cycle-4 import-skip rows". The audience is unchanged from cycle 4 — software i18n teams loading their own glossaries — and confirmed at cycle-4 /bet.

## Appetite

**6w wall-clock ceiling.** The cycle has five reviewer-shaped surfaces (auto-promotion queue, import-skip queue, termbase curation, persona inspector, QA confidence display) plus a Flask scaffolding scope and a docs scope. Code execution is hours per the project memory rule. The 6w wall-clock buffer covers reviewer-iteration cycles on the actual UI shape (visual / interaction quality is harder to nail in a single shaping pass than back-end work) + a back-translation QA layer that may or may not pan out (circuit-breaker target). A 4w would force shipping without back-translation; a 2w would not fit five UI surfaces with even minimal review iterations. 6w matches the cycle-3 / cycle-2 wall-clock shape for cycles with this many independent surfaces.

## Solution shape

```
┌─ Cycle-1..4 substrate (already shipped) ──────────────────────────┐
│                                                                   │
│   Termbase Protocol           (cycle 3)                           │
│   TranslationMemory Protocol  (cycle 1)                           │
│   ProviderRouter + UsageLog   (cycle 2)                           │
│   ImportReport.skipped_details  (cycle 4)                         │
│   PromotionCandidate            (cycle 3)                         │
│   Persona system + YAML loader (cycle 3)                          │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌─ Cycle 5 adds ─────────────────────────────────────────────────────┐
│                                                                    │
│  Flask app under src/ainemo/app/                                   │
│   │                                                                │
│   ├─ /promote    auto-promotion candidate queue (cycle-3 S5 UI)    │
│   ├─ /imports    import-skip queue (cycle-4 ImportReport UI)       │
│   ├─ /termbase   concept/term curation (list / search / edit)      │
│   ├─ /personas   persona inspector (read-only with hit-preview)    │
│   └─ /qa         confidence display + opt-in back-translation      │
│                                                                    │
│  HTMX-driven fragments — no Node toolchain. Server-rendered        │
│  Jinja templates; HTMX swaps partials per row decision.            │
│                                                                    │
│  All UI actions write through existing core Protocols              │
│  (`Termbase.add_concept`, `Termbase.add_persona`, etc.) —           │
│  Flask runs in-process; no shell-out to `nemo termbase`.           │
│                                                                    │
│  CLI surfaces (`nemo termbase promote --review`, `nemo termbase    │
│  import-from-csv`, etc.) all stay; the UI is **additive**.         │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

┌─ ImportSkipStore (NEW — cycle 5) ──────────────────────────────────┐
│                                                                    │
│   The cycle-4 importer shipped skipped_details as printed strings. │
│   Cycle-5 wraps the importer in a thin store that *also* writes    │
│   each skipped row to a SQLite table at `.ainemo/import_skips.db`  │
│   with the original row payload preserved (CSV row → JSON dict;    │
│   JSONL row → JSON line). The /imports queue reads from there;     │
│   the CLI `nemo termbase import-from-csv` / `-jsonl` print path    │
│   stays byte-for-byte stable so cycle-4 tests do not regress.      │
│                                                                    │
│   **Cycle-4 SkippedRow extension (additive Protocol change):**     │
│   `SkippedRow` today is `(reason: str)` only — the row payload,    │
│   index, and source path are dropped before the loader sees the    │
│   skip, so a queue keyed only on `reason` cannot retry. S3 adds    │
│   four optional fields to `SkippedRow` (`row_payload: str | None`, │
│   `row_index: int | None`, `source_path: str | None`,              │
│   `source_format: str | None`) populated by `CsvSource` /          │
│   `JsonLinesSource` and threaded through the loader to             │
│   `ImportSkipStore.add(...)`. Defaults `None` so cycle-4 callers   │
│   that read `SkippedRow` as `(reason,)` stay byte-stable; the      │
│   cycle-4 contract test for the print path is unaffected.          │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

The shape is "thin Flask app over the existing Protocols" — five HTMX-driven views, one new SQLite-backed store for import-skip persistence, zero new core abstractions. Library-first / CLI-second / build-tool-plugin-third / **UI-fourth** per CLAUDE.md § Architecture Rules: the UI is the last surface, never source-of-truth. Every UI action that writes calls into a cycle-1/2/3/4 Protocol method that the CLI also calls; the CLI surfaces stay byte-stable so cycle-3 + cycle-4 integration tests continue to pass unchanged.

### Frontend stack — HTMX + Jinja (decision)

Two genuine alternatives surfaced at shaping: HTMX + server-rendered Jinja vs React + JSON API. **Decision: HTMX + Jinja.** Rationale:

- **No Node toolchain.** AI-NEMO ships as a Python package; CI runs Python only (cycles 0–4). Adding a Node + bundler dependency for cycle 5 puts a new prerequisite on every contributor and every CI matrix cell.
- **Local-first alignment.** CLAUDE.md § Architecture Rules: *"Local-first. No SaaS, no telemetry, no phone-home."* HTMX renders on the server; React shifts logic to the client without buying anything for a single-user-localhost surface.
- **Test infrastructure already exists.** Flask test client + `pytest` markers (`unit` / `integration` / `e2e`) cover server-rendered fragments without Selenium / Playwright. A React app would force introducing JSDOM or component-test tooling, which adds a CI matrix dimension.
- **Audience fit.** Software i18n teams running a localhost reviewer don't care about SPA polish; they care about page weight, latency, and that the surface keeps working when they upgrade Python.
- **Reversible.** A future cycle can layer a React or Vue surface on top of the same Flask routes if a real user surfaces a need — HTMX does not preclude that, while a React-first cycle 5 would lock in the toolchain.

This is the contested call the cooldown-after-04 report flagged for /bet. The shape commits to HTMX + Jinja; if /bet wants to revisit, the alternative is a 2-week appetite reduction (drop S5 entirely, ship S1–S4 + S6) rather than a swap to React, since React doubles the scaffolding work in S1.

### QA Layer scope — cheap signals as core, back-translation as opt-in (decision)

Three options at shaping: (a) ship full back-translation QA, (b) ship cheap signals only, (c) ship cheap signals + back-translation as a per-segment opt-in flag. **Decision: option (c).** Rationale:

- **Cheap signals are zero marginal cost.** MiniLM cosine to nearest termbase concept (cycle-3 embedding model already pinned; embeddings already computed for TM fuzzy lookup), placeholder-parity score (cycle-1 validator already runs), length-budget flag (cycle-1 validator already runs) — all three reuse existing infrastructure and add no provider tokens.
- **Back-translation is high-signal but expensive.** Translating target → source via a *different* provider doubles per-segment cost on every QA-checked segment. For a project that pins `temperature=0` for reproducibility (CLAUDE.md § Translation-Domain Conventions), the cost-per-bit-of-confidence ratio is unproven on real corpora.
- **Opt-in flag de-risks the cycle.** The user clicks a "Run back-translation" button per segment; the action records the second provider's cost in the existing `UsageLog` (cycle-2 surface) and shows the similarity score. No hot-path cost; reviewer controls the spend.
- **Circuit-breaker fits cleanly.** If back-translation turns out to be either expensive (the user reports the per-segment cost is too high to be useful in practice) or unreliable (the similarity score doesn't correlate with actual translation quality on the dogfood corpus), the breaker drops S5's back-translation half and keeps cheap signals. The reviewer UI still ships its full headline minus one button.

### Interfaces (SDD layer)

**`src/ainemo/app/_ids.py`** — module-level `Final` constants per the *No magic strings* rule (mirrors cycle-3's `core/termbase/_ids.py` and cycle-4's `core/termbase/sources/_ids.py`):

```python
from typing import Final

# Route names (used in url_for + template hrefs; never inline strings)
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

# Decision tokens (form values for accept / reject / edit-then-accept)
DECISION_ACCEPT: Final = "accept"
DECISION_REJECT: Final = "reject"
DECISION_EDIT: Final = "edit"

# Default storage paths
DEFAULT_IMPORT_SKIPS_PATH: Final = ".ainemo/import_skips.db"

# Confidence-signal weights (open question — see § Open questions Q1)
WEIGHT_TERMBASE_COSINE: Final = 0.4
WEIGHT_PLACEHOLDER_PARITY: Final = 0.4
WEIGHT_LENGTH_BUDGET: Final = 0.2
WEIGHT_BACK_TRANSLATION_COSINE: Final = 1.0   # only when opted in
```

**`src/ainemo/app/__init__.py`** — Flask app factory:

```python
def create_app(
    *,
    termbase: Termbase,
    tm: TranslationMemory,
    router: ProviderRouter,
    import_skips: ImportSkipStore,
    config: AppConfig | None = None,
) -> Flask: ...
```

The factory takes injected dependencies (Protocols, not concretes) so tests can swap in `MemoryTermbase` / in-memory TM / fake router. Mirrors the cycle-3 termbase + cycle-2 router DI conventions.

**`src/ainemo/app/views/promote.py`** — auto-promotion candidate queue. Reads `find_candidates(tm, src, tgt, ...)` from cycle-3, augments each `PromotionCandidate` with:
- The list of TM segment fingerprints contributing the n-gram (so the reviewer sees real source segments).
- For each contributing segment: provider/model from the TM row's metadata.
- Existing termbase concept hits for the source n-gram (so the reviewer doesn't add a duplicate).
- Confidence signals from S5 (MiniLM cosine, placeholder parity, length budget).

Decision form posts `decision={accept|reject|edit}` + optional `edited_target_surface`; on accept, calls the same `_write_candidate(tb, candidate)` helper the CLI uses (extracted to `core/termbase/promotion.py` from `cli/termbase_commands.py:614-647` so it's no longer CLI-private). The CLI's `--review` loop continues to work unchanged.

**`src/ainemo/app/views/imports.py`** — import-skip queue. Reads from `ImportSkipStore`, displays one row per skipped import with the original CSV/JSONL row preserved. Per row: the user can edit the row's fields in-place and submit "retry-with-edits"; the retry calls back into `load_into_termbase` with a single-row in-memory `TermbaseSource` adapter. On success, the skip row is deleted from the store; on second skip, the row updates with the new reason.

**`src/ainemo/app/views/termbase.py`** — list / search / edit Concepts and Terms. Search by source surface (literal n-gram match using cycle-3 `lookup_concepts_for`). Edit form modifies a Term's `surface` / `register` / `part_of_speech`; calls a new `Termbase.update_term(term_id, **fields)` Protocol method (additive — backward compat preserved). Quick-export button calls cycle-3 `TbxExporter` and streams TBX 3.0 as a download.

**`src/ainemo/app/views/personas.py`** — read-only persona inspector. Lists personas from `tb.list_personas()`; per persona, shows YAML-source + a "preview hits" form: paste a source segment + target lang, get back the glossary block the persona's domain filter would surface (the same block that `core/pipeline.py` builds before injecting into the provider system prompt — extracted to `core/termbase/persona_glue.py` so the UI and the pipeline share one builder).

**`src/ainemo/app/views/qa.py`** — confidence display + back-translation. Per-segment confidence is computed lazily on first view from the cheap signals (no provider call). The "Run back-translation" button posts to `/qa/back-translate?segment_fingerprint=...&provider=...` — translates target → source via the named provider (different from the original provider; if no different provider is available, the form rejects), computes MiniLM cosine between the back-translation and the original source, and updates the segment's confidence row. Cost recorded in `UsageLog`.

**`src/ainemo/app/store/import_skips.py`** — `ImportSkipStore`:

```python
@dataclass(frozen=True)
class ImportSkipRow:
    skip_id: str                    # content-addressed: sha256(source_path || row_index || row_payload)
    source_path: str                # e.g. "/path/to/glossary.csv"
    source_format: str              # "csv" | "jsonl"
    row_index: int                  # 1-based, matches ImportReport.skipped_details
    row_payload: str                # JSON-serialized original row
    skip_reason: str                # the line from ImportReport.skipped_details
    created_at: int                 # epoch seconds
    last_retried_at: int | None

class ImportSkipStore(Protocol):
    def add(self, row: ImportSkipRow) -> None: ...
    def list(self, *, source_path: str | None = None) -> tuple[ImportSkipRow, ...]: ...
    def get(self, skip_id: str) -> ImportSkipRow | None: ...
    def remove(self, skip_id: str) -> None: ...
    def update_retry(self, skip_id: str, *, success: bool, new_reason: str | None) -> None: ...

class SqliteImportSkipStore: ...   # cycle-5 only impl; Protocol exists for tests
```

The `id` derivation uses the cycle-3 + cycle-4 content-addressed pattern. The cycle-4 CLI gets a thin additive write — when `ImportSkipStore` is supplied to `load_into_termbase`, skipped rows write to the store *in addition to* the existing `ImportReport.skipped_details` print path; when omitted (cycle-4 default), behavior is byte-stable.

**Pipeline + CLI integration**:

- `core/termbase/promotion.py` gains `write_accepted_candidate(tb, candidate)` extracted from the CLI's private `_write_candidate`. Both the CLI `--review` loop and the Flask `/promote/decide` route call it. Cycle-3 `--accept-all` regression-clean.
- `core/termbase/sources/loader.py` `load_into_termbase` gains an optional keyword-only `skip_store: ImportSkipStore | None = None` parameter. When supplied, skipped rows are also written to the store. When `None` (default), behavior is identical to cycle 4.
- `cli/__init__.py` gains `nemo app run [--host 127.0.0.1] [--port 5050] [--termbase-path PATH] [--tm-path PATH]`. Wraps `flask --app ainemo.app run` with the project's defaults pre-wired so users don't have to remember Flask CLI invocation. Default bind is `127.0.0.1` (single-user-localhost; pre-resolved Q1).

## Scopes

> Estimates are session-execution time, not human-developer-days (project memory rule: *Calibrate estimates for Claude Code, not human-days*). Total cycle 5 execution is ~6–8 hours; the 6w appetite is wall-clock willingness to wait for review iterations + dogfooding + the back-translation experiment.

### S1: Flask app scaffolding + DI factory + `nemo app run` CLI

`src/ainemo/app/__init__.py` (factory), `src/ainemo/app/_ids.py` (route + decision constants), `src/ainemo/app/config.py` (`AppConfig` Pydantic model — `extra="forbid"` per cycle-3 S4 lesson, `host` / `port` / `debug` / `secret_key` / paths to TM / termbase / import-skip store), `src/ainemo/app/extensions.py` (Flask extension wiring — Jinja env + HTMX response helper), `src/ainemo/app/static/htmx.min.js` (**vendored**, version-pinned via SHA-256 in `_ids.py:HTMX_VENDORED_SHA256`; **no CDN script tag** — local-first / no-phone-home per CLAUDE.md § Architecture Rules), `src/ainemo/app/templates/base.html` (shared layout that loads HTMX via `url_for('static', filename='htmx.min.js')`), `src/ainemo/cli/app_commands.py` (`nemo app run`). CI gains a Flask-test-client smoke test asserting the app starts, `GET /` returns 200, and `GET /static/htmx.min.js` is served by Flask (not redirected to a CDN). Files: `src/ainemo/app/__init__.py`, `src/ainemo/app/_ids.py`, `src/ainemo/app/config.py`, `src/ainemo/app/extensions.py`, `src/ainemo/app/static/htmx.min.js` (vendored), `src/ainemo/app/templates/base.html`, `src/ainemo/app/templates/_index.html`, `src/ainemo/cli/app_commands.py`, `tests/integration/test_app_smoke.py`. **Estimate: ~75 min.**

### S2: Auto-promotion candidate queue (`/promote`)

`src/ainemo/app/views/promote.py` (queue list + decide POST), `src/ainemo/app/templates/promote/list.html` + `promote/_row.html` (HTMX fragment per candidate). Extract `_write_candidate` from `cli/termbase_commands.py:614-647` to `core/termbase/promotion.py:write_accepted_candidate(tb, candidate)`; both CLI and UI call the shared helper. Augment each candidate display with: contributing TM segment fingerprints (sample up to 5), provider/model breakdown across those segments, existing concept hits for the source n-gram, all four confidence signals from S5 displayed inline. Files: `src/ainemo/app/views/promote.py`, `src/ainemo/app/templates/promote/*.html`, `core/termbase/promotion.py` (additive), `cli/termbase_commands.py` (refactored to call shared helper), `tests/integration/test_app_promote.py` (≥ 6 cases incl. accept / reject / edit-then-accept / decision is idempotent on re-POST / CLI `--review` and UI accept produce identical termbase rows). **Estimate: ~75 min.**

### S3: Import-skip queue (`/imports`) + `ImportSkipStore` + `SkippedRow` payload extension

**Cycle-4 Protocol extension (additive, defaults preserve byte-stability):**
`core/termbase/sources/base.py` — `SkippedRow` gains four optional fields: `row_payload: str | None = None` (JSON-serialized original CSV row dict / JSONL line), `row_index: int | None = None` (1-based, matches the `row N:` prefix on `reason`), `source_path: str | None = None`, `source_format: str | None = None` (`"csv"` / `"jsonl"`). `CsvSource` and `JsonLinesSource` populate them when emitting a `SkippedRow`; their existing print-path tests stay green because `reason` formatting is unchanged. The cycle-4 `TermbaseSource` Protocol contract test is extended with one new case asserting the structured fields are populated for both sources.

**Loader bridge:** `core/termbase/sources/loader.py:load_into_termbase` gains keyword-only `skip_store: ImportSkipStore | None = None`. When supplied, the loader threads `SkippedRow.row_payload` / `row_index` / `source_path` / `source_format` plus the `reason` into `ImportSkipStore.add(...)`. When `None` (cycle-4 default), behavior is identical — print path unchanged, cycle-4 tests byte-stable.

**Store + UI:** `src/ainemo/app/store/import_skips.py` (Protocol + `SqliteImportSkipStore`), `src/ainemo/app/views/imports.py` (list + retry POST), `src/ainemo/app/templates/imports/list.html` + `imports/_row.html`. Retry path reconstructs a single-row `TermbaseSource` from `ImportSkipRow.row_payload` + `source_format` (the `single_row_source(row, mapping)` factory documented in § Risks) and calls `load_into_termbase` for that row.

**CLI integration:** `cli/termbase_commands.py` — `nemo termbase import-from-csv` / `-jsonl` gain an optional `--import-skip-store PATH` flag (default off). When set, also writes to the store; CLI stdout output stays byte-stable per the cycle-4 acceptance criteria.

Files: `core/termbase/sources/base.py` (additive `SkippedRow` fields), `core/termbase/sources/csv_source.py` + `jsonl_source.py` (populate the new fields), `core/termbase/sources/loader.py` (additive `skip_store` parameter), `cli/termbase_commands.py` (additive `--import-skip-store` flag), `src/ainemo/app/store/__init__.py`, `src/ainemo/app/store/import_skips.py`, `src/ainemo/app/views/imports.py`, `src/ainemo/app/templates/imports/*.html`, `tests/unit/test_import_skip_store.py`, `tests/integration/test_app_imports.py` (≥ 6 cases incl. retry success removes row, retry failure updates reason, idempotency on re-POST, CLI-only path with no `--import-skip-store` flag remains byte-stable, `SkippedRow` structured fields populated end-to-end). **Estimate: ~120 min.**

### S4: Termbase curation (`/termbase`)

`src/ainemo/app/views/termbase.py` (list / search / edit / quick-export), `src/ainemo/app/templates/termbase/*.html`. Adds `Termbase.update_term(term_id, **fields)` to the cycle-3 Protocol (additive — concrete impl on `KuzuTermbase`, no-op-friendly default on `MemoryTermbase` test double). Search uses `lookup_concepts_for` (cycle-3 surface) for source-side queries; target-side / metadata search via direct Kuzu-API calls in the `KuzuTermbase` impl. Quick-export streams TBX 3.0 via cycle-3 `TbxExporter`. Files: `src/ainemo/app/views/termbase.py`, `src/ainemo/app/templates/termbase/*.html`, `core/termbase/base.py` (additive `update_term` method), `core/termbase/kuzu/store.py` (impl), `tests/integration/test_app_termbase.py` (≥ 6 cases incl. list pagination, search hits / misses, edit round-trip, quick-export integrity). **Estimate: ~75 min.**

### S5: QA Layer — cheap-signal confidence + back-translation opt-in (`/qa`)

**Cheap signals:** `src/ainemo/app/qa/signals.py` — pure-Python computation of MiniLM cosine to nearest termbase concept, placeholder-parity score (delegates to cycle-1 `PlaceholderParityValidator`), length-budget flag (delegates to cycle-1 `LengthBudgetValidator`). All three reuse cycle-1/3 infrastructure; zero new provider calls.

**Cycle-2 Provider/Router/UsageLog API additions (additive — back-translation needs surfaces that don't exist today):**

- `providers/router.py` — `ProviderRouter.translate_with(provider_id: str, segment, target_lang) -> ProviderResult`: bypasses `RoutingConfig` to invoke a *named* provider directly. The cycle-2 router today routes by config rule; cycle-5 needs an explicit-provider override for the QA layer. Raises `UnknownProviderError` when `provider_id` is not registered. Cost still records to `UsageLog`.
- `providers/router.py` — `ProviderRouter.list_registered() -> tuple[str, ...]`: returns provider IDs the router knows about. The QA form uses this to populate the back-translation provider dropdown and reject when only one provider is registered.
- `providers/_usage_log.py` — `UsageLog.estimate_for(provider_id: str, model: str | None, segment_length: int) -> float | None`: returns a cost estimate from historical per-(provider, model) median cost-per-character on the same `UsageLog`; returns `None` when no historical data. The QA form displays the estimate before activating the back-translation button. (Falls back gracefully — `None` shows "no historical cost data; first run will record" in the form.)

These three additions are additive to the cycle-2 surfaces and ship with their own unit tests. The cycle-2 contract tests for `ProviderRouter` + `UsageLog` are extended; existing routing-by-config behavior is unchanged.

**View:** `src/ainemo/app/views/qa.py` — confidence display + back-translation POST. The route accepts `?segment_fingerprint=...&provider_id=...`; back-translation chooses a *different* provider than the segment's original (rejects when `ProviderRouter.list_registered()` returns only one entry, or when the requested provider matches the original; surfaces the constraint in the form). Calls `ProviderRouter.translate_with(provider_id, ...)`; cost is recorded automatically in the existing `UsageLog` flow. Cosine of back-translation vs. original source uses the same MiniLM embedder cycle-1 TM uses. `src/ainemo/app/templates/qa/*.html`.

Files: `src/ainemo/app/qa/__init__.py`, `src/ainemo/app/qa/signals.py`, `src/ainemo/app/views/qa.py`, `src/ainemo/app/templates/qa/*.html`, `providers/router.py` (additive `translate_with` + `list_registered`), `providers/_usage_log.py` (additive `estimate_for`), `providers/_errors.py` (new `UnknownProviderError`), `tests/unit/test_qa_signals.py`, `tests/unit/test_router_translate_with.py`, `tests/unit/test_usage_log_estimate_for.py`, `tests/integration/test_app_qa.py` (≥ 6 cases incl. cheap signals deterministic on fixture, back-translation form rejects same-provider, rejects when only one provider registered, cost lands in UsageLog, `estimate_for` displays in form, opt-in flag does not run on page load). **Estimate: ~120 min.**

### S6: Persona inspector (`/personas`)

`src/ainemo/app/views/personas.py` (read-only list + preview-hits form), `src/ainemo/app/templates/personas/*.html`. Extract the persona-aware glossary-block builder from `core/pipeline.py` to `core/termbase/persona_glue.py:build_glossary_block(tb, persona, source_text, source_lang, target_lang) -> str`; pipeline keeps calling it; UI also calls it for the preview. Files: `src/ainemo/app/views/personas.py`, `src/ainemo/app/templates/personas/*.html`, `core/termbase/persona_glue.py`, `core/pipeline.py` (refactored to call shared helper), `tests/unit/test_persona_glue.py`, `tests/integration/test_app_personas.py` (≥ 4 cases incl. preview matches pipeline output byte-for-byte on shared fixture). **Estimate: ~60 min.**

### S7: Documentation + cycle-5 outcomes hooks

`docs/reviewer-ui.md` — getting started (`nemo app run`), each of the five views with a screenshot or ASCII diagram, security notes (single-user-localhost default, opt-in basic auth deferred to cycle 6), the QA layer's signals + back-translation opt-in semantics. `README.md` updated with a "Reviewer UI" section. `docs/qa-layer.md` — confidence-signal weights, back-translation procedure + cost trade-off. `specs/ROADMAP.md` § Cycle 5 row gets the *shipped* + *retro link* edits at cycle close. Files: `docs/reviewer-ui.md`, `docs/qa-layer.md`, `README.md`, `specs/ROADMAP.md`. **Estimate: ~45 min.**

**Total session-execution estimate: ~9 hours.** The 6w appetite is wall-clock budget for review iterations + UI dogfooding + the back-translation experiment + the inevitable HTMX-edge-case scope-hammer.

## Test strategy

**Unit** (per-module, fast, deterministic):
- `app/qa/signals.py`: deterministic cheap-signal computation on fixture termbase + fixture segment (assert exact float-tuple).
- `app/store/import_skips.py`: `SqliteImportSkipStore` add/list/get/remove/update_retry round-trip; content-addressed `skip_id` is stable.
- `core/termbase/promotion.py:write_accepted_candidate`: idempotent on re-write (cycle-3 S5 P2 fix preserved).
- `core/termbase/persona_glue.py:build_glossary_block`: byte-equivalent output on the same input as cycle-3 pipeline integration test.

**Integration** (slower, marked `integration`):
- Flask test client smoke test on every view (S1 baseline for every later S).
- `/promote` accept ↔ CLI `--review` accept produce identical termbase rows (regression of the shared-helper extraction).
- `/imports` retry-on-edited-row path: skip → edit-row → retry → row removed from store + concept added to termbase.
- `/termbase` edit form round-trip: edit Term → re-render list → edit reflected; quick-export TBX is a cycle-3 valid file.
- `/personas` preview matches `core/pipeline.py` glossary-block output on a shared fixture (regression of the shared-helper extraction).
- `/qa` cheap signals on a fixture: assert weights from `_ids.py` produce the documented composite score; back-translation rejects when no different provider available.

**Contract**:
- `ImportSkipStore` Protocol contract test: same suite runs against `SqliteImportSkipStore` + an in-memory test double. Mirrors cycle-3/4 contract-test convention.

**Acceptance criteria — cycle is "done" when**:
- `nemo app run` starts the Flask app on `127.0.0.1:5050` with all five views reachable.
- `/promote` decisions write to the same termbase rows as `nemo termbase promote --review`.
- `/imports` retry-on-edit successfully imports a previously-skipped row without re-editing the source CSV/JSONL.
- `/termbase` curation supports list, search, edit, quick-TBX-export.
- `/personas` preview-hits form returns the byte-equivalent glossary block the pipeline would inject.
- `/qa` displays cheap-signal confidence per segment; back-translation opt-in records cost in `UsageLog`.
- `docs/reviewer-ui.md` + `docs/qa-layer.md` written; README updated.
- CI green: ruff + format + mypy strict + pytest on Python 3.10/3.11/3.12 (no Selenium / Playwright introduced — Flask test client only).

## Rabbit holes

- **Don't reimplement the CLI surfaces inside the UI.** `nemo termbase init` / `import` / `export` / `promote` / `stats` / `import-from-csv` / `import-from-jsonl` all stay; the UI is *additive*. Per CLAUDE.md § Architecture Rules: *Library-first, CLI-second, build-tool-plugin-third*; UI is fourth and never source-of-truth.
- **Don't introduce a JS toolchain.** HTMX is shipped as a single vendored, version-pinned `htmx.min.js` under `src/ainemo/app/static/`. **No CDN script tag** (local-first / no-phone-home). No Node, no bundler, no TypeScript, no React. The "Pure Flask" constraint and "no Selenium / Playwright" testing constraint both lean against it.
- **Don't add real-time / WebSocket / SSE.** Single-user-localhost is the audience; multi-tab consistency via page refresh is fine. Adding a real-time layer doubles the test surface and changes the deployment story (gunicorn-with-eventlet vs. just `flask run`).
- **Don't model "session" / "review-batch" entities.** Each decision (accept/reject/retry) is independent and idempotent. A review-batch table would let users group decisions, but that's a UX feature with no shipped-cycle precedent — defer to user demand.
- **Don't try to make back-translation cheap.** The whole point of opting in per segment is that it's expensive. Don't pre-emit back-translations on page load, don't cache aggressively, don't try to amortize across segments. The reviewer pays for the segments they look at.
- **Don't generalize the persona inspector into a persona editor in cycle 5.** Editing personas means writing back to YAML files that ship with the package — that's a deployment / packaging question (does the user override under `~/.ainemo/personas/`? does the UI write to a project-local `.ainemo/personas/` directory?). The cycle-5 surface is read-only; persona editing is a cycle-6+ pitch if real users ask.
- **Don't add a "translate from the UI" button.** Translation runs through the existing CLI / daemon / Gradle plugin. The UI displays / curates / approves the *output* of translation; the only provider call the UI initiates is the back-translation in S5 (and that's an explicitly-flagged QA action, not a translation). Per CLAUDE.md § Architecture Rules: *Translation execution from the UI* is a no-go.

## No-gos

- No multi-tenant SaaS, hosted reviewer service, telemetry, or account systems beyond a single-user-localhost default. (CLAUDE.md § Architecture Rules: *Local-first*.)
- No translation execution from the UI. Translation stays in the CLI / daemon / Gradle plugin path. The UI's only provider call is the explicit per-segment back-translation in S5.
- No real-time collaboration features (live cursors, presence indicators, multi-user document editing). Single-reviewer-at-a-time is the audience.
- No mobile-first / mobile-optimized layout. Desktop-only is fine; the audience is software engineers at desks.
- No reimplementation of CLI surfaces. Every `nemo termbase ...` command stays; the UI is additive.
- No React / Vue / Svelte / Angular / SPA frontend in cycle 5. HTMX + Jinja only.
- No Node toolchain in CI. Python-only matrix stays.
- No basic-auth multi-user mode. Single-user-localhost default; multi-user authentication deferred to cycle 6 if real users ask.
- No new bundle formats. (Cycle 1's four — `.properties`, i18next JSON, gettext `.po`, XLIFF 2.0 — stay the canonical set.)
- No new providers. (Cycle 2's five — NLLB, OPUS, OpenAI, Anthropic, Ollama — stay the canonical set.)
- No new termbase storage backend. KuzuTermbase from cycle 3 stays the only impl.
- No persona editing UI. Read-only inspector only in cycle 5.
- No telemetry, no SaaS, no phone-home. (AGENTS.md § Architecture Rules: *Local-first*.)

## Risks

- **HTMX learning curve / interaction-design rabbit hole.** HTMX is straightforward but interaction quality (when does a row swap, when does the whole list re-render, when do errors surface inline) eats time if not pinned at shaping. Mitigation: every view ships a "list + per-row HTMX fragment" shape; no inline editing in the list; all edits go via a dedicated edit page that returns the refreshed row fragment. Documented in `docs/reviewer-ui.md` so future cycles inherit the convention.
- **Flask app factory + DI complexity.** The factory takes Termbase + TM + Router + ImportSkipStore — four injected dependencies. Mitigation: `AppConfig` Pydantic model with `extra="forbid"` (cycle-3 S4 lesson); test setup uses `MemoryTermbase` + in-memory TM + a fake router; integration tests assert each view works on the full DI graph.
- **Back-translation cost surprise.** A reviewer who clicks the back-translation button on every segment of a 1000-segment bundle racks up real API spend. Mitigation: the form shows the estimated cost from the new cycle-5 `UsageLog.estimate_for(provider_id, model, segment_length)` API (returns `None` and shows "no historical data" the first time the (provider, model) pair appears) *before* the button activates; the button is per-segment and never bulk; `docs/qa-layer.md` calls out the cost trade-off.
- **Provider-availability-for-back-translation gap.** If the user has only one provider configured, back-translation has nowhere to go. Mitigation: form rejects with "Configure a second provider in `RoutingConfig` to enable back-translation"; the cheap signals still display, so confidence is non-empty even without back-translation.
- **Protocol additions ripple across cycles.** Cycle 5 lands four additive surface changes: (a) `SkippedRow` gains four optional fields (S3); (b) `Termbase.update_term` lands on the Protocol + `KuzuTermbase` (S4); (c) `ProviderRouter` gains `translate_with` + `list_registered` (S5); (d) `UsageLog` gains `estimate_for` (S5). Each is additive and ships in the same PR as its concrete impl + test-double impl + contract-test extension. Cycle-1/2/3/4 contract tests stay byte-stable: defaults preserve old behavior on every Protocol where one applies. The cycle-4 `SkippedRow` fix is the riskiest of the four because it touches an actively-tested print path; mitigation is the existing `reason` formatting stays unchanged and the existing `tuple[ImportRecord | SkippedRow, ...]` consumers (the cycle-4 loader) read only `reason`.
- **CLI ↔ UI write-path divergence.** `_write_candidate` lives in `cli/termbase_commands.py` today; extracting to `core/termbase/promotion.py` and having both UI and CLI call it is the design, but a regression where one path drifts from the other would silently corrupt termbase rows. Mitigation: the S2 integration test asserts CLI accept and UI accept produce identical concept/term rows on the same candidate; this test is the canary if anyone refactors either path.
- **Single-row `TermbaseSource` retry adapter shape.** The `/imports` retry path reconstructs a single-row `TermbaseSource` from `ImportSkipRow.row_payload`. The `TermbaseSource` Protocol is iterator-shaped (cycle-4 S1); a single-row impl is mechanical but still a new code path. Mitigation: `app/store/import_skips.py:single_row_source(row, mapping)` factory + a focused unit test pinning round-trip semantics with a known-skipped fixture row.

## Open questions

These are pre-resolved from project docs per the *Pre-resolve "open questions" from project docs before asking the user* memory rule. **Two were genuinely contested** at shaping (frontend stack, QA layer scope) and both were decided at shaping with explicit rationale in § Solution shape — `/bet` may revisit but the shape commits to the decisions. The remaining nine are settled in the relevant cycle's pitch / retro / ROADMAP / CLAUDE.md.

### Decided at shaping (genuinely contested — `/bet` may revisit)

1. **Frontend stack** → **HTMX + Jinja.** See § Solution shape § "Frontend stack — HTMX + Jinja (decision)" for the four-point rationale (no Node toolchain / local-first alignment / existing Flask test infra / audience fit). React was the alternative; rejected for adding a Node prerequisite and doubling S1's scaffolding work without buying anything for a single-user-localhost surface. **`/bet` action**: confirm or swap. Swapping to React is a cycle-shape change (S1 doubles), not a no-op tweak.

2. **QA Layer scope** → **cheap signals as core, back-translation as opt-in flag.** See § Solution shape § "QA Layer scope — cheap signals as core, back-translation as opt-in (decision)" for the rationale. Full-back-translation-by-default was rejected on cost; cheap-signals-only was rejected for missing the QA Layer half of the cycle headline. The opt-in shape is the synthesis. **`/bet` action**: confirm; the circuit breaker is sized around dropping back-translation if it doesn't pan out, so the decision is recoverable mid-cycle.

### Pre-resolved (recorded at shaping, not contested at /bet)

3. **Auth model** → **single-user-localhost default, no auth in cycle 5.** Per CLAUDE.md § Architecture Rules (*Local-first*) — the audience is one reviewer at one workstation, not a team server. Multi-user / basic-auth deferred to cycle 6 if real users ask. The Flask app binds to `127.0.0.1` by default; `--host 0.0.0.0` is documented as "you accept full responsibility for any auth layer in front of it" but the cycle-5 product is single-user-localhost.

4. **Real-time vs page-refresh** → **page-refresh, no WebSocket / SSE.** Single-user-localhost means no multi-tab consistency requirement; HTMX's per-row fragment swap is sufficient interactivity. Adding SSE would double the test surface and change deployment from `flask run` to gunicorn-with-eventlet — disproportionate.

5. **Termbase write surface — in-process Protocol vs shell-out** → **in-process Protocol calls.** Per CLAUDE.md § Architecture Rules (*Library-first … all UI actions write through existing core APIs*) — the Flask app runs in the same Python process as the Termbase Protocol; in-process is the obvious fit. Daemon-IPC (the cycle-2 Gradle-plugin pattern) is for cross-language clients; in-Python is direct call. This is one of the two surfaces where the user's pre-shaping question list explicitly noted CLAUDE.md leans against shell-out.

6. **Persona editing in cycle 5** → **read-only inspector only.** Persona authoring is a deployment / packaging question (where do user-authored personas live? `~/.ainemo/personas/`? project-local `.ainemo/personas/`?) that the cycle-3 spec did not pin. Editing surface is cycle-6+ if real users ask. The cycle-5 inspector shows what's there + previews hits — that's enough to validate persona behavior.

7. **Translation execution from UI** → **out of scope.** The UI's only provider call is back-translation in S5; everything else routes through the CLI / daemon / Gradle plugin. Per the user-supplied constraint and CLAUDE.md § Architecture Rules.

8. **Back-translation provider selection** → **must be a different provider than the segment's original.** Rationale: same-provider back-translation gives no independent signal — the model that wrote the translation is the worst judge of it. Form rejects same-provider with a clear message pointing at `RoutingConfig`.

9. **Confidence-signal weights** → **start with the four `Final` constants in `app/_ids.py` (0.4 / 0.4 / 0.2 / 1.0); cooldown re-tunes after dogfooding.** No magic numbers; weights are module-level constants per the *No magic strings/numbers* rule. Initial values are reasoned defaults (termbase + placeholder weighted equally, length is a softer signal, back-translation when present dominates), not derived from a benchmark. Cycle-5 cooldown candidate: re-tune from real reviewer-decision data.

10. **CLI ↔ UI shared write path** → **extract `_write_candidate` to `core/termbase/promotion.py`, not duplicate.** The cycle-3 CLI's private helper at `cli/termbase_commands.py:614-647` is reused verbatim by the UI; both surfaces call the same function. SOLID + DRY in new code (project memory `feedback_solid_modularization.md`). The cycle-3 fix-#8 lesson (content-addressed promotion concept ids) lives in the helper and is preserved.

11. **Cycle-5 additions to existing core surfaces** → **scoped explicitly, all additive**: `ImportSkipStore` (new — `app/store/`); `SkippedRow` four optional fields (S3, additive); `Termbase.update_term` (S4, additive); `ProviderRouter.translate_with` + `list_registered` (S5, additive); `UsageLog.estimate_for` (S5, additive); `core/termbase/promotion.py:write_accepted_candidate` (S2, refactor of CLI-private helper); `core/termbase/persona_glue.py:build_glossary_block` (S6, refactor of pipeline-private helper). Everything else lives in `src/ainemo/app/`. Each additive Protocol change preserves byte-stability on existing callers via defaulted parameters / fields. The UI is the last surface, never source-of-truth (CLAUDE.md § Architecture Rules).

After /bet, no new questions allowed. Anything that surfaces during build goes to the cycle-5 cooldown shaping queue.

## Circuit breaker

Mirrors the YAML frontmatter `circuit_breaker:` — *"If the QA Layer (S5 — back-translation behind opt-in flag + cheap-signal confidence scoring) is still uphill at week 4, ship the reviewer UI without back-translation: the auto-promotion queue (S2), import-skip queue (S3), termbase curation (S4), persona inspector (S6), and cheap-signal confidence display (subset of S5) are core; back-translation moves to cycle-5 cooldown or cycle-6. The reviewer UI is the moat-builder for cycle 5; back-translation is a nice-to-have."*

Context for "exhausted" on this pitch: S5's back-translation is the most novel surface in the cycle and the one with the most adversarial unknowns (cost-vs-signal-quality on real corpora). The other four surfaces (S2 promote, S3 imports, S4 termbase, S6 personas) all consume *already-shipped* substrate from cycles 1–4 and have no comparable risk. Without back-translation, AI-NEMO still ships the reviewer UI's full headline (auto-promotion queue, import-skip triage, curation, persona inspector) plus three cheap signals (MiniLM cosine, placeholder parity, length budget) — only the per-segment back-translation button is missing. The circuit breaker therefore protects the reviewer UI at the cost of the QA-layer headline's most-expensive half.

**Core (must-ship): S1 (scaffolding), S2 (promote), S3 (imports), S4 (termbase), S6 (personas), S7 (docs).**
**Trim-able (cooldown candidate): S5's back-translation half — cheap signals still ship; the back-translation button + UsageLog integration moves to cycle-5 cooldown if S5 is still uphill at week 4.**
**Documentation (S7) lands either way; the docs scope re-points at whatever S5 actually shipped.**

## Bet log

| Date | bet_status | Note |
|------|------------|------|
| 2026-05-07 | shaping | Pitch drafted by `/shape reviewer-ui-qa-layer` per cooldown-after-04 § "Shaping queue for the next betting table" headline. |
| 2026-05-07 | shaped | Scopes sized at 7; circuit breaker pinned around back-translation; two genuinely contested questions (frontend stack, QA layer scope) decided at shaping with explicit rationale — `/bet` may revisit. Three pre-resolved questions surfaced from CLAUDE.md § Architecture Rules (auth, real-time, write surface). |
| 2026-05-07 | refined | Pre-/bet review surfaced four findings. (P1) `ImportSkipStore` could not preserve the original CSV/JSONL row payload because `SkippedRow` is `(reason: str)` only; fix: S3 explicitly scopes a four-field additive Protocol extension to `SkippedRow` with defaulted-`None` byte-stability for cycle-4 callers. (P2) Back-translation referenced `ProviderRouter` / `UsageLog` APIs that do not exist; fix: S5 explicitly scopes `ProviderRouter.translate_with` + `list_registered` and `UsageLog.estimate_for` as additive cycle-2 surface additions with their own unit tests + cycle-2 contract-test extensions. (P2) S1 allowed a CDN-pinned HTMX script tag, conflicting with local-first / no-phone-home; fix: S1 now requires a vendored `app/static/htmx.min.js` with SHA-256 pin in `_ids.py`, and the smoke test asserts Flask serves it locally. (P3) `cycle:` frontmatter was blank; set to `"05"`. S3 estimate raised 90→120 min; S5 estimate raised 90→120 min; total session-execution estimate raised ~7–8h → ~9h. No scope-count change. |
| 2026-05-07 | bet | Bet for cycle 05. |
| 2026-05-07 | building | /cycle-start: hill.json initialized with all 7 scopes uphill (S1–S7); bet_status flipped bet → building. Cycle 05 is open for execution. |
| 2026-05-11 | shipped | Cycle 05 closed. All 7/7 scopes done: Flask scaffolding + /promote queue + /imports queue + ImportSkipStore + /termbase curation + Termbase.update_term + /qa layer (cheap signals + back-translation opt-in) + /personas inspector + build_glossary_block extraction + docs (PRs #21-#27). Manual dogfood verified the five views; surfaced one threading bug (fixed in cooldown-window commit a6a553e) and 4 additional findings filed in cooldown-after-05.md. |
