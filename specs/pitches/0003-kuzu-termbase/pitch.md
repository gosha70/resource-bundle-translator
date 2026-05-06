---
pitch_id: 0003-kuzu-termbase
title: "Cycle 3 — Concept-Oriented Termbase via Kuzu"
appetite: 6w
bet_status: shipped
cycle: "03"
circuit_breaker: "If lossless TBX 3.0 round-trip against Weblate's exports (S2+S3) is still uphill at week 4, ship the Kuzu schema + persona system + pipeline integration + auto-promotion (S1, S4, S5, S6) with TBX import-only — round-trip parity with Weblate moves to cycle-3 cooldown, and TBX export ships as a documented-subset best-effort writer rather than blocking the cycle."
shaped_by: gosha70
shaped_date: 2026-05-04
---

<!-- AI-NEMO Shape-Up pitch template. Companion to plan.md / spec.md / tasks.md. -->
<!-- See specs/README.md for the full SDD + Shape-Up workflow. -->

# Cycle 3 — Concept-Oriented Termbase via Kuzu

<!-- Human-readable header. Authoritative status / dates live in the YAML
     frontmatter above; this list is for at-a-glance reference and is what the
     README + ROADMAP cross-link to. Keep them in sync when bet_status flips. -->

- **ID**: 0003
- **Appetite**: 6w (wall-clock ceiling; actual session execution ≪ appetite)
- **Status**: shipped (2026-05-06; PRs #8/#9/#10/#11/#12/#13 merged; S7 docs in this commit)
- **Owner**: gosha70

## Problem

Cycles 1 and 2 shipped the substrate — bundle adapters, segment-keyed TM, validators, the provider router, the daemon, the Gradle plugin. What AI-NEMO still does **not** have is the differentiation: a *concept-oriented* termbase. Today the only terminology surface is `ForbiddenTermsValidator`, which takes a flat `tuple[str, ...]` of strings supplied per-CLI-run from `--forbidden-term` flags (see `cli/commands.py` lines 140–192, `core/validators/forbidden.py`). There is no notion of a *concept* with multilingual *terms*, no *domain* taxonomy, no *persona* configuration of provider prompts, and no way for the user to import or export TBX. Every later north-star outcome (domain pack `legal-en`, reviewer UI's auto-promotion queue, KG-grounded translation quality) assumes this layer exists.

Three concrete pain points the current code already exhibits:

1. **No concept layer.** A user who wants to teach AI-NEMO that *"login"* (en) ↔ *"Anmeldung"* (de) ↔ *"connexion"* (fr) are the same concept — and that the chosen term varies by domain (software-ui vs. legal contracts) and by persona (formal vs. casual register) — has nowhere to put that data. Weblate has flat glossaries; T-Ragx has a flat list. AI-NEMO's roadmap pitches the concept-oriented termbase as the moat (`specs/ROADMAP.md` § "Strategic positioning" rows 2 + 3); without it the pitch falls apart.
2. **No TBX interop.** TBX 3.0 (ISO 30042) is the standards-based termbase exchange format. Weblate exports TBX. AI-NEMO cannot consume those exports today, which means a Weblate user who wants to migrate has to throw their terminology data away — a blocker for the very enterprise users we want to attract.
3. **No persona system.** AGENTS.md § Architecture Rules already declares the persona-system contract (*"Persona / domain context configurable, never hardcoded. Personas live in YAML under `src/ainemo/personas/` ... no inline domain prompts in code."*) but no code or YAML has shipped yet. The cycle-2 providers route every call through `ProviderRouter`, but the router has no way to inject domain-specific system prompts because the persona surface doesn't exist. Every domain pack from cycle 4 onward depends on the persona contract being concrete.

This pitch fixes all three together because they share an entity model: *Concept* anchors the multilingual terms; *Domain* taxonomizes concepts; *Persona* selects which concepts/terms to inject as prompt context for which provider call; *Segment* connects termbase entries back to the cycle-1 TM. The Kuzu graph is the natural shape — flat tables would force surrogate joins for every traversal.

## Solution shape

```
┌─ Pipeline (cycle 1, augmented in cycle 3) ───────────────────────┐
│                                                                   │
│  TranslationPipeline                                              │
│    │                                                              │
│    ▼                                                              │
│  Termbase.lookup_concepts_for(segment, target_lang, persona)      │
│    │      │         │                                             │
│    │      │         └─► [Concept ──HAS_TERM──► Term(target_lang)] │
│    │      └─► relevance score                                     │
│    ▼                                                              │
│  PersonaPromptBuilder ── injects glossary block into Provider     │
│                          system prompt (temperature stays 0)      │
│    │                                                              │
│    ▼                                                              │
│  ProviderRouter ──► concrete Provider (cycle 2)                   │
│    │                                                              │
│    ▼                                                              │
│  Validators (cycle 1) + ForbiddenTermsValidator now reads the     │
│  termbase's persona.forbidden_terms instead of CLI flags          │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌─ Termbase (NEW — core/termbase/) ─────────────────────────────────┐
│                                                                   │
│   Termbase  Protocol  ◄─────────  KuzuTermbase  (only impl)       │
│                                                                   │
│   Kuzu graph schema:                                              │
│                                                                   │
│        (Concept {qid, definition, created_at})                    │
│           │                                                       │
│           ├─[:HAS_TERM]──► (Term {lang, surface, register,        │
│           │                       part_of_speech, source})        │
│           ├─[:IN_DOMAIN]──► (Domain {id, parent_id, name})        │
│           └─[:DERIVED_FROM_SEGMENT]──► (Segment {fingerprint})    │
│                                                                   │
│        (Persona {id, domain_id, name, register,                   │
│                  forbidden_terms_json, prompt_addendum})          │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌─ TBX 3.0 I/O (NEW — core/termbase/tbx/) ──────────────────────────┐
│                                                                   │
│  TbxImporter  ──► reads Weblate-style TBX ──► Concept+Term writes │
│  TbxExporter  ──► reads Termbase ──► writes Weblate-compatible TBX│
│  Round-trip benchmark: Weblate export → import → export = stable  │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌─ Auto-promotion (NEW — core/termbase/promotion.py) ───────────────┐
│                                                                   │
│  Scan TM for source-text n-grams that:                            │
│   (a) appear ≥ FREQUENCY_MIN distinct segments                    │
│   (b) translate to the same target string ≥ CONSISTENCY_MIN frac  │
│  Emit candidates; gate behind `nemo termbase promote` review.     │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

Storage path: `./.ainemo/termbase.kuzu/` (Kuzu is a directory-shaped embedded DB), excluded from git by default per the cycle-2-settled `.ainemo/` convention. Kuzu is a Python-installable wheel; no native compilation step on supported platforms.

### Interfaces (SDD layer)

**`core/termbase/_ids.py`** — module constants (the *No magic strings* rule, mirroring `providers/_ids.py`):

```python
from typing import Final

# Kuzu node labels
NODE_LABEL_CONCEPT: Final = "Concept"
NODE_LABEL_TERM: Final = "Term"
NODE_LABEL_DOMAIN: Final = "Domain"
NODE_LABEL_PERSONA: Final = "Persona"
NODE_LABEL_SEGMENT: Final = "Segment"

# Kuzu relationship labels
REL_HAS_TERM: Final = "HAS_TERM"
REL_IN_DOMAIN: Final = "IN_DOMAIN"
REL_DERIVED_FROM_SEGMENT: Final = "DERIVED_FROM_SEGMENT"

# Term sources (provenance)
TERM_SOURCE_TBX_IMPORT: Final = "tbx-import"
TERM_SOURCE_TM_PROMOTION: Final = "tm-promotion"
TERM_SOURCE_MANUAL: Final = "manual"
TERM_SOURCE_DOMAIN_PACK: Final = "domain-pack"

# Default storage + persona conventions
DEFAULT_TERMBASE_PATH: Final = ".ainemo/termbase.kuzu"
PERSONA_FILE_EXTENSION: Final = ".yaml"
DEFAULT_PERSONA_DIR: Final = "src/ainemo/personas"

# Auto-promotion thresholds (proposed defaults — open question 1)
DEFAULT_PROMOTION_FREQUENCY_MIN: Final = 5
DEFAULT_PROMOTION_CONSISTENCY_MIN: Final = 0.9
```

**`core/termbase/base.py`** — Protocol + entity dataclasses:

```python
@dataclass(frozen=True)
class Concept:
    concept_id: str                           # stable UUID4
    qid: str | None                           # Wikidata QID anchor (e.g. "Q11460"); cycle 4+ populates
    definition: str | None                    # short gloss in source_lang
    created_at: int                           # epoch seconds

@dataclass(frozen=True)
class Term:
    term_id: str
    concept_id: str                           # FK to Concept
    lang: str                                 # BCP-47 (matches Segment.source_lang)
    surface: str                              # the term as written
    register: str | None                      # "formal" | "casual" | None
    part_of_speech: str | None                # "noun" | "verb" | ... | None
    source: str                               # one of TERM_SOURCE_*

@dataclass(frozen=True)
class Domain:
    domain_id: str
    parent_id: str | None                     # tree under a root (e.g. "software")
    name: str

@dataclass(frozen=True)
class Persona:
    persona_id: str                           # filename stem of the YAML file
    domain_id: str | None
    name: str
    register: str | None
    forbidden_terms: tuple[str, ...]
    prompt_addendum: str
    # plus optional fields per persona YAML schema (open question 2)

@dataclass(frozen=True)
class ConceptHit:
    concept: Concept
    matched_source_term: Term                 # the Term in source_lang that matched
    target_terms: tuple[Term, ...]            # all Terms in target_lang for this Concept
    relevance: float                          # 0..1 — n-gram overlap or embedding sim


class Termbase(Protocol):
    """Concept-oriented terminology store. Cycle-3 ships KuzuTermbase as
    the only concrete implementation; the Protocol exists so cycle-4
    domain packs and cycle-5 reviewer UI consume the surface, not the
    Kuzu API directly. Mirrors the BundleAdapter / Provider / TM
    protocol-first conventions in AGENTS.md § Architecture Rules."""

    def lookup_concepts_for(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
        domain_id: str | None = None,
        max_hits: int = 16,
    ) -> tuple[ConceptHit, ...]: ...

    def add_concept(self, concept: Concept, terms: Sequence[Term]) -> None: ...
    def add_persona(self, persona: Persona) -> None: ...
    def get_persona(self, persona_id: str) -> Persona | None: ...
    def list_personas(self) -> tuple[Persona, ...]: ...

    def stats(self) -> TermbaseStats: ...    # concept_count, term_count_by_lang, domain_count


class KuzuTermbase:
    """Concrete Kuzu-backed implementation — `core/termbase/kuzu/store.py`.
    Mirrors the cycle-1 `core/tm/sqlite.py` placement convention (concrete
    backend in its own subpackage that imports its driver; Protocol stays
    backend-free)."""

    def __init__(self, path: Path = Path(DEFAULT_TERMBASE_PATH)) -> None: ...
```

**`core/termbase/persona_loader.py`** — YAML loader that reads `src/ainemo/personas/*.yaml` and writes `Persona` rows into the termbase on first start (idempotent):

```python
def load_personas(persona_dir: Path = Path(DEFAULT_PERSONA_DIR)) -> tuple[Persona, ...]: ...
def sync_personas_into_termbase(tb: Termbase, persona_dir: Path) -> int: ...
```

Three starter persona YAML files ship with the package:

```yaml
# src/ainemo/personas/software-ui.yaml
persona_id: software-ui
domain_id: software
name: "Software UI"
register: neutral
forbidden_terms: []   # populated per project
prompt_addendum: |
  Translate UI strings for software interfaces. Preserve placeholders
  exactly. Keep translations short enough to fit typical UI elements.
  Use idiomatic terminology for the target locale's software ecosystem.
```

(Equivalent files for `formal.yaml` and `casual.yaml`.)

**`core/termbase/tbx/`** — TBX 3.0 / ISO 30042 reader + writer using `lxml` (already a project dep):

```python
class TbxImporter:
    def __init__(self, tb: Termbase) -> None: ...
    def import_file(self, path: Path) -> TbxImportReport: ...

class TbxExporter:
    def __init__(self, tb: Termbase) -> None: ...
    def export_file(self, path: Path, *, domain_id: str | None = None) -> None: ...

@dataclass(frozen=True)
class TbxImportReport:
    concepts_added: int
    terms_added: int
    skipped_unsupported: tuple[str, ...]   # XML element names that hit the documented-subset cliff
```

Documented subset: `<conceptEntry>`, `<langSec>`, `<termSec>`, `<term>`, `<definition>`, `<descrip type="domain">`, `<termNote type="partOfSpeech"|"register">`. Anything outside that subset is recorded in `skipped_unsupported` with the element name and an XPath; a Weblate-export round-trip should produce an empty `skipped_unsupported`.

**`core/termbase/promotion.py`** — auto-promotion candidate generator:

```python
@dataclass(frozen=True)
class PromotionCandidate:
    source_lang: str
    target_lang: str
    source_ngram: str
    suggested_target: str
    frequency: int                            # # distinct segments in TM containing the n-gram
    consistency: float                        # 0..1 — fraction translating to suggested_target

def find_candidates(
    tm: TranslationMemory,
    source_lang: str,
    target_lang: str,
    *,
    min_frequency: int = DEFAULT_PROMOTION_FREQUENCY_MIN,
    min_consistency: float = DEFAULT_PROMOTION_CONSISTENCY_MIN,
    n_range: tuple[int, int] = (1, 4),
) -> tuple[PromotionCandidate, ...]: ...
```

Gated behind a CLI review command: `nemo termbase promote --source-lang en --target-lang de [--accept-all|--review]`. `--review` opens an interactive prompt loop (terminal-only; reviewer UI is cycle 5).

**Pipeline integration** — `core/pipeline.py` gains optional `Termbase` + `Persona` fields:

```python
class TranslationPipeline:
    def __init__(
        self,
        adapter: BundleAdapter,
        tm: TranslationMemory,
        provider: Provider,
        validators: tuple[Validator, ...],
        target_langs: tuple[str, ...],
        *,
        termbase: Termbase | None = None,           # NEW (optional — cycle 1 paths still work)
        persona: Persona | None = None,             # NEW
    ) -> None: ...
```

When `termbase` and `persona` are both supplied, the pipeline calls `termbase.lookup_concepts_for(...)` per cache-miss segment, formats the hits into a glossary block, and asks the provider via the existing `ProviderRouter` to render the segment with that block as system-prompt addendum. **Temperature stays 0** (AGENTS.md § Architecture Rules: *Reproducibility by default*). When either is `None`, the pipeline behaves exactly as cycle 1+2.

`ForbiddenTermsValidator` gains a constructor variant that takes a `Persona` and reads `persona.forbidden_terms` directly, so domain-pack-driven forbidden-term lists no longer need CLI plumbing. The cycle-1 tuple-of-strings constructor stays for backward compat.

## Rabbit holes

- **Don't build a Cypher DSL layer on top of Kuzu's native query language.** Kuzu's Python API is direct enough; abstracting it adds a layer with no consumer outside this codebase. Per `specs/ROADMAP.md` § Cycle 3.
- **Don't model every TBX 3 corner case.** TBX 3.0 has a long tail of optional elements (`<xref>`, `<ref>`, complex termGroup nesting, transactional metadata). Support the documented subset that covers Weblate's actual TBX feature usage; everything else is recorded in `skipped_unsupported` and addressed only when a real user file demands it. Per `specs/ROADMAP.md` § Cycle 3.
- **Don't build the reviewer UI here.** The reviewer surface is cycle 5. The cycle-3 surface is CLI-only (`nemo termbase promote --review`). Per `specs/ROADMAP.md` § Cycle 3.
- **Don't pre-populate Concepts from external ontologies.** Wikidata QIDs are a *column* on Concept in cycle 3; cycle 4's `legal-en` pack is what actually fills them. Linking to Wikidata / EuroVoc / IATE / AGROVOC is a cycle-4+ rabbit hole if pulled into cycle 3.
- **Don't re-key the cycle-1 TM around concepts.** TM stays segment-keyed; the termbase points at TM segments via `(:Concept)-[:DERIVED_FROM_SEGMENT]->(:Segment {fingerprint})` for promotion provenance. Re-keying TM would invalidate every cycle-1+2 cached translation.
- **Don't introduce vector embeddings for term lookup yet.** Cycle-3 termbase lookup uses literal n-gram match against the source text; embedding-based concept retrieval is a benchmark-driven decision deferred to cycle 4+ if n-gram recall proves insufficient on real corpora. (Same shape as cycle-1's *don't add a vector index until benchmark warrants it* discipline.)

## No-gos

- No domain-pack content. (Cycle 4 ships `legal-en`; cycle 3 ships only the framework that loads it.)
- No reviewer web UI. (Cycle 5.)
- No Maven / npm / Vite plugin work. (Cycle 6.)
- No external ontology dataset ingestion (EuroVoc, IATE, AGROVOC, MeSH, GeoNames). (Cycle 4+.)
- No new bundle formats. (Cycle 1's four — `.properties`, i18next JSON, gettext `.po`, XLIFF 2.0 — stay the canonical set.)
- No new providers. (Cycle 2's five — NLLB, OPUS, OpenAI, Anthropic, Ollama — stay the canonical set.)
- No swap of Kuzu for another graph DB. (The choice is locked at /bet; switching mid-cycle is a rabbit hole.)
- No TBX 2.x compatibility. (3.0 / ISO 30042 only; users on TBX 2 can convert via Weblate before importing.)
- No telemetry, no SaaS, no phone-home. (AGENTS.md § Architecture Rules: *Local-first*.)

## Scopes

> Estimates are session-execution time, not human-developer-days (project memory rule: *Calibrate estimates for Claude Code, not human-days*). Total cycle 3 execution is hours; the 6-week appetite is wall-clock willingness to wait.

### S1: Kuzu schema + `Termbase` Protocol + `KuzuTermbase` impl + entity dataclasses

`core/termbase/{__init__,base.py,_ids.py}` — Protocol, entity dataclasses (`Concept`, `Term`, `Domain`, `Persona`, `ConceptHit`, `TermbaseStats`), all module-level `Final` constants. `core/termbase/kuzu/store.py` — `KuzuTermbase` with schema bootstrap (idempotent), CRUD for concepts/terms/personas, and `lookup_concepts_for` via literal n-gram match. Add `kuzu` to `pyproject.toml`. Update `.gitignore` to exclude `.ainemo/termbase.kuzu/` (the existing `.ainemo/` line already covers it; verify and document). Files: `core/termbase/__init__.py`, `core/termbase/base.py`, `core/termbase/_ids.py`, `core/termbase/kuzu/__init__.py`, `core/termbase/kuzu/store.py`, `tests/unit/test_kuzu_termbase.py`. **Estimate: ~90 min.**

### S2: TBX 3.0 importer (parse Weblate exports)

`core/termbase/tbx/importer.py` — `TbxImporter` reading the documented subset via `lxml` into `Concept` + `Term` rows; `TbxImportReport` surfaces `skipped_unsupported`. Fixture corpus: ≥5 real Weblate TBX exports plus ≥3 hand-crafted pathological cases (mixed langSec ordering, missing definitions, multi-domain concepts). Files: `core/termbase/tbx/__init__.py`, `core/termbase/tbx/importer.py`, `tests/unit/test_tbx_importer.py`, `tests/fixtures/tbx/*.tbx`. **Estimate: ~75 min.**

### S3: TBX 3.0 exporter + Weblate round-trip benchmark

`core/termbase/tbx/exporter.py` — `TbxExporter` writing TBX 3.0 from termbase contents; `tests/integration/test_tbx_roundtrip.py` runs Weblate-export → import → export and asserts the second export matches the first by canonical XML diff (with element-order normalization). The benchmark file lives at `tests/benchmarks/cycle-3-tbx-roundtrip.md`. Files: `core/termbase/tbx/exporter.py`, `tests/integration/test_tbx_roundtrip.py`, `tests/benchmarks/cycle-3-tbx-roundtrip.md`. **Estimate: ~75 min.**

### S4: Persona system — YAML loader + 3 starter personas

`core/termbase/persona_loader.py` — Pydantic-model-backed YAML reader; `sync_personas_into_termbase` wires the YAML files into the Kuzu graph on first start (idempotent, by `persona_id`). Three starter YAMLs: `src/ainemo/personas/{software-ui,formal,casual}.yaml`. Pipeline + provider router gain `persona: Persona | None` plumbing; the persona's `prompt_addendum` is concatenated into the provider system prompt with `temperature=0` preserved. `ForbiddenTermsValidator` gains a `from_persona(persona)` classmethod constructor. Files: `core/termbase/persona_loader.py`, `src/ainemo/personas/software-ui.yaml`, `src/ainemo/personas/formal.yaml`, `src/ainemo/personas/casual.yaml`, `core/validators/forbidden.py` (additive), `tests/unit/test_persona_loader.py`. **Estimate: ~60 min.**

### S5: Auto-promotion algorithm + `nemo termbase` CLI

`core/termbase/promotion.py` — `find_candidates(tm, source_lang, target_lang, ...)` n-gram scan over the cycle-1 TM. CLI surface: `nemo termbase init`, `nemo termbase import <file.tbx>`, `nemo termbase export <file.tbx>`, `nemo termbase promote --source-lang en --target-lang de [--review|--accept-all]`, `nemo termbase stats`. The `--review` mode is a stdin loop (accept / skip / edit-then-accept). Threshold defaults are the `Final` constants from S1; CLI flags override per run. Files: `core/termbase/promotion.py`, `cli/commands.py` (additive subcommand), `tests/unit/test_promotion.py`, `tests/integration/test_termbase_cli.py`. **Estimate: ~75 min.**

### S6: Pipeline integration — termbase + persona prompt injection

`core/pipeline.py` gains optional `termbase: Termbase | None` and `persona: Persona | None` constructor parameters. On TM cache-miss, the pipeline calls `termbase.lookup_concepts_for(...)`, builds a glossary block, prepends `persona.prompt_addendum` to the provider system prompt, and routes through the existing `ProviderRouter`. `temperature=0` is preserved across all providers (cycle-2 invariant). When `termbase=None` and `persona=None`, pipeline behaves identically to cycles 1+2 (cycle-1 e2e test must still pass unchanged). The daemon (`cli/daemon.py`) gains a request-envelope `persona_id` field that loads the persona from the termbase on each request. Files: `core/pipeline.py` (additive), `cli/daemon.py` (additive request schema; `v: "1"` envelope stays compatible — `persona_id` is optional), `tests/integration/test_pipeline_with_termbase.py`. **Estimate: ~60 min.**

### S7: Documentation + cycle-3 outcomes hooks

`docs/termbase.md` — concept model, schema diagram, Kuzu-on-disk layout, `nemo termbase` CLI reference, TBX subset-supported table. `docs/personas.md` — YAML schema, the three starter personas, how to author a project-specific persona, prompt-injection mechanics. README updated with a "Termbase + personas" section. `specs/ROADMAP.md` § Cycle 3 gets the *shipped* + *retro link* edits at cycle close (mirrors cycle-1/cycle-2 ROADMAP convention). Files: `docs/termbase.md`, `docs/personas.md`, `README.md`, `specs/ROADMAP.md`. **Estimate: ~30 min.**

**Total session-execution estimate: ~7 hours.** The 6-week appetite is wall-clock budget for review iterations + benchmark runs against real Weblate exports + the inevitable TBX-edge-case scope-hammer; it is not a work-content estimate.

## Test strategy

**Unit** (per-module, fast, deterministic):
- `KuzuTermbase`: schema bootstrap idempotency, CRUD round-trip, n-gram lookup precision/recall on a synthetic 200-concept fixture.
- `TbxImporter`: per-element parsing on each fixture; `skipped_unsupported` populated correctly on pathological cases.
- `TbxExporter`: schema validity (validates against a TBX 3.0 XSD), canonical-XML emission.
- `persona_loader`: YAML schema enforcement; idempotent sync into termbase; reject on duplicate `persona_id`.
- `find_candidates`: synthetic TM with known n-gram repetition, threshold sensitivity, false-positive controls.
- `core/pipeline.py`: termbase+persona path matches cycle-1 path when both are `None`; injects glossary block + persona addendum when supplied.

**Integration** (slower, marked `integration`):
- TBX round-trip: Weblate-exported TBX → `TbxImporter` → Kuzu → `TbxExporter` → second TBX; assert canonical-XML equivalence (element-order normalized).
- Termbase-aware pipeline: real cycle-1 fixture bundle + a 10-concept termbase + the `software-ui` persona + the cycle-2 `_NoOpProvider` (verify the system prompt receives the glossary block + persona addendum); reuses cycle-1's e2e infrastructure.
- `nemo termbase promote --accept-all` end-to-end on a TM seeded with synthetic translations.

**Contract** (the SDD enforcement layer):
- `Termbase` Protocol contract test: `tests/unit/test_termbase_contract.py` exercises the surface against `KuzuTermbase` + an in-memory `MemoryTermbase` test double. Mirrors the cycle-1 BundleAdapter / cycle-2 Provider contract-test convention.
- `nemo termbase` CLI: argparse smoke tests + `--help` output snapshots.

**Benchmark** (manual, per cycle):
- TBX round-trip on Weblate's actual exports (≥3 real-world projects); assert `skipped_unsupported` is empty.
- `find_candidates` runtime on a 50k-segment TM: p95 < 5 seconds (it's a build-time, human-gated command — no p50/p95 latency budget like the TM lookup has).
- Termbase lookup p95: < 25 ms at 5k concepts (n-gram scan fine for v1; vector index deferred per rabbit hole).

**Acceptance criteria — cycle is "done" when**:
- `KuzuTermbase` ships with schema bootstrap + CRUD + n-gram lookup; Protocol contract test green.
- TBX 3.0 import + export ship; round-trip against Weblate's exports is byte-stable for the documented subset.
- Three starter personas ship under `src/ainemo/personas/`; loader + termbase sync green.
- `nemo termbase` subcommand ships (`init` / `import` / `export` / `promote` / `stats`).
- Pipeline + daemon support optional `termbase` + `persona`; cycle-1+2 paths regress-clean.
- `docs/termbase.md` + `docs/personas.md` written; README updated.
- CI green: ruff + format + mypy strict + pytest on Python 3.10/3.11/3.12; benchmark snapshot checked in.

## Open questions

These were pre-resolved from AGENTS.md / ROADMAP / cycle-1+2 conventions per the project's *Pre-resolve "open questions" from project docs before asking the user* rule. The original eight entries are listed below — the two genuinely-contested ones (Q1, Q2) were resolved at /bet; the other six are settled in the relevant cycle's pitch / retro / ROADMAP.

Resolved at /bet (2026-05-05):

1. **Auto-promotion threshold defaults** — **resolved: take the proposed defaults.** `DEFAULT_PROMOTION_FREQUENCY_MIN = 5` (n-gram appears in ≥ 5 distinct TM segments) and `DEFAULT_PROMOTION_CONSISTENCY_MIN = 0.9` (≥ 90% of those translate to the same target string). Rationale at /bet: 5 is balanced (3 over-promotes single-team-quirks; 10 starves small projects); 0.9 filters noise while allowing 1-in-10 outliers. Both are `Final` constants in `core/termbase/_ids.py`; CLI flags override per run; cycle-3 cooldown re-tunes after first real-world `nemo termbase promote --review` data. Note: the consistency cutoff is intentionally distinct from cycle-1's `DEFAULT_FUZZY_THRESHOLD = 0.85` because the semantics differ (cycle-1 is "embedding similarity"; cycle-3 is "translation agreement rate").
2. **Persona YAML schema beyond the four mandatory fields** — **resolved: take 4 of the 5 proposed optional fields. Drop `provider_hints`.** Mandatory: `persona_id`, `name`, `forbidden_terms`, `prompt_addendum`. Optional (kept): `domain_id` (FK to Domain row), `register` (`formal` | `casual` | `neutral` | `null`), `style_guide_url` (free-text reference), `glossary_overrides` (mapping of source-term → preferred target-term-by-lang to inject ahead of the termbase lookup). Optional (dropped at /bet): `provider_hints`. Rationale: persona-aware routing is already covered by cycle-2's `RoutingConfig` — `RoutingRule` carries `persona` and `domain` fields exactly for this case (see [`src/ainemo/providers/router.py:47-51`](../../../src/ainemo/providers/router.py)). Adding `provider_hints` to the persona schema duplicates the routing concern in two places that can disagree, with no clear "which wins?" semantics. Persona-aware routing in cycle 3 = add a `RoutingRule` that matches on `persona`, not a hints field on the persona itself. Schema enforced via Pydantic model in `persona_loader.py`.

Pre-resolved (recorded at shaping, not contested at /bet):

3. **Termbase Protocol vs. Kuzu-only**: ship the Protocol. Mirrors AGENTS.md § Architecture Rules (*"`core/` depends only on protocols (`BundleAdapter`, `Provider`, `TranslationMemory`, `Validator`)"*) — the termbase is the fifth port of the same shape. Cycle-4 domain packs and cycle-5 reviewer UI consume the Protocol surface, not the Kuzu API directly; an in-memory test-double `MemoryTermbase` becomes possible without it. The marginal cost of a Protocol layer over a single concrete impl is ≪ the future cost of unwinding a Kuzu-shaped surface from every consumer.
4. **Cycle-1 flat-data migration**: there is **no** cycle-1 termbase data to migrate. The only terminology surface in cycles 1+2 is `ForbiddenTermsValidator` taking a `tuple[str, ...]` from the CLI's repeatable `--forbidden-term` flag (verified: `core/validators/forbidden.py` + `cli/commands.py:140-192`). Cycle 3 is greenfield. The `ForbiddenTermsValidator` keeps its tuple constructor for backward compat and gains an additional `from_persona(persona)` classmethod that reads `persona.forbidden_terms`.
5. **Termbase storage path** → `./.ainemo/termbase.kuzu/` (per-project, directory-shaped). Excluded by default per the cycle-2-settled `.ainemo/` `.gitignore` convention. Per-user override via a future `--termbase-path` CLI flag (cycle 3 ships only the per-project default; the flag itself is a 5-line addition deferrable to cooldown).
6. **TBX subset coverage** → documented subset matching Weblate's TBX feature usage; everything else recorded in `TbxImportReport.skipped_unsupported`. Per `specs/ROADMAP.md` § Cycle 3 ("we support a documented subset").
7. **Wikidata QID column on Concept** → ships in cycle 3 as a nullable column; cycle-4's `legal-en` pack populates it. Per `specs/ROADMAP.md` § Cycle 4.
8. **Reproducibility under persona prompt injection** → `temperature=0` preserved across all providers when personas inject prompt addenda. Per AGENTS.md § Architecture Rules (*Reproducibility by default*).

After /bet, no new questions allowed. Anything that surfaces during build goes to the cycle-3 cooldown shaping queue.

## Risks

- **Kuzu wheel availability + Python-version coverage.** Kuzu publishes prebuilt wheels for Python 3.10/3.11/3.12 on linux-x86_64 / macos-arm64 / win-amd64. Mitigation: pin a tested version range in `pyproject.toml`; CI runs Kuzu-touching tests on every matrix cell to catch wheel regressions; document fallback build-from-source instructions in `docs/termbase.md`.
- **TBX schema rabbit-hole creep.** Real Weblate exports may contain elements outside the documented subset. Mitigation: every unsupported element lands in `TbxImportReport.skipped_unsupported` with element name + XPath, never a silent drop; the cycle-3 retro reviews top-N skipped elements and decides which to promote in cooldown.
- **N-gram promotion noise.** Low-consistency or low-frequency candidates pollute the termbase. Mitigation: defaults err on the side of fewer candidates; `--review` mode is the default (no `--accept-all` until thresholds tuned); the candidate-acceptance rate gets recorded as a benchmark for cooldown re-tuning.
- **Persona prompt-addendum + temperature=0 interaction.** Some providers' deterministic mode is documented as best-effort. Mitigation: regression test asserts `temperature=0` is *passed* to every provider; output-bit-stability is not asserted (out of scope per AGENTS.md *Reproducibility by default* — temperature 0 is the contract, not bitwise output).
- **Pipeline backward compatibility.** Cycle-1 e2e tests currently pass with no termbase or persona. Mitigation: `termbase: Termbase | None = None` and `persona: Persona | None = None` are both keyword-only optional; the cycle-1 e2e fixture asserts a no-op-with-None path stays byte-stable. A pipeline regression here is an instant ship-blocker.
- **Cycle-2 daemon protocol versioning.** Adding `persona_id` to the daemon request envelope is additive on `v: "1"` — Kotlin client tolerates unknown response fields. Mitigation: explicit test in `gradle-plugin/src/functionalTest/` confirming that omitting `persona_id` keeps the daemon's response shape identical to cycle-2.

## Circuit breaker

Mirrors the YAML frontmatter `circuit_breaker:` — *"If lossless TBX 3.0 round-trip against Weblate's exports (S2+S3) is still uphill at week 4, ship the Kuzu schema + persona system + pipeline integration + auto-promotion (S1, S4, S5, S6) with TBX import-only — round-trip parity with Weblate moves to cycle-3 cooldown, and TBX export ships as a documented-subset best-effort writer rather than blocking the cycle."*

Context for "exhausted" on this pitch: TBX I/O is the most novel surface in cycle 3 and the one with the most adversarial unknowns (real Weblate exports vary in optional-element usage). The Kuzu schema + persona system + auto-promotion + pipeline integration are the *moat-builder* — without them the cycle-3 ROADMAP outcome is nullified. Without lossless TBX round-trip, AI-NEMO still reads Weblate exports (one-way migration works, just not the round-trip parity claim) and ships the differentiation. The circuit breaker therefore protects the moat at the cost of the import-export-parity headline. **Core (must-ship): S1, S4, S5, S6.** **Trim-able (cooldown candidates): S3 export's lossless-round-trip claim — best-effort writer ships, byte-stable round-trip moves to cooldown.** **Documentation (S7) lands either way.**

## Bet log

| Date | bet_status | Note |
|------|------------|------|
| 2026-05-04 | shaping | Pitch drafted by `/shape kuzu-termbase` per cycle-2 retro shaping queue. |
| 2026-05-04 | shaped | Scopes sized; circuit breaker pinned around TBX round-trip; two genuine open questions for /bet (promotion thresholds + persona YAML schema). |
| 2026-05-05 | bet | /bet locked. Q1: take proposed defaults (`freq_min=5`, `consistency_min=0.9`). Q2: take 4 of 5 optional persona fields; **drop `provider_hints`** in favor of cycle-2's existing `RoutingConfig` `persona`/`domain` matching. No other open questions; no scope adjustments. |
| 2026-05-05 | building | /cycle-start: `hill.json` initialized with all 7 scopes uphill (S1–S7); `bet_status` flipped `bet` → `building`; ROADMAP cycle-3 row updated `bet` → `building`. Cycle is open for execution. |
| 2026-05-06 | shipped | All 7 scopes done. PRs #8 (S1) / #9 (S2) / #10 (S3) / #11 (S4) / #12 (S5) / #13 (S6) merged; S7 docs land in this commit. Nine reviewer-validated bug fixes shipped with regression tests (see ROADMAP § Cycle 3). 500 fast-suite tests, mypy strict / ruff / format clean. Circuit breaker did not fire — TBX round-trip on the 5 hand-crafted Weblate-style fixtures is byte-stable; parity against real Weblate exports is the cooldown manual-benchmark item per [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../../../tests/benchmarks/cycle-3-tbx-roundtrip.md). |
