# AI-NEMO — Master Roadmap

> **Networked Engine for Multilingual Ontologies** — knowledge-graph-grounded terminology and localization for software, with versioned domain packs and CC0/CC-BY ontology integrations.

This document is the high-altitude view of where AI-NEMO is going. Pitches in `pitches/` are the betting-table-ready details. Anything in this roadmap beyond the next bet is provisional — Shape-Up does not do long-range commitments, only long-range *direction*.

## Strategic positioning

AI-NEMO occupies a gap that no current open-source project fills:

1. **LLM-based localization** of software resource bundles — competed on heavily, but commodity.
2. **Auto-built, concept-oriented termbase** — partially served by Weblate's OpenAI backend; nobody builds it incrementally from translation traffic.
3. **Knowledge-graph substrate for domain packs** — *unfilled in OSS*. This is the moat.
4. **Build-tool-native developer adoption** (Gradle first) — partially served by `io.github.philkes.auto-translation` (Android only).

The defensible product is the **intersection of all four**, plus a CC0/CC-BY-only ontology stack (Wikidata, EuroVoc, IATE, AGROVOC, MeSH-via-BioPortal, GeoNames, Schema.org, ISCO-08).

## Closest projects to differentiate against

| Project | Strength | Where AI-NEMO wins |
|---|---|---|
| Weblate + OpenAI backend | Mature TBX, large community, prompt-injects glossary | KG (not flat list), domain packs, build-tool-first not server-first |
| T-Ragx | RAG over TM + glossary, beat DeepL on JA→ZH | i18n format awareness, concept-oriented termbase, Gradle plugin |
| `io.github.philkes.auto-translation` Gradle plugin | Direct Gradle integration, multi-provider | JVM/Spring `.properties` (Android already covered there), termbase, multi-format core |

## North-star outcomes (12 months)

- AI-NEMO Gradle plugin in production use on at least one real OSS project.
- One distributed domain pack (`legal-en`) on Maven Central / PyPI, version-pinnable.
- TBX 3.0 round-trip parity with Weblate (so users can migrate without losing data).
- Concept-oriented termbase backed by Kuzu, with auto-promotion from translation memory.
- Public benchmark page comparing translation quality with/without termbase, with/without persona, on a real software-strings corpus.

## Cycle plan

Each cycle below is a single Shape-Up bet. Cycles 0–1 are committed; 2 is shaped-pending; 3 onward is provisional and will be re-shaped before betting.

| # | Title | Appetite | Status | Goal in one line |
|---|---|---|---|---|
| 0 | Rebrand & Stabilize | 2w | committed | Become AI-NEMO, fix audit bugs, set up CI. |
| 1 | Foundation: Adapters + TM + Validators | 6w | shaped | Multi-format bundles, SQLite TM with fuzzy match, ICU-aware validators. |
| 2 | Provider Abstraction + Gradle Plugin | 6w | stub | Pluggable LLM providers (Anthropic, Ollama added) + first Gradle plugin for JVM `.properties`. |
| 3 | Concept-Oriented Termbase via Kuzu | 6w | stub | Migrate flat termbase to Kuzu, TBX 3.0 I/O, persona system. |
| 4 | First Domain Pack: legal-en | 6w | stub | Pack format spec, IATE+EuroVoc-derived legal-en pack, Wikidata anchors. |
| 5 | Reviewer Web UI + QA Layer | 6w | stub | Auto-promotion review queue, confidence scoring, back-translation QA. |
| 6 | Multi-Platform Expansion | 6w | stub | Maven plugin, npm plugin, `.xcstrings` and Fluent adapters. |
| 7+ | Additional domain packs | recurring | future | medical-en (MeSH), aerospace-en, finance-en (IATE finance subset). |

## Cycle 0 — Rebrand & Stabilize (2 weeks)

**Pitch**: [pitches/0000-rebrand-stabilize.md](pitches/0000-rebrand-stabilize.md) *(to be drafted before this cycle starts — it's small enough that a one-pager will do).*

**Outcome**: A repo named `ai-nemo` with green CI, fixed audit bugs, reorganized package layout, and a README that reflects the new positioning. No new product capability.

**In scope**:
- Rename repo `resource-bundle-translator` → `ai-nemo` on GitHub. Set up redirects.
- Fix bugs from the audit: `translationss` typo ([translation_request.py:33](../translation_request.py)), duplicate `preserve_glossary_words()` ([models/marian_mt/marian_mt_model.py:217](../models/marian_mt/marian_mt_model.py)), `openaipw` → `openai` in `requirements.txt`, README port mismatch (5005 vs 5001).
- Replace `print()` with `logging` throughout.
- Reorganize: `core/`, `adapters/`, `providers/`, `cli/`, `app/`, `test/`. Old top-level modules become deprecation shims for one release, then delete.
- Pin Python ≥3.10 in `pyproject.toml`. Migrate from bare `requirements.txt`.
- GitHub Actions: lint (ruff), type-check (mypy), test (pytest). Block PRs on red CI.
- Update README with AI-NEMO positioning, north-star, and link to roadmap.

**No-gos**:
- No new translation features.
- No KG, no Kuzu, no domain packs.
- No new providers.
- No format adapters beyond `.properties`.

**Why now**: The audit found real bugs that block the OpenAI provider and crash the request envelope. These have to be fixed before any new pitch lands on top, or every later cycle inherits them.

## Cycle 1 — Foundation: Adapters + TM + Validators (6 weeks)

**Pitch**: [pitches/0001-foundation/pitch.md](pitches/0001-foundation/pitch.md) — fully shaped, ready for betting.

**Outcome**: AI-NEMO can translate four bundle formats (`.properties`, i18next JSON, gettext `.po`, XLIFF 2.0), preserves ICU MessageFormat correctly, caches results in a SQLite-backed translation memory with fuzzy match, and validates every output against placeholder/ICU/length rules.

**Why this is cycle 1**: every later capability (Gradle plugin, KG termbase, domain packs) builds on the bundle adapter interface and the TM. Get the contracts right here or pay forever.

## Cycle 2 — Provider Abstraction + Gradle Plugin (6 weeks)

**Provisional outcome**: Clean `Provider` interface (NLLB, OpenAI, Anthropic Claude, Ollama). Cost & latency tracking per call. Caching layer. First Gradle plugin shipping to plugin portal as `io.aineмo.translate` (or similar — namespace TBD), targeting JVM `messages_*.properties` and Spring resource bundles.

**Why this order**: the Gradle plugin needs the provider abstraction to be useful (an Anthropic-only or Ollama-only plugin is a non-starter for enterprise users). Cycle 1's daemon-mode IPC enables the plugin to delegate without re-implementing core logic.

**Likely no-gos**: Maven plugin, npm plugin, Android `strings.xml` (PhilKes already owns that), web UI.

## Cycle 3 — Concept-Oriented Termbase via Kuzu (6 weeks)

**Provisional outcome**: Flat YAML termbase replaced by Kuzu. Schema includes `Concept`, `Term`, `Domain`, `Persona`, `Segment`. TBX 3.0 (ISO 30042) round-trip import/export — must be lossless against Weblate's TBX exports. Persona system with three starter personas (`software-ui`, `formal`, `casual`). Auto-promotion from TM into termbase based on frequency + consistency thresholds, gated behind a CLI review command.

**Why this is the moat-builder**: this is where AI-NEMO stops being "yet another LLM i18n tool" and becomes a terminology platform. Without this cycle, the differentiation pitch falls apart.

**Likely rabbit holes to avoid**: building a graph query DSL on top of Cypher; modeling every TBX-3 corner case (we support a documented subset); building the reviewer UI here (that's cycle 5).

## Cycle 4 — First Domain Pack: legal-en (6 weeks)

**Provisional outcome**: Domain pack format spec (versioned artifact, distributable via Maven Central + PyPI). One real pack: `legal-en` derived from IATE legal subset + EuroVoc legal branch, ~2k concepts, with Wikidata QID anchors where available. Pack loader with version resolution. CLI: `nemo pack install legal-en@1.0`.

**Why legal first**: IATE + EuroVoc have the cleanest open licensing and the most volume. Legal terminology is also the domain where bad translations have the highest cost — a compelling demo.

**Likely no-gos**: medical, aerospace, finance packs (those are cycle 7+); a pack registry server (use Maven Central / PyPI directly).

## Cycle 5 — Reviewer Web UI + QA Layer (6 weeks)

**Provisional outcome**: Minimal Flask + HTMX (or React) UI for: (a) approving auto-promotion candidates, (b) curating personas, (c) reviewing low-confidence segments, (d) seeing translation provenance (which model, which persona, which termbase entries fired). Confidence scoring per segment. Back-translation QA pass with a different provider for high-stakes domains.

**Why now and not earlier**: the UI is only useful once there's enough TM + termbase + provider data to curate. Building it before cycle 3 = building a UI for a flat list, which doesn't justify the surface area.

## Cycle 6 — Multi-Platform Expansion (6 weeks)

**Provisional outcome**: Maven plugin (`nemo-maven-plugin`). npm plugin / Vite plugin for the i18next ecosystem. Apple `.xcstrings` adapter. Rust Fluent (`.ftl`) adapter. The core daemon + IPC stays the same; these are thin wrappers that route work into it.

**Why last**: each plugin is straightforward once the core is solid. Doing them earlier inflates surface area before the core differentiation is proven.

## Cycle 7+ — Domain pack expansion (recurring)

Each pack is its own pitch. Order driven by user demand and license cleanliness:

- `medical-en` (MeSH via BioPortal RDF — license OK; UMLS is **out** for redistribution)
- `aerospace-en` (sources TBD — possibly NASA STI thesaurus, ESA terms)
- `finance-en` (IATE finance subset)
- `agriculture-en` (AGROVOC — cleanest RDF licensing of any anchor)
- `tech-en` (Schema.org + Wikidata software entities)

Packs are content work, not engineering work. Once the format is locked in cycle 4, new packs should fit a 2-week appetite each.

## Out of scope for the foreseeable future

These are real possibilities but not on the current roadmap. Listing them here so they can be deflected when proposed:

- SaaS / hosted multi-tenant version. AI-NEMO is local-first, period.
- Translation of long-form content (documentation, articles). Stay focused on software resource bundles.
- Voice / audio translation.
- Fine-tuning custom models. Provider abstraction handles this from outside (use Ollama with a custom checkpoint).
- Real-time translation API for production traffic. Wrong shape; this is a build-time tool.
- Mobile apps (iOS/Android client). Out of scope; the Apple `.xcstrings` adapter is a *build-time* feature.

## Risks & open questions for the program

These are bigger than any one cycle and need answers before they bite:

1. **License of generated translations**. If the LLM provider is OpenAI/Anthropic, who owns the output? Document policy clearly in the README. Recommendation: AI-NEMO ships under permissive license (MIT or Apache-2.0); generated translations inherit the user's project license; provider TOS pass through.
2. **Reproducibility**. LLM outputs vary run-to-run. The TM cache makes this mostly moot for re-runs, but the *first* translation is non-deterministic. Decide: do we pin a `temperature: 0` policy for all providers? Probably yes.
3. **Test corpus**. We need a public benchmark — likely a curated subset of real OSS resource bundles (e.g., IntelliJ Community, JetBrains plugins, Spring Boot demos). Build during cycle 1.
4. **Naming collisions**. Confirm `ai-nemo` is free across GitHub org, npm, PyPI, Maven Central group, Gradle plugin portal, ai-nemo.dev, before cycle 0 commits to the name.
5. **Distribution of domain packs that derive from IATE/EuroVoc**. Confirm the EU re-use license permits redistribution as a transformed artifact (TBX subset). Almost certainly yes, but document the attribution chain.

## How this document evolves

- After every cycle, a one-paragraph **Outcomes** entry is added under that cycle's section: what shipped, what was scope-hammered, what was learned.
- The next 1–2 cycles' provisional plans are re-validated during cooldown. Order may swap; nothing is committed until the betting table.
- Domain pack pitches are added as they're shaped, not pre-planned in detail.
