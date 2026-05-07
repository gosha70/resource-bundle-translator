---
pitch_id: 0004-termbase-importer-pipeline
title: "Cycle 4 — Pluggable Termbase Importer Pipeline"
appetite: 2w
bet_status: shipped
cycle: "04"
circuit_breaker: "If CSV field-mapping turns out to need more than YAML can express (multi-column compound source terms; per-row computed targets), ship CSV-only (S1, S2, S4, S6) and shelve JSON-Lines (S3 + S5) + the richer mapping DSL to a cycle-4 cooldown one-liner. The CSV importer + CLI is the moat-builder for cycle-4's audience (i18n teams loading their own glossaries); JSON-Lines is the second-source nice-to-have."
shaped_by: gosha70
shaped_date: 2026-05-06
---

<!-- AI-NEMO Shape-Up pitch template. Companion to plan.md / spec.md / tasks.md. -->
<!-- See specs/README.md for the full SDD + Shape-Up workflow. -->

# Cycle 4 — Pluggable Termbase Importer Pipeline

<!-- Human-readable header. Authoritative status / dates live in the YAML
     frontmatter above; this list is for at-a-glance reference and is what the
     README + ROADMAP cross-link to. Keep them in sync when bet_status flips. -->

- **ID**: 0004
- **Appetite**: 2w (wall-clock ceiling; actual session execution measured in hours per project memory rule *Calibrate estimates for Claude Code, not human-days*)
- **Status**: shipped (cycle 04 closed 2026-05-07; see [`cooldown-after-04.md`](../../retros/cooldown-after-04.md))
- **Owner**: gosha70

## Problem

Cycle 3 shipped the concept-oriented termbase + a TBX 3.0 importer (`nemo termbase import x.tbx`). That works for users who already have a TBX file — Weblate exporters, glossaries from CAT tools that emit TBX. But AI-NEMO's actual audience — software i18n teams translating their own UI strings — almost never has TBX. They have:

- A spreadsheet from the marketing team: *"Here's our 200 brand-protected terms and their preferred renderings in DE/FR/ES."*
- A Google Sheet maintained by the localization lead with team-specific verb-tense conventions for button labels.
- A CSV exported from Confluence, an internal wiki page, or a quick `git grep` of the codebase for `tr("...")` strings.
- A one-off JSON dump from someone's `npm run extract-terms` script.

Without a way to get this data into the cycle-3 termbase, the cycle-3 substrate stays underused: only the TBX path and the TM auto-promotion path populate it, and neither matches what most i18n teams have on hand.

The cycle-3 cooldown report flagged the cycle-4 ROADMAP slot (a pre-built `legal-en` pack) as serving <5% of AI-NEMO's actual audience. The 90%+ majority wants their own glossary loaded — brand names, product terminology, the team's preferred verb tense, the marketing department's *"we say cancel not abort"* rule. That is the user-visible value cycle 4 should deliver.

## Appetite

**2w wall-clock ceiling.** Cycle-4 work is bounded: extend cycle-3's adapter pattern with two more `TermbaseSource` impls and a CLI surface. Code execution is hours per the project memory rule. The 2w wall-clock buffer covers reviewer-validation iterations + any CSV-encoding edge cases that surface during dogfooding on a real glossary. No external dependencies, no review queues, no licensing or distribution work — none of those apply (see § No-gos).

## Solution shape

```
┌─ Cycle-3 termbase substrate (already shipped) ───────────────────┐
│                                                                   │
│   Termbase Protocol                                               │
│      ├── add_concept(concept, terms)                              │
│      ├── add_domain(domain)                                       │
│      ├── attach_concept_to_domain(...)                            │
│      └── ...                                                      │
│                                                                   │
│   Concrete: KuzuTermbase (`.ainemo/termbase.kuzu/`)               │
│                                                                   │
│   Existing import paths:                                          │
│      • TbxImporter            (cycle-3 S2)                        │
│      • TM auto-promotion      (cycle-3 S5)                        │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌─ Cycle 4 adds ────────────────────────────────────────────────────┐
│                                                                   │
│   TermbaseSource Protocol  (new — `core/termbase/sources/base.py`)│
│      └── iter_concepts(...) -> Iterator[ImportRecord|SkippedRow]  │
│                                                                   │
│   Concrete impls:                                                 │
│      • CsvSource             (S2 — primary user value)            │
│      • JsonLinesSource       (S3 — symmetric secondary path)      │
│                                                                   │
│   Field mapping config (YAML file via --map-config):              │
│      source_column: term_en                                       │
│      target_columns:                                              │
│        de-DE: term_de                                             │
│        fr-FR: term_fr                                             │
│      domain_column: category   # optional                         │
│      definition_column: notes  # optional                         │
│                                                                   │
│   CLI:                                                            │
│      nemo termbase import-from-csv path/to/glossary.csv \         │
│          --map-config mapping.yaml                                │
│      nemo termbase import-from-jsonl path/to/dump.jsonl \         │
│          --map-config mapping.yaml                                │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

The shape mirrors cycle-3's importer (TbxImporter): a Protocol-first source surface that produces `ImportRecord` rows, a concrete impl per format, and a CLI surface that bridges. Re-runs are idempotent via the same content-addressed concept-id pattern cycle 3 settled on (sha256 of the row's identifying fields → stable concept id; re-running the same import upserts onto the same row).

### Interfaces (SDD layer)

**`core/termbase/sources/_ids.py`** — `Final` constants module:

```python
from typing import Final

# Source provenance tags (extend the cycle-3 TERM_SOURCE_* set;
# stored on Term.source so the cycle-5 reviewer UI can audit
# imported-from-CSV separately from imported-from-TBX, etc.)
TERM_SOURCE_CSV_IMPORT: Final = "csv-import"
TERM_SOURCE_JSONL_IMPORT: Final = "jsonl-import"

# Default CSV dialect — RFC 4180. Override-able via --csv-dialect.
DEFAULT_CSV_DELIMITER: Final = ","
DEFAULT_CSV_QUOTECHAR: Final = '"'
DEFAULT_CSV_ENCODING: Final = "utf-8"

# Field-mapping YAML keys (no magic strings; the loader reads
# these from the user's --map-config file).
MAP_KEY_SOURCE_COLUMN: Final = "source_column"
MAP_KEY_SOURCE_LANG: Final = "source_lang"
MAP_KEY_TARGET_COLUMNS: Final = "target_columns"
MAP_KEY_DOMAIN_COLUMN: Final = "domain_column"
MAP_KEY_DEFINITION_COLUMN: Final = "definition_column"
```

**`core/termbase/sources/base.py`** — Protocol + record types:

```python
@dataclass(frozen=True)
class ImportRecord:
    """One conceptual row read from a source: a source-language term
    + zero-or-more target-language renderings + optional metadata.
    The importer turns each ImportRecord into a Concept + Terms +
    optional Domain attachment in the termbase."""

    source_term: str
    source_lang: str
    target_terms: tuple[tuple[str, str], ...]   # ((target_lang, surface), ...)
    domain_id: str | None
    definition: str | None


@dataclass(frozen=True)
class ImportReport:
    concepts_added: int
    terms_added: int
    domains_added: int
    rows_skipped: int
    """Rows that failed mapping (e.g. blank source_term, encoding
    error) — recorded with row index for the caller to surface."""

    skipped_details: tuple[str, ...]
    """One human-readable line per skipped row: format
    ``"row N: <reason>"``. Empty when every row imported cleanly."""


class TermbaseSource(Protocol):
    """Read-side surface for any structured terminology data file.
    Cycle 4 ships CsvSource + JsonLinesSource; cycle 7+ may add
    SkosRdfSource / Wikidata-enricher if real demand surfaces."""

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]: ...
```

**`core/termbase/sources/csv_source.py`** — `CsvSource`:

```python
class CsvSource:
    def __init__(
        self,
        path: Path,
        mapping: FieldMapping,
        *,
        encoding: str = DEFAULT_CSV_ENCODING,
        delimiter: str = DEFAULT_CSV_DELIMITER,
    ) -> None: ...

    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]: ...
```

**`core/termbase/sources/jsonl_source.py`** — `JsonLinesSource` (same shape as CsvSource; reads one JSON object per line and applies the same FieldMapping over its keys).

**`core/termbase/sources/mapping.py`** — `FieldMapping` (Pydantic-strict YAML schema, mirrors the cycle-3 S4 persona schema discipline: every field has its required-vs-optional + enum-where-applicable + `extra="forbid"` decision baked in up-front per the cycle-3 cooldown lesson).

**`core/termbase/sources/loader.py`** — bridges a `TermbaseSource` into the cycle-3 `Termbase` Protocol:

```python
def load_into_termbase(
    tb: Termbase,
    source: TermbaseSource,
    *,
    namespace: str | None = None,
) -> ImportReport: ...
```

`namespace` is the keyword-only per-import namespace tag that the CLI's `--namespace TAG` flag forwards. It participates in concept-id derivation via the resolution chain documented below (row `domain_id` → this `namespace` → empty-global) so callers building on the loader directly (CLI, future REST surface, tests) all share one identity contract. ``None`` means no per-import namespace; row-level `domain_id` (when set) still applies.

Concept ids are content-addressed over a **(source_lang, source_term, namespace)** triple:

```
import-<sha256(source_lang || U+001F || source_term || U+001F || namespace)[:16]>
```

where `namespace` resolves to the first non-empty of:

1. The row's `domain_id` (from `FieldMapping.domain_column`, when set).
2. The per-import `--namespace` CLI flag value (defaults to None).
3. The empty string — global namespace.

This prevents collisions when the *same* surface appears in *different* domains. Concrete failure case the namespace fixes: marketing-team CSV has `cancel → Abbrechen` (UI domain) and legal-team CSV has `cancel → Stornieren` (contract domain). Without a namespace component, both rows hash to the same concept_id and the second import overwrites the first; with namespace from `domain_id`, they are separate Concepts and both renderings are preserved. **Same-source-term-in-same-namespace** still collides (intentional: if the user did not tell AI-NEMO these are different concepts, they get merged — that is the upsert-on-re-import behavior the cycle-3 idempotency lesson settled on).

**`cli/termbase_commands.py`** gains two new sub-subcommands:

- `nemo termbase import-from-csv path/to/glossary.csv --map-config mapping.yaml [--encoding utf-8] [--delimiter ,] [--namespace TAG]`
- `nemo termbase import-from-jsonl path/to/dump.jsonl --map-config mapping.yaml [--namespace TAG]`

`--namespace` is the cleanest way to import two same-surface glossaries when neither has a `domain_column` (e.g. `--namespace marketing` for one CSV and `--namespace legal` for another). Both accept `--termbase-path` (cycle-3 default `.ainemo/termbase.kuzu`).

## Scopes

> Estimates are session-execution time, not human-days (project memory rule: *Calibrate estimates for Claude Code, not human-days*). Total cycle 4 execution is hours; the 2w appetite is wall-clock willingness to wait.

### S1: `TermbaseSource` Protocol + `_ids.py` constants + `ImportRecord` / `ImportReport` / `FieldMapping` schema

`core/termbase/sources/__init__.py`, `core/termbase/sources/_ids.py`, `core/termbase/sources/base.py`, `core/termbase/sources/mapping.py`. Pydantic-strict `FieldMapping` schema with `extra="forbid"` and explicit required-vs-optional decisions per cycle-3 S4 cooldown lesson. `tests/unit/test_field_mapping.py` (≥ 8 cases incl. unknown-field rejection, missing-mandatory-field rejection, target-columns shape validation). **Estimate: ~30 min.**

### S2: `CsvSource` + `load_into_termbase` bridge

`core/termbase/sources/csv_source.py` reads CSV via Python stdlib `csv` module, applies the `FieldMapping` to produce `ImportRecord` rows, surfaces row-level skip reasons in `ImportReport.skipped_details`. `core/termbase/sources/loader.py` adds the `load_into_termbase(tb, source, *, namespace=None)` bridge — content-addressed concept ids over the `(source_lang, source_term, namespace)` triple per the cycle-3 idempotency pattern + this pitch's collision-fix. `tests/unit/test_csv_source.py` (≥ 10 cases incl. empty file, blank source_term skip, multi-target-lang row, missing optional column, encoding fallback, RFC 4180 quoting edge cases). `tests/unit/test_loader_concept_ids.py` (≥ 4 cases pinning the namespace contract: same source_term in different `domain_id` values produces *different* concept ids; same source_term + same `domain_id` produces *the same* id across re-imports; explicit `--namespace` flag is honored when no `domain_column`; row `domain_id` overrides the per-import flag when both are set). **Estimate: ~75 min.**

### S3: `JsonLinesSource`

`core/termbase/sources/jsonl_source.py` — same shape as CsvSource but reads one JSON object per line. Reuses `FieldMapping` (same schema applies — JSON keys map the same as CSV columns). `tests/unit/test_jsonl_source.py` (≥ 6 cases). **Estimate: ~30 min.**

### S4: `nemo termbase import-from-csv` CLI

`core/termbase/sources/csv_source.py` is wired into a new sub-subcommand on the cycle-3 `nemo termbase` dispatcher. `--map-config` path (required), optional `--encoding` / `--delimiter` for CSV-dialect overrides, optional `--namespace` for collision-disambiguation when the mapping has no `domain_column`. Delegates to `load_into_termbase` and prints the `ImportReport` summary. `tests/integration/test_termbase_import_csv_cli.py` (≥ 6 cases incl. round-trip to `nemo termbase stats`, missing-mapping-file usage error, idempotent re-run, `--namespace` collision-disambiguation between two CSVs sharing source surfaces, mapping-validation error surfaces clearly). **Estimate: ~45 min.**

### S5: `nemo termbase import-from-jsonl` CLI

`core/termbase/sources/jsonl_source.py` is wired into a new sub-subcommand. Same shape as S4's CLI; same `--map-config` + `--namespace` flags; no `--delimiter` (JSONL has no field separator). `--encoding` retained for parity with `import-from-csv` (JSONL is UTF-8 by convention but the override exists for non-UTF-8 dumps). `tests/integration/test_termbase_import_jsonl_cli.py` (≥ 4 cases incl. round-trip to `nemo termbase stats`, malformed-line skip surfaces in stdout, idempotent re-run, latin-1 round-trip via `--encoding`, decode-error surfaces `--encoding` hint). **Estimate: ~30 min.**

### S6: Documentation + cycle-4 outcomes hooks

`docs/importers.md` — `TermbaseSource` Protocol, the two concrete impls, `FieldMapping` YAML schema with annotated examples, CLI reference, idempotency contract. `README.md` updated with an "Import your team's glossary" section pointing at the new CLI. `docs/termbase.md` cross-linked. `specs/ROADMAP.md` § Cycle 4 row gets the *shipped* + *retro link* edits at cycle close. **Estimate: ~30 min.**

**Total session-execution estimate: ~3.5 hours.** The 2w appetite is wall-clock budget for review iterations + dogfooding on a real glossary.

## Test strategy

**Unit** (per-module, fast, deterministic):
- `FieldMapping` Pydantic schema: every mandatory field rejection; unknown-field rejection (per cycle-3 S4 lesson — `extra="forbid"`); valid mapping round-trip via `model_validate(yaml.safe_load(...))`.
- `CsvSource`: empty file, single-row file, multi-target-lang rows, blank source_term skip surfaces in `ImportReport.skipped_details`, RFC 4180 quoted fields with embedded delimiters, optional columns absent vs. present, encoding override (latin-1 fallback).
- `JsonLinesSource`: malformed JSON line surfaces in `skipped_details` (not raised — the rest of the file should still import); missing required field; multi-target-lang row.
- `load_into_termbase`: content-addressed ids stable across two import passes (regression-style assertion mirroring cycle-3 S2 P2 fix); `ImportReport` aggregates correctly.
- **Namespace-collision contract** (regression-pinned per the cycle-4 P2 fix): same `source_term` + same `source_lang` in two different `domain_id` values produces two distinct Concept rows; same `(source_term, source_lang, domain_id)` triple across re-imports upserts onto one row; per-import `--namespace` flag is honored when `FieldMapping.domain_column` is unset; row-level `domain_id` (when present) takes precedence over the per-import `--namespace` flag.

**Integration** (slower, marked `integration`):
- End-to-end CSV import → `nemo termbase stats` → `nemo termbase export some.tbx` round-trip via cycle-3 TBX exporter (proves the cycle-3 termbase + cycle-4 import surfaces compose).
- `nemo termbase import-from-csv` + `nemo termbase import-from-csv` (idempotency at the CLI level — second run must not duplicate concept count).
- Two-CSV namespace collision: `--namespace marketing` import + `--namespace legal` import on two CSVs sharing the source surface "cancel" → two distinct Concepts in the termbase, both target renderings preserved (cycle-4 P2 regression).

**Contract** (the SDD enforcement layer):
- `TermbaseSource` Protocol contract test: `tests/unit/test_termbase_source_contract.py` exercises the surface against `CsvSource` + `JsonLinesSource` + an in-memory test double. Mirrors the cycle-3 contract-test convention.

**Acceptance criteria — cycle is "done" when**:
- `CsvSource` + `JsonLinesSource` ship with the Protocol contract test green.
- `nemo termbase import-from-csv` + `import-from-jsonl` ship with idempotency-on-re-run pinned by integration test.
- `docs/importers.md` written; README updated.
- CI green: ruff + format + mypy strict + pytest on Python 3.10/3.11/3.12.

## Open questions

These were pre-resolved from project docs per the *Pre-resolve "open questions" from project docs before asking the user* memory rule. None are genuinely contested at /bet — see § Pre-resolved.

If anything genuinely contested surfaces during shaping review, it lands here as a numbered item for /bet to resolve.

### Pre-resolved (recorded at shaping, not contested at /bet)

1. **Source format set for cycle 4** → **CSV + JSON-Lines only.** RDF/SKOS / Wikidata SPARQL / IATE-XML / proprietary CAT-tool formats are deferred to cycle 7+ if a real user asks. Rationale: cycle-4 audience is i18n teams with spreadsheets and ad-hoc JSON dumps; the long tail of structured-ontology formats serves <5% per the cycle-3 cooldown audience analysis.

2. **Field-mapping config shape** → **YAML file passed via `--map-config`**, not inline CLI flags. Inline `--map src=col_en,target.de=col_de` was considered and rejected: every team's mapping is reusable across many imports of the same glossary's revisions; a YAML file the team commits alongside the glossary CSV is the natural shape. The `FieldMapping` schema is Pydantic-strict per the cycle-3 S4 lesson.

3. **Idempotency** → **content-addressed concept ids over a `(source_lang, source_term, namespace)` triple** (`import-<sha256(source_lang || '\\x1f' || source_term || '\\x1f' || namespace)[:16]>`). `namespace` resolves first non-empty of: row's `domain_id` → per-import `--namespace` flag → empty-global. Re-running `nemo termbase import-from-csv` with the same input upserts onto the same row. The `namespace` component prevents the same surface in two different domains from collapsing onto one Concept (cycle-4 P2 fix; see § Test strategy "Namespace-collision contract"). Mirrors and extends the cycle-3 S2 (TBX termSec ids) and S5 (promotion concept ids) idempotency pattern. Project memory promotion candidate per cycle-3 cooldown § Process notes.

4. **No data redistribution** → **AI-NEMO ships software, not data.** No pre-built terminology packs; no PyPI/Maven Central pack artifacts; no `PROVENANCE.md`; no license-attribution paragraphs. The user runs the importer against their own data — IATE/EuroVoc/etc. license terms apply directly to the user, not to AI-NEMO. Per project memory rule *Stay in the original plan + actual audience*.

5. **CSV encoding default** → **utf-8 with `--encoding` override** (typically `latin-1` for legacy European CSVs). No `chardet`-style auto-detection — that's a 5+ MB dep for a problem the user can solve with one CLI flag.

6. **CSV dialect** → **RFC 4180 default; Python stdlib `csv.reader` defaults**. No support for tab-separated / pipe-separated / Excel-CRLF dialects out of the box; `--delimiter` overrides for the common case. Cycle 7+ revisits if real users hit this.

7. **Schema-strictness audit on `FieldMapping`** → **applied up-front per cycle-3 S4 cooldown lesson**. Every Pydantic field has its required-vs-optional + closed-set-where-applicable + `extra="forbid"` decision documented in the schema source. `target_columns` is `dict[str, str]` (lang → CSV column name), at least one entry required (a mapping with no targets imports nothing useful — surface that as a load error).

8. **Wikidata QID enrichment** → **out of scope for cycle 4**. Useful only after the termbase has data; deferred to cycle 7+ as a post-import enrichment pass *if* real users ask for it. Cycle-3 cooldown's "embedding-lookup harness as cooldown prep work" is the more natural next-investigation if AI-NEMO needs to extend term-lookup quality.

After /bet, no new questions allowed. Anything that surfaces during build goes to the cycle-4 cooldown shaping queue.

## Rabbit holes

- **Don't auto-detect CSV field mappings from headers.** Tempting to look for columns named `source` / `target` / `en` / `de` and infer. Rejected: every team's column naming is different, header-detection failures fail silently, and the explicit `--map-config` shape is more honest. Per `specs/ROADMAP.md` § Cycle 4 (in spirit — the audience is teams with their own conventions, not generic glossaries).
- **Don't write a SPARQL query DSL for Wikidata.** Wikidata enrichment is out of scope per Q8 above; if it ever lands, simple URL templates with the public SPARQL endpoint are sufficient — no DSL layer.
- **Don't try to support every CSV dialect.** RFC 4180 + `--delimiter` override. Tab-separated / pipe-separated land in cycle 7+ if real users need them.
- **Don't handle multi-million-row CSVs.** Cycle-4 audience is glossaries — hundreds to low thousands of rows. Streaming-iterator surface (already shipped on cycle-3 `iter_translations`) handles up to several MB without memory pressure; that's enough.
- **Don't ship a pre-built terminology pack** (legal-en, medical-en, etc.). AI-NEMO ships the importer; the user provides the data. Per project memory rule *Stay in the original plan + actual audience* — the pre-built `legal-en` pack from the cooldown ROADMAP serves <5% of users.
- **Don't add a pack distribution channel.** No PyPI artifacts for terminology data. No Maven Central. No registry server. Per AGENTS.md *Local-first* + ROADMAP § Cycle 4 explicit no-go (carried forward).

## No-gos

- No pre-built terminology packs (`legal-en`, `medical-en`, etc.). Cycle-4 ships the importer pipeline; users provide their own data.
- No data redistribution from AI-NEMO. No PyPI / Maven Central pack artifacts. No `PROVENANCE.md`. No license-attribution work.
- No SPARQL / RDF / SKOS / IATE-XML / proprietary-CAT-tool source formats. Cycle 7+ if a real user asks.
- No Wikidata QID enrichment. Cycle 7+ if real users ask.
- No CSV header auto-detection. `--map-config` is required.
- No reviewer web UI. (Cycle 5.)
- No Maven / npm / Vite plugin work. (Cycle 6.)
- No new bundle formats. (Cycle 1's four — `.properties`, i18next JSON, gettext `.po`, XLIFF 2.0 — stay the canonical set.)
- No new providers. (Cycle 2's five stay the canonical set.)
- No telemetry, no SaaS, no phone-home. (AGENTS.md § Architecture Rules: *Local-first*.)

## Risks

- **CSV encoding chaos.** Non-UTF-8 CSVs are common in European localization workflows. Mitigation: `--encoding` flag with utf-8 default; the importer surfaces encoding errors as `ImportReport.skipped_details` row entries rather than crashing on the first bad byte.
- **Field-naming chaos across teams.** Every team's mapping differs. Mitigation: explicit `--map-config` (no auto-detection); the YAML schema enforces required fields up-front.
- **Idempotency under content-addressed ids when source data evolves.** Concept identity is the `(source_lang, source_term, namespace)` triple (where `namespace` resolves first non-empty of: row `domain_id` → per-import `--namespace` flag → empty-global; see § Solution shape). The behaviors that follow:
  - Editing a *target-language rendering* (e.g. the German column for a row) keeps the triple stable → re-import upserts on the same concept and refreshes the German term. **Desired behavior.**
  - Editing the *source_term itself* (e.g. typo fix in the English column) changes the triple → a new concept is created; the old concept is orphaned in the termbase.
  - Editing the *namespace* — either the row's `domain_id` value (e.g. recategorizing a term from `marketing` to `legal`) or the per-import `--namespace` flag (e.g. running the same CSV under a different namespace tag) — also changes the triple → likewise produces a new concept and orphans the old one.
  Mitigation: documented behavior, not a bug — any change to an *identity field* is by design a new concept. Typo fixes / recategorizations require either (a) accepting the orphan or (b) running `nemo termbase prune` (cycle 5+ surface; cycle 4 documents the workaround as "delete the termbase and re-import").
- **JSON-Lines malformed line.** A single malformed line in an otherwise-valid JSONL file would crash a naive importer. Mitigation: catch `json.JSONDecodeError` per line; surface as `skipped_details` and continue.

## Circuit breaker

Mirrors the YAML frontmatter `circuit_breaker:` — *"If CSV field-mapping turns out to need more than YAML can express (multi-column compound source terms; per-row computed targets), ship CSV-only (S1, S2, S4, S6) and shelve JSON-Lines (S3 + S5) + the richer mapping DSL to a cycle-4 cooldown one-liner."*

Context for "exhausted" on this pitch: the cycle-4 surface is small enough that the realistic risk is a YAML-mapping shape that can't express what real glossaries need (e.g. one team's source column is `term_en` for some rows and `english_term` for others, depending on category). If the schema doesn't stretch cleanly to cover the dogfood case, ship the simple shape against well-formed CSVs and treat the richer-mapping work as cooldown.

**Core (must-ship): S1, S2, S4, S6.** **Trim-able (cooldown candidate): S3 (`JsonLinesSource`) + S5 (`import-from-jsonl` CLI) — the secondary format; CSV alone covers the audience's common case. The split into two scopes makes the breaker subset clean — S4 is purely the CSV CLI, so dropping S5 leaves the CSV path complete.** **Documentation (S6) lands either way.**

## Bet log

| Date | bet_status | Note |
|------|------------|------|
| 2026-05-06 | shaping | First-pass pitch shaped as `0004-legal-en-pack`: pre-built `legal-en` domain pack with PyPI/Maven Central distribution, license attribution, and 2k-concept IATE+EuroVoc ingestion. |
| 2026-05-06 | reshaped | User pushback: "I never mention the need for license !!!" + "don't fall to solving the problems which were not in the original plan or almost has no value for my target audience." Audience analysis showed the pre-built legal pack served <5% of AI-NEMO's actual user base (software i18n teams translating UI strings). Reshaped to `0004-termbase-importer-pipeline`: cycle 4 ships the importer pipeline (CSV + JSON-Lines), users provide their own data. License/distribution/lawyer scope dropped entirely. Lesson promoted to project memory as `feedback_stay_in_audience_scope.md`. |
| 2026-05-06 | shaped | Scopes sized at 5 (down from 7); appetite at 2w (down from 6w); circuit breaker pinned around field-mapping richness. No genuinely contested open questions for /bet. |
| 2026-05-06 | refined | Pre-/bet review surfaced two pitch-level P2s. (1) Concept-id derivation collapsed same-source-term-different-domain rows; fix: hash includes a third `namespace` component derived from row `domain_id` → per-import `--namespace` flag → empty-global, with documented merge semantics. Test strategy gains a namespace-collision contract (unit + integration). (2) Combined CSV/JSONL CLI scope made the CSV-only circuit-breaker subset under-defined; fix: split S4 into S4 (CSV CLI) + S5 (JSONL CLI), bumping scope count to 6 and making the breaker drop S3 + S5 cleanly while keeping S4 self-contained. Docs scope renumbered S5 → S6. |
| 2026-05-06 | refined | Re-review surfaced three follow-on inconsistencies from the first refinement pass. (P2) The authoritative `load_into_termbase` interface block still showed `(tb, source)` after the surrounding prose was updated to thread `namespace`; fix: keyword-only `namespace: str | None = None` parameter added to the signature with explicit documentation that the CLI's `--namespace` flag forwards to it. (P2) The § Solution shape diagram still advertised "YAML or inline `--map`" after pre-resolved Q2 explicitly rejected inline mapping; fix: diagram now says "YAML file via `--map-config`" only. (P3) The § Risks idempotency note still described the hash as `source_lang+source_term`; fix: rewritten to cover the three identity fields (source_term, target rendering, namespace) and the orphan behavior on each. No scope or estimate changes. |
| 2026-05-06 | bet | Bet for cycle 04. |
| 2026-05-06 | building | /cycle-start: hill.json initialized with all 6 scopes uphill (S1–S6); bet_status flipped bet → building. Cycle 04 is open for execution. |
| 2026-05-07 | shipped | Cycle 04 closed. All 6/6 scopes done: TermbaseSource Protocol + FieldMapping schema (S1, PR #15), CsvSource + load_into_termbase bridge (S2, PR #16), JsonLinesSource (S3, PR #17), `nemo termbase import-from-csv` CLI (S4, PR #18), `nemo termbase import-from-jsonl` CLI (S5, PR #19), and docs/importers.md + README "Import your team's glossary" + termbase.md cross-link (S6, PR #20). |
