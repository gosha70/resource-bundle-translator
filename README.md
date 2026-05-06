# AI-NEMO

**Networked Engine for Multilingual Ontologies** — knowledge-graph-grounded terminology and localization for software, with versioned domain packs and CC0/CC-BY ontology integrations. Distributed under the **egoge.com** namespace alongside [AI-ATLAS](https://github.com/gosha70/ai-atlas).

> **Status**: pre-release. Cycles 0–2 **shipped**. Cycle 0 (rebrand & stabilize) shipped 2026-05-03 — see the [retrospective](specs/retros/cycle-0.md). Cycle 1 (foundation: adapters + translation memory + validators) shipped 2026-05-03 — four bundle adapters, SQLite TM with embedding-based fuzzy lookup, four validators, end-to-end pipeline, and the `nemo` CLI. Cycle 2 (provider abstraction + Gradle plugin) shipped 2026-05-05 — `Provider` Protocol with NLLB / OPUS / OpenAI / **Anthropic Claude** / **Ollama** backends behind a cost/latency-tracked `ProviderRouter`, `~/.ainemo/usage.jsonl` UsageLog, `nemo daemon` JSON-over-stdio IPC, and the `com.egoge.ai.nemo.translate` Gradle plugin — see the [retrospective](specs/retros/cycle-2.md) and the [post-cycle cooldown report](specs/retros/cooldown-after-02.md). Cycle 3 (concept-oriented termbase via Kuzu) is the next ROADMAP bet. See [`specs/ROADMAP.md`](specs/ROADMAP.md) for the full plan and [`specs/pitches/`](specs/pitches/) for individual cycles.

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
| 3 | Concept-Oriented Termbase via Kuzu | next ROADMAP bet — pitch shaping during cooldown |

Future cycles (Kuzu termbase, domain packs, reviewer UI, multi-platform expansion) are sketched in [`specs/ROADMAP.md`](specs/ROADMAP.md) but re-shaped before each betting table.

## License

GPL-3.0-or-later (inherited from the prototype). Final license decision before public release: see [`specs/ROADMAP.md` § Risks](specs/ROADMAP.md#risks--open-questions-for-the-program).
