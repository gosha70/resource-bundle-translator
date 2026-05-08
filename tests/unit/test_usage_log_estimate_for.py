# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for UsageLog.estimate_for — cycle-5 S5 additive cycle-2 surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.providers._usage_log import UsageLog

pytestmark = pytest.mark.unit


def _record(
    log: UsageLog, *, provider: str, model: str, cost: float, in_tok: int, out_tok: int
) -> None:
    log.record(
        provider=provider,
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=10,
        cost_usd=cost,
        source_lang="en",
        target_lang="de",
        segment_fingerprint=f"fp-{provider}-{model}-{cost}",
    )


def test_estimate_for_empty_log_returns_none(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    assert log.estimate_for("openai", "gpt-4o", total_tokens=100) is None


def test_estimate_for_returns_none_when_all_records_have_null_cost(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    log.record(
        provider="openai",
        model="gpt-4o",
        input_tokens=10,
        output_tokens=10,
        latency_ms=10,
        cost_usd=None,
        source_lang="en",
        target_lang="de",
        segment_fingerprint="fp-1",
    )
    assert log.estimate_for("openai", "gpt-4o", total_tokens=100) is None


def test_estimate_for_returns_estimate_from_valid_records(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    # Single record: cost 0.002 over 20 tokens → 0.0001 per token.
    _record(log, provider="openai", model="gpt-4o", cost=0.002, in_tok=10, out_tok=10)

    estimate = log.estimate_for("openai", "gpt-4o", total_tokens=100)
    assert estimate is not None
    # 0.0001 * 100 = 0.01
    assert estimate == pytest.approx(0.01, rel=1e-9)


def test_estimate_for_uses_median_not_mean(tmp_path: Path) -> None:
    """Median is robust to outliers; this test seeds an outlier 100x the
    typical cost-per-token and checks that the median ignores it."""
    log = UsageLog(tmp_path / "usage.jsonl")
    # 5 typical records at 0.0001/token + 1 outlier at 0.01/token.
    for _ in range(5):
        _record(log, provider="openai", model="gpt-4o", cost=0.001, in_tok=5, out_tok=5)
    _record(log, provider="openai", model="gpt-4o", cost=1.0, in_tok=5, out_tok=5)

    estimate = log.estimate_for("openai", "gpt-4o", total_tokens=100)
    assert estimate is not None
    # Median of [0.0001 * 5, 0.1 * 1] = 0.0001; * 100 = 0.01.
    assert estimate == pytest.approx(0.01, rel=1e-9)


def test_estimate_for_model_none_matches_any_model(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    _record(log, provider="openai", model="gpt-4o", cost=0.002, in_tok=10, out_tok=10)
    _record(log, provider="openai", model="gpt-3.5", cost=0.001, in_tok=5, out_tok=5)

    estimate_with_model = log.estimate_for("openai", "gpt-4o", total_tokens=100)
    estimate_any_model = log.estimate_for("openai", None, total_tokens=100)

    assert estimate_with_model is not None
    assert estimate_any_model is not None
    # Both records have 0.0001/token, so median is the same → identical estimates.
    assert estimate_with_model == pytest.approx(estimate_any_model, rel=1e-9)


def test_estimate_for_length_scales_linearly(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    _record(log, provider="openai", model="gpt-4o", cost=0.002, in_tok=10, out_tok=10)

    e100 = log.estimate_for("openai", "gpt-4o", total_tokens=100)
    e200 = log.estimate_for("openai", "gpt-4o", total_tokens=200)
    assert e100 is not None
    assert e200 is not None
    assert e200 == pytest.approx(2 * e100, rel=1e-9)


def test_estimate_for_filters_by_provider(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    _record(log, provider="anthropic", model="claude", cost=0.005, in_tok=10, out_tok=10)

    # OpenAI hasn't been seen — even though anthropic has data.
    assert log.estimate_for("openai", None, total_tokens=100) is None
    # Anthropic has data and returns an estimate.
    assert log.estimate_for("anthropic", None, total_tokens=100) is not None


def test_estimate_tokens_from_chars_default_ratio() -> None:
    """4 chars per token (OpenAI rule of thumb for English)."""
    from ainemo.providers._usage_log import estimate_tokens_from_chars

    assert estimate_tokens_from_chars(0) == 0
    assert estimate_tokens_from_chars(4) == 1
    assert estimate_tokens_from_chars(40) == 10
    assert estimate_tokens_from_chars(400) == 100


def test_estimate_tokens_from_chars_floor_at_one_for_nonempty() -> None:
    from ainemo.providers._usage_log import estimate_tokens_from_chars

    # 1, 2, 3 chars all round down to <1, but the helper guarantees ≥1
    # for any non-zero char count so the resulting cost estimate isn't 0.
    assert estimate_tokens_from_chars(1) == 1
    assert estimate_tokens_from_chars(2) == 1


def test_estimate_tokens_from_chars_custom_ratio() -> None:
    from ainemo.providers._usage_log import estimate_tokens_from_chars

    # NLLB-style ~2.5 chars/token.
    assert estimate_tokens_from_chars(100, chars_per_token=2.5) == 40
