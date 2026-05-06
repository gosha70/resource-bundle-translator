---
cycle: "03"
pitch_ids: [0003-kuzu-termbase]
appetite: 6w
started: 2026-05-05
ended: 2026-05-06
outcome: shipped
---

<!-- Generated at the end of cycle 3 by the cycle-retro agent. -->
<!-- Reads pitch.md, hill.json, and git log to summarize the cycle. -->

# Cycle 3 Retrospective — Concept-Oriented Termbase via Kuzu

- **Pitch**: [`specs/pitches/0003-kuzu-termbase/pitch.md`](../pitches/0003-kuzu-termbase/pitch.md) — `bet_status: shipped`
- **Hill chart**: [`specs/pitches/0003-kuzu-termbase/hill.json`](../pitches/0003-kuzu-termbase/hill.json)
- **Appetite**: 6 weeks (wall-clock ceiling)
- **Actual execution**: hours of session time across 2026-05-05 / 2026-05-06
- **Shipped**: 2026-05-06 via seven scope-scoped PRs (one PR per scope), see Bets below
- **Outcomes prose** (not duplicated here): see [`specs/ROADMAP.md`](../ROADMAP.md) § Cycle 3

## Bets

| Pitch | Appetite | Outcome | Final bet_status | Notes |
|-------|----------|---------|-------------------|-------|
| 0003-kuzu-termbase | 6w | shipped | shipped | All 7 scopes done inside appetite. Circuit breaker did not fire. Nine reviewer-validated bug fixes landed mid-cycle, every one with a regression test. |

## Hill chart final state

### 0003-kuzu-termbase

All 7 scopes ended `done` (`hill.json` final state: every scope's `moved_at` is 2026-05-05 for S1 or 2026-05-06 for S2–S7).

| Scope | Final status | Landing PR | Notes |
|-------|--------------|------------|-------|
| S1 — Kuzu schema + `Termbase` Protocol + `KuzuTermbase` + entity dataclasses | done | [#8 `e684616`](https://github.com/gosha70/resource-bundle-translator/pull/8) | Schema bootstrap is idempotent; Protocol + in-memory test-double pattern carries from cycles 1+2. P2 atomicity fix landed in the same PR. |
| S2 — TBX 3.0 importer (parse Weblate exports) | done | [#9 `c266cfb`](https://github.com/gosha70/resource-bundle-translator/pull/9) | Documented-subset coverage; deterministic term ids when `termSec @id` is absent. `skipped_unsupported` populated on pathological cases. |
| S3 — TBX 3.0 exporter + Weblate round-trip benchmark | done | [#10 `921e098`](https://github.com/gosha70/resource-bundle-translator/pull/10) | In-tree round-trip is byte-stable on 5 hand-crafted Weblate-style fixtures. Real-Weblate-export parity is the manual benchmark deferred to cooldown. |
| S4 — Persona system: YAML loader + 3 starter personas | done | [#11 `6d71c78`](https://github.com/gosha70/resource-bundle-translator/pull/11) | Pydantic-enforced schema; `software-ui` / `formal` / `casual` ship under `src/ainemo/personas/`. Two P2 schema fixes (`forbidden_terms` required, `register` literal-typed) landed inside the PR. |
| S5 — Auto-promotion + `nemo termbase` CLI | done | [#12 `19a5ba2`](https://github.com/gosha70/resource-bundle-translator/pull/12) | Two-pass aggregation by `(source_text, source_lang)` then by target-form fraction; streaming TM cursor; idempotent `--accept-all` via content-addressed `tm-promo-<sha256>` ids. |
| S6 — Pipeline integration: termbase + persona prompt injection | done | [#13 `d69c90f`](https://github.com/gosha70/resource-bundle-translator/pull/13) | `Termbase` + `Persona` are kw-only optional on `TranslationPipeline.__init__`; `persona`/`domain` now thread through to `ProviderRouter.translate()` so cycle-2 routing-rule matchers actually fire. |
| S7 — Documentation + cycle-3 outcomes hooks | done | [#14 `acebc29`](https://github.com/gosha70/resource-bundle-translator/pull/14) | `docs/termbase.md`, `docs/personas.md`, README termbase section, ROADMAP cycle-3 close-out, this retro. |

## Outcome metrics

| Dimension | Value |
|---|---|
| Scopes shipped | 7 / 7 |
| PRs merged | 7 (#8 / #9 / #10 / #11 / #12 / #13 / #14) |
| Fast-suite tests passing | 500 |
| `mypy --strict` over `src/` | 100 source files clean |
| `ruff check` + `ruff format --check` | clean |
| Python matrix | 3.10 / 3.11 / 3.12 green |
| Reviewer-validated mid-cycle fixes | 9 (each with a regression test — see "Reviewer-validated fixes" below) |
| Circuit-breaker activations | 0 |
| Wall-clock vs. appetite | < 2 days vs. 6-week ceiling |

## Circuit breaker activations

- **0003-kuzu-termbase**: not hit. The pre-declared rule was *"If lossless TBX 3.0 round-trip against Weblate's exports (S2+S3) is still uphill at week 4, ship S1+S4+S5+S6 with TBX import-only."* In practice S3 landed at PR #10 with byte-stable round-trip on the in-tree fixture corpus, which is the sufficiency bar for the headline claim. Parity against *real* Weblate exports stayed inside the cycle as a manual benchmark — see [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../../tests/benchmarks/cycle-3-tbx-roundtrip.md) — and is the cooldown carryforward, not a circuit-breaker trim.

## Scope-by-scope notes

### S1 — Kuzu schema + Protocol + `KuzuTermbase` + entity dataclasses

The schema-bootstrap path was straightforward; the surprise was the **atomicity gap on `add_concept`**. The original write order was *create concept node → write each term node → wire `:HAS_TERM`*; if a single term failed validation mid-loop, the concept node remained in the graph as an orphan with no terms, and a second call would silently no-op the duplicate-id check while the caller thought nothing had been written. Fix: validate every term up-front, then write the whole concept-plus-terms cluster in one transaction; nothing reaches Kuzu until the validation pass is clean. Regression test seeds an invalid term in a multi-term concept and asserts the concept node is absent after the failure.

### S2 — TBX 3.0 importer

The fixture corpus (5 real-shaped Weblate exports + 3 hand-crafted pathological cases) was the right size. The reviewer-caught issue was term identity: when `<termSec>` lacks an `@id`, the original implementation generated a fresh UUID4 per import, which meant *re-importing the same TBX file doubled every term*. Fix is the recurring shape of cycle 3 — content-addressed ids: derive the term id deterministically from `(concept_id, lang, surface)`. Re-import is now idempotent. The importer docs (S7 territory but flagged here) had to be rewritten to distinguish the two `@id`-absent paths now that they have different lifecycles.

### S3 — TBX 3.0 exporter + round-trip benchmark

Byte-stable export required canonical-XML emission with deterministic element ordering and namespace handling — not just `lxml.etree.tostring(canonicalize=True)` but explicit attribute-order and child-order control inside `<conceptEntry>`. The in-tree round-trip test `tests/integration/test_tbx_roundtrip.py` is byte-equality, not canonical-XML diff, which is the strongest contract we can enforce in CI. The "real Weblate exports" pass is documented as a manual benchmark in [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../../tests/benchmarks/cycle-3-tbx-roundtrip.md) — running it on ≥ 3 real exports is the cooldown work item, not a CI gate.

### S4 — Persona system

The Pydantic schema landed clean on first cut; both reviewer fixes were schema-strictness oversights rather than design problems. (a) `forbidden_terms` was declared with `default_factory=list`, which made it silently optional in YAML and let typos in the field name pass without error; the fix removes the default so omission is a Pydantic validation error. (b) `register` was typed `str | None`, which accepted `"frmal"` or `"verypolite"` and crashed downstream; the fix tightens to `Literal["formal", "casual", "neutral"] | None`. Both are durable shapes: every persona-style configuration field should either be a `Literal` or an explicit enum, and `default_factory` on a *required* collection is a smell. <!-- author note: candidate for project memory promotion if this shape recurs in cycle 4's domain-pack manifests. -->

### S5 — Auto-promotion + CLI

This was the scope with the most real algorithmic complexity. Three separate reviewer findings, all in the same shape (data the pipeline assumed was distinct turned out not to be):

- **Frequency counted translation rows, not distinct segments.** A single segment that had been translated by two providers contributed `2` to its n-gram's frequency count, which inflated promotion candidates against the `frequency_min=5` threshold. Fix: bucket by segment fingerprint before counting.
- **TM iteration via `cursor.fetchall()`.** Fine on a 200-row test fixture, OOM-prone on a 50k-segment real TM. Fix: stream the cursor row-by-row; the n-gram aggregator is already streaming-friendly.
- **`--accept-all` duplicated concepts on re-run.** Same shape as S2's term-id issue — generated a fresh concept id each call. Fix: content-addressed ids of the form `tm-promo-<sha256(source_text + source_lang + target_text + target_lang)>`, so re-running `--accept-all` is idempotent.

The recurring **content-addressed ids** pattern (S2 term ids, S5 promotion concept ids, conceptually echoing cycle-1 segment fingerprints) is the cycle-3 lesson worth promoting — see "Lessons" below.

### S6 — Pipeline integration

The pipeline-side wiring was small (kw-only optional `termbase` + `persona`, glossary block prepended to system prompt, temperature stays 0). The reviewer-caught bug was a **plumbing miss**: the pipeline's internal `_call_provider` path threaded the segment text and target_lang into `ProviderRouter.translate()` but did not pass `persona` or `domain` — so cycle-2's `RoutingRule` matchers on those dimensions (the `persona`/`domain` fields on `RoutingRule` we deliberately *did not* add to the persona schema during /bet — see pitch open question 2) had no inputs to match against and silently never fired. Fix is one-line at the call site: thread `persona=persona.persona_id, domain=persona.domain_id` through. Regression test asserts a routing rule keyed on a persona id actually selects the matching provider on a cache-miss path.

### S7 — Documentation

Mechanical writing on top of code that already shipped. `docs/termbase.md` covers the concept model, schema diagram, on-disk Kuzu layout, full `nemo termbase` CLI reference, the TBX subset-supported table. `docs/personas.md` covers the YAML schema, the three starter personas, authoring a project persona, and prompt-injection mechanics including the temperature-0 contract. README gained a "Termbase + personas" section. ROADMAP § Cycle 3 was edited at cycle close (this retro is its companion).

## Reviewer-validated fixes (the nine)

Restated in retro shape — the prose lives in [`specs/ROADMAP.md`](../ROADMAP.md) § Cycle 3; the lesson per fix is here. Every fix shipped with a regression test in the same PR; "what was wrong / how it was fixed / regression test" is implicit in each row.

| # | Scope | Severity | What to learn |
|---|-------|----------|----------------|
| 1 | S1 | P2 | A multi-write graph mutation is one transaction or it is wrong. Validate-before-write is the cheap default; it is also the only way to keep the graph free of orphan partials. |
| 2 | S2 | P2 | Identity columns must be derived from the data when the source format omits an explicit id. UUID4-per-call is a duplication bug waiting for the second import. |
| 3 | S2 | P3 | Documentation that describes a removed implementation path is worse than no documentation — it actively misleads. When fixing identity logic, audit the docs for the same call site in the same PR. |
| 4 | S4 | P2 | `default_factory=[]` on a required field is the same bug shape as a silent default in YAML. Required collections must be required; optional collections need explicit opt-in semantics. |
| 5 | S4 | P2 | Configuration string fields that take a closed set of values are `Literal` or an enum. `str | None` is a typo factory. |
| 6 | S5 | P2 | When you count "occurrences", define the bucket explicitly. *Distinct segments* is not the same shape as *translation rows*; the difference shows up at scale, not at fixture size. |
| 7 | S5 | P2 | Iterating a SQLite result set via `fetchall()` is fine for tests and a footgun for real workloads. Streaming is the default; materialization is the special case. |
| 8 | S5 | P2 | Idempotency comes from content-addressed ids, not from re-run guards. The same lesson applies to TBX term ids (fix #2) and to TM segment fingerprints from cycle 1. |
| 9 | S6 | P2 | If a routing layer takes a `persona`/`domain` field, every caller path must populate it — otherwise the matcher silently never fires and no test catches it without an explicit *match-on-persona-actually-fires* assertion. Cycle-2's `RoutingConfig` had this latent gap; cycle 3 closed it. |

## What worked

- **One-PR-per-scope cadence.** Seven scopes, seven PRs (#8 → #14), each scoped tightly enough for review to be substantive without becoming a megathread. Bisects on a regression in S5 don't have to wade through S1+S2+S3 at the same SHA. This is a clear improvement on cycle 2's two-PR shape (#6 covering scopes 1–4 and #7 covering scopes 5–14) where review notes piled into PR #7 across many unrelated surfaces.
- **Conditional-kwarg backward-compat pattern held.** `TranslationPipeline.__init__` gained `termbase: Termbase | None = None` and `persona: Persona | None = None` as kw-only optionals; the cycle-1 e2e test passes byte-identical, no flag, no migration. Same shape worked for `ForbiddenTermsValidator.from_persona(persona)` as an additive classmethod constructor next to the cycle-1 `tuple[str, ...]` constructor. This is the right cycle-on-cycle additive shape and should be the default for cycle 4 too.
- **Pre-resolved /bet questions stayed pre-resolved.** Q1 (promotion thresholds) and Q2 (persona schema, drop `provider_hints`) were locked at /bet on 2026-05-05 and neither was reopened during build. The decision to drop `provider_hints` in favor of cycle-2's existing `RoutingConfig` `persona`/`domain` matching was directly validated by fix #9 — that same routing path needed plumbing, not duplication.
- **Content-addressed ids became the default shape for any cross-run-stable identity.** S2's `(concept_id, lang, surface)` term ids and S5's `tm-promo-<sha256(...)>` promotion concept ids are the same lesson cycle 1 already taught with segment fingerprints. The pattern is ready for promotion to project memory — see "Lessons".

## What didn't

- **Schema P2s on S4 (`forbidden_terms` default, `register` `Literal`) should have been caught by a schema audit before review.** Both are mechanical Pydantic strictness checks that a "review every persona/config field for: required-vs-optional? closed-vs-open value set?" pass would have surfaced before the reviewer round. Implication for cycle 4: when introducing a Pydantic schema for domain packs, run an explicit *schema-strictness audit* checklist over every field before opening the PR. <!-- author note: this checklist could become a project memory rule — keep an eye on whether it recurs in cycle 4's pack-manifest schema. -->
- **The pipeline-`persona`/`domain`-not-threaded bug (fix #9) should have been caught by an end-to-end routing test in S6, not in review.** The unit test for `_call_provider` covered the no-persona path and the with-persona-glossary-injected path but not "with-persona-and-a-routing-rule-matching-on-persona". Implication: when wiring a new dimension into an existing routing surface, the *match-on-that-dimension-actually-fires* assertion is a required test, not a nice-to-have.
- **Real-Weblate-export round-trip parity stayed manual.** The in-tree fixture corpus (5 hand-crafted Weblate-style files) is byte-stable, but the headline claim *parity with Weblate exports* needs ≥ 3 real exports run through the round-trip. The cycle ran out of natural in-cycle moments to do this without a full Weblate install dance, so it lives as a manual benchmark in [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../../tests/benchmarks/cycle-3-tbx-roundtrip.md). Implication for cooldown: this is a real work item, not a documentation chore.
- **The `tm-promo-<sha256>` content-addressed-id fix (fix #8) had to be applied a second time in the same shape as fix #2 (term ids).** Both are "deterministic id from data, not UUID4 per call"; the lesson from S2 should have been applied to S5 the first time around. Implication: when a fix in one scope is a generalizable shape, search the rest of the in-flight cycle for the same shape *before* the reviewer does.

## Carryover into cooldown

The five items below match `specs/ROADMAP.md` § Cycle 3 *Cycle-3 limitations carried forward*. They are the cooldown bug-fix queue, not in-flight work:

- [ ] **TBX round-trip parity against real Weblate exports.** Run [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../../tests/benchmarks/cycle-3-tbx-roundtrip.md) on ≥ 3 real Weblate exports; for each unsupported element that surfaces in `TbxImportReport.skipped_unsupported`, decide promote-to-supported-subset or document-and-defer. — *cycle-3, S2 + S3*
- [ ] **`--termbase-path` per-user / global override flag.** Currently `.ainemo/termbase.kuzu` is the only path. A 5-line CLI addition to mirror the `--tm-path` shape from cycle 1. — *cycle-3, S5*
- [ ] **Embedding-based concept retrieval — benchmark first.** Termbase lookup uses literal n-gram match today. The "vector lookup" decision is benchmark-driven; cooldown runs the recall benchmark on a real corpus and decides whether cycle 4 promotes the lookup to embedding-similarity. — *cycle-3, S1*
- [ ] **Wikidata QID enrichment hook.** Column exists on `Concept`, nothing populates it. Cycle 4's `legal-en` pack is the first real consumer; cooldown's job is to validate the column is wired correctly into TBX import/export so the pack lands cleanly. — *cycle-3, S1*
- [ ] **Reviewer-UI surface for auto-promotion.** Today the surface is the `nemo termbase promote --review` CLI loop. Cycle 5 ships the web reviewer; cooldown captures any UX learnings from the CLI loop that cycle 5 should inherit (which fields the reviewer actually wants to see, which actions they actually want). — *cycle-3, S5*

## Inputs to next betting table

- **Cycle 4 — `legal-en` domain pack.** Already roadmapped. The cycle-3 termbase + persona + auto-promotion substrate is now concrete; the cycle-4 question is *what's the pack manifest schema*, which inherits S4's Pydantic-strictness lessons. Appetite: 6w (per ROADMAP).
- **Schema-strictness audit checklist (durable, not a pitch).** A short document in `specs/` or in agent memory listing the "every Pydantic / dataclass field gets reviewed for: required-vs-optional, closed-vs-open value set, default semantics, content-addressed-id-vs-UUID" passes. Land in cooldown so cycle 4 has it.
- **`tests/benchmarks/cycle-3-tbx-roundtrip.md` execution slot.** Not a new pitch; a cooldown work item. Calling it out at betting-table level so it does not slip past cooldown.

## Lessons to consider for project memory

One candidate is durable enough that promotion is worth considering — flagged here for human decision rather than auto-promoted:

- **Content-addressed ids for any cross-run-stable identity.** Cycle 1 taught it (segment fingerprints). Cycle 3 taught it twice more (S2 term ids, S5 promotion concept ids — fixes #2 and #8). The shape: when a record needs to be the same record across separate runs / re-imports / re-promotions, derive its id from a `sha256` (or equivalent) of the data fields that define identity, not from `uuid.uuid4()`. UUID4 per call is appropriate only for *truly* per-call identity (a request id, a span id) — never for an entity that should be idempotent under re-creation. <!-- author note: promote into project memory if cycle 4's pack-manifest work hits the same shape. -->
