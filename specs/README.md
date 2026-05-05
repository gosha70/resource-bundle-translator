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

Each pitch in `pitches/` is a `pitch.md` with **YAML frontmatter** (the validator's source of truth) plus a **Markdown body** (the human-readable pitch). The full template lives at [`pitch-template.md`](pitch-template.md); copy it for new pitches.

The frontmatter is what `~/.claude/templates/sdd/validate-pitch.sh` checks against on every cycle close:

```yaml
---
pitch_id: NNNN-slug          # must match the directory name
title: "..."
appetite: 2w | 4w | 6w
bet_status: shaping | shaped | bet | building | shipped | shelved
cycle: ""                    # required when bet_status ∈ {bet, building, shipped}
circuit_breaker: "..."       # required when bet_status ∈ {shaped, bet, building, shipped, shelved}
shaped_by: "author"
shaped_date: YYYY-MM-DD
---
```

The body follows this section structure:

```markdown
# <Cycle N — Title>

<!-- Human-readable header. Authoritative status / dates live in the YAML
     frontmatter above; this list is what the README + ROADMAP cross-link to. -->

- **ID**: NNNN
- **Appetite**: ...
- **Status**: ...
- **Owner**: ...

## Problem
<2–4 paragraphs. Concrete, with examples. Why now.>

## Solution shape
<Rough sketch. Prose + fat-marker diagrams. NOT a detailed design.>

### Interfaces (SDD layer)
<Public API contracts the implementation must satisfy. File paths, function
signatures, schema sketches. Detailed enough that the build is a mechanical
translation.>

### Data model
<If applicable. Schema diagrams or DDL sketches.>

## Rabbit holes
<Specific risks to steer around.>

## No-gos
<Out of scope. Explicit list.>

## Scopes
<3–7 vertical slices, each shippable in a session-execution chunk
(per AI-NEMO memory rule "Calibrate estimates for Claude Code, not human-days").
These become the hill-chart items.>

## Test strategy
<What does "done" mean? Unit / integration / contract / manual. Concrete
acceptance criteria. AI-NEMO convention: ruff + mypy strict + pytest on the
3.10/3.11/3.12 matrix.>

## Open questions
<Resolve before betting. After betting, no new questions allowed.
Per AI-NEMO memory rule "Pre-resolve from project docs before asking the user":
search CLAUDE.md / AGENTS.md / specs/ROADMAP.md first.>

## Circuit breaker
<Concrete trigger and action — mirror frontmatter, add 1–2 sentences of
context on which scopes are core vs. trim-able.>
```

### Validation

```bash
bash ~/.claude/templates/sdd/validate-pitch.sh --all          # validate every pitch
bash ~/.claude/templates/sdd/validate-pitch.sh --pitch-id 0002-providers-gradle
```

The validator enforces required frontmatter fields, the appetite/bet_status enums, and the conditional `cycle` / `circuit_breaker` rules. CI does not (yet) run this on every PR — cooldown after each cycle pins the validator pass.

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
├── README.md                            (this file — methodology)
├── ROADMAP.md                           (master Shape-Up roadmap, all cycles)
├── pitch-template.md                    (canonical pitch skeleton — copy for new pitches)
├── pitches/
│   └── <NNNN-slug>/                     (one directory per pitch)
│       ├── pitch.md                     (YAML frontmatter + problem/scopes/no-gos — required)
│       ├── plan.md                      (build-phase implementation plan — optional)
│       ├── spec.md                      (deeper SDD spec if pitch.md interfaces aren't enough — optional)
│       ├── tasks.md                     (task breakdown for scope-executor — added during build)
│       └── hill.json                    (hill-chart state per scope — created on /cycle-start)
├── retros/
│   ├── cycle-NN.md                      (per-cycle retrospective — written by cycle-retro agent)
│   └── cooldown-after-NN.md             (cooldown report — written by cooldown-report agent)
└── adr/                                 (architecture decision records, created as decisions are made)
```

Cycles 0–2 are shipped (`pitches/0000-rebrand-stabilize`, `pitches/0001-foundation`, `pitches/0002-providers-gradle`). Cycle 3 (`0003-*`) is the next ROADMAP target; future cycles (0004 — domain pack legal-en, 0005 — reviewer UI, 0006 — multi-platform) will be shaped during cooldowns and land under their own `pitches/<NNNN-slug>/` directories.

## See also

- [ROADMAP.md](ROADMAP.md) — the master cycle plan
- [Shape Up by Ryan Singer](https://basecamp.com/shapeup) — the methodology this is based on
