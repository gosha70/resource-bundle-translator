---
cooldown_after_cycle: 03
started: 2026-05-06
ended: TBD
duration: TBD
---

<!-- Generated at the end of cycle 3 by the cooldown-report agent. -->
<!-- Cycle 3 retro carryover: specs/retros/cycle-3.md § "Carryover into cooldown" -->

# Cooldown after Cycle 3

## Summary

Cycle 3 (Concept-Oriented Termbase via Kuzu) shipped on 2026-05-06 across seven scope-scoped PRs (#8 → #14, retro `0033153`) — all 7 hill scopes done inside appetite, circuit breaker untouched, nine reviewer-validated mid-cycle fixes each landed with a regression test (full table in [`cycle-3.md`](./cycle-3.md)). This cooldown opens at cycle close: no fixes have landed *in* the cooldown window yet. Cycle 3's retro hands off five carryforward items (mirrored in [`ROADMAP.md`](../ROADMAP.md) § Cycle 3) — three are downstream-cycle work, one runs *during* cooldown as a manual benchmark, and one is a small-enough fix to shape as a cooldown one-liner pitch. The headline shaping target for the next betting table is **Cycle 4 — First Domain Pack: legal-en**, which is the first real consumer of cycle 3's termbase + persona substrate.

## Bug fixes shipped

<!-- Cooldown is just opening; cooldown-window fix-prefixed commits to be
     filled in as fixes land. The cycle-3 mid-cycle fixes are catalogued in
     cycle-3.md § "Reviewer-validated fixes (the nine)" and are not duplicated
     here — they shipped during the cycle, not during cooldown. -->

| Commit | Pitch / area | One-line description |
|--------|--------------|----------------------|
| _to be filled in as fixes land_ | — | — |

## Polish & follow-ups

<!-- Non-fix commits that land during the cooldown window. To be filled in. -->

- _to be filled in as cooldown work lands_

## Pitches shaped during cooldown

<!-- No new pitches have moved to bet_status: shaped during this cooldown.
     This report is being run at cooldown open. -->

| pitch_id | Title | Appetite | Status |
|----------|-------|----------|--------|
| _none yet_ | — | — | — |

## Carryforward queue from cycle 3

<!-- Source: specs/retros/cycle-3.md § "Carryover into cooldown" and
     ROADMAP.md § Cycle 3 § "Cycle-3 limitations carried forward".
     Not duplicated — see those files for the full design context. -->

The five items below are restated from cycle 3's retro with an explicit "shape candidate?" column so the betting table knows which to treat as cooldown-shapeable vs. strictly downstream.

| # | Item | Origin scope | Shape candidate this cooldown? |
|---|------|--------------|--------------------------------|
| 1 | **TBX round-trip parity against real Weblate exports** — execute [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../../tests/benchmarks/cycle-3-tbx-roundtrip.md) on ≥ 3 real exports. | S2 + S3 | **No** — runs DURING cooldown as the manual benchmark itself; outcomes feed next-cycle TBX work *if* anything regresses. Not a pitch. |
| 2 | **`--termbase-path` per-user / global override flag** — mirror cycle-1's `--tm-path` shape; ~5 lines + tests. | S5 | **Yes** — small enough to shape as a cooldown one-liner pitch and land inside the window. |
| 3 | **Embedding-based concept retrieval** — promote literal n-gram lookup to embedding-similarity. | S1 | **Not yet** — explicitly benchmark-driven; needs the recall benchmark on a real corpus before it's shapeable. See "Open questions" below. |
| 4 | **Wikidata QID enrichment hook** — `Concept.wikidata_qid` column exists, nothing populates it. | S1 | **No** — this is cycle-4 `legal-en` pack work by design (the pack is the first real consumer). |
| 5 | **Reviewer-UI surface for auto-promotion** — capture UX learnings from the `nemo termbase promote --review` CLI loop. | S5 | **No** — explicit cycle-5 work (Reviewer Web UI + QA Layer). Cooldown only collects observations. |

## Shaping queue for the next betting table

<!-- ROADMAP-default cycles 4 through 6+ — calling out the shaping topics, not
     prescribing scopes. The pitch-shaper agent does the actual shaping. -->

- **Cycle 4 — First Domain Pack: legal-en** *(headline shaping target this cooldown)*. The cycle-3 termbase + persona + auto-promotion substrate is concrete; cycle 4 is the first consumer pack. The S4 schema-strictness lessons (every Pydantic field reviewed for required-vs-optional, closed-vs-open value sets, content-addressed-id-vs-UUID) directly inform the pack-manifest schema. Appetite per ROADMAP: 6w. **No `0004-*` pitch document exists yet** — shaping this pitch is the cooldown's headline non-fix work item.
- **Cycle 5 — Reviewer Web UI + QA Layer** *(downstream)*. Not a cooldown shaping target; carryforward item #5 above feeds cycle 5 with CLI-loop UX observations.
- **Cycle 6+ — Multi-platform plugins (Maven, npm/Vite)** *(downstream)*. Not a cooldown shaping target.

## Process notes for cycle 4 onward

Two patterns from cycle 3 worth carrying forward into cycle 4 shaping and execution:

- **Default to content-addressed ids for any cross-run-stable identity.** This was the recurring fix shape across cycle 3 (S2 term ids — fix #2; S5 promotion concept ids — fix #8) and it echoes cycle 1's segment fingerprints. If cycle 4's pack-manifest work introduces *any* identity field that needs to be stable across re-imports / re-installs / re-publishes, default to `sha256` of the identifying data fields rather than `uuid.uuid4()` unless there's a concrete reason not to. UUID4 per call is appropriate only for truly per-call identity (request id, span id) — never for an entity that should be idempotent under re-creation. <!-- author note: candidate for project memory promotion if cycle 4 hits the same shape; cycle-3 retro flagged the same. -->
- **Keep the one-PR-per-scope cadence for cycle 4.** Cycle 3's seven-scope / seven-PR shape (#8 → #14, ~9 P2/P3 reviewer-validated fixes total) gave each PR a tight enough surface for substantive review without becoming a megathread; bisects on a regression in any one scope don't have to wade through unrelated scopes at the same SHA. This is a clear win over cycle 2's two-PR consolidated shape (#6 covering scopes 1–4, #7 covering scopes 5–14) where review notes piled into PR #7 across many unrelated surfaces. **Recommend the same cadence for cycle 4; skip the cycle-2-style consolidated scope-set approach.**

## Open questions for the next betting table

None mandatory. One worth flagging for cooldown-time use:

- **Embedding-lookup deferral needs a benchmark before it can be shaped.** Carryforward item #3 above is explicitly benchmark-driven — the question is "does embedding similarity beat literal n-gram match enough to justify the lookup-path complexity?" — and that question can't be answered without a real corpus + a recall benchmark harness. If anyone wants to bet on embedding lookup for cycle 5+, **this cooldown is the natural slot to set up the benchmark harness** so the cycle-5 betting table has data instead of speculation. <!-- author note: scope and ownership of the benchmark harness is a human call; the cooldown-report agent is flagging the shaping prerequisite, not recommending the work. -->

## Recommended bets for next cycle

<!-- The cooldown-report agent's recommendation is input, not a decision.
     The actual bet is locked at the betting table. No 0004-* pitch document
     exists yet, so this is a shaping target rather than a shaped pitch. -->

The ROADMAP-default next bet is **Cycle 4 — First Domain Pack: legal-en**. There is no pitch document for it yet (`specs/pitches/0004-*` does not exist), so this is a shaping target rather than a shaped pitch. <!-- author note: cycle 4 needs a pitch shaped during this cooldown before it can be bet. The ROADMAP entry has the strategic framing; shaping work is to translate that into appetite + scopes + circuit breaker + no-gos, with explicit pack-manifest schema strictness checks per S4's lessons. -->

The cooldown-shapeable carryforward (item #2, `--termbase-path` flag) is small enough to land inside the cooldown window itself rather than be carved out as its own betting-table pitch.

## Carryover

- [ ] Shape a pitch for cycle 4 (`legal-en` domain pack, 6w appetite per ROADMAP). The ROADMAP entry is the strategic framing; shape it into appetite + scopes + circuit breaker + no-gos + open questions for the betting table. Apply S4's schema-strictness lessons to the pack-manifest schema design up-front.
- [ ] Execute the manual TBX round-trip benchmark — [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../../tests/benchmarks/cycle-3-tbx-roundtrip.md) on ≥ 3 real Weblate exports. For each unsupported element surfacing in `TbxImportReport.skipped_unsupported`, decide promote-to-supported-subset vs. document-and-defer. (Carryforward #1.)
- [ ] Shape and land the `--termbase-path` override flag as a cooldown one-liner pitch. (Carryforward #2.)
- [ ] _(Optional)_ Set up the embedding-similarity recall benchmark harness so cycle 5+ has data, not speculation, on whether to promote termbase lookup beyond literal n-gram match. (Carryforward #3 prerequisite.)
- [ ] _(Defer)_ Wikidata QID enrichment lands inside cycle 4's `legal-en` pack work — not cooldown. (Carryforward #4.)
- [ ] _(Defer)_ Reviewer-UI auto-promotion surface lands in cycle 5. Cooldown only captures CLI-loop UX observations if any surface during the round-trip benchmark or `--termbase-path` work. (Carryforward #5.)
- [ ] Cycle-2 carryover items #1 (daemon payload-size ceiling), #2 (concurrency contract), #5 (cross-language nullable drift audit) **remain deferred** from post-cycle-2 cooldown. The CI matrix from cycle-2 cooldown's #6 has been accumulating data; check whether #5's "what's actually drifting" question is answerable yet. (Source: [`cooldown-after-02.md`](./cooldown-after-02.md) § Carryover.)
- [ ] Medium-severity backlog from [`cycle-2.md`](./cycle-2.md#medium-severity-cooldown-if-room-otherwise-cycle-3) remains open. Pull forward only if cycle-4 shaping leaves room.
