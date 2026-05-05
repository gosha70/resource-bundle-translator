"""Provider routing + UsageLog benchmark — cycle-2 scope 14.

Pitch contract (specs/pitches/0002-providers-gradle/pitch.md § Test
strategy / AGENTS.md § Provider Rules): every LLM call wrapped with
cost + latency tracking. The provider call itself is dominated by
network (cloud) or model inference (local) — not interesting to
benchmark in CI. **What IS interesting** is the cycle-2 plumbing
overhead: the router's rule lookup, the UsageLog JSONL append, and
the provider-result extraction. If any of these grows materially,
batch jobs (Gradle plugin) feel it directly.

Targets (cycle-2 baseline; cycle-3+ tightens as data lands):

- Router + UsageLog overhead per call: p95 < 1ms (TM hit not
  involved — that's the cycle-1 benchmark)
- UsageLog stats() over 100k records: p95 < 200ms

Run manually:

    pytest -m benchmark tests/benchmarks/test_provider_benchmark.py

Results land under ``tests/benchmarks/results/`` so cycle-over-cycle
regressions are visible in code review. The harness uses a noop
provider (echoes source text, latency 0) so the benchmark measures
only the cycle-2 plumbing — not the provider's own cost.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import ClassVar, Final

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

# --- Cycle-2 latency targets ----------------------------------------------

_ROUTER_OVERHEAD_P95_TARGET_MS: Final = 1.0
"""Per-call router + UsageLog overhead target. The whole point of
ProviderRouter is that surveillance is *free* relative to the actual
provider call — if it ever isn't, batch jobs (Gradle plugin / cycle-2
daemon) feel it segment-by-segment."""

_USAGE_LOG_STATS_P95_TARGET_MS: Final = 200.0
"""Reading 100k records back via :meth:`UsageLog.stats`. The cycle-2
``nemo provider stats`` CLI sits on top of this; users who run it as
part of every translate cycle should not hit a noticeable delay."""

# --- Stub provider --------------------------------------------------------


class _NoopBenchProvider:
    """Minimal Provider impl — returns the source text unchanged with
    zero latency. Lets the benchmark measure router + UsageLog
    overhead without provider variance."""

    provider_id: ClassVar[str] = PROVIDER_ID_NOOP

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        return ProviderResult(
            target_text=segment.source_text,
            provider=PROVIDER_ID_NOOP,
            model=PROVIDER_ID_NOOP,
            input_tokens=10,
            output_tokens=10,
            latency_ms=0,
            cost_usd=None,
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


_: type[Provider] = _NoopBenchProvider  # Protocol-conformance check.


# --- Benchmarks ----------------------------------------------------------


@pytest.mark.benchmark
def test_router_overhead_per_call_under_1ms_p95(tmp_path: Path) -> None:
    """End-to-end: router selection + provider call + UsageLog.record
    for 1000 calls. The provider returns instantly so the measurement
    isolates cycle-2 plumbing."""
    usage_log = UsageLog(tmp_path / "bench.jsonl")
    router = ProviderRouter(
        providers={PROVIDER_ID_NOOP: _NoopBenchProvider()},
        routing_config=RoutingConfig(default_provider=PROVIDER_ID_NOOP),
        usage_log=usage_log,
    )
    segment = Segment(key="k", source_text="Hello, {name}!", source_lang="en-US")

    latencies_ms: list[float] = []
    for _ in range(1000):
        started = time.perf_counter()
        router.translate(segment, "de-DE")
        latencies_ms.append((time.perf_counter() - started) * 1000)

    p95 = statistics.quantiles(latencies_ms, n=20)[18]  # 95th percentile
    p50 = statistics.median(latencies_ms)
    _record_result(
        tmp_path,
        "router_overhead",
        {
            "p50_ms": p50,
            "p95_ms": p95,
            "n": len(latencies_ms),
            "target_p95_ms": _ROUTER_OVERHEAD_P95_TARGET_MS,
        },
    )
    assert p95 < _ROUTER_OVERHEAD_P95_TARGET_MS, (
        f"Router overhead p95={p95:.3f}ms exceeds target "
        f"{_ROUTER_OVERHEAD_P95_TARGET_MS}ms — cycle-2 plumbing has "
        f"regressed. Inspect ProviderRouter.translate or UsageLog.record."
    )


@pytest.mark.benchmark
def test_usage_log_stats_100k_records_under_200ms_p95(tmp_path: Path) -> None:
    """Pre-populate the JSONL log with 100k records, then time
    ``UsageLog.stats()`` 10 times. The cycle-2 ``nemo provider stats``
    CLI uses this exact code path."""
    log_path = tmp_path / "big.jsonl"
    log = UsageLog(log_path)
    for i in range(100_000):
        log.record(
            provider="bench",
            model="bench-model",
            input_tokens=10,
            output_tokens=20,
            latency_ms=5,
            cost_usd=0.0001,
            source_lang="en-US",
            target_lang="de-DE",
            segment_fingerprint=f"fp-{i}",
        )

    latencies_ms: list[float] = []
    for _ in range(10):
        started = time.perf_counter()
        stats = log.stats()
        latencies_ms.append((time.perf_counter() - started) * 1000)

    assert stats.call_count == 100_000
    p95 = max(latencies_ms)  # 10 samples; max ≈ p95.
    p50 = statistics.median(latencies_ms)
    _record_result(
        tmp_path,
        "usage_log_stats_100k",
        {
            "p50_ms": p50,
            "p95_ms": p95,
            "records": 100_000,
            "samples": len(latencies_ms),
            "target_p95_ms": _USAGE_LOG_STATS_P95_TARGET_MS,
        },
    )
    assert p95 < _USAGE_LOG_STATS_P95_TARGET_MS, (
        f"UsageLog.stats() over 100k records p95={p95:.1f}ms exceeds "
        f"target {_USAGE_LOG_STATS_P95_TARGET_MS}ms — cycle-3 may need "
        f"a SQLite-backed log or an aggregation cache."
    )


# --- Helpers --------------------------------------------------------------


def _record_result(tmp_path: Path, name: str, data: dict[str, object]) -> None:
    """Write the benchmark result alongside the test so cycle-over-
    cycle regressions are visible in PR diffs. The file lives in the
    repo (committed); the tmp_path is just for the fixture data."""
    import json

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    target = results_dir / f"{name}.json"
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
