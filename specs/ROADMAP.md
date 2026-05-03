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

Each cycle below is a single Shape-Up bet. Cycles 0 and 1 are shipped; 2 is shaped and the next bet; 3 onward is provisional and will be re-shaped before betting.

| # | Title | Appetite | Status | Goal in one line |
|---|---|---|---|---|
| 0 | Rebrand & Stabilize | 2w | **shipped** (PR #2 merged 2026-05-03; retro: [`retros/cycle-0.md`](retros/cycle-0.md)) | Became AI-NEMO, fixed audit bugs, set up green CI matrix. |
| 1 | Foundation: Adapters + TM + Validators | 6w | **shipped** (216 tests; CLI ships with `_NoOpProvider` until cycle 2 wires the router) | Four bundle adapters, SQLite TM with embedding fuzzy match, four validators, end-to-end pipeline, `nemo` CLI. |
| 2 | Provider Abstraction + Gradle Plugin | 6w | **shaped (next bet)** | Pluggable LLM providers (Anthropic + Ollama added) + first Gradle plugin for JVM `.properties`. |
| 3 | Concept-Oriented Termbase via Kuzu | 6w | stub | Migrate flat termbase to Kuzu, TBX 3.0 I/O, persona system. |
| 4 | First Domain Pack: legal-en | 6w | stub | Pack format spec, IATE+EuroVoc-derived legal-en pack, Wikidata anchors. |
| 5 | Reviewer Web UI + QA Layer | 6w | stub | Auto-promotion review queue, confidence scoring, back-translation QA. |
| 6 | Multi-Platform Expansion | 6w | stub | Maven plugin, npm plugin, `.xcstrings` and Fluent adapters. |
| 7+ | Additional domain packs | recurring | future | medical-en (MeSH), aerospace-en, finance-en (IATE finance subset). |

## Cycle 0 — Rebrand & Stabilize (shipped)

**Pitch**: [pitches/0000-rebrand-stabilize/pitch.md](pitches/0000-rebrand-stabilize/pitch.md) — status `shipped`.
**Retro**: [retros/cycle-0.md](retros/cycle-0.md).
**Shipped**: 2026-05-03 via [PR #2](https://github.com/gosha70/resource-bundle-translator/pull/2), merge commit `a563dd5`.

All 7 scopes landed inside the 2-week appetite (actual session execution: hours). Two iterative review passes caught 5 P1 bugs before merge. Five durable feedback rules were added to project memory during the cycle (estimate calibration, doc pre-resolution, pitch-in-build-PR, no magic strings, SOLID/DRY).

**Outstanding action carried forward**: GitHub-side repo rename `resource-bundle-translator` → `ai-nemo` (deferred per pitch open question 4 — pair with the first AI-NEMO release tag).

## Cycle 1 — Foundation: Adapters + TM + Validators (shipped)

**Pitch**: [pitches/0001-foundation/pitch.md](pitches/0001-foundation/pitch.md) — status `shipped`.

All 12 scopes landed: Segment + ICU parser, BundleAdapter Protocol with four concrete adapters (Java properties, i18next JSON, gettext PO, XLIFF 2.0), SqliteTranslationMemory with exact + embedding-based fuzzy lookup, four validators (placeholder parity, ICU syntax, length budget, forbidden terms), TranslationPipeline orchestrator, `nemo` CLI (translate / tm stats / validate), e2e tests, benchmark harness, and per-component docs.

**Cycle-1 limitations carried forward** (intentional scope-hammers, see the pitch's Outcomes section for the rationale and pin tests):
- Gettext plural output is 2-form-only; languages with more plural categories (Russian/Polish/Arabic/Czech) need cycle 3+ for full N-form output. Serializer already passes through forms 2..N when supplied.
- XLIFF inline markup (`<mrk>`, `<ph>`, `<sc>`, `<ec>`) is dropped on parse — preserving it as XML strings produces silently-broken serialize output. Cycle 2+ rebuilds inline children as real XML nodes.
- The `nemo translate` CLI ships with a `_NoOpProvider` (returns source text unchanged). Real-LLM translation lands in cycle 2 with the provider router and `nemo daemon`.

**Why this was cycle 1**: every later capability (Gradle plugin, KG termbase, domain packs) builds on the bundle adapter interface and the TM. The contracts shipped here are the foundation everything else lands on.

## Cycle 2 — Provider Abstraction + Gradle Plugin (6 weeks)

**Pitch**: [pitches/0002-providers-gradle/pitch.md](pitches/0002-providers-gradle/pitch.md) — fully shaped, awaiting `/bet`.

**Outcome**: Clean `Provider` Protocol (NLLB, OPUS, OpenAI, **Anthropic Claude**, **Ollama**). Cost & latency tracking per call recorded to `~/.ainemo/usage.jsonl`. Daemon-mode IPC (`nemo daemon`) for build-tool integration. First Gradle plugin published as `com.egoge.ai.nemo.translate`, targeting JVM `messages_*.properties` and Spring resource bundles.

**Why this order**: the Gradle plugin needs the provider abstraction to be useful (an Anthropic-only or Ollama-only plugin is a non-starter for enterprise users). The router-level cache reuses cycle-1's TM table — no double-caching.

**Likely no-gos**: Maven plugin, npm plugin (cycle 6), Android `strings.xml` (PhilKes already owns that), web UI (cycle 5), `.xcstrings` / Fluent / `.resx`, KG / termbase work.

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
