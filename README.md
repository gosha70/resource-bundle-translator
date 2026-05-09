# AI-NEMO

**Networked Engine for Multilingual Ontologies** — knowledge-graph-grounded terminology and localization for software, with versioned domain packs and CC0/CC-BY ontology integrations. Distributed under the **egoge.com** namespace alongside [AI-ATLAS](https://github.com/gosha70/ai-atlas).

> **Status**: pre-release. Cycles 0–4 **shipped**, cycle 5 **closing**. Cycle 0 (rebrand & stabilize) shipped 2026-05-03 — see the [retrospective](specs/retros/cycle-0.md). Cycle 1 (foundation: adapters + translation memory + validators) shipped 2026-05-03. Cycle 2 (provider abstraction + Gradle plugin) shipped 2026-05-05 — `Provider` Protocol + NLLB / OPUS / OpenAI / Anthropic / Ollama backends + `ProviderRouter` + UsageLog + Gradle plugin (see [retro](specs/retros/cycle-2.md), [cooldown](specs/retros/cooldown-after-02.md)). Cycle 3 (concept-oriented termbase via Kuzu) shipped 2026-05-06 — `Termbase` Protocol + `KuzuTermbase` + TBX 3.0 round-trip + persona system + TM auto-promotion + `nemo termbase` CLI (see [retro](specs/retros/cycle-3.md), [cooldown](specs/retros/cooldown-after-03.md)). Cycle 4 (pluggable termbase importer pipeline) shipped 2026-05-07 — `TermbaseSource` Protocol + `CsvSource` + `JsonLinesSource` + `nemo termbase import-from-csv` / `import-from-jsonl` (see [cooldown](specs/retros/cooldown-after-04.md), [`docs/importers.md`](docs/importers.md)). Cycle 5 (reviewer web UI + QA layer) is closing on 2026-05-08 — Flask app under `src/ainemo/app/` with five views (`/promote`, `/imports`, `/termbase`, `/qa`, `/personas`), HTMX-driven with vendored static assets, `ImportSkipStore` + `Termbase.update_term` + `ProviderRouter.translate_with` + `UsageLog.estimate_for` + `build_glossary_block` as additive Protocol additions, `nemo app run` CLI; cooldown retro pending. See [`specs/ROADMAP.md`](specs/ROADMAP.md) for the full plan and [`specs/pitches/`](specs/pitches/) for individual cycles.

## What this is

AI-NEMO localizes software resource bundles (`.properties`, JSON, `.po`, XLIFF) using LLMs while:

- **Preserving placeholders.** `{0}`, `{name}`, ICU `{count, plural, ...}` are extracted, tokenized, translated around, and restored. Validators block any output that drops or mangles a placeholder.
- **Caching with a translation memory.** Re-running on an unchanged file is a no-op for the LLM — translations come from a SQLite-backed TM with embedding-based fuzzy lookup. Cycle-2 lookups are scoped to the requested provider so a `--provider noop` run does not satisfy a later `--provider openai` run.
- **Eventually, grounding terms in a knowledge graph.** Cycle 3+ replaces the flat glossary with a Kuzu-backed concept-oriented termbase plus version-pinned domain packs (legal, medical, aerospace) anchored to Wikidata, EuroVoc, IATE, AGROVOC, MeSH, and friends. The KG is the moat — see [§ Strategic positioning in the roadmap](specs/ROADMAP.md#strategic-positioning).

## Closest projects to differentiate against

| Project | Strength | Where AI-NEMO wins |
|---|---|---|
| Weblate + OpenAI backend | Mature TBX, large community, prompt-injects glossary | KG (not flat list), domain packs, build-tool-first not server-first |
| T-Ragx | RAG over TM + glossary, beat DeepL on JA→ZH | i18n format awareness, concept-oriented termbase, Gradle plugin |
| `io.github.philkes.auto-translation` | Direct Gradle integration, multi-provider | JVM `.properties` (Android already covered there), termbase, multi-format core |

## Installation

AI-NEMO targets **Python ≥ 3.10**. From a checked-out repo:

```bash
pip install -e ".[dev]"
```

This installs the package in editable mode plus the dev tooling (`ruff`, `mypy`, `pytest`, `pytest-cov`).

## Usage

### CLI

The `nemo` console script ships five cycle-2 subcommands plus the cycle-3 `termbase` family.

```bash
# Translate a source bundle to one or more target languages.
nemo translate \
  --from messages_en_US.properties \
  --to-langs de-DE,fr-FR,es-ES \
  --output-dir ./.ainemo/output \
  [--from-lang en-US] \
  [--format java-properties|i18next-json|gettext-po|xliff-2] \
  [--provider noop|nllb|opus|openai|anthropic|ollama] \
  [--tm-path ./.ainemo/tm.sqlite] \
  [--usage-log ~/.ainemo/usage.jsonl] \
  [--strict] \
  [--forbidden-term BrandX]…

# Inspect the local translation memory.
nemo tm stats --tm-path ./.ainemo/tm.sqlite

# Re-run validators on an existing source/target pair.
nemo validate \
  --source messages_en_US.properties \
  --target messages_de_DE.properties \
  --to-lang de-DE

# List registered providers and their environment availability.
nemo provider list

# Aggregate the per-call usage log (calls, tokens, latency, USD cost).
nemo provider stats [--usage-log PATH] [--since 2026-05-01]

# Run a long-lived JSON-over-stdio daemon (used by the Gradle plugin).
nemo daemon [--usage-log PATH]

# Manage the cycle-3 concept-oriented termbase.
nemo termbase init [--persona-dir PATH]
nemo termbase import path/to/glossary.tbx
nemo termbase export path/to/out.tbx [--domain-id software]
nemo termbase promote --source-lang en --target-lang de [--review|--accept-all]
nemo termbase stats

# Cycle-4 — import your team's CSV / JSONL glossary (see "Import your
# team's glossary" below + docs/importers.md for the YAML schema).
nemo termbase import-from-csv path/to/glossary.csv --map-config mapping.yaml
nemo termbase import-from-jsonl path/to/dump.jsonl --map-config mapping.yaml

# Cycle-5 — start the reviewer + admin web app on localhost (single-user
# default; see docs/reviewer-ui.md for the full tour).
nemo app run [--host 127.0.0.1] [--port 5050] [--debug] \
             [--termbase-path .ainemo/termbase.kuzu] [--tm-path .ainemo/tm.sqlite]
```

`nemo translate` infers the bundle format from the source path's extension; pass `--format` to override. See [`docs/adapters.md`](docs/adapters.md) for the format → adapter table and [`docs/providers.md`](docs/providers.md) for per-provider prereqs, default models, env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_HOST`), and cost tracking.

The default `--provider noop` echoes source text unchanged, so the pipeline (parse → TM → provider → validators → serialize) runs offline without any model. Switch to `nllb` / `opus` / `openai` / `anthropic` / `ollama` when you want real translations. Every provider call routes through `ProviderRouter` and records to the UsageLog (`~/.ainemo/usage.jsonl` by default), even on noop runs — uniform cost surveillance is the cycle-2 contract.

### Gradle plugin

```kotlin
// build.gradle.kts
plugins {
    id("com.egoge.ai.nemo.translate") version "0.1.0"
}

aiNemoTranslate {
    sourceFile.set(file("src/main/resources/messages_en_US.properties"))
    sourceLanguage.set("en-US")
    targetLanguages.set(listOf("de-DE", "fr-FR", "ja-JP"))
    provider.set("openai")
}
```

```bash
./gradlew translateBundles
```

The plugin spawns one `nemo daemon` subprocess per task run, batches all configured target languages into one `translate_file` op, and amortizes model load + SDK init across the whole build. See [`docs/gradle-plugin.md`](docs/gradle-plugin.md) for the full DSL reference, the JSON-over-stdio IPC contract, build instructions (Gradle wrapper bootstrap deferred to cycle-3 cooldown), and troubleshooting. JDK 17+ required.

## Supported languages

AI-NEMO inherits the language set from the prototype it descends from:

| Code | Language |
|---|---|
| `ar` | Modern Standard Arabic |
| `de` | German |
| `el` | Greek |
| `en_GB` / `en_US` | English |
| `es` | Spanish |
| `fr_CA` / `fr_CH` / `fr_FR` | French |
| `it` | Italian |
| `iw` | Hebrew |
| `hi` | Hindi |
| `ja` | Japanese |
| `ko` | Korean |
| `nl` | Dutch |
| `pl` | Polish |
| `pt` | Portuguese |
| `ru` | Russian |
| `sv` | Swedish |
| `th` | Thai |
| `tr` | Turkish |
| `zh_CN` / `zh_HK` | Chinese (Mandarin) |

Cycle 1 expanded format coverage (i18next JSON, gettext `.po`, XLIFF 2.0) on top of the original `.properties` support.

## Translation providers

Cycle 2 finalized the `Provider` Protocol: every backend implements `translate(segment, target_lang) -> ProviderResult` and `supports(source_lang, target_lang) -> bool`. `ProviderResult` carries `target_text`, `provider`, `model`, `input_tokens`, `output_tokens`, `latency_ms`, `cost_usd`, and `confidence`. Every call goes through `ProviderRouter`, which records to `~/.ainemo/usage.jsonl` and applies optional retry + exponential backoff via `with_retry`.

| Backend | Kind | Default model | Cost tracked | Status |
|---|---|---|---|---|
| `noop` | placeholder | — | no | always available |
| `nllb` | local NMT | `facebook/nllb-200-distilled-600M` | no | always available |
| `opus` | local NMT (OPUS-MT, English source only) | per-pair Helsinki-NLP model | no | always available |
| `openai` | managed LLM | `gpt-4o-2024-11-20` | yes | needs `OPENAI_API_KEY` |
| `anthropic` | managed LLM | `claude-sonnet-4-5-20250929` | yes | needs `ANTHROPIC_API_KEY` |
| `ollama` | local LLM (HTTP) | `llama3.2` | no (local) | needs running daemon at `OLLAMA_HOST` (default `http://localhost:11434`) |

All cloud providers run with `temperature=0` for reproducibility (per AGENTS.md § Architecture Rules). See [`docs/providers.md`](docs/providers.md) for per-provider prereqs, full pricing tables, supported language pairs, and the "adding a new provider" checklist.

## Termbase + personas

Cycle 3 ships AI-NEMO's moat: a Kuzu-backed **concept-oriented termbase** plus a **persona system** that injects a per-call prompt addendum into the provider's system prompt.

```bash
# One-time setup — creates .ainemo/termbase.kuzu and syncs the three
# starter personas (software-ui, formal, casual).
nemo termbase init

# Import a TBX 3.0 glossary (e.g. exported from Weblate).
nemo termbase import glossary.tbx

# Promote stable n-grams from the TM into the termbase, gated behind
# an interactive y/n/q review loop.
nemo termbase promote --source-lang en --target-lang de
```

When the pipeline is constructed with a termbase + persona — for example via the daemon's `persona_id` envelope field — every TM-miss segment runs `termbase.lookup_concepts_for(...)` against the configured persona's domain, formats the hits as a glossary block, and prepends the persona's `prompt_addendum`. The combined string lands as a system-prompt addendum on the provider call. LLM providers (OpenAI / Anthropic / Ollama) consume it; seq2seq providers (NLLB / OPUS) accept-and-ignore. `temperature=0` is preserved across the change.

When neither a termbase nor a persona is configured, the pipeline behaves identically to cycles 1+2 — the cycle-1 e2e regress-clean contract holds.

See [`docs/termbase.md`](docs/termbase.md) for the concept model, schema, TBX subset table, and `nemo termbase` CLI reference, and [`docs/personas.md`](docs/personas.md) for the YAML schema, starter personas, authoring guide, and prompt-injection mechanics.

## Import your team's glossary

Cycle 4 ships the **pluggable termbase importer pipeline** for the 90%+ of i18n teams whose glossary lives in a spreadsheet rather than TBX. Two formats supported out of the box:

```bash
# A spreadsheet exported as CSV.
nemo termbase import-from-csv path/to/glossary.csv \
    --map-config mapping.yaml \
    [--encoding latin-1] [--delimiter ';'] [--namespace marketing]

# A one-record-per-line JSON dump (e.g. `npm run extract-terms`).
nemo termbase import-from-jsonl path/to/dump.jsonl \
    --map-config mapping.yaml \
    [--namespace marketing]
```

Both flow through a YAML field-mapping file the team commits alongside the data:

```yaml
# mapping.yaml
source_lang: en-US
source_column: term_en
target_columns:
  de-DE: term_de
  fr-FR: term_fr
domain_column: category      # optional
definition_column: notes     # optional
```

Re-running an import with unchanged source data + unchanged `--namespace` is byte-stable at the termbase level — concept ids are content-addressed `import-<sha256[:16]>` over `(source_lang, source_term, namespace)`, so the second run upserts onto the same rows. Two glossaries sharing a source surface (`cancel` in marketing.csv vs legal.csv) stay distinct via `--namespace` or a per-row `domain_column`.

See [`docs/importers.md`](docs/importers.md) for the full `FieldMapping` schema, the `TermbaseSource` Protocol, error surfaces, and the idempotency / namespace-collision contracts.

## Reviewer UI

Cycle 5 ships AI-NEMO's **reviewer + admin web app** — a Flask surface for triaging auto-promotion candidates, retrying skipped imports, curating the termbase, inspecting persona behavior, and scoring per-segment confidence.

```bash
# Start the reviewer app on localhost (defaults: 127.0.0.1:5050).
nemo app run
```

The five views the reviewer can reach:

| View | URL | Purpose |
|---|---|---|
| `/promote` | Auto-promotion queue — accept / reject / edit-then-accept TM-derived `PromotionCandidate` rows; replaces the cycle-3 `--review` stdin loop. |
| `/imports` | Import-skip queue — retry rows that `import-from-csv` / `-jsonl` skipped, with optional in-place edits. |
| `/termbase` | Concept / term curation — list, search, edit, quick TBX 3.0 export. |
| `/qa` | QA layer — per-segment cheap signals (termbase cosine + placeholder parity + length budget) and opt-in back-translation. |
| `/personas` | Read-only persona inspector with a glossary-block preview that's byte-equivalent to the pipeline's system-prompt addendum. |

**Local-first.** HTMX is vendored at `src/ainemo/app/static/htmx.min.js` (no CDN). Single-user-localhost by default — no auth, no telemetry, no phone-home. Multi-user / basic-auth deferred to a later cycle. CSRF wiring lands alongside that auth surface.

The UI is **additive** — every CLI surface keeps working unchanged. UI writes go through the same `Termbase` / `TranslationMemory` / `ProviderRouter` / `ImportSkipStore` Protocols the CLI uses, so a candidate accepted via `nemo termbase promote --review` and the same candidate accepted via the UI produce byte-identical termbase rows.

See [`docs/reviewer-ui.md`](docs/reviewer-ui.md) for the full view-by-view tour, security model, and architecture; [`docs/qa-layer.md`](docs/qa-layer.md) for confidence-signal weights, back-translation procedure, and the cost-trade-off framing.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy src/ainemo
pytest --cov
```

### Project layout (post-cycle-2)

```
src/ainemo/
├── core/
│   ├── segment.py          # Segment, Placeholder, TranslatedSegment
│   ├── icu.py              # ICU MessageFormat parser
│   ├── adapters/           # JavaProperties, I18NextJson, GettextPo, Xliff
│   ├── tm/                 # SqliteTranslationMemory + base Protocol
│   ├── validators/         # placeholder, ICU, length, forbidden
│   └── pipeline.py         # TranslationPipeline orchestrator
├── providers/
│   ├── base.py             # Provider Protocol + ProviderResult
│   ├── router.py           # ProviderRouter — cost/latency-tracked façade
│   ├── _ids.py             # PROVIDER_ID_* constants
│   ├── _usage_log.py       # ~/.ainemo/usage.jsonl writer + stats
│   ├── _retry.py           # with_retry exponential backoff
│   ├── nllb/               # facebook/nllb-200-distilled-600M
│   ├── opus/               # Helsinki-NLP OPUS-MT (per-pair)
│   ├── openai/             # gpt-4o-2024-11-20 (default)
│   ├── anthropic/          # claude-sonnet-4-5-20250929 (default)
│   └── ollama/             # llama3.2 (default), local HTTP
└── cli/
    ├── commands.py         # translate / tm / validate / provider
    └── daemon.py           # nemo daemon — JSON-over-stdio
gradle-plugin/              # com.egoge.ai.nemo.translate Kotlin plugin
├── src/main/kotlin/...     # AiNemoTranslatePlugin, TranslateBundlesTask, DaemonClient
└── src/{test,functionalTest}/  # JUnit5 + Gradle TestKit
tests/
├── unit/                   # fast, isolated (cycle-2: 371 cases)
├── e2e/                    # full pipeline against real bundle fixtures
└── benchmarks/             # opt-in throughput / cost benchmarks (`pytest -m benchmark`)
docs/                       # adapters, TM, validators, providers, gradle-plugin
specs/                      # SDD + Shape-Up artifacts (pitches, ROADMAP, retros, cooldown reports)
scratch/                    # experimental scripts kept for reference; not run by pytest
```

## Spec-Driven Shape-Up

Development cadence is documented in [`specs/README.md`](specs/README.md). Each cycle gets a pitch under `specs/pitches/<id>/`. Currently:

| Cycle | Pitch | Status |
|---|---|---|
| 0 | [Rebrand & Stabilize](specs/pitches/0000-rebrand-stabilize/pitch.md) | shipped — see [retro](specs/retros/cycle-0.md) |
| 1 | [Foundation: Adapters + TM + Validators](specs/pitches/0001-foundation/pitch.md) | shipped — adapters + TM + validators + pipeline + CLI all in `src/ainemo/core/` |
| 2 | [Provider Abstraction + Gradle Plugin](specs/pitches/0002-providers-gradle/pitch.md) | shipped — see [retro](specs/retros/cycle-2.md) and [cooldown report](specs/retros/cooldown-after-02.md) |
| 3 | [Concept-Oriented Termbase via Kuzu](specs/pitches/0003-kuzu-termbase/pitch.md) | shipped — see [retro](specs/retros/cycle-3.md) and [cooldown report](specs/retros/cooldown-after-03.md) |
| 4 | [Pluggable Termbase Importer Pipeline](specs/pitches/0004-termbase-importer-pipeline/pitch.md) | shipped — see [cooldown report](specs/retros/cooldown-after-04.md) |
| 5 | [Reviewer Web UI + QA Layer](specs/pitches/0005-reviewer-ui-qa-layer/pitch.md) | closing — all seven scopes done; cooldown retro pending |

Future cycles (multi-platform expansion — Maven plugin, npm/Vite plugin, `.xcstrings` and Fluent adapters; pre-built domain packs; further reviewer-UI hardening like multi-user auth + CSRF) are sketched in [`specs/ROADMAP.md`](specs/ROADMAP.md) but re-shaped before each betting table.

## License

GPL-3.0-or-later (inherited from the prototype). Final license decision before public release: see [`specs/ROADMAP.md` § Risks](specs/ROADMAP.md#risks--open-questions-for-the-program).
