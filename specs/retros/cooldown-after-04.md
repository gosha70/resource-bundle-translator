---
cooldown_after_cycle: 04
started: 2026-05-07
ended: 2026-05-07
duration: same-day (no fixes or polish landed during the cooldown window)
---

<!-- Generated at the end of cycle 4 by the cooldown-report agent. -->
<!-- Cycle 4 retro is folded into this report — the cycle was small enough -->
<!-- (2w appetite, 6 scopes, hours of session execution) that a separate -->
<!-- cycle-4.md retro adds noise rather than signal. Cycles 0/2/3 each had a -->
<!-- standalone retro because they ran 6w with 7+ scopes; cycle 4 does not. -->

# Cooldown after Cycle 4

## Summary

Cycle 4 (Pluggable Termbase Importer Pipeline) shipped on 2026-05-07 across six scope-scoped PRs (#15 → #20, terminal commit `ae2b520`) — all 6/6 hill scopes done inside the 2w appetite, circuit breaker untouched, every reviewer-validated mid-cycle fix landed with a regression test. The cooldown window closed same-day with no additional fixes or polish — cycle 4 closed clean. The pitch was reshaped at /bet (originally `0004-legal-en-pack`, ~6w of pre-built packs + license/distribution scope) into the importer pipeline against direct user pushback that the legal-en pack served <5% of the actual audience — software i18n teams loading their own glossaries. That reshape is the cycle's headline lesson; the pre-built `legal-en` pack is now optional cycle-7+ work, not a roadmap commitment. The headline shaping target for the next betting table is **Cycle 5 — Reviewer Web UI + QA Layer**, the natural consumer of the cycle-3 termbase + cycle-4 importer surfaces (auto-promotion candidates and import-skip rows are both reviewer-shaped queues today).

## Bug fixes shipped

None landed in the cooldown window — cycle 4 closed clean. The cycle's mid-cycle review fixes (eight of them) are catalogued in [§ Reviewer-validated fixes](#reviewer-validated-fixes-in-cycle) below; they shipped *during* the cycle, not during cooldown, and are not duplicated here.

## Polish & follow-ups

None. No cooldown-window polish commits landed before this report was finalized.

## Cycle 4 — what shipped

All six scopes shipped one-PR-per-scope, matching the cadence cycle 3 settled on. Final hill state: every scope `done`, S1–S3 on 2026-05-06 and S4–S6 on 2026-05-07.

| Scope | Final status | Landing PR | Commit | Notes |
|-------|--------------|------------|--------|-------|
| S1 — `TermbaseSource` Protocol + `_ids.py` constants + `ImportRecord` / `ImportReport` / `FieldMapping` schema | done | [#15](https://github.com/gosha70/resource-bundle-translator/pull/15) | `596db9e` | Pydantic-strict `FieldMapping` with `extra="forbid"` and explicit required-vs-optional decisions per cycle-3 S4 lesson. |
| S2 — `CsvSource` + `load_into_termbase` bridge | done | [#16](https://github.com/gosha70/resource-bundle-translator/pull/16) | `7752b99` | Content-addressed concept ids over `(source_lang, source_term, namespace)` triple. `CsvDecodeError` wraps `UnicodeDecodeError` with `--encoding latin-1` named verbatim in the message. |
| S3 — `JsonLinesSource` | done | [#17](https://github.com/gosha70/resource-bundle-translator/pull/17) | `a6fc109` | Strict-on-all-mapped-columns (string-or-null only); `JsonlDecodeError` with `__cause__` chaining for byte offset. |
| S4 — `nemo termbase import-from-csv` CLI | done | [#18](https://github.com/gosha70/resource-bundle-translator/pull/18) | `ada6cf3` | `--delimiter '\t'` argparse normalization via a closed-set escape map; multi-character delimiters rejected with clean stderr. |
| S5 — `nemo termbase import-from-jsonl` CLI | done | [#19](https://github.com/gosha70/resource-bundle-translator/pull/19) | `e183794` | Same shape as S4; no `--delimiter` (JSONL has no field separator). `--encoding` retained for parity with `import-from-csv`; tests cover latin-1 round-trip + decode-error hint. |
| S6 — Documentation + cycle-4 outcomes hooks | done | [#20](https://github.com/gosha70/resource-bundle-translator/pull/20) | `ae2b520` | `docs/importers.md`, README "Import your team's glossary" section, `docs/termbase.md` cross-link. README top status block fixed to reflect cycles 0–3 shipped + cycle 4 closing. |

## Reviewer-validated fixes (in-cycle)

These were caught by review *during* the cycle, each with a regression test in the same PR. Listed for the same reason cycle 3's nine were — to make the lesson per fix legible at retro time.

| # | Scope | Severity | What to learn |
|---|-------|----------|----------------|
| 1 | S1 | P2 | Concept-id derivation collapsed same-source-term-different-domain rows (e.g. `cancel` in marketing vs. legal). Fix: hash includes a third `namespace` component, resolved from row `domain_id` → per-import `--namespace` → empty-global. Pinned by a namespace-collision contract test. The recurring shape: when a content-addressed id needs to disambiguate "the same surface in different contexts", the namespace component is part of identity, not a tag on top of it. |
| 2 | S2 | P2 | Walkthrough push-back surfaced that the on-disk concept-id format (`import-<sha256(...)[:16]>`) had no regression test pinning its literal hash, so a silent refactor of `_derive_import_concept_id` could change every previously-imported row's id without a test failing. Fix: literal-hash regression test for the helper. The shape: any function whose return value becomes part of a stored row's identity needs at least one test pinning a literal output, not just a "round-trip" assertion. |
| 3 | S2 | P2 | `CsvSource` raised raw `UnicodeDecodeError` on non-utf-8 input, leaving the user staring at a stack trace with no remediation hint. Fix: `CsvDecodeError` wraps the underlying error and names `--encoding latin-1` verbatim in the message — the most common workaround written into the error itself. |
| 4 | S3 | P2 | Initial JSONL parse-error path silently cited "RFC 7464" as the JSON-Lines spec; that RFC is JSON Text Sequences (`0x1e`-prefixed), a different format. Fix: error message now references jsonlines.org honestly. The lesson: when an error message wants to be helpful by linking a spec, the spec must actually describe the format the parser implements. |
| 5 | S3 | P2 | Original `JsonLinesSource` accepted any JSON value type for mapped columns, which then exploded downstream when a list or dict landed in a string field. Fix: strict-on-all-mapped-columns policy (string or null only); `JsonlDecodeError` carries `__cause__` for byte-offset traceability. |
| 6 | S4 | P1 | `--delimiter '\t'` was passed through argparse as the literal two-character string `\t` (backslash + t) because shells leave backslash escapes literal in single and plain double quotes. Fix: closed-set escape map for `\t \n \r \v \f \0` applied at argparse parse time; multi-character delimiters that are not in the map are rejected with a clean stderr error rather than crashing the `csv` reader downstream. The shape: any CLI flag that takes a single character is a candidate for "did the shell pass me a literal escape sequence?" — handle it explicitly, do not assume the shell already unescaped. |
| 7 | S6 | P2 | README top status block was stale (still said cycles 0–2 shipped, cycle 3 next); fixed during S6 review to reflect cycles 0–3 shipped + cycle 4 closing, plus the cycle table updated. The shape: the README status block is *cumulative* — every cycle's S6 (or S7) needs to update it, not just append a new entry. |
| 8 | S6 | P3 | JSONL skip-reason phrasing in `docs/importers.md` described the error in domain prose rather than in the actual `JsonLinesSource` output (which surfaces Python type names). Fix: doc text realigned to mirror the real on-disk message. The shape: when documentation describes an error message, copy-paste the real one — paraphrasing drifts. |

## Outcome metrics

| Dimension | Value |
|---|---|
| Scopes shipped | 6 / 6 |
| PRs merged | 6 (#15 / #16 / #17 / #18 / #19 / #20) |
| Reviewer-validated mid-cycle fixes | 8 (each with a regression test) |
| Circuit-breaker activations | 0 |
| Wall-clock vs. appetite | < 2 days vs. 2-week ceiling |
| Audience-fit reshape at /bet | 1 (legal-en pack → importer pipeline) |

## What worked

- **One-PR-per-scope cadence held a second cycle running.** Six scopes, six PRs, no consolidated megathreads. Cycle 3's cooldown report explicitly recommended this cadence for cycle 4 — confirmed durable.
- **Audience-fit reshape at /bet was the highest-leverage move of the cycle.** The original `0004-legal-en-pack` pitch (6w, pre-built `legal-en` pack with PyPI/Maven Central distribution + license attribution) would have shipped real software for <5% of the actual user base. User pushback caught it; reshape produced a 2w pitch that targets the 90%+. The lesson is already promoted as project memory `feedback_stay_in_audience_scope.md`. **What to carry forward**: the ROADMAP's "next cycle" entry is *strategic framing*, not a shaping decision — re-validate audience fit at /bet, not after the cycle ships.
- **Pydantic schema-strictness audit applied up-front, not in review.** Cycle 3's S4 cooldown lesson (every Pydantic field reviewed for required-vs-optional + closed-set value ranges + `extra="forbid"` up-front) was applied to `FieldMapping` at S1 and held through review. Two cycles in a row of that pattern is enough to make it the default for any future schema work.
- **Content-addressed concept ids stretched cleanly to the new namespace dimension.** The cycle-3 idempotency pattern (sha256 of the identifying fields → stable id) extended to a triple `(source_lang, source_term, namespace)` without restructuring. The P2 fix at S1 was about *which fields define identity*, not about replacing the pattern. Project-memory promotion candidate (still flagged from cycle 3); cycle 4 is the second confirmation.

## What didn't

- **Concept-id namespace collision (fix #1) should have been caught at shaping, not at S1 review.** The pitch's pre-resolved Q3 (idempotency) committed to `(source_lang, source_term)` as the identity columns; the marketing-vs-legal `cancel` collision is the obvious failure case for that choice and would have surfaced if the shaping pass had asked "what real-world rows would collide here?". Fix landed cleanly at S1 with the namespace component, but the recurring lesson is: **enumerate at least one realistic collision case per identity decision during shaping, not after**. Cycle-3 S2 (term-id duplication on re-import) was the same shape of miss; this is the second time. Promote the check to project memory if it shows up a third time.
- **The literal-hash regression test for `_derive_import_concept_id` (fix #2) was a walkthrough push-back, not a test the cycle wrote unprompted.** The contract is "this hash format is part of the on-disk row's identity" — that contract needs a test pinning a *literal output*, not just a round-trip property. Implication for any cycle that introduces a new content-addressed id: write the literal-hash test in the same PR that introduces the id, not in a follow-up.
- **CLI escape-sequence handling (fix #6 — `--delimiter '\t'`) was not anticipated at shaping despite being the first user-typable single-character flag the project has shipped.** Cycle 1's `--strict` is boolean; cycle 2's `--provider` is multi-character; cycle 3's `--accept-all` is boolean. Cycle 4 introduced the first single-character flag, and the shell-escape-passthrough behavior is well-known but did not surface in the pitch. Implication: when a CLI flag's value space is *one character*, the shaping checklist should include "what does the shell pass through for the most-common escape sequences in this surface?"
- **README top status block went stale silently (fix #7).** No automated check exists that ties the cycle table at the top of the README to the actual shipped state of each cycle. Cycle 0's README work was correct; cycles 1/2/3 each updated their own row but the cumulative top block was not part of the cycle-3 S7 docs scope. Cycle 4's S6 caught it on review. **Cooldown candidate**: a small doc-test or pre-commit check that asserts the README status block matches each cycle's pitch frontmatter `bet_status` value. Less than a one-cycle pitch — fits as a cooldown one-liner.

## Lessons to consider for project memory

Two candidates are durable enough that promotion is worth considering — flagged here for human decision rather than auto-promoted:

- **Enumerate one realistic collision case per identity-fields decision during shaping.** Cycle 3 S2 (TBX re-import term duplication) and cycle 4 S1 (marketing-vs-legal `cancel` collision) are the same shape of miss: a pre-resolved "what fields define identity?" question that shipped without a sample case proving the chosen fields actually disambiguate. Two cycles is a pattern; if a third cycle introduces another content-addressed id and ships without enumerating a collision case, promote this. <!-- author note: hold for cycle 5 — if the reviewer UI's accept/reject queue introduces any cross-run-stable identity, that's the natural third data point. -->
- **CLI single-character flags need explicit escape-handling at shaping time.** Cycle 4's `--delimiter` was the first single-character flag the project has shipped; the shell-escape-passthrough behavior was discovered in review, not at shaping. If cycle 5 (or any later cycle) introduces another single-character flag and hits the same fix shape, promote. <!-- author note: not yet a pattern — one data point. Hold for confirmation. -->

## Pitches shaped during cooldown

<!-- No new pitches have moved to bet_status: shaped during this cooldown.
     This report is being run at cooldown open. -->

| pitch_id | Title | Appetite | Status |
|----------|-------|----------|--------|
| _none yet_ | — | — | — |

## Carryforward queue from cycle 4

| # | Item | Origin scope | Shape candidate this cooldown? |
|---|------|--------------|--------------------------------|
| 1 | **README status-block consistency check** — small doc-test or pre-commit hook asserting the cycle table at the top of `README.md` matches each pitch's `bet_status`. | S6 (fix #7) | **Yes** — small enough to land inside the cooldown window as a one-liner pitch. |
| 2 | **Auto-detect CSV encoding heuristic** — investigate a stdlib-only sniff (BOM detection + utf-8 decode attempt + latin-1 fallback) so users do not need `--encoding` for the common European cases. Not `chardet` — that's a 5+ MB dep rejected at shaping. | S2 + S4 | **Maybe** — investigation worth doing in cooldown; commit only if the stdlib path is honest about its failure modes. If it's not, document the gap and stay with `--encoding`. |
| 3 | **Multi-column compound source terms via richer mapping DSL** — the `circuit_breaker` carve-out scenario that did not fire. If real users hit "one team's source column is `term_en` for some rows and `english_term` for others", the mapping DSL needs a fallback-chain shape. | Circuit breaker | **No** — defer until a real user surfaces it. Premature DSL is the rabbit hole the pitch already called out. |
| 4 | **`SkosRdfSource`** — third source format. Pre-resolved out of cycle 4 (Q1: deferred to cycle 7+). | Pre-resolved Q1 | **No** — cycle 7+ if a real user asks. |
| 5 | **Pre-built `legal-en` domain pack** (the *original* cycle-4 shape, dropped at /bet). | /bet reshape | **No** — moved to cycle 7+ as a content-work pitch, contingent on real user demand. The cycle-3 cooldown report's "headline shaping target" framing is **explicitly retracted**: that target was wrong about the audience. |

## Shaping queue for the next betting table

<!-- ROADMAP-default cycles 5 through 6+ — calling out the shaping topics, not
     prescribing scopes. The pitch-shaper agent does the actual shaping. -->

- **Cycle 5 — Reviewer Web UI + QA Layer** *(headline shaping target this cooldown)*. Now the natural next bet — both cycle 3's auto-promotion candidates (`nemo termbase promote --review` CLI loop) and cycle 4's `ImportReport.skipped_details` rows are reviewer-shaped queues today; a web UI replaces both CLI loops with one surface and adds confidence scoring + back-translation QA on top. The cycle-3 cooldown carryforward item #5 (CLI-loop UX observations) and cycle-4's S6 fixes (#7 + #8 — surface honest error text in the right place) directly inform what the reviewer UI should expose. Appetite per ROADMAP: 6w. **No `0005-*` pitch document exists yet** — shaping this pitch is the cooldown's headline non-fix work item.
- **Maven plugin** *(downstream)*. Cycle 6 per ROADMAP. The Gradle plugin from cycle 2 is the template; the Maven plugin is a thin Mojo over the same daemon IPC. Not a cooldown shaping target unless cycle 5 slips and the betting table wants a smaller-appetite alternative.
- **Domain-pack-shipping work — `legal-en` as a content-only pitch** *(retracted from cycle-4-original; cycle 7+ if at all)*. Listed for honesty: the cycle-3 cooldown report flagged this as the cycle-4 headline; the cycle-4 reshape proved that framing wrong. Recording the retraction so future cooldown reports do not silently reinstate it. <!-- author note: do not auto-revive this without a real user request. The project-memory rule "Stay in the original plan + actual audience" applies. -->

## Process notes for cycle 5 onward

Two patterns from cycle 4 worth carrying forward into cycle 5 shaping and execution:

- **Re-validate audience fit at /bet, not after the cycle ships.** The cycle-3 cooldown report named `legal-en` as the cycle-4 headline; the cycle-4 reshape at /bet proved that target was wrong about who the actual audience is. The lesson is not "the cooldown report was wrong" — it's "the cooldown's shaping queue is *input* to /bet, not the bet itself, and /bet is where audience-fit gets re-checked against the project's actual user base". For cycle 5: when the betting table convenes, explicitly ask "who is the user this serves?" before locking the bet, even if the cooldown report and ROADMAP both name the same thing. <!-- author note: this is the cycle-4 lesson most worth carrying forward — promotion to project memory `feedback_stay_in_audience_scope.md` already done. -->
- **Keep the one-PR-per-scope cadence for cycle 5.** Two cycles in a row of one-PR-per-scope (cycle 3's #8 → #14, cycle 4's #15 → #20) is enough to call it the default. The cycle-2 consolidated-PR shape (#6 / #7) does not need to come back. Reviewer UI work in cycle 5 will likely have more visual / cross-scope coupling than cycle 3 or 4 had — flag this at shaping and decide consciously whether any single feature crosses scope boundaries enough to merit a 2-PR shape, but the default stays one-per-scope.

## Open questions for the next betting table

None mandatory. One worth flagging for cooldown-time use:

- **Reviewer UI tech-stack decision.** ROADMAP entry says "Flask + HTMX (or React)". This is a real fork: HTMX keeps the project Python-only and easy to ship; React adds a frontend toolchain dependency the project has so far avoided. The cycle-5 betting table needs a clear recommendation, not the parenthetical. **Cooldown-time prep**: a short note in `specs/` listing the trade-offs (toolchain weight vs. interactive surface vs. reviewer-UI requirements as we know them today) so /bet has a starting point. <!-- author note: technology choice is a human call, not the cooldown-report agent's. Cooldown only flags the prep work. -->

## Recommended bets for next cycle

<!-- The cooldown-report agent's recommendation is input, not a decision.
     The actual bet is locked at the betting table. No 0005-* pitch document
     exists yet, so this is a shaping target rather than a shaped pitch. -->

The ROADMAP-default next bet is **Cycle 5 — Reviewer Web UI + QA Layer**, and unlike the cycle-3-cooldown `legal-en` recommendation (retracted at cycle-4 /bet), this one has a concrete audience already proven by cycle 3 and cycle 4: the same i18n teams who now have an importer pipeline + an auto-promotion queue need a surface to triage both. There is no pitch document for it yet (`specs/pitches/0005-*` does not exist), so this is a shaping target rather than a shaped pitch.

A second-strongest candidate is the **Maven plugin** (cycle 6 per ROADMAP) — the Gradle plugin from cycle 2 is a working template and a Maven Mojo over the same daemon IPC is a smaller-appetite cycle (likely 2–3w) than a reviewer UI. If the cycle-5 reviewer-UI shaping pass surfaces real complexity at /bet (e.g. the React-vs-HTMX question can't be resolved cleanly), the Maven plugin is the natural fall-back bet for a one-cycle delay on the UI work. <!-- author note: ordering is the cooldown-report agent's reading; the betting table makes the actual call. -->

## Carryover

- [ ] Shape a pitch for cycle 5 (`Reviewer Web UI + QA Layer`, 6w appetite per ROADMAP). The ROADMAP entry is the strategic framing; shape it into appetite + scopes + circuit breaker + no-gos + open questions for the betting table. Apply cycle-3's content-addressed-id pattern + cycle-4's namespace-collision lesson to any persistent reviewer-state schema.
- [ ] Re-validate audience fit at the cycle-5 /bet pass — confirm the reviewer UI serves the same i18n-teams audience as cycle 4, not a separate "translation reviewer" persona. (Cycle-4 reshape lesson; project memory `feedback_stay_in_audience_scope.md`.)
- [ ] Land the README status-block consistency check as a cooldown one-liner pitch. (Carryforward #1.)
- [ ] _(Optional, in cooldown if there's room)_ Investigate stdlib-only CSV encoding sniffer; commit only if the failure modes are honest, otherwise document the gap. (Carryforward #2.)
- [ ] _(Defer)_ `SkosRdfSource` and the richer mapping DSL stay deferred — cycle 7+ if real users surface them. (Carryforward #3 + #4.)
- [ ] _(Retracted)_ Pre-built `legal-en` domain pack is no longer a cooldown or near-cycle target. Reinstate only if a real user requests it. (Carryforward #5; cycle-3 cooldown's headline-shaping recommendation explicitly retracted.)
- [ ] Cycle-3 cooldown's open carryover items (TBX round-trip benchmark, `--termbase-path` flag, embedding-similarity benchmark harness) **remain open** — none were picked up during cycle 4. Recheck whether any are right-sized for this cooldown's window. (Source: [`cooldown-after-03.md`](./cooldown-after-03.md) § Carryover.)
- [ ] Cycle-2 carryover items (#1 daemon payload-size ceiling, #2 concurrency contract, #5 cross-language nullable drift audit) **remain deferred** from post-cycle-2 cooldown. The CI matrix from cycle-2 cooldown's #6 has been accumulating data across cycles 3 and 4; check whether #5's "what's actually drifting" question is answerable yet. (Source: [`cooldown-after-02.md`](./cooldown-after-02.md) § Carryover.)
