# Translation Memory

The translation memory (TM) is the **first stop** in AI-NEMO's pipeline. Every Segment is looked up against the TM before any provider is called. Exact matches are zero-cost; fuzzy matches return a similar segment plus a similarity score so the pipeline (or the cycle-5 reviewer UI) can decide whether to accept the cached translation or forward to a provider.

## Default backend: SQLite + MiniLM

`SqliteTranslationMemory` stores translations in a file-based SQLite database (default: `./.ainemo/tm.sqlite`). Embeddings — needed for fuzzy lookup — are computed by a `sentence-transformers` model and stored inline as BLOBs.

```python
from pathlib import Path
from ainemo.core.tm.sqlite import SqliteTranslationMemory, make_default_embedder

tm = SqliteTranslationMemory(
    Path(".ainemo/tm.sqlite"),
    embedder=make_default_embedder(),  # ~120 MB on first run
)
```

**Default embedder**: `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, multilingual). Lazy-loaded on first call so importing the module doesn't trigger the download. Tests pass deterministic stub embedders rather than calling this — see `tests/unit/test_sqlite_tm.py`.

## TM commit policy

Per `AGENTS.md` § Translation-Domain Conventions: **TM is opt-in for git tracking, not the default.** `.ainemo/` is in `.gitignore` from cycle 0. The TM contains source strings, translated strings, and provider/model metadata — potentially proprietary product text — and is a binary file that grows and conflicts in normal git workflows.

Teams that want shared cached translations for deterministic, zero-cost CI runs can opt in per-project by removing `.ainemo/` from `.gitignore` and committing the SQLite file. Document the privacy/repo-size trade-offs in your project's README before doing this.

## Lookup flow

```python
hit = tm.lookup(segment, target_lang="de-DE", fuzzy_threshold=0.85)
if hit is None:
    # cache miss → forward to provider
    ...
elif hit.match_type == "exact":
    # primary-key hit; similarity == 1.0
    ...
elif hit.match_type == "fuzzy":
    # cosine similarity in [threshold, 1.0]; consider whether
    # to accept directly or send for human review.
    ...
```

Exact match is checked first (cheap; primary-key lookup on `(fingerprint, target_lang, provider)`). Only on miss does the TM consider fuzzy lookup. If no embedder was supplied at construction, fuzzy is silently disabled and the TM serves exact matches only — the right default for CI runs that don't want a 120 MB model download.

## Schema

Two tables plus a `meta` table for schema versioning.

```sql
CREATE TABLE segments (
  fingerprint       TEXT PRIMARY KEY,        -- SHA-256 of (source_text + source_lang + placeholder shape)
  source_text       TEXT NOT NULL,
  source_lang       TEXT NOT NULL,           -- BCP-47
  placeholders_json TEXT NOT NULL,           -- JSON-encoded list of (kind, raw, span)
  embedding         BLOB,                    -- float32 array; NULL when no embedder available
  created_at        INTEGER NOT NULL
);

CREATE TABLE translations (
  fingerprint  TEXT NOT NULL,
  target_lang  TEXT NOT NULL,
  target_text  TEXT NOT NULL,
  provider     TEXT NOT NULL,                -- e.g. "openai", "nllb", "manual"
  confidence   REAL,                         -- optional, provider-supplied
  source       TEXT NOT NULL,                -- "exact_tm" | "fuzzy_tm" | "provider" | "manual"
  created_at   INTEGER NOT NULL,
  PRIMARY KEY (fingerprint, target_lang, provider)
);

CREATE INDEX idx_translations_lang ON translations(target_lang);
```

Schema version is recorded in `meta`. Cycle-1 ships schema version 1; future migrations bump the version and run automatically on `__init__`.

## Fuzzy lookup performance

Cycle 1 uses a **linear cosine scan** over segments with embeddings filtered by source language and target-language availability. The cycle-1 design choice: a vector index (sqlite-vec, hnswlib, faiss) only lands when a benchmark on a 50k-segment corpus shows the linear scan crossing the **p95 < 50ms** target.

The benchmark lives at `tests/benchmarks/test_tm_lookup_benchmark.py`. Run with:

```bash
uv run --extra dev pytest -m benchmark tests/benchmarks/
```

## Stats

```python
stats = tm.stats()
print(f"segments: {stats.segment_count}")
print(f"translations: {stats.translation_count}")
print(f"target langs: {stats.target_lang_count}")
print(f"embeddings: {stats.embedding_count}")
```

Or via the CLI:

```bash
nemo tm stats
```

## Tuning

| Parameter | Default | Notes |
|---|---|---|
| `fuzzy_threshold` | `0.85` | Below this, fuzzy hits are treated as misses. Raise for stricter caching, lower for more aggressive reuse. |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` | 384-dim, ~120MB. Cycle 1 doesn't expose a config knob; cycle 3+ persona work may. |
| TM file location | `./.ainemo/tm.sqlite` | Per-project. CLI `--tm-path` overrides. |
