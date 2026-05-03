# Cycle 1 — Foundation: Adapters + Translation Memory + Validators

- **ID**: 0001
- **Appetite**: 6 weeks
- **Status**: shaped
- **Owner**: TBD

## Problem

Today AI-NEMO (post-rebrand) translates exactly one bundle format — Java `.properties` — and re-translates every string from scratch on every run. Every later differentiator on the roadmap (Gradle plugin, Kuzu termbase, domain packs, reviewer UI) assumes a stable bundle-format abstraction and a translation memory underneath. We can't bolt those on later without paying a refactor tax that grows with each cycle.

Three concrete pain points the current code already exhibits:

1. **Format lock-in.** The CLI hard-codes `.properties` parsing in two places ([cli/resource_bundle_generator.py](../../cli/resource_bundle_generator.py), [cli/resource_bundle_git.py](../../cli/resource_bundle_git.py)). A user who wants to translate `messages.json` (i18next) or `Localizable.strings` (Apple) cannot use the tool at all.
2. **No memory.** Re-running the CLI on an unchanged file calls the LLM for every key, every time. For a 500-key bundle × 20 languages, that's 10,000 calls per re-run — each costing tokens or local GPU time. Users will not adopt a tool that wastes their model budget.
3. **No validation.** If the LLM drops a `{0}` placeholder or breaks ICU `{count, plural, ...}` syntax, the broken translation lands in the output file and only fails at app runtime — sometimes in production. Industry-standard CAT tools catch these at translate-time.

This pitch fixes all three together because they share a contract: the *segment* (a unit of source text + its placeholders + its metadata) is the data type that the adapters produce, the TM caches, the providers translate, and the validators check.

## Solution shape

```
┌─ Bundle file (any format) ─────────────────────────────────┐
│  parsed by                                                 │
│      ↓                                                     │
│  BundleAdapter ──► [Segment, Segment, …]                   │
│                       │                                    │
│                       ▼                                    │
│              ┌─ TranslationMemory ────────────────┐        │
│              │  exact match? → return cached      │        │
│              │  fuzzy match? → return + mark      │        │
│              │  miss        → forward to provider │        │
│              └────────────────────────────────────┘        │
│                       │                                    │
│                       ▼                                    │
│                  Provider (existing NLLB/OPUS/OpenAI)      │
│                       │                                    │
│                       ▼                                    │
│              ┌─ Validators ─────────────────────────┐      │
│              │  placeholder parity                  │      │
│              │  ICU syntax                          │      │
│              │  length budget                       │      │
│              │  forbidden terms                     │      │
│              └──────────────────────────────────────┘      │
│                       │                                    │
│                       ▼                                    │
│              TM stores (source, target, lang, model)       │
│                       │                                    │
│                       ▼                                    │
│              BundleAdapter.serialize → file                │
└────────────────────────────────────────────────────────────┘
```

`Segment` is the universal currency. Adapters convert files ↔ segments. TM, providers, and validators all operate on segments. Adding a new format = writing a new adapter, no other changes.

### Interfaces (SDD layer)

**`core/segment.py`**

```python
@dataclass(frozen=True)
class Segment:
    key: str                       # bundle key, e.g. "login.button.submit"
    source_text: str               # source-language text
    source_lang: str               # BCP-47, e.g. "en-US"
    placeholders: list[Placeholder]  # parsed positional/named/ICU placeholders
    metadata: dict[str, str] = field(default_factory=dict)  # comments, max-length, context

    @property
    def fingerprint(self) -> str:
        """Stable hash for TM keying. Includes source_text + source_lang + placeholder shape."""

@dataclass(frozen=True)
class Placeholder:
    kind: Literal["positional", "named", "icu_plural", "icu_select", "icu_selectordinal"]
    raw: str                       # e.g. "{0}", "{name}", "{count, plural, one {...} other {...}}"
    span: tuple[int, int]          # offsets in source_text

@dataclass(frozen=True)
class TranslatedSegment:
    segment: Segment
    target_lang: str
    target_text: str
    provider: str
    confidence: float | None
    source: Literal["exact_tm", "fuzzy_tm", "provider", "manual"]
```

**`core/adapters/base.py`**

```python
class BundleAdapter(Protocol):
    format_id: ClassVar[str]      # "java-properties", "i18next-json", "gettext-po", "xliff-2"
    file_extensions: ClassVar[tuple[str, ...]]

    def parse(self, path: Path) -> list[Segment]: ...
    def serialize(
        self,
        path: Path,
        translated: list[TranslatedSegment],
        target_lang: str,
    ) -> None: ...

    def preserve_placeholders(self, text: str) -> tuple[str, list[Placeholder]]:
        """Extract and tokenize placeholders so the model doesn't translate them.
        Returns (tokenized_text, placeholders_in_order)."""

    def restore_placeholders(self, text: str, placeholders: list[Placeholder]) -> str: ...
```

Adapter implementations to ship in this cycle:

| Adapter | Module | Notes |
|---|---|---|
| `JavaPropertiesAdapter` | `core/adapters/java_properties.py` | Reuses logic from current `resource_bundle_generator.py`, generalized. |
| `I18NextJsonAdapter` | `core/adapters/i18next_json.py` | Nested JSON, dot-keyed flatten/unflatten. |
| `GettextPoAdapter` | `core/adapters/gettext_po.py` | Use `polib`. Handles plurals via msgstr[0..N]. |
| `XliffAdapter` | `core/adapters/xliff.py` | XLIFF 2.0 only. Use `lxml`. |

ICU parsing centralizes in `core/icu.py` (wrap `pyicu` or a pure-Python parser like `babel.messages`). Adapters that *can* contain ICU (`.properties`, JSON, `.po`) call into it; XLIFF handles ICU at the `<segment>` level natively.

**`core/tm.py`**

```python
class TranslationMemory(Protocol):
    def lookup(
        self,
        segment: Segment,
        target_lang: str,
        fuzzy_threshold: float = 0.85,
    ) -> TmHit | None: ...

    def store(self, translated: TranslatedSegment) -> None: ...

    def stats(self) -> TmStats: ...

@dataclass(frozen=True)
class TmHit:
    translated: TranslatedSegment
    similarity: float                 # 1.0 for exact match
    match_type: Literal["exact", "fuzzy"]
```

Concrete: `SqliteTranslationMemory` in `core/tm/sqlite.py`. Schema:

```sql
CREATE TABLE segments (
  fingerprint TEXT PRIMARY KEY,
  source_text TEXT NOT NULL,
  source_lang TEXT NOT NULL,
  placeholders_json TEXT NOT NULL,
  embedding BLOB,                    -- 384-dim float32 from MiniLM, NULL until fuzzy index built
  created_at INTEGER NOT NULL
);

CREATE TABLE translations (
  fingerprint TEXT NOT NULL,
  target_lang TEXT NOT NULL,
  target_text TEXT NOT NULL,
  provider TEXT NOT NULL,
  confidence REAL,
  source TEXT NOT NULL,              -- "provider" | "manual"
  created_at INTEGER NOT NULL,
  PRIMARY KEY (fingerprint, target_lang, provider)
);

CREATE INDEX idx_translations_lang ON translations(target_lang);
```

Embeddings via `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim, ~120MB, runs on CPU at ~1k segments/sec). Stored inline in SQLite; fuzzy lookup uses cosine similarity scanned linearly for <100k segments (fine for v1) — switch to a vector index (sqlite-vec or hnswlib) only if benchmark shows it matters.

**`core/validators/base.py`**

```python
class Validator(Protocol):
    name: ClassVar[str]
    severity: ClassVar[Literal["error", "warning"]]

    def check(
        self,
        source: Segment,
        translated: TranslatedSegment,
    ) -> list[Violation]: ...

@dataclass(frozen=True)
class Violation:
    validator: str
    severity: Literal["error", "warning"]
    message: str
    span: tuple[int, int] | None = None
```

Validators to ship:

| Validator | What it catches |
|---|---|
| `PlaceholderParityValidator` | Source has 3 placeholders, target has 2. Or target invented `{99}`. |
| `IcuSyntaxValidator` | Output is malformed ICU MessageFormat. |
| `LengthBudgetValidator` | `metadata["max_length"]` set and target exceeds it. Warning, not error. |
| `ForbiddenTermsValidator` | Target contains a term in the run's forbidden list. |

Pipeline runs all validators; any `error` violation prevents the segment from being written and emits a structured failure that the CLI surfaces in its summary.

**`core/pipeline.py`**

The orchestrator:

```python
class TranslationPipeline:
    def __init__(
        self,
        adapter: BundleAdapter,
        tm: TranslationMemory,
        provider: Provider,           # existing TranslatorModel, renamed
        validators: list[Validator],
        target_langs: list[str],
    ): ...

    def translate_file(
        self, source_path: Path, output_dir: Path
    ) -> PipelineResult: ...
```

The pipeline replaces the current ad-hoc orchestration in `translation_service.py`. The old module becomes a deprecation shim for one release, then deletes.

## Rabbit holes

- **Don't** build a generic plugin system for adapters in this cycle. Concrete classes registered in a dict are enough. Plugin discovery can come in cycle 6 if external adapters become a real demand.
- **Don't** build a vector index. Linear cosine over <100k rows is fast enough; benchmark in scope 7 to confirm before adding hnswlib.
- **Don't** model translation memory as a knowledge graph yet. That's cycle 3. Keep TM relational, keep termbase out of the picture entirely this cycle.
- **Don't** chase 100% TBX 3.0 round-trip parity for XLIFF. XLIFF is a translation interchange format — XLIFF→Segment→XLIFF round-trip is the contract; XLIFF→TBX is out of scope.
- **Don't** add async / concurrency. Provider calls happen sequentially. We can revisit if benchmark proves it matters; premature concurrency will eat the cycle.

## No-gos

- No new providers. Providers refactored only as much as needed to fit the `Provider` Protocol — Anthropic/Ollama additions are cycle 2.
- No Gradle plugin work.
- No knowledge graph, no Kuzu, no termbase upgrade.
- No web UI.
- No domain packs.
- No `.xcstrings`, no Fluent, no `.resx`. (Cycle 6.)
- No fine-tuning, no custom models.

## Scopes

Vertical slices, each shippable in 1–3 days. These become hill-chart items. Goal: every scope past the top of the hill by week 3.

1. **Segment + Placeholder data model + ICU parser wrapper** (1 day). Tests on a hand-curated fixture of 50 ICU messages from real OSS bundles.
2. **`BundleAdapter` Protocol + `JavaPropertiesAdapter` migrated from existing code** (2 days). Old CLI delegates to the new adapter; behavior unchanged for `.properties` files.
3. **`I18NextJsonAdapter`** (2 days). Nested JSON flatten/unflatten with dot-keys; preserves key ordering.
4. **`GettextPoAdapter`** (2 days). `polib`-backed; handles plurals.
5. **`XliffAdapter` (XLIFF 2.0)** (3 days). Read + write; preserve `<note>`, `<mrk>`, segment IDs.
6. **`SqliteTranslationMemory`: schema + exact-match lookup + store** (2 days). No embeddings yet. Wire into pipeline.
7. **Embedding-based fuzzy match** (3 days). MiniLM model lazy-loaded, 384-dim cosine, threshold tunable, returns top-1 hit above threshold. Benchmark: TM lookup p95 < 50ms for 50k-segment corpus.
8. **Validators: placeholder parity + ICU syntax + length budget + forbidden terms** (3 days). Pipeline integration; CLI surfaces violations.
9. **`TranslationPipeline` orchestrator** (2 days). Replaces `translation_service.py`. Old module → deprecation shim.
10. **CLI surface update** (2 days). New flags: `--format` (auto-detected from extension by default), `--tm-path` (default `./.nemo/tm.sqlite`), `--strict` (fail run on any validator error).
11. **Test corpus + benchmark harness** (2 days). 5 real OSS bundles × 4 formats; reproducible report on cache-hit rate, validator pass rate, p50/p95 latency.
12. **Documentation** (1 day). README updated; `docs/adapters.md`, `docs/translation-memory.md`, `docs/validators.md` written.

Slack budget (~5 days): scope hammering, integration debugging, the inevitable "polib doesn't handle X" surprises.

## Test strategy

**Unit** (per-module, fast):

- Adapters: round-trip property — `parse → serialize → parse` is identity for every test fixture. Per format, ≥10 fixtures including pathological cases (Unicode keys, escape sequences, multi-line values, empty values, comments).
- ICU parser: 50-message fixture including plural, select, selectordinal, nested. Hand-validated golden output.
- TM: deterministic fixtures; exact-match retrieval; fuzzy retrieval with synthetic near-duplicates at known cosine distances.
- Validators: each validator hit with positive and negative cases; assert exactly the expected `Violation` set.

**Integration** (slower, per-cycle CI):

- End-to-end pipeline run on each format: parse → translate (mock provider returning canned outputs) → validate → serialize. Assert full round-trip and TM hit-rate on second run.
- Real provider (NLLB local, since OpenAI requires a key): translate a 20-segment fixture, assert validators pass on outputs, assert TM caches and second run is no-network.

**Contract** (the SDD enforcement layer):

- Each adapter ships a `test_contract.py` that runs the same test matrix against the format's reference fixtures. New adapters cannot land without a passing contract test.
- Pipeline-level: a `test_pipeline_contract.py` that asserts the orchestrator's externally visible behavior (cache-hit reduces provider calls; validator errors prevent writes; etc.).

**Benchmarks** (manual, per-cycle):

- Cache-hit rate on second run of identical input: must be ≥99% (≥1% allowed for floating-point determinism quirks).
- TM lookup p95 < 50ms at 50k segments.
- Pipeline throughput: ≥100 segments/sec when all hit TM exact (no provider calls).

**Acceptance criteria — cycle is "done" when**:

- All four adapters pass round-trip property tests.
- TM exact + fuzzy match work on the benchmark corpus, hitting the targets above.
- All four validators integrated into the pipeline.
- CLI runs end-to-end on a real OSS bundle (`messages_en_US.properties` from a real Spring Boot project) and produces validated translations to ≥3 target languages.
- Old `translation_service.py` is a deprecation shim.
- README documents the new CLI surface; old commands still work or print deprecation warnings.
- CI green: ruff clean, mypy clean, pytest green on Python 3.10/3.11/3.12.

## Open questions

These should be answered before betting:

1. **Pure-Python ICU parser vs. `pyicu` C-extension?** `pyicu` is faster and more correct but adds a heavy build dependency. Pure-Python (`babel.messages.format` or hand-rolled) is portable but may miss edge cases. **Recommendation**: start pure-Python with explicit unsupported-feature warnings; switch to `pyicu` if real users hit a wall.
2. **Embedding model choice.** MiniLM-L12 (384-dim, 120MB, multilingual) vs LaBSE (768-dim, 1.7GB, more accurate) vs E5-multilingual (newer, better but bigger). **Recommendation**: MiniLM-L12 for v1; benchmark in scope 11 and reconsider.
3. **TM file location.** `./.nemo/tm.sqlite` (per-project) vs `~/.nemo/tm.sqlite` (per-user). **Recommendation**: per-project default, per-user via flag — most users want TM committed to git for team sharing of cached translations.
4. **Should the TM commit-to-git by default?** Encourage yes — it makes CI runs deterministic and zero-cost. Document in README.
5. **Adapter auto-detection precedence.** Same extension can mean different formats (`.json` could be i18next, ARB, or generic). **Recommendation**: explicit `--format` flag wins; on auto-detect, ambiguous extensions log a warning and pick the first registered adapter.

## Risks

- **`polib` plural handling has edge cases**. Mitigation: heavy fixture coverage + warning-not-error on unknown plural forms.
- **MiniLM download in CI** could slow down test runs. Mitigation: cache in CI step; mock the embedding step in unit tests; only the integration suite actually loads the model.
- **XLIFF 2.0 parsing complexity** is higher than other formats. If scope 5 blows past 3 days, scope-hammer XLIFF down to read-only (parse but not serialize) and defer write to cycle 2 cooldown.
- **Backward compatibility with existing CLI users**. The old `cli.resource_bundle_generator` and `cli.resource_bundle_git` modules continue to work as deprecation shims for one release; the new entry point is `nemo translate` (or chosen equivalent — see open question on the binary name during cycle 0).
