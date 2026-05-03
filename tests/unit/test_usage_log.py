"""Unit tests for :mod:`ainemo.providers._usage_log`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ainemo.providers._usage_log import (
    DEFAULT_USAGE_LOG_PATH,
    FIELD_MODEL,
    FIELD_PROVIDER,
    UsageLog,
)


def _record_one(log: UsageLog, **overrides: object) -> None:
    payload = dict(
        provider="openai",
        model="gpt-4o-2024-11-20",
        input_tokens=120,
        output_tokens=42,
        latency_ms=850,
        cost_usd=0.0021,
        source_lang="en-US",
        target_lang="de-DE",
        segment_fingerprint="abc123",
    )
    payload.update(overrides)
    log.record(**payload)  # type: ignore[arg-type]


def test_default_path_under_home() -> None:
    """Per AGENTS.md, the default log lives in ~/.ainemo/."""
    assert DEFAULT_USAGE_LOG_PATH.parent.name == ".ainemo"
    assert DEFAULT_USAGE_LOG_PATH.name == "usage.jsonl"


def test_record_creates_directory(tmp_path: Path) -> None:
    log_path = tmp_path / "deep" / "nested" / "usage.jsonl"
    log = UsageLog(log_path)
    _record_one(log)
    assert log_path.exists()


def test_record_appends_one_line_per_call(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_one(log)
    _record_one(log)
    _record_one(log)
    lines = (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_stats_aggregates_counts(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_one(log, input_tokens=100, output_tokens=50, latency_ms=500, cost_usd=0.001)
    _record_one(log, input_tokens=200, output_tokens=80, latency_ms=300, cost_usd=0.002)

    stats = log.stats()
    assert stats.call_count == 2
    assert stats.total_input_tokens == 300
    assert stats.total_output_tokens == 130
    assert stats.total_latency_ms == 800
    assert abs(stats.total_cost_usd - 0.003) < 1e-9


def test_stats_groups_by_provider_and_model(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_one(log, provider="openai", model="gpt-4o-2024-11-20")
    _record_one(log, provider="openai", model="gpt-4o-2024-11-20")
    _record_one(log, provider="anthropic", model="claude-sonnet-4-5-20250929")

    stats = log.stats()
    assert stats.by_provider == {"openai": 2, "anthropic": 1}
    assert stats.by_model == {
        "gpt-4o-2024-11-20": 2,
        "claude-sonnet-4-5-20250929": 1,
    }


def test_stats_handles_none_token_and_cost(tmp_path: Path) -> None:
    """Local providers (NLLB/Ollama) record None for tokens and cost.
    Aggregation must treat None as zero, not crash."""
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_one(
        log,
        provider="nllb",
        model="nllb-200-distilled-600M",
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
    )
    stats = log.stats()
    assert stats.call_count == 1
    assert stats.total_input_tokens == 0
    assert stats.total_cost_usd == 0.0


def test_stats_filters_by_since(tmp_path: Path) -> None:
    """`since` filter narrows the window to records at or after the
    given timestamp."""
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_one(log)
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
    # All records were before the cutoff → filtered out.
    stats = log.stats(since=cutoff)
    assert stats.call_count == 0


def test_stats_missing_file_returns_zeros(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "never_written.jsonl")
    stats = log.stats()
    assert stats.call_count == 0
    assert stats.total_cost_usd == 0.0
    assert stats.by_provider == {}


def test_stats_skips_partial_last_line(tmp_path: Path) -> None:
    """JSONL design tolerates SIGKILL mid-write: a partial last line
    must be skipped, not crash the read path."""
    log_path = tmp_path / "usage.jsonl"
    log = UsageLog(log_path)
    _record_one(log)
    # Append a corrupt partial line to simulate crash-during-write.
    with log_path.open("a", encoding="utf-8") as f:
        f.write('{"provider": "openai", "mod')
    stats = log.stats()
    assert stats.call_count == 1


def test_record_uses_constant_field_names(tmp_path: Path) -> None:
    """The on-disk JSON keys come from the FIELD_* constants —
    extracted-as-constants per AGENTS.md § Prohibited Patterns. This
    test pins that contract by importing the constants and checking
    they appear verbatim in the written record."""
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_one(log)
    raw = (tmp_path / "usage.jsonl").read_text(encoding="utf-8")
    assert f'"{FIELD_PROVIDER}"' in raw
    assert f'"{FIELD_MODEL}"' in raw
