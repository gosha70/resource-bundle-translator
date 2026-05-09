# Reviewer UI

Cycle-5 ships AI-NEMO's **reviewer + admin web app** — a Flask surface over the cycle-1 TM, cycle-3 termbase + persona substrate, and cycle-4 import pipeline. The audience is software i18n teams running a localhost reviewer to triage auto-promotion candidates, retry skipped imports, curate the termbase, and inspect persona behavior.

The UI is **additive**: every CLI surface (`nemo termbase init` / `import` / `export` / `promote` / `stats` / `import-from-csv` / `import-from-jsonl`) keeps working unchanged. The UI consumes the same Protocols (`Termbase`, `TranslationMemory`, `ProviderRouter`, `ImportSkipStore`) the CLI uses; it never reaches around them.

## Getting started

```bash
# One-time termbase setup (cycle 3 / 4) — required before the UI is useful.
nemo termbase init
nemo termbase import-from-csv path/to/glossary.csv --map-config mapping.yaml

# Start the reviewer app on localhost.
nemo app run
# → serving on http://127.0.0.1:5050
```

`nemo app run` defaults to `--host 127.0.0.1 --port 5050 --debug false`. The app is **single-user-localhost by design** — no auth, no session management beyond Flask's per-process secret. Binding to `0.0.0.0` is allowed but the operator accepts responsibility for any auth layer in front of it (multi-user / basic-auth deferred to a later cycle).

```bash
# Override defaults if your local stack already uses 5050 or your termbase
# lives elsewhere.
nemo app run --port 8080 --termbase-path ./team/termbase.kuzu --tm-path ./team/tm.sqlite
```

The app loads a `KuzuTermbase` + `SqliteTranslationMemory` + `ProviderRouter` (with a no-op default provider) + `SqliteImportSkipStore` and dependency-injects them into the Flask app factory. Other services (Anthropic / OpenAI / Ollama / NLLB / OPUS) are not wired into `nemo app run` by default — back-translation in `/qa` requires at least two registered providers and is otherwise gracefully disabled.

## Five views

| View | URL | What it does |
|---|---|---|
| Landing | `/` | Lists the five views and their entry points. |
| Auto-promotion queue | `/promote` | Triage TM-derived `PromotionCandidate` rows. Accept / reject / edit-then-accept per candidate. |
| Import-skip queue | `/imports` | Retry rows that `nemo termbase import-from-csv` / `-jsonl` skipped, with optional in-place edits. |
| Termbase curation | `/termbase` | List / search / edit `Concept` + `Term` rows. Quick TBX 3.0 export. |
| QA layer | `/qa` | Per-segment confidence (cheap signals + opt-in back-translation). |
| Persona inspector | `/personas` | Read-only persona browser + glossary-block preview. |

### `/promote` — auto-promotion candidate queue

Replaces the cycle-3 stdin loop (`nemo termbase promote --review`) with a richer browser surface. Each candidate row shows:

- The n-gram, frequency, and consistency from `find_candidates(...)`.
- Up to 5 contributing TM segment previews (source text + provider/model + target text), so the reviewer can see the actual segments that voted for the n-gram.
- Up to 3 existing termbase concept hits for the same source surface (so the reviewer doesn't add a duplicate).
- Cheap-signal confidence display (cycle-5 S5 retrofit — termbase cosine, placeholder parity, length budget).
- Decision form: `accept` / `reject` / `edit + accept` with an HTMX in-place row swap.

`POST /promote/decide` validates the natural key against a fresh `find_candidates(...)` result before any termbase write — direct/malformed POSTs that name an unknown candidate are rejected with HTTP 400.

The CLI `nemo termbase promote --review` still works; both call the same `core/termbase/promotion.py:write_accepted_candidate(...)` helper, so a candidate accepted via either surface produces byte-identical termbase rows (asserted by the CLI-parity integration test).

### `/imports` — import-skip queue

Cycle-4 imports surfaced skipped rows as printed strings only (`ImportReport.skipped_details`). Cycle-5 persists them via `SqliteImportSkipStore` so the reviewer can fix-and-retry from the UI without re-editing the source CSV/JSONL.

The store is opt-in at the CLI: `nemo termbase import-from-csv --import-skip-store .ainemo/import_skips.db ...`. The default-off path stays byte-identical to cycle 4. `nemo app run` constructs the store at `.ainemo/import_skips.db` automatically so the UI always has somewhere to read from.

Each row shows: source file + 1-based row index + the original payload (pretty-printed JSON) + the skip reason + last-retry timestamp. The retry form lets the reviewer:

- Retry as-is (e.g. after fixing the source data and re-importing).
- Edit individual fields via `payload[<field_name>]` form keys, then retry.

Successful retries delete the row from the store; failed retries update `skip_reason` + `last_retried_at` so the reviewer can see what changed.

### `/termbase` — concept / term curation

Lists concepts with pagination (25/page), source-side search via cycle-3 `Termbase.lookup_concepts_for(...)`. The edit page validates that the posted `term_id` actually belongs to the URL's `concept_id` — direct POSTs that pair an unrelated `term_id` with a `concept_id` are rejected with HTTP 400.

The cycle-5 `Termbase.update_term(term_id, *, surface, register, part_of_speech)` Protocol method (additive on cycle-3) is the write path. Identity fields (`term_id`, `concept_id`, `lang`, `source`) are immutable; only the three reviewer-edited fields can change. Each field defaults to a typed `_UNSET` sentinel so partial updates don't corrupt unspecified columns.

Quick-export `GET /termbase/export.tbx` streams TBX 3.0 from the cycle-3 `TbxExporter` as a date-suffixed download.

### `/qa` — confidence + back-translation

Per-segment cheap-signal confidence (no provider call on page load):

| Signal | Range | Source |
|---|---|---|
| `termbase_cosine` | 0–1 | MiniLM cosine to nearest matching termbase concept (reuses the cycle-1 embedder). 0.0 when no concept matches. |
| `placeholder_parity` | 0 / 1 | Cycle-1 `PlaceholderParityValidator` — 1.0 if the target preserves every source placeholder, 0.0 otherwise. |
| `length_budget` | 0 / 1 | Cycle-1 `LengthBudgetValidator` — 1.0 within `Segment.metadata['max_length']` (or no budget set), 0.0 over. |
| `back_translation_cosine` | 0–1 / `None` | Opt-in. None until the reviewer clicks **Run back-translation**. |

Composite is a weighted sum normalized to `[0, 1]`: weights live in `app/_ids.py` (`WEIGHT_TERMBASE_COSINE = 0.4`, `WEIGHT_PLACEHOLDER_PARITY = 0.4`, `WEIGHT_LENGTH_BUDGET = 0.2`, `WEIGHT_BACK_TRANSLATION_COSINE = 1.0`). The cycle-5 cooldown re-tunes them once dogfood data lands.

Back-translation is **per-segment opt-in** — never bulk, never on page load, never amortized. The reviewer pays for the segments they look at. See [`docs/qa-layer.md`](qa-layer.md) for the full back-translation procedure, the validation guards (`>= 2 providers registered`, `provider != original`, etc.), and the cost-trade-off framing.

### `/personas` — read-only persona inspector

Lists synced personas with their read-only fields (`persona_id`, `name`, `domain_id`, `register`, `style_guide_url`, `prompt_addendum`, `forbidden_terms`). The detail page exposes a **preview-hits form**: paste a candidate source segment + lang pair, and the inspector renders the **byte-equivalent glossary block** the cycle-3 pipeline would inject for that input under this persona's domain filter.

Both the pipeline (`core/pipeline.py`) and the UI (`app/views/personas.py`) call the same `core/termbase/glossary.py:build_glossary_block(...)` helper. The cycle-3 byte-stability invariant is asserted at the integration level (`tests/integration/test_app_personas.py:test_post_preview_hits_byte_equivalent_to_pipeline`).

Persona **editing** is deferred to a later cycle (see § Rabbit holes below).

## Architecture

```
src/ainemo/app/
├── __init__.py            # create_app(*, termbase, tm, router, import_skips, config) -> Flask
├── _ids.py                # ROUTE_*, DECISION_*, WEIGHT_*, HTMX_VENDORED_SHA256, etc.
├── config.py              # AppConfig (Pydantic, extra="forbid", port-range validator)
├── extensions.py          # Jinja htmx_static_url() global
├── static/htmx.min.js     # vendored HTMX 2.0.4 — no CDN script tag
├── templates/             # base + per-view: promote/, imports/, termbase/, qa/, personas/
├── views/                 # promote.py, imports.py, termbase.py, qa.py, personas.py
├── store/                 # ImportSkipStore Protocol + SqliteImportSkipStore
└── qa/signals.py          # ConfidenceSignals + compute_cheap_signals
```

Library-first / CLI-second / build-tool-plugin-third / **UI-fourth** per `CLAUDE.md` § Architecture Rules. The UI is the last surface, never source-of-truth — every write goes through an existing core Protocol.

### Frontend stack — HTMX + Jinja

No Node toolchain. No bundler. No SPA. HTMX is shipped as a single vendored, version-pinned `app/static/htmx.min.js` (sha256 verified by the smoke test); the rendered HTML never references `unpkg.com` / `cdn.jsdelivr.net`. Per `CLAUDE.md` § Architecture Rules: *Local-first. No SaaS, no telemetry, no phone-home.*

This decision was contested at shaping (HTMX vs React); the cycle-5 pitch's § Solution shape § "Frontend stack — HTMX + Jinja (decision)" has the four-point rationale.

### Protocol additions landed by cycle 5

All additive (cycle-1/2/3/4 contracts byte-stable):

| Protocol / module | Addition | Scope |
|---|---|---|
| `SkippedRow` | Four optional structured fields (`row_payload`, `row_index`, `source_path`, `source_format`) | S3 |
| `core/termbase/sources/loader.py:load_into_termbase` | `skip_store: ImportSkipStore \| None = None` kwarg (additive — `TermbaseSource.iter_concepts` still yields `ImportRecord \| SkippedRow` unchanged) | S3 |
| `Termbase.update_term` | New method; identity fields immutable; `_UnsetType` sentinel for partial updates | S4 |
| `ProviderRouter.translate_with` | Bypass routing config, invoke named provider directly | S5 |
| `ProviderRouter.list_registered` | Return registered provider ids ascending | S5 |
| `UsageLog.estimate_for` | Median historical cost-per-token × `total_tokens` | S5 |
| `core/termbase/glossary.py:build_glossary_block` | Extracted from pipeline-private; pipeline + daemon + UI all share it | S6 |

## Security

**Single-user-localhost is the default.** The cycle-5 app binds to `127.0.0.1:5050`, has no auth surface, and CSRF protection is intentionally absent on POST routes. The reasoning is documented per route (e.g. `personas.py:personas_preview` — "CSRF-exempt: read-only lookup, no state mutation").

Routes that mutate state (`/promote/decide`, `/imports/retry`, `/termbase/<concept_id>/terms/<term_id>/edit`, `/qa/back-translate`) all guard against direct/malformed POSTs by validating posted natural keys against the current termbase / TM / store state — an attacker who somehow reaches the localhost socket cannot forge writes for arbitrary concepts.

**Production / multi-user deployment is out of scope for cycle 5.** A future cycle will land basic-auth + Flask-WTF CSRF wiring + an opt-in bind-to-non-loopback flag.

## Rabbit holes (out of scope for cycle 5)

These were considered and explicitly rejected — see `specs/pitches/0005-reviewer-ui-qa-layer/pitch.md` § Rabbit holes for the full list:

- Don't reimplement the CLI surfaces inside the UI.
- Don't introduce a JS toolchain (HTMX from the vendored static asset is the limit).
- Don't add real-time / WebSocket / SSE.
- Don't model "session" / "review-batch" entities — each decision is independent.
- Don't try to make back-translation cheap.
- Don't generalize the persona inspector into a persona editor.
- Don't add a "translate from the UI" button — translation runs through the CLI / daemon / Gradle plugin.

## See also

- [`docs/qa-layer.md`](qa-layer.md) — confidence-signal weights, back-translation procedure, cost-trade-off framing.
- [`docs/termbase.md`](termbase.md) — concept model, schema, TBX subset, `nemo termbase` CLI reference.
- [`docs/personas.md`](personas.md) — persona YAML schema, starter personas, prompt-injection mechanics.
- [`docs/importers.md`](importers.md) — CSV / JSONL importer pipeline (cycle 4).
- [`specs/pitches/0005-reviewer-ui-qa-layer/pitch.md`](../specs/pitches/0005-reviewer-ui-qa-layer/pitch.md) — the cycle-5 Shape-Up pitch.
