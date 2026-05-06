# Termbase

Cycle-3 ships the **concept-oriented termbase** — AI-NEMO's moat. Where cycle 1 had a flat list of forbidden terms supplied per-CLI-run, cycle 3 introduces a graph-shaped store of *concepts* anchored to multilingual *terms*, taxonomized by *domain*, and selectable by *persona*. The pipeline (cycle-3 S6) consults the termbase on every TM-miss segment, builds a glossary block, and injects it into the provider's system prompt alongside the persona's prompt addendum.

The termbase is the substrate cycle 4's domain packs (`legal-en`, `medical-en`, ...) plug into and the cycle-5 reviewer UI curates. Without it, every later north-star outcome of the project falls apart — see `specs/ROADMAP.md` § Strategic positioning.

## Concept model

```
(Concept {concept_id, qid?, definition?, created_at})
   │
   ├─[:HAS_TERM]──► (Term {term_id, lang, surface, register?, part_of_speech?, source})
   ├─[:IN_DOMAIN]──► (Domain {domain_id, parent_id?, name})
   └─[:DERIVED_FROM_SEGMENT]──► (Segment {fingerprint})

(Persona {persona_id, domain_id?, name, register?, forbidden_terms_json,
          prompt_addendum, style_guide_url?, glossary_overrides_json})
```

- **Concept** — language-neutral anchor. One identity per meaning. `qid` is the optional Wikidata anchor (cycle-4 packs populate it; cycle 3 leaves it nullable).
- **Term** — surface form of a concept in one language. A concept has many terms; a term belongs to exactly one concept.
- **Domain** — optional taxonomy node. Modeled as a tree via `parent_id`. A concept can be `IN_DOMAIN` of more than one domain (a `license` is both `legal` and `software`).
- **Persona** — configuration record. Selects which concepts/terms apply to which provider call (`prompt_addendum` + optional `domain_id` + optional `glossary_overrides`). See [`docs/personas.md`](personas.md).
- **Segment** — minimal stub keyed on the cycle-1 TM `fingerprint`. The cycle-1 SQLite TM owns the real segment data; the graph just stores the fingerprint so auto-promoted concepts retain provenance.

## Storage layout

```
.ainemo/
├── tm.sqlite                 # cycle-1 translation memory (segment-keyed)
├── termbase.kuzu/            # cycle-3 termbase (Kuzu, directory-shaped DB)
└── usage.jsonl               # cycle-2 per-call usage log
```

`.ainemo/` is in `.gitignore` from cycle 0. Per AGENTS.md § Translation-Domain Conventions, **the termbase is local-by-default**; teams that want shared terminology distribute it via TBX export/import (see below) or via cycle-4 domain packs, not by committing the Kuzu directory.

The Kuzu directory is opaque — back it up wholesale rather than editing files inside.

## Protocol surface

`core/` consumers depend only on the `Termbase` Protocol; concrete backends live in their own subpackages. Cycle 3 ships `KuzuTermbase` as the only impl; cycle 5+ may add an in-memory `MemoryTermbase` test double.

```python
from ainemo.core.termbase.base import (
    Concept, ConceptEntry, ConceptHit, Domain, Persona,
    Term, Termbase, TermbaseStats,
)
```

Read surface:

```python
def lookup_concepts_for(
    source_text: str, source_lang: str, target_lang: str,
    domain_id: str | None = None, max_hits: int = 16,
) -> tuple[ConceptHit, ...]: ...

def iter_concept_entries(
    domain_id: str | None = None,
) -> Iterator[ConceptEntry]: ...

def get_persona(persona_id: str) -> Persona | None: ...
def list_personas() -> tuple[Persona, ...]: ...
def stats() -> TermbaseStats: ...
```

Write surface:

```python
def add_concept(concept: Concept, terms: Sequence[Term]) -> None: ...
def add_domain(domain: Domain) -> None: ...
def attach_concept_to_domain(concept_id: str, domain_id: str) -> None: ...
def add_persona(persona: Persona) -> None: ...
```

All writes are upserts on the entity's PK, so re-adding the same `Concept` / `Term` / `Domain` / `Persona` refreshes properties without duplicating rows. `add_concept` validates every term's `concept_id` *before* the first Kuzu write so a rejected call leaves zero partial state — Kuzu's embedded driver does not expose multi-statement transactions, so atomicity comes from input validation rather than rollback.

## `nemo termbase` CLI

Cycle-3 S5 ships five sub-subcommands. All accept `--termbase-path` (default `.ainemo/termbase.kuzu`).

| Command | What it does |
|---|---|
| `nemo termbase init` | Create a fresh Kuzu termbase + sync the three starter personas (`software-ui`, `formal`, `casual`). Idempotent. |
| `nemo termbase import <file.tbx>` | Import a TBX 3.0 file. Prints concept/term/domain counts and any skipped elements. |
| `nemo termbase export <file.tbx> [--domain-id DOM]` | Export to TBX 3.0. Output is byte-stable — re-export of an unchanged termbase produces identical bytes. |
| `nemo termbase promote --source-lang en --target-lang de` | Scan the TM for promotable n-grams and write accepted candidates as `Concept` + `Term` rows tagged `tm-promotion`. `--review` (default) walks each candidate y/n/q; `--accept-all` skips the prompt. |
| `nemo termbase stats` | Print concept / domain / persona counts + per-language term counts. |

Auto-promotion thresholds (resolved at /bet, 2026-05-05; tunable per run):

- `--min-frequency` (default `5`) — n-gram must appear in ≥ N distinct TM segments.
- `--min-consistency` (default `0.9`) — of those segments, ≥ this fraction must translate to the same target string.

Re-running `nemo termbase promote --accept-all` against unchanged TM data is idempotent: each candidate gets a stable content-addressed concept id (`tm-promo-<sha256[:16]>`) so the second run upserts onto the same row.

## TBX 3.0 (ISO 30042) interop

AI-NEMO reads and writes the *documented subset* of TBX 3.0 — the elements Weblate's "Export glossary as TBX" flow emits in practice. Anything outside that subset is recorded in `TbxImportReport.skipped_unsupported` so the cycle-3 retro can survey real exports for promote-to-supported candidates.

| TBX element | AI-NEMO mapping |
|---|---|
| `<conceptEntry id="...">` | `Concept` (id preserved) |
| `<descrip type="domain">` | `Domain` + `IN_DOMAIN` edge (multi-domain supported) |
| `<langSec xml:lang="...">` | Language scope for child terms |
| `<termSec>` | One `Term` per `<termSec>` |
| `<term>` | `Term.surface` |
| `<termNote type="partOfSpeech">` | `Term.part_of_speech` |
| `<termNote type="register">` | `Term.register` |
| `<definition>` | `Concept.definition` (first source-lang `<langSec>` wins) |

Anything else — `<xref>`, `<ref>`, `<transac>`, `<descrip type="context">`, `<termNote type="usageStatus">`, etc. — is recorded as `name[@type=...] @ /xpath` in `skipped_unsupported`. A Weblate-export round-trip should produce an empty tuple; the cycle-3 round-trip benchmark ([`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../tests/benchmarks/cycle-3-tbx-roundtrip.md)) is the manual procedure for asserting that against ≥ 3 real exports.

### Idempotent re-import

- `conceptEntry @id` is preserved when present (Weblate always writes it). Absent `@id` falls back to UUID4 — that path is non-idempotent and surfaces via `TbxImportReport.synthesized_id_count`.
- `termSec @id` is taken from the source when present; absent (Weblate's normal shape) falls back to a stable `(concept_id, lang, surface)` sha256 hash. Re-importing the same TBX upserts onto the same `term_id`.

### Deterministic export

The exporter writes byte-stable output across runs:

- Concepts ordered by `concept_id` ascending.
- `langSec` ordered by `xml:lang` ascending.
- Terms within a `langSec` ordered by `(surface, term_id)` ascending.
- `<descrip type="domain">` entries one per attached domain id, ascending.
- `<definition>` lands on the first `termSec` of the source-lang `langSec`.
- Optional fields (POS, register, definition) are omitted when None — never empty elements.

This means `nemo termbase import x.tbx && nemo termbase export y.tbx && nemo termbase import y.tbx && nemo termbase export z.tbx` produces `y.tbx` and `z.tbx` byte-identical for the cycle-3 Weblate-style fixtures we ship under `tests/fixtures/tbx/`. Parity against *real* Weblate exports is the cooldown manual-benchmark item — see [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../tests/benchmarks/cycle-3-tbx-roundtrip.md).

## Pipeline integration

When the pipeline is constructed with `termbase=` and/or `persona=`, every TM-miss segment goes through:

1. `termbase.lookup_concepts_for(source_text, source_lang, target_lang, domain_id=persona.domain_id)`
2. Hits formatted as a `Glossary (apply to the segment if relevant): - "src" → "tgt"` block
3. `persona.prompt_addendum` prepended to the glossary block
4. Combined string passed as `system_prompt_addendum` to the provider

LLM providers (OpenAI / Anthropic / Ollama) concatenate it onto their default system prompt. Seq2seq providers (NLLB / OPUS) accept-and-ignore — they have no system-prompt surface. `temperature=0` is preserved across the change (AGENTS.md § Architecture Rules: *Reproducibility by default*).

When `termbase=None` and `persona=None`, the pipeline behaves identically to cycles 1+2 — the cycle-1 e2e test passes byte-stable.

## Auto-promotion algorithm

`find_candidates(tm, source_lang, target_lang, ...)` two-pass aggregation:

1. **Bucket by segment fingerprint.** TM v2 stores multiple translations per segment (one row per `(provider, model)`). Iterating raw rows would double-count one source segment as if it were many. We bucket by fingerprint here.
2. **Reduce + aggregate.** Each bucket contributes ONE `(source_text, target)` observation, where `target` is the mode across that segment's provider/model rows. Then aggregate across segments to get per-n-gram `frequency` + `consistency`.

N-grams are whitespace-tokenized, length 1..4 by default (override via `n_range`), set-based per row (so `"foo foo"` contributes the n-gram `foo` once, not twice). Output sorted `(frequency desc, consistency desc, ngram asc)` — highest-signal candidates surface first in `--review`.

## See also

- [`docs/personas.md`](personas.md) — persona YAML schema, starter pack, authoring guide.
- [`tests/benchmarks/cycle-3-tbx-roundtrip.md`](../tests/benchmarks/cycle-3-tbx-roundtrip.md) — manual benchmark procedure for parity against real Weblate exports.
- [`specs/pitches/0003-kuzu-termbase/pitch.md`](../specs/pitches/0003-kuzu-termbase/pitch.md) — the cycle-3 Shape-Up pitch.
