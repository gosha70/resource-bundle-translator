# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for ProviderRouter.translate_with + list_registered — cycle-5 S5."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._errors import UnknownProviderError
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

pytestmark = pytest.mark.unit


def _make_stub(
    provider_id: str, calls: list[tuple[str, str]], *, supports: bool = True
) -> Provider:
    """Build a stub Provider whose `provider_id` ClassVar matches the given id.

    The Provider Protocol declares `provider_id: ClassVar[str]`, so each id
    needs its own class. Wrapping the class definition in a factory keeps
    the test setup compact.
    """
    _pid = provider_id
    _supports = supports

    class _Stub:
        provider_id: ClassVar[str] = _pid

        def translate(
            self,
            segment: Segment,
            target_lang: str,
            *,
            system_prompt_addendum: str | None = None,
        ) -> ProviderResult:
            del system_prompt_addendum
            calls.append((self.provider_id, segment.source_text))
            return ProviderResult(
                target_text=f"[{self.provider_id}] {segment.source_text}",
                provider=self.provider_id,
                model=f"{self.provider_id}-model",
                input_tokens=10,
                output_tokens=12,
                latency_ms=5,
                cost_usd=0.001,
                confidence=None,
            )

        def supports(self, source_lang: str, target_lang: str) -> bool:
            return _supports

    instance: Provider = _Stub()
    return instance


def _make_router(tmp_path: Path, providers: dict[str, Provider]) -> ProviderRouter:
    log = UsageLog(tmp_path / "usage.jsonl")
    config = RoutingConfig(default_provider=next(iter(providers)))
    return ProviderRouter(providers=providers, routing_config=config, usage_log=log)


def _make_segment() -> Segment:
    return Segment(key="k1", source_text="hello world", source_lang="en")


def test_translate_with_invokes_named_provider(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    providers: dict[str, Provider] = {
        "alpha": _make_stub("alpha", calls),
        "beta": _make_stub("beta", calls),
    }
    router = _make_router(tmp_path, providers)

    result = router.translate_with("beta", _make_segment(), "de")

    assert result.provider == "beta"
    assert calls == [("beta", "hello world")]


def test_translate_with_unknown_provider_raises(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    providers: dict[str, Provider] = {"alpha": _make_stub("alpha", calls)}
    router = _make_router(tmp_path, providers)

    with pytest.raises(UnknownProviderError) as excinfo:
        router.translate_with("not-registered", _make_segment(), "de")
    assert "not-registered" in str(excinfo.value)
    assert calls == []


def test_translate_with_records_cost_to_usage_log(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    log_path = tmp_path / "usage.jsonl"
    providers: dict[str, Provider] = {"alpha": _make_stub("alpha", calls)}
    router = ProviderRouter(
        providers=providers,
        routing_config=RoutingConfig(default_provider="alpha"),
        usage_log=UsageLog(log_path),
    )

    router.translate_with("alpha", _make_segment(), "de")

    contents = log_path.read_text(encoding="utf-8").strip()
    assert "alpha" in contents
    assert '"cost_usd": 0.001' in contents


def test_list_registered_returns_sorted_tuple(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    providers: dict[str, Provider] = {
        "zeta": _make_stub("zeta", calls),
        "alpha": _make_stub("alpha", calls),
        "mu": _make_stub("mu", calls),
    }
    router = _make_router(tmp_path, providers)

    assert router.list_registered() == ("alpha", "mu", "zeta")


def test_list_registered_matches_init_keys(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    providers: dict[str, Provider] = {
        "alpha": _make_stub("alpha", calls),
        "beta": _make_stub("beta", calls),
    }
    router = _make_router(tmp_path, providers)

    assert set(router.list_registered()) == set(providers.keys())


def test_translate_with_bypasses_routing_config(tmp_path: Path) -> None:
    """RoutingConfig points at 'alpha', but translate_with('beta', ...) routes
    to beta regardless. This is the QA-layer's whole point: the reviewer picks
    the back-translation provider, not the routing rules."""
    calls: list[tuple[str, str]] = []
    providers: dict[str, Provider] = {
        "alpha": _make_stub("alpha", calls),
        "beta": _make_stub("beta", calls),
    }
    log = UsageLog(tmp_path / "usage.jsonl")
    router = ProviderRouter(
        providers=providers,
        routing_config=RoutingConfig(default_provider="alpha"),
        usage_log=log,
    )

    result = router.translate_with("beta", _make_segment(), "de")

    assert result.provider == "beta"
    assert calls == [("beta", "hello world")]


def test_translate_with_unsupported_pair_raises(tmp_path: Path) -> None:
    from ainemo.providers.router import ProviderUnsupportedPair

    calls: list[tuple[str, str]] = []
    providers: dict[str, Provider] = {
        "strict": _make_stub("strict", calls, supports=False),
    }
    router = _make_router(tmp_path, providers)

    with pytest.raises(ProviderUnsupportedPair):
        router.translate_with("strict", _make_segment(), "de")
    assert calls == []
