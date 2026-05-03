# AI-NEMO

**Networked Engine for Multilingual Ontologies** — knowledge-graph-grounded terminology and localization for software, with versioned domain packs and CC0/CC-BY ontology integrations. Distributed under the **egoge.com** namespace alongside [AI-ATLAS](https://github.com/gosha70/ai-atlas).

> **Status**: pre-release. Cycle 0 (rebrand & stabilize) **shipped** 2026-05-03 — see the [retrospective](specs/retros/cycle-0.md). Cycle 1 (foundation: adapters + translation memory + validators) **shipped** — four bundle adapters, SQLite TM with embedding-based fuzzy lookup, four validators, end-to-end pipeline, and the `nemo` CLI now ship. Cycle 2 (provider abstraction + Gradle plugin — bringing real-LLM translation online via daemon-mode IPC) is shaped and queued. See [`specs/ROADMAP.md`](specs/ROADMAP.md) for the full plan and [`specs/pitches/`](specs/pitches/) for individual cycles.

## What this is

AI-NEMO localizes software resource bundles (`.properties`, JSON, `.po`, XLIFF) using LLMs while:

- **Preserving placeholders.** `{0}`, `{name}`, ICU `{count, plural, ...}` are extracted, tokenized, translated around, and restored. Validators block any output that drops or mangles a placeholder.
- **Caching with a translation memory.** Re-running on an unchanged file is a no-op for the LLM — translations come from a SQLite-backed TM with embedding-based fuzzy lookup. Cycle 1 introduces this layer.
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

The `nemo` console script ships three subcommands as of cycle 1.

```bash
# Translate a source bundle to one or more target languages.
nemo translate \
  --from messages_en_US.properties \
  --to-langs de-DE,fr-FR,es-ES \
  --output-dir ./.ainemo/output \
  [--format java-properties|i18next-json|gettext-po|xliff-2] \
  [--tm-path ./.ainemo/tm.sqlite] \
  [--strict] \
  [--forbidden-term BrandX]…

# Inspect the local translation memory.
nemo tm stats --tm-path ./.ainemo/tm.sqlite

# Re-run cycle-1 validators on an existing source/target pair.
nemo validate \
  --source messages_en_US.properties \
  --target messages_de_DE.properties \
  --to-lang de-DE
```

`nemo translate` infers the bundle format from the source path's extension; pass `--format` to override. See [`docs/adapters.md`](docs/adapters.md) for the format → adapter table and per-format limitations.

> **Cycle-1 caveat**: the CLI ships with a `_NoOpProvider` that returns source text unchanged. The full pipeline runs end-to-end (parse → TM → validators → serialize) on real files and surfaces TM cache hits on second runs, but real-LLM translation against NLLB/OpenAI/Anthropic/Ollama lands in cycle 2 with the provider router and `nemo daemon`. Use cycle 1 to validate the plumbing on your bundles; wait for cycle 2 to translate against a live model.

### Flask app (admin / reviewer surface)

```bash
python -m ainemo.app.translator_app --port 5001
```

Reads `src/ainemo/config/translation_config.json` for the source/target language list and glossary. The app exposes `POST /translate`:

```bash
curl -X POST http://localhost:5001/translate \
  -H "Content-Type: application/json" \
  -d '{
    "messages": ["Hello world!", "This is a test text."],
    "to_languages": ["fr_FR", "iw"]
  }'
```

CLI flags accepted by `translator_app`:

| Flag | Description | Default |
|---|---|---|
| `--port` | HTTP port for the Flask app | `5001` |
| `--from_lang` | BCP-47 source language | `en_US` |
| `--to_langs` | Space-separated list of target languages (defaults to all supported except source) | `None` |
| `--model_name` | Translation backend: `nllb`, `opus`, `openai` | `nllb` |

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

Cycle 1 expands format coverage (i18next JSON, gettext `.po`, XLIFF 2.0) on top of the existing `.properties` support.

## Translation models

| Backend | Type | Notes |
|---|---|---|
| **NLLB-200** | Local (Facebook) | Default; broadest language coverage. See [the NLLB README](https://github.com/facebookresearch/flores/blob/main/flores200/README.md#languages-in-flores-200). |
| **OPUS / Marian** | Local (Helsinki-NLP) | Strong on European languages; weaker on Thai, Turkish, etc. |
| **OpenAI** | Managed | Calls `https://api.openai.com/v1/chat/completions`. Set `OPENAI_API_KEY` in the environment. |

Cycle 1's `Provider` Protocol is the minimum surface (`translate(segment, target_lang) -> str`) — concrete backends still go through the legacy `TranslatorModel` ABC alongside it. Cycle 2 finalizes the Protocol with cost + latency tracking, retry + backoff, and a `ProviderRouter` that records every call to `~/.ainemo/usage.jsonl`. Anthropic Claude and Ollama backends land in cycle 2 as well.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy src/ainemo
pytest --cov
```

### Project layout (post-cycle-1)

```
src/ainemo/
├── core/
│   ├── segment.py          # Segment, Placeholder, TranslatedSegment
│   ├── icu.py              # ICU MessageFormat parser
│   ├── adapters/           # JavaProperties, I18NextJson, GettextPo, Xliff
│   ├── tm/                 # SqliteTranslationMemory + base Protocol
│   ├── validators/         # placeholder, ICU, length, forbidden
│   └── pipeline.py         # TranslationPipeline orchestrator
├── providers/              # cycle-1 Provider Protocol + legacy ABC; cycle 2 adds router + Anthropic + Ollama
├── cli/                    # `nemo` translate / tm / validate subcommands
├── app/                    # Flask reviewer + admin (cycle 5 expands)
├── config/                 # configuration loaders, persona templates
├── utils/                  # git inspection, logging setup
└── _legacy/                # pre-cycle-0 data modules — DELETED in cycle 2 cooldown
tests/
├── unit/                   # fast, isolated (~210 cases as of cycle 1)
├── e2e/                    # full pipeline against real bundle fixtures
└── benchmarks/             # opt-in TM throughput benchmarks (`pytest -m benchmark`)
docs/                       # adapter, TM, validator references
specs/                      # SDD + Shape-Up artifacts (pitches, ROADMAP, retros, ADRs)
scratch/                    # experimental scripts kept for reference; not run by pytest
```

## Spec-Driven Shape-Up

Development cadence is documented in [`specs/README.md`](specs/README.md). Each cycle gets a pitch under `specs/pitches/<id>/`. Currently:

| Cycle | Pitch | Status |
|---|---|---|
| 0 | [Rebrand & Stabilize](specs/pitches/0000-rebrand-stabilize/pitch.md) | shipped — see [retro](specs/retros/cycle-0.md) |
| 1 | [Foundation: Adapters + TM + Validators](specs/pitches/0001-foundation/pitch.md) | shipped — adapters + TM + validators + pipeline + CLI all in `src/ainemo/core/` |
| 2 | [Provider Abstraction + Gradle Plugin](specs/pitches/0002-providers-gradle/pitch.md) | shaped (next bet) |

Future cycles (Kuzu termbase, domain packs, reviewer UI, multi-platform expansion) are sketched in [`specs/ROADMAP.md`](specs/ROADMAP.md) but re-shaped before each betting table.

## License

GPL-3.0-or-later (inherited from the prototype). Final license decision before public release: see [`specs/ROADMAP.md` § Risks](specs/ROADMAP.md#risks--open-questions-for-the-program).

## Legacy invocations

The pre-cycle-0 prototype documented these CLI entry points. They were renamed during cycle 0's reorganization; calls to the old paths will fail with `ModuleNotFoundError`. New paths:

| Old | New |
|---|---|
| `python -m cli.resource_bundle_generator --from_file ... --to_langs ...` | `python -m ainemo.cli.resource_bundle_generator --from_file ... --to_langs ...` |
| `python -m cli.resource_bundle_git --repo_path ... --model_name nllb --to_lang iw` | `python -m ainemo.cli.resource_bundle_git --repo_path ... --model_name nllb --to_lang iw` |
| `python -m app.translator_app` | `python -m ainemo.app.translator_app` |

Cycle 1 ships `nemo translate` as the going-forward CLI (see § Usage). The legacy `python -m ainemo.cli.resource_bundle_*` invocations still work for backward compat through cycle 2; the cycle-0 deprecation shims at the repository root (`languages.py`, `translation.py`, `translation_request.py`, `translation_service.py`) delete during cycle 2's cooldown when the provider router migration is done.
