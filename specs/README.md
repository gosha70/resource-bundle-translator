# AI-NEMO — Spec-Driven Development with Shape-Up

This directory holds the living specs that drive AI-NEMO's development. We use **Spec-Driven Development (SDD)** layered on top of **Shape-Up** (Basecamp's product methodology). Specs are versioned alongside the code they describe; every cycle ships a coherent slice of the product, and nothing enters a cycle without being shaped first.

## Why this combination

- **Shape-Up** answers *"what do we build next, and how big is it?"* — pitches with fixed appetite, variable scope, and explicit boundaries.
- **SDD** answers *"how do we know we built the right thing?"* — every pitch has a written spec with interfaces, acceptance criteria, and test strategy that the implementation must satisfy.

Together they keep the project from drifting into either feature-creep (Shape-Up's circuit-breaker stops this) or under-specified hand-waving (SDD forces the contract before the code).

## Glossary

| Term | Meaning here |
|---|---|
| **Pitch** | A shaped problem + rough solution + appetite. Lives in `pitches/NNNN-slug.md`. |
| **Appetite** | The time we're willing to spend. Small batch = 2 weeks. Big batch = 6 weeks. Hard ceiling. |
| **Cycle** | A focused build period at the appetite. Uninterrupted work; no new pitches mid-cycle. |
| **Cooldown** | 1–2 weeks between cycles. Bug fixes, polish, and **shaping the next pitches**. No new feature work. |
| **Hill chart** | Progress indicator. *Uphill* = still figuring out unknowns. *Downhill* = mechanical execution. Goal: get every scope to the top of the hill in the first half of the cycle. |
| **Scope** | A vertical slice of the pitch deliverable in 1–3 days. Pitches break into 3–7 scopes. |
| **Rabbit hole** | A risk the pitch explicitly tells the team to avoid. |
| **No-go** | Out-of-scope items. Anything not listed as a no-go is fair game inside the appetite. |
| **Circuit breaker** | If appetite is exhausted, ship what's there or shelve it. Never extend a cycle. |

## Cadence (proposed)

- Default cycle length: **6 weeks** for new capability, **2 weeks** for stabilization/rebrand work.
- Cooldown: **1 week** between standard cycles, **2 weeks** before a major release.
- Shaping happens during cooldowns and is owned by whoever pitches.
- Betting (deciding which pitch enters the next cycle) happens at the end of cooldown.

A solo or small-team project can compress this — but the *order* (shape → bet → build → cooldown) must not collapse.

## Spec structure

Each pitch in `pitches/` follows this template:

```markdown
# <Title>

- **ID**: NNNN
- **Appetite**: 2w | 4w | 6w
- **Status**: shaping | shaped | bet | building | shipped | shelved
- **Owner**:

## Problem
<2–4 paragraphs. Concrete, with examples. Why now.>

## Solution shape
<Rough sketch. Prose + fat-marker diagrams. NOT a detailed design.>

### Interfaces (SDD layer)
<Public API contracts the implementation must satisfy. File paths, function signatures, schema sketches. Detailed enough that the build is a mechanical translation.>

### Data model
<If applicable. Schema diagrams or DDL sketches.>

## Rabbit holes
<Specific risks to steer around.>

## No-gos
<Out of scope. Explicit list.>

## Scopes
<3–7 vertical slices, each shippable in 1–3 days. These become the hill-chart items.>

## Test strategy
<What does "done" mean? Unit / integration / contract / manual. Concrete acceptance criteria.>

## Open questions
<Resolve before betting. After betting, no new questions allowed.>
```

## How specs and code coexist

- A pitch enters `pitches/` in `shaping` status.
- When shaped and ready for the betting table, status flips to `shaped`.
- After betting, status flips to `bet` and the pitch is locked.
- During the cycle, the pitch is the source of truth. Implementation diffs may update the **interfaces** section if reality forces a contract change — but only with a written note explaining why.
- After ship, the pitch moves to status `shipped` and gains a `## Outcomes` section: what shipped, what was scope-hammered, what learnings inform future shaping.

This is what makes it Spec-Driven: the spec is part of the artifact, not a throwaway planning doc.

## File layout

```
specs/
├── README.md                       (this file — methodology)
├── ROADMAP.md                      (master Shape-Up roadmap, all cycles)
├── pitches/
│   ├── 0001-foundation.md          (cycle 1 — fully shaped)
│   ├── 0002-providers-gradle.md    (cycle 2 — stub, shape during cooldown)
│   ├── 0003-kuzu-termbase.md       (cycle 3 — stub)
│   ├── 0004-domain-pack-legal.md   (cycle 4 — stub)
│   ├── 0005-reviewer-ui.md         (cycle 5 — stub)
│   └── 0006-multi-platform.md      (cycle 6 — stub)
└── adr/                            (architecture decision records, created as decisions are made)
```

## See also

- [ROADMAP.md](ROADMAP.md) — the master cycle plan
- [Shape Up by Ryan Singer](https://basecamp.com/shapeup) — the methodology this is based on
