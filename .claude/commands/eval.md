Run the AI-NEMO translation evaluation pipeline:
1. Load eval corpus from tests/benchmarks/datasets/ (real OSS resource bundles).
2. Clear or use a temp TM, run the pipeline once (cold), then again (warm) to measure cache behavior.
3. Compute and report:
   - TM exact-match hit rate on the warm run (target ≥99%)
   - TM lookup p50/p95 latency at corpus size (target p95 < 50ms at 50k segments)
   - Validator pass rate per validator (placeholder parity, ICU syntax, length budget, forbidden terms) — target 100% on shipped translations
   - BLEU and chrF vs reference translations where the corpus provides them
   - Per-provider cost + latency (read from ~/.ainemo/usage.jsonl or equivalent)
   - Pipeline throughput (segments/sec) on the TM-hit-only path (target ≥100 segments/sec)
4. Print summary table with pass/fail thresholds clearly marked.
5. If any metric is below threshold, flag it with the specific number, the threshold, and the suspected cause (cold cache, embedding miss, validator regression, provider drift).
6. Append the run to tests/benchmarks/results/ with timestamp + commit SHA so cycle-over-cycle trends are visible.
