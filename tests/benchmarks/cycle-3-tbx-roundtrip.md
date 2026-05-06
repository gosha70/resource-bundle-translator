# Cycle-3 TBX 3.0 Round-Trip Benchmark

**Target**: TBX export → Weblate import → Weblate export → AI-NEMO import → AI-NEMO export is byte-stable for the documented subset (cycle-3 pitch, S3 acceptance criterion).

**Cadence**: manual, run once per cycle on real-world Weblate exports. Not part of the per-PR CI gate (the in-repo round-trip is asserted in [`tests/integration/test_tbx_roundtrip.py`](../integration/test_tbx_roundtrip.py)).

## Why a manual benchmark?

The cycle-3 in-tree round-trip test (`test_weblate_fixture_round_trip_is_byte_stable`) asserts the **AI-NEMO ↔ AI-NEMO** round-trip is byte-stable on five hand-crafted Weblate-style fixtures. That pins determinism but does not cover Weblate's specific TBX dialect quirks (whitespace handling, attribute ordering, header structure, optional-element usage). Real Weblate exports vary across projects, Weblate versions, and per-glossary settings — pinning byte-equality against a moving target as a CI gate would flake on every Weblate point release.

The documented subset (per pitch § Solution shape) is the contract:

- `<conceptEntry id="...">`
- `<descrip type="domain">` (multi-domain supported)
- `<langSec xml:lang="...">`
- `<termSec>` with `<term>`, optional `<termNote type="partOfSpeech">`, optional `<termNote type="register">`, optional `<definition>`

Anything outside that subset is recorded in `TbxImportReport.skipped_unsupported`. A round-trip that produces an empty `skipped_unsupported` is a passing run.

## Procedure

Run this against ≥3 real Weblate-exported TBX files at the end of each cycle and on the first day of cooldown. Pick three projects of different shape — software UI, documentation, multilingual marketing copy — to catch divergent feature usage.

### 1. Acquire real exports

Pull TBX from three live Weblate projects:

```bash
mkdir -p /tmp/tbx-bench
curl -o /tmp/tbx-bench/proj-a.tbx 'https://hosted.weblate.org/api/components/<proj-a>/<comp>/glossary/?format=tbx'
curl -o /tmp/tbx-bench/proj-b.tbx 'https://hosted.weblate.org/api/components/<proj-b>/<comp>/glossary/?format=tbx'
curl -o /tmp/tbx-bench/proj-c.tbx 'https://hosted.weblate.org/api/components/<proj-c>/<comp>/glossary/?format=tbx'
```

Public-facing Weblate instances expose the glossary export under each component's API. For private instances substitute the host and an authenticated header.

### 2. Run the parity script

```bash
uv run --extra dev python tests/benchmarks/_run_tbx_parity.py /tmp/tbx-bench/*.tbx
```

The runner is intentionally not committed yet — it's a one-time hand-run script per cycle. Skeleton:

```python
import sys
import tempfile
from pathlib import Path

from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.termbase.tbx.exporter import TbxExporter
from ainemo.core.termbase.tbx.importer import TbxImporter

for source_path in map(Path, sys.argv[1:]):
    with tempfile.TemporaryDirectory() as tmp:
        tb1 = KuzuTermbase(Path(tmp) / "tb1.kuzu")
        report1 = TbxImporter(tb1).import_file(source_path)
        export1 = TbxExporter(tb1).export_bytes()

        tb2 = KuzuTermbase(Path(tmp) / "tb2.kuzu")
        report2 = TbxImporter(tb2).import_bytes(export1)
        export2 = TbxExporter(tb2).export_bytes()

        print(f"{source_path.name}:")
        print(f"  concepts={report1.concepts_added} terms={report1.terms_added}")
        print(f"  skipped_count_pass1={len(report1.skipped_unsupported)}")
        print(f"  skipped_count_pass2={len(report2.skipped_unsupported)}")
        print(f"  byte_stable={export1 == export2}")
        if report1.skipped_unsupported:
            print("  top-5 skipped elements:")
            for entry in report1.skipped_unsupported[:5]:
                print(f"    - {entry}")
```

### 3. Record results

Capture the run output as `tests/benchmarks/results/cycle-3-tbx-roundtrip-<YYYY-MM-DD>.txt`. Track cycle-over-cycle regressions by diffing successive snapshots.

## Pass criteria

A passing benchmark run satisfies all of:

- **`byte_stable=True`** for every input file. The AI-NEMO ↔ AI-NEMO round-trip determinism is the cycle-3 contract; if this fails, the exporter is non-deterministic and the cycle ships without the round-trip claim.
- **`skipped_count_pass1 == skipped_count_pass2`** for every input. If pass 2 surfaces skips that pass 1 did not, the exporter is emitting something the importer rejects — a hard contract bug.
- **`skipped_count_pass1 == 0`** is the *aspirational* target. Non-zero on real Weblate exports means real-world Weblate uses TBX features outside our cycle-3 documented subset; the cycle-3 retro reviews the top-N skipped elements and decides which to promote in cooldown.

## Circuit-breaker mapping

The cycle-3 pitch defines the circuit breaker:

> If lossless TBX 3.0 round-trip against Weblate's exports (S2+S3) is still uphill at week 4, ship S1, S4, S5, S6 with TBX import-only — round-trip parity moves to cycle-3 cooldown, and TBX export ships as a documented-subset best-effort writer rather than blocking the cycle.

This benchmark is the operational signal for that decision. If at week 4 ≥1 of the three Weblate sources fails `byte_stable=True` and the cause is not a documented-subset bug we can fix in cycle, the circuit breaker fires and S3's export becomes "best-effort writer" rather than a parity claim.

## History

| Cycle | Date | Sources | byte_stable | skipped_total | Notes |
|------:|------|---------|:-----------:|--------------:|-------|
| 3 | TBD | TBD | TBD | TBD | First run pending; ship after S3 lands. |

Append one row per cycle's run. Cycle-3 cooldown will populate the first row with results from three real Weblate projects.
