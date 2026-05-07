# Termbase importers

Cycle-4 ships the **pluggable termbase importer pipeline** — a Protocol-first surface for draining structured glossaries (CSV exports, JSON-Lines dumps from internal scripts) into the cycle-3 [`Termbase`](termbase.md) without writing custom code per file format.

Cycle 3's only import path was [TBX 3.0](termbase.md#tbx-30-iso-30042-interop), which served users who already had a Weblate-style glossary. Cycle 4's audience — software i18n teams loading their own marketing/product/UI glossaries — almost never has TBX. They have a CSV from a spreadsheet, or a JSONL dump from `npm run extract-terms`. This is the import surface for that data.

## Protocol surface

`core/` consumers depend only on the [`TermbaseSource`](../src/ainemo/core/termbase/sources/base.py) Protocol; concrete backends live in their own modules and bring whatever stdlib parser they need. Cycle 4 ships [`CsvSource`](../src/ainemo/core/termbase/sources/csv_source.py) and [`JsonLinesSource`](../src/ainemo/core/termbase/sources/jsonl_source.py); cycle 7+ may add SKOS-RDF or a Wikidata enricher if real demand surfaces.

```python
from ainemo.core.termbase.sources.base import (
    ImportRecord, ImportReport, SkippedRow, TermbaseSource,
)

@runtime_checkable
class TermbaseSource(Protocol):
    provenance: ClassVar[str]                              # e.g. "csv-import"
    def iter_concepts(self) -> Iterator[ImportRecord | SkippedRow]: ...
```

`iter_concepts()` yields **one item per source-file row**: an `ImportRecord` when the row parsed cleanly, a `SkippedRow` (with a `"row N: <reason>"` line) when it didn't. Implementations MUST NOT raise for row-level parse / mapping errors — surfacing them as `SkippedRow` items lets one bad row coexist with the rest of the import. File-level errors that no caller could recover from (file does not exist, malformed CSV header) MAY raise.

The `provenance` ClassVar (e.g. `TERM_SOURCE_CSV_IMPORT`, `TERM_SOURCE_JSONL_IMPORT`) is stamped on every `Term.source` the loader writes, so the cycle-5 reviewer UI can audit imported-from-CSV terms separately from imported-from-JSONL / imported-from-TBX (cycle 3) / auto-promoted-from-TM (cycle 3 S5) terms.

### Loader bridge

[`load_into_termbase(tb, source, *, namespace=None) -> ImportReport`](../src/ainemo/core/termbase/sources/loader.py) drains any `TermbaseSource` into any `Termbase` via the Protocol surface only — both `KuzuTermbase` (production) and the in-memory `RecordingTermbase` test stub work.

```python
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.termbase.sources.csv_source import CsvSource
from ainemo.core.termbase.sources.loader import load_into_termbase
from ainemo.core.termbase.sources.mapping import field_mapping_from_yaml_dict
import yaml

mapping = field_mapping_from_yaml_dict(yaml.safe_load(open("mapping.yaml")))
source = CsvSource(Path("glossary.csv"), mapping)
tb = KuzuTermbase(".ainemo/termbase.kuzu")
try:
    report = load_into_termbase(tb, source, namespace="marketing")
finally:
    tb.close()
print(report.concepts_added, report.terms_added, report.rows_skipped)
```

## `FieldMapping` YAML schema

Every importer is driven by a YAML file passed via `--map-config`. The schema is enforced strictly by [`FieldMapping`](../src/ainemo/core/termbase/sources/mapping.py) (Pydantic, `extra="forbid"`) — typo'd keys raise instead of silently producing zero terms.

```yaml
# mapping.yaml — minimal example
source_lang: en-US           # mandatory — BCP-47 tag for every row in this file
source_column: term_en       # mandatory — column / JSON key holding the source-lang term
target_columns:              # mandatory — at least one target rendering
  de-DE: term_de
  fr-FR: term_fr
domain_column: category      # optional — per-row domain id; omit to disable
definition_column: notes     # optional — per-row source-lang definition
```

| Key                  | Required | Notes                                                                                                                                |
|----------------------|----------|--------------------------------------------------------------------------------------------------------------------------------------|
| `source_lang`        | yes      | BCP-47 tag applied to every row. Single-valued per file — multi-source-lang glossaries split into one file per source-lang.          |
| `source_column`      | yes      | Column / JSON key holding the source-language term.                                                                                  |
| `target_columns`     | yes      | Mapping of BCP-47 target-lang tag → column / JSON key. At least one entry; blank keys or values are rejected at load time.           |
| `domain_column`      | no       | When set and a row's value is non-blank, the row's `domain_id` participates in concept-id derivation as the highest-precedence namespace component. |
| `definition_column`  | no       | When set and a row's value is non-blank, lands on `Concept.definition`.                                                              |

**Rejected up-front** (per the cycle-3 S4 schema-strictness lesson):

- Unknown fields — `extra="forbid"`. A typo'd `source_columns` (with the trailing `s`) surfaces as a load error instead of silently importing nothing.
- Empty `target_columns` — a mapping with no targets imports nothing useful.
- Blank string values for required scalars (`source_lang`, `source_column`).
- Blank optional scalars when the key is present — operator clearly meant to omit the field.
- Inline mapping via CLI flags — only a YAML file via `--map-config` is accepted. Mappings are reusable across many revisions of the same glossary; a YAML file the team commits alongside the data is the natural shape (per pitch Q2).

## `nemo termbase import-from-csv`

```bash
nemo termbase import-from-csv path/to/glossary.csv \
    --map-config mapping.yaml \
    [--encoding utf-8] \
    [--delimiter ','] \
    [--namespace marketing] \
    [--termbase-path .ainemo/termbase.kuzu]
```

| Flag                 | Default                  | Notes                                                                                                              |
|----------------------|--------------------------|--------------------------------------------------------------------------------------------------------------------|
| `--map-config PATH`  | required                 | YAML field-mapping file.                                                                                           |
| `--encoding NAME`    | `utf-8`                  | File encoding. Mismatch surfaces a `CsvDecodeError` with `--encoding latin-1` named verbatim in the error message. |
| `--delimiter CHAR`   | `,`                      | Single character. Backslash escapes (`\t`, `\n`, `\r`, `\v`, `\f`, `\0`) are normalized so the documented `--delimiter '\t'` invocation works through normal shell quoting. Multi-character delimiters are rejected with a clean stderr message. |
| `--namespace TAG`    | none                     | Per-import namespace for concept-id derivation. See [Concept identity](#concept-identity).                         |
| `--termbase-path PATH` | `.ainemo/termbase.kuzu` | Kuzu termbase directory.                                                                                           |

CSV dialect is RFC 4180. Quoted fields with embedded delimiters, multi-line values, escape sequences, and Unicode keys are all handled by the stdlib `csv.DictReader`.

## `nemo termbase import-from-jsonl`

```bash
nemo termbase import-from-jsonl path/to/dump.jsonl \
    --map-config mapping.yaml \
    [--encoding utf-8] \
    [--namespace marketing] \
    [--termbase-path .ainemo/termbase.kuzu]
```

Same flags as `import-from-csv` minus `--delimiter` (JSONL has no field separator). One JSON object per line; nested objects/arrays under a mapped key are not destructured — they surface as a `SkippedRow` rather than silently coercing.

**Strict-string policy on mapped columns.** A mapped column whose value is a non-string, non-null JSON scalar (number, boolean) — or a nested object / array — is rejected with a `SkippedRow`. This keeps round-trip parity with CSV (which always sees strings) and rescues users who accidentally lost translations to a spreadsheet's Boolean coercion. Skip-reason phrasing matches the Python type name on the value, e.g.:

- `row 12: 'def' is dict, expected string`
- `row 12: target key 'term_de' is bool, expected string`
- `row 12: 'category' is list, expected string`

JSONL is utf-8 by convention (per [jsonlines.org](https://jsonlines.org/); there is no IETF RFC). The `--encoding` override exists for parity with `import-from-csv`. A decode error is wrapped as `JsonlDecodeError` with the original `UnicodeDecodeError` reachable via `__cause__` for callers that want the byte offset.

## Idempotency contract

Re-running an import with **unchanged source data and unchanged `--namespace`** is byte-stable at the termbase level: concept count and per-language term count are unchanged after the second run. The contract is pinned by integration tests in [`tests/integration/test_termbase_import_csv_cli.py`](../tests/integration/test_termbase_import_csv_cli.py) and [`tests/integration/test_termbase_import_jsonl_cli.py`](../tests/integration/test_termbase_import_jsonl_cli.py).

### Concept identity

Concept ids are content-addressed:

```
import-<sha256(source_lang || U+001F || source_term || U+001F || namespace)[:16]>
```

`namespace` resolves first non-empty of:

1. The row's `domain_id` (from `FieldMapping.domain_column` when set per-row).
2. The per-import `--namespace TAG` flag value.
3. Empty string (global namespace).

Same `(source_lang, source_term, namespace)` triple → same concept id → upsert. Different triple → different concept. This is the cycle-4 S1 P2 fix that keeps two CSVs sharing the source surface `cancel` (one marketing, one legal) from collapsing onto one concept.

The 16-hex-char sha256 truncation is a **durable on-disk format** — every concept stored in a user's `.ainemo/termbase.kuzu/` carries an id of the form `import-abc123def456...`. The format is pinned by `tests/unit/test_loader_concept_ids.py` so a refactor that flips the separator, reorders fields, or migrates the truncation length cannot silently fragment existing user termbases.

### Term identity

Each concept's source-language and target-language terms get deterministic ids of the form `<concept_id>-<lang>`. With the concept_id already content-addressed, term ids are stable across re-imports without an extra hash.

### Orphan caveat

Changing any identity field (rename a `source_term`, change the `--namespace`, change the row's `domain_id`) produces a **new** concept and orphans the previous one. The previous concept stays in the termbase with its original terms; the new concept lands alongside it. This matches cycle-3 TBX import behavior and is documented in the pitch's § Risks. Use `nemo termbase stats` to spot orphan growth, and re-import after fixing the source data to add the corrected concepts. (No automatic prune — that's a cycle-5 reviewer-UI concern.)

## Error surfaces

| Error                         | Where                                       | Operator-facing message                                          |
|-------------------------------|---------------------------------------------|------------------------------------------------------------------|
| Missing input file            | CLI exit 2                                  | `CSV file not found: …` / `JSONL file not found: …`              |
| Missing `--map-config` file   | CLI exit 2                                  | `Field-mapping file not found: …`                                |
| Invalid YAML mapping          | CLI exit 2                                  | `Invalid field-mapping in …: <pydantic / yaml message>`          |
| Mapping references absent column | CLI exit 2 (CSV only — header validates) | `MissingColumnError: …`                                          |
| File-level decode error       | CLI exit 2                                  | `CsvDecodeError` / `JsonlDecodeError`, names `--encoding latin-1` verbatim |
| Row-level parse / mapping error | `ImportReport.skipped_details` (stdout)   | `row N: <reason>` — never aborts the import                      |

All file-level errors print a single stderr line; **no Python tracebacks reach the operator**. Per-row failures land in the printed import summary so an operator dogfooding a real glossary can see *why* particular rows were dropped.

## See also

- [`docs/termbase.md`](termbase.md) — concept model, schema, TBX subset, `nemo termbase` CLI reference.
- [`specs/pitches/0004-termbase-importer-pipeline/pitch.md`](../specs/pitches/0004-termbase-importer-pipeline/pitch.md) — the cycle-4 Shape-Up pitch.
- [`tests/integration/test_termbase_import_csv_cli.py`](../tests/integration/test_termbase_import_csv_cli.py) / [`test_termbase_import_jsonl_cli.py`](../tests/integration/test_termbase_import_jsonl_cli.py) — the integration-level idempotency + namespace-collision contracts.
