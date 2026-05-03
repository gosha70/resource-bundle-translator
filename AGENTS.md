# AI-NEMO — Networked Engine for Multilingual Ontologies

Knowledge-graph-grounded terminology and localization for software, with versioned domain packs and CC0/CC-BY ontology integrations. Distributed under the **egoge.com** namespace alongside [AI-ATLAS](https://github.com/gosha70/ai-atlas).

> **Current state**: pre-rebrand prototype (`resource-bundle-translator`). The repo is mid-Shape-Up cycle 0 (rebrand + stabilize). The conventions below describe the **target architecture** that lands during cycles 0–1; some directories don't exist yet but will. The legacy top-level Python modules (`translation_service.py`, `translation_request.py`, `translation.py`, `languages.py`) are deprecation shims that delete after cycle 1.

## Stack

- **Python 3.10+**, packaging via `pyproject.toml` + `pip install -e ".[dev]"` (no Poetry — keep tooling minimal)
- **Flask** for the reviewer/admin app (cycle 5 expands this)
- **SQLite** for the translation memory (default `./.ainemo/tm.sqlite`)
- **Kuzu** for the concept-oriented termbase (cycle 3+)
- **sentence-transformers** (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim) for embedding-based fuzzy TM lookup
- **HF transformers** for local NLLB-200 and Helsinki-NLP/OPUS providers
- **openai**, **anthropic** (cycle 2), **ollama** (cycle 2) SDKs for managed/local-LLM providers
- **polib** for gettext `.po`; **lxml** for XLIFF 2.0
- **Code quality**: ruff (lint + format), mypy strict, pytest
- **CI**: GitHub Actions (matrix on Python 3.10/3.11/3.12)
- **Future modules**: Gradle plugin (Kotlin DSL, cycle 2), Maven plugin (cycle 6), npm/Vite plugin (cycle 6)

## Project Structure (target — landing across cycles 0–1)

```
src/ainemo/
├── core/
│   ├── segment.py            # Segment + Placeholder + TranslatedSegment data model
│   ├── icu.py                # ICU MessageFormat parser (plurals, select, selectordinal)
│   ├── adapters/             # BundleAdapter implementations
│   │   ├── base.py           # BundleAdapter Protocol
│   │   ├── java_properties.py
│   │   ├── i18next_json.py
│   │   ├── gettext_po.py
│   │   └── xliff.py
│   ├── tm/                   # TranslationMemory implementations
│   │   ├── base.py           # TranslationMemory Protocol + TmHit
│   │   └── sqlite.py         # SqliteTranslationMemory (exact + fuzzy)
│   ├── validators/           # Validator implementations
│   │   ├── base.py           # Validator Protocol + Violation
│   │   ├── placeholder.py
│   │   ├── icu.py
│   │   ├── length.py
│   │   └── forbidden.py
│   ├── termbase/             # cycle 3+ — concept-oriented termbase via Kuzu
│   └── pipeline.py           # TranslationPipeline orchestrator
├── providers/                # LLM provider abstraction (replaces legacy models/)
│   ├── base.py               # Provider Protocol
│   ├── router.py             # Cost/latency-tracked routing layer
│   ├── nllb/
│   ├── opus/
│   ├── openai/
│   ├── anthropic/            # cycle 2
│   └── ollama/               # cycle 2
├── cli/                      # `nemo` CLI entry points
├── app/                      # Flask reviewer + admin (expands cycle 5)
├── config/                   # Pydantic settings, persona templates (YAML)
└── personas/                 # Versioned persona packs (software-ui, formal, casual; legal/medical/aerospace from cycle 4)
tests/
├── unit/
├── integration/
├── e2e/
└── benchmarks/               # Cache-hit rate, p50/p95 latency, validator pass rate
specs/                        # SDD + Shape-Up artifacts (see Shape-Up section below)
gradle-plugin/                # cycle 2+ — separate module, wraps Python core via daemon IPC
```

## Architecture Rules

> **Non-negotiable.** Violations must be flagged during review, not silently accepted.

- **Library-first, CLI-second, build-tool-plugin-third.** The core library is the source of truth. The CLI is a thin Pythonic wrapper. The Gradle/Maven/npm plugins shell out to the daemon. Never reimplement core logic in a wrapper.
- **Ports and adapters.** `core/` depends only on protocols (`BundleAdapter`, `Provider`, `TranslationMemory`, `Validator`). Concrete backends live in their own subpackages and implement the protocols.
- **Placeholder preservation is a hard invariant.** A translation that drops, invents, or corrupts a placeholder is a failure, never a soft warning. Validators block the write.
- **ICU MessageFormat parsing centralized.** `core/icu.py` is the single parser; adapters delegate. Pure-Python implementation for v1 (cycle 1 open question; pyicu is a possible future swap).
- **Translation memory is the first stop, not the last.** Every segment hits TM before any provider. Provider calls are the slow path; TM hits are the common path.
- **All LLM provider calls wrapped with cost + latency tracking.** Every call records (provider, model, input_tokens, output_tokens, latency_ms, cost). No bare provider invocations.
- **Persona / domain context configurable, never hardcoded.** Personas live in YAML under `src/ainemo/personas/`. Loading a persona is the canonical way to inject domain context — no inline domain prompts in code.
- **Local-first. No SaaS, no telemetry, no phone-home.** TM, termbase, personas, packs are all on disk. The user owns their data.
- **Reproducibility by default**: temperature 0 across all providers unless explicitly overridden.

## Translation-Domain Conventions

- **Segment fingerprint** = stable hash of `source_text + source_lang + placeholder shape`. The TM key.
- **Glossary terms** are tokenized to `[i~~i]` (NLLB-style) or `_TERM` (Marian-style) before translation; restored after. Adapter chooses the token format.
- **Numbered placeholders** (`{0}`, `{1}`) and named (`{name}`) follow the same encode/decode pattern.
- **ICU placeholders** (`{count, plural, ...}`) preserve their inner structure; the parser identifies branches and treats each as its own translatable text.
- **TM commit policy**: project TM (`./.ainemo/tm.sqlite`) is **opt-in** for git tracking, not default. The TM contains source strings, translated strings, and provider/model metadata — potentially proprietary product text — and is a binary file that grows and conflicts in normal git workflows. Default `.gitignore` excludes `.ainemo/`. Teams that want shared cached translations for deterministic, zero-cost CI may opt in per-project; the README and `nemo tm init` will document the privacy and repo-size trade-offs before recommending it.
- **Embedding model**: pinned in config (`paraphrase-multilingual-MiniLM-L12-v2`); never hardcoded in pipeline code.
- **Fuzzy threshold**: 0.85 default, tunable per project. Below threshold = miss = forward to provider.
- **API keys** via env vars only (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.); never in config files.
- **Logging** via stdlib `logging`. No `print()` in shipped code.

## Provider Rules

- All LLM providers implement the `Provider` protocol in `providers/base.py`.
- Provider modules under `providers/<name>/`. Never import provider modules from `core/` — go through `providers/router.py`.
- Cost tracking is mandatory. The router records every call to `~/.ainemo/usage.jsonl` (or configured location).
- Retry policy: exponential backoff on rate limits, max 3 attempts. Failures surface to the caller — never silently swallow.
- Provider routing rules (which provider for which language pair / domain) are configuration, not code.

## Translation Memory Rules

- `SqliteTranslationMemory` is the default backend. Other backends must implement `TranslationMemory` protocol.
- Schema: see `specs/pitches/0001-foundation/pitch.md` § "Data model". Don't drift from it without an ADR.
- Exact match before fuzzy match. Fuzzy uses cosine over MiniLM embeddings; linear scan acceptable up to ~100k segments. Add a vector index only if a benchmark shows it matters.
- Every translation is stored after validation passes. Failed validations never enter the TM.
- TM stats (size, hit rate) exposed via `nemo tm stats` CLI.

## Validator Rules

- All validators implement the `Validator` protocol. Severity is `error` (blocks write) or `warning` (logs).
- Built-in (cycle 1): `PlaceholderParityValidator`, `IcuSyntaxValidator`, `LengthBudgetValidator`, `ForbiddenTermsValidator`.
- Pipeline runs all configured validators; the aggregate `Violation` list is surfaced in the CLI summary and to the reviewer UI (cycle 5).
- The `--strict` CLI flag escalates warnings to errors for the run.

## Bundle Adapter Rules

- One adapter per format under `core/adapters/`. Each implements `BundleAdapter` and ships a contract test.
- `parse(path) → list[Segment]` and `serialize(path, list[TranslatedSegment])` are the only public methods consumers call.
- Round-trip identity is the headline contract: `parse → serialize → parse` must equal the original for every fixture.
- New adapters cannot land without (a) ≥10 fixtures including pathological cases (Unicode keys, escape sequences, multi-line values, empty values, comments), and (b) a passing contract test.

## Testing

- `pytest` with markers: `unit`, `integration`, `e2e`, `slow`, `benchmark`.
- **Unit**: per-module, fast, deterministic. Mock embeddings, mock providers.
- **Integration**: real SQLite, real MiniLM model, mock providers OR local NLLB.
- **E2E**: full CLI run on a real OSS bundle fixture; assert TM hit-rate on second run ≥99%.
- **Contract**: every adapter ships `test_contract.py` with the round-trip property test matrix.
- **Benchmark**: TM lookup p95 < 50ms at 50k segments; pipeline throughput ≥100 segments/sec on TM-hit-only path.
- Coverage target: ≥80% on `core/`, ≥60% on `providers/`.
- All tests pass on Python 3.10, 3.11, 3.12 in CI.

## Commands

> Some commands work today; others land during cycle 0/1. Marked with [c0], [c1] as needed.

```bash
# Install (after cycle 0 lands pyproject.toml)
pip install -e ".[dev]"                               # [c0]

# Lint + type-check
ruff check . && ruff format --check .                 # [c0]
mypy src/                                             # [c0]

# Tests
pytest -m "not slow" --tb=short -q                    # fast suite
pytest -m integration --tb=short                      # integration
pytest -m benchmark                                   # benchmarks (manual, per cycle)

# CLI (legacy, until cycle 0 renames)
python -m cli.resource_bundle_generator --from_file messages_en_US.properties --to_langs de fr he
python -m cli.resource_bundle_git --repo_path . --model_name nllb --to_lang iw

# CLI (target, post-cycle-0)
nemo translate --from messages_en_US.properties --to-langs de,fr,he --provider nllb        # [c1]
nemo tm stats                                                                              # [c1]
nemo validate path/to/translated_de.properties                                             # [c1]

# Flask app (admin/reviewer surface; expands cycle 5)
python -m app.translator_app                          # legacy
flask --app src.ainemo.app run                        # [c1]

# Spec validation (Shape-Up)
bash scripts/validate-spec.sh --all                   # validates SDD artifacts
bash scripts/validate-pitch.sh --all                  # validates Shape-Up pitches
```

## Shape-Up + SDD Workflow

This project uses **Spec-Driven Development on top of Shape-Up cycles**. Methodology, glossary, and templates live in `specs/`.

- **Methodology**: [`specs/README.md`](specs/README.md) — pitch template, cadence, lifecycle states, file layout.
- **Roadmap**: [`specs/ROADMAP.md`](specs/ROADMAP.md) — strategic positioning, north-star outcomes, all 7 cycles, program-level risks.
- **Active pitches**: `specs/pitches/<NNNN-slug>/{pitch.md, plan.md, spec.md, tasks.md, hill.json}`.
- **Cycle 1 (foundation)** is fully shaped at [`specs/pitches/0001-foundation/pitch.md`](specs/pitches/0001-foundation/pitch.md).

### Workflow agents (from `code-copilot-team`'s Shape-Up extension)

| Agent | Purpose |
|---|---|
| `pitch-shaper` | Rough idea → Shape-Up pitch (appetite, scopes, no-gos, rabbit holes) |
| `scope-executor` | One scope from a pitch → impl + tests + hill-chart update |
| `cycle-retro` | End of cycle → retrospective from git log + hill.json + outcomes |
| `cooldown-report` | End of cooldown → bug-fix summary + next-cycle shaping queue |

### Slash commands

| Command | Use |
|---|---|
| `/shape <topic>` | Invoke `pitch-shaper` |
| `/bet <pitch-id>` | Lock a pitch for the upcoming cycle |
| `/cycle-start <pitch-id>` | Initialize hill.json with all scopes uphill |
| `/hill <scope> <up\|down\|done>` | Update hill-chart status |
| `/cooldown` | Run `cooldown-report` and ship/shelve the active pitch |

### Discipline

- No work begins on a pitch until it's shaped *and* bet.
- The appetite is a hard ceiling. If unfinished at deadline → ship what's there or shelve. **Never extend a cycle.**
- Scope-hammering inside the cycle is encouraged. Adding scope mid-cycle is forbidden.
- Pitch + plan + spec + tasks all live under `specs/pitches/<id>/`. SDD nests under Shape-Up; the pitch is the source of truth.

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, architecture decisions, API contracts, code review, cross-cutting changes | Coordination, `core/segment.py`, `core/pipeline.py`, `core/icu.py`, persona system |
| **Adapter Engineer** | New bundle format; round-trip preservation; ICU edge cases | `core/adapters/` |
| **TM Engineer** | TM schema, fuzzy match, embedding pipeline, cache discipline | `core/tm/` |
| **Provider Engineer** | LLM provider abstraction, cost/latency tracking, routing, retry/backoff | `providers/` |
| **Validator Engineer** | Placeholder parity, ICU syntax, length budgets, forbidden terms | `core/validators/` |
| **Termbase Engineer** *(cycle 3+)* | Kuzu schema, TBX 3.0 import/export, persona system, domain packs, auto-promotion from TM | `core/termbase/`, `personas/`, `packs/` |
| **Gradle Plugin Engineer** *(cycle 2+)* | Kotlin DSL plugin, daemon IPC to Python core, TestKit functional tests | `gradle-plugin/` |
| **UI Engineer** *(cycle 5+)* | Reviewer web UI, auto-promotion review queue, confidence display | `app/`, `app/templates/` |
| **QA Engineer** | Test architecture, contract tests, benchmarks, CI matrix | `tests/`, `tests/benchmarks/` |

### Team Lead — Default Behavior

You ARE the Team Lead. For every user request:

1. Check the active pitch in `specs/pitches/`. The pitch defines what's in scope this cycle. Anything outside the pitch is rabbit-hole territory.
2. Assess complexity. Single-domain, single-layer changes → handle directly.
3. Multi-layer or >50 lines of specialized code → delegate to the relevant specialist via `Agent` tool.
4. Always review sub-agent output against project conventions before presenting.
5. Coordinate when a task spans layers (e.g., new adapter needs `core/adapters/` + ICU edge case + validator coverage + tests).
6. Own domain entities, cross-cutting concerns, and the Shape-Up discipline (don't quietly grow scope mid-cycle).

### Delegation Prompt Template

When spawning a specialist sub-agent via the `Agent` tool, use this pattern:

```
You are the [ROLE] on AI-NEMO — a knowledge-graph-grounded localization platform
for software resource bundles.

Architecture: ports and adapters. Domain logic in core/ depends on protocols only.
Library-first, CLI-second, build-tool-plugin-third. Local-first; no SaaS.

Active cycle: [N], pitch [pitch-id]. See specs/pitches/<id>/pitch.md for in-scope/no-gos.

Project conventions:
- [paste relevant section of AGENTS.md]

Your task: [specific task description]

Constraints:
- Follow all conventions above
- Type-annotated Python, mypy strict
- Stay inside the active pitch's scope; flag if you find yourself heading into a rabbit hole
- Do NOT modify files outside your ownership area without flagging it
- Update specs/pitches/<id>/hill.json if completing a scope
- Return: code changes + brief summary of decisions made
```

### Specialist constraints (selected highlights)

- **Adapter Engineer**: every new format must ship ≥10 fixtures + a passing round-trip contract test. ICU parsing routes through `core/icu.py`, never reimplemented.
- **TM Engineer**: schema changes require an ADR under `specs/adr/`. Don't introduce a vector index until a benchmark demands it.
- **Provider Engineer**: every call goes through `providers/router.py`. Cost tracking is non-negotiable. API keys via env, never in config files.
- **Validator Engineer**: violations must include `span` offsets when meaningful, so the reviewer UI can highlight them.
- **Termbase Engineer**: Kuzu schema must support TBX 3.0 round-trip lossless against Weblate's TBX exports — that's the interop benchmark.
- **Gradle Plugin Engineer**: the plugin is a thin façade. Translation logic stays in the Python core; the plugin shells out via JSON-over-stdio (or gRPC if benchmark warrants).
- **QA Engineer**: contract tests run on every PR. Benchmarks run manually per cycle, with results checked into `tests/benchmarks/results/`.

## Reference

- **Strategic positioning** (gap analysis vs Weblate, T-Ragx, PhilKes Gradle plugin): see `specs/ROADMAP.md` § "Strategic positioning".
- **Distribution namespace** (AI-ATLAS suite convention): Maven group `com.egoge.ai.nemo` with per-module artifacts (`core`, `cli`, `gradle-plugin`, `pack-legal-en`, ...). PyPI distribution `ai-nemo` (Python import `ainemo`). npm scope `@egoge/ai-nemo`. CLI binary `nemo`. GitHub repo `ai-nemo` after rebrand.
- **License**: TBD before public release. Recommended: Apache-2.0 for code; data packs declare their own (CC0 / CC-BY / CC-BY-SA per source ontology).
- **Closest competitors to differentiate against**: Weblate (TBX-mature, server-shaped, glossary is flat), T-Ragx (RAG over glossary, no i18n format awareness), `io.github.philkes.auto-translation` Gradle plugin (Android-only, no termbase).
- **External ontology anchors** (cycle 4+): Wikidata (CC0), EuroVoc (EU re-use), IATE (free public download), AGROVOC (CC BY 4.0), MeSH via BioPortal (NLM free for any use), GeoNames (CC BY 4.0). **Avoid**: BabelNet (NC), UMLS (per-user license, not redistributable).
