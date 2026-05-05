---
pitch_id: [NNNN-slug]
title: "[Pitch title — short, descriptive]"
appetite: [2w | 4w | 6w]
bet_status: shaping
cycle: ""
circuit_breaker: "[The line we will not cross. e.g. 'If S3 is still uphill at week 3, ship S1+S2 and shelve S3.']"
shaped_by: "[author]"
shaped_date: [YYYY-MM-DD]
---

<!-- AI-NEMO Shape-Up pitch template. Companion to plan.md / spec.md / tasks.md. -->
<!-- See specs/README.md for the full SDD + Shape-Up workflow. -->

# [Cycle N — Title]

<!-- Human-readable header. Authoritative status / dates live in the YAML
     frontmatter above; this list is for at-a-glance reference and is what the
     README + ROADMAP cross-link to. Keep them in sync when bet_status flips. -->

- **ID**: [NNNN]
- **Appetite**: [2w | 4w | 6w] (wall-clock ceiling; actual session execution ≪ appetite)
- **Status**: shaping
- **Owner**: [author]

## Problem

<!-- One paragraph. The raw, unshaped problem. Who hits it, when, and what
     does it cost them today? Avoid solutions here. -->

[2–4 sentences describing the problem.]

## Solution shape

<!-- A rough sketch, not a spec. Enough to convince the betting table this fits
     the appetite. ASCII fat-marker drawings are encouraged for non-trivial
     architecture changes. -->

[Describe the high-level approach in 1–3 paragraphs. Identify the key elements
the team will build and how they fit together.]

## Rabbit holes

<!-- Specific things we can imagine going wrong or sucking up time. Name them
     so the team knows to route around them. -->

- **[Rabbit hole]**: [What it is, and the workaround we'll prefer.]
- **[Rabbit hole]**: [What it is, and the workaround we'll prefer.]

## No-gos

<!-- What's explicitly out of scope. Distinct from rabbit holes — these are
     things we *could* build but have decided not to. -->

- No [thing] — [reason]
- No [thing] — [reason]

## Scopes

<!-- 3–7 self-contained slices. Each scope is something a single executor can
     pick up and finish without blocking on another scope. Scopes appear on
     hill.json and get tracked uphill → downhill → done. Per AI-NEMO memory
     rule "Calibrate estimates for Claude Code, not human-days": estimates
     are session-execution time, not human-developer-days. -->

### S1: [Scope name]

[1–2 sentences. What this scope delivers. Reference any FRs from spec.md if a
spec has been produced.]

### S2: [Scope name]

[…]

### S3: [Scope name]

[…]

<!-- Add S4–S7 as needed. If you need more than 7, the appetite is probably wrong. -->

## Test strategy

<!-- One paragraph: what kinds of tests cover this cycle (unit / integration /
     e2e / contract / benchmark) and what the per-PR CI gate looks like.
     AI-NEMO convention: ruff check + ruff format --check + mypy strict +
     pytest with --cov on Python 3.10 / 3.11 / 3.12. -->

[Describe the test gates and any cycle-specific test infrastructure.]

## Open questions

<!-- Per AI-NEMO memory rule "Pre-resolve from project docs before asking the
     user": search CLAUDE.md / AGENTS.md / specs/ROADMAP.md for the answer
     before surfacing here. List only genuinely-contested questions for /bet
     to resolve. -->

- [Open question for /bet]

## Circuit breaker

<!-- Concrete trigger and action. When the appetite is exhausted, what ships,
     what gets shelved, and what gets fixed in cooldown. Mirror the YAML
     frontmatter `circuit_breaker:` line and add 1–2 sentences of context on
     what "exhausted" looks like for this pitch and which scopes are core
     vs. trim-able. -->

[Mirror the circuit_breaker line from frontmatter, then add context.]

## Bet log

<!-- Filled in as the pitch progresses through bet_status transitions.
     Append-only — do not rewrite history. Optional but encouraged for
     non-trivial cycles where the bet evolved during shaping. -->

| Date | bet_status | Note |
|------|------------|------|
| [YYYY-MM-DD] | shaping | Pitch drafted. |
