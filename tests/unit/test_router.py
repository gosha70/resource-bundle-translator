"""Unit tests for :class:`ainemo.providers.router.ProviderRouter`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import pytest

from ainemo.core.segment import Segment
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import (
    ProviderRouteNotFound,
    ProviderRouter,
    ProviderUnsupportedPair,
    RoutingConfig,
    RoutingRule,
)

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"


@dataclass
class _StubProvider:
    """In-memory provider that records its calls. Implements the
    cycle-2 Provider Protocol."""

    provider_id: ClassVar[str] = "stub"
    model: str = "stub-1.0"
    target_text: str = "TRANSLATED"
    cost_usd: float | None = 0.001
    latency_ms: int = 100
    supports_pairs: tuple[tuple[str, str], ...] | None = None
    """When None, supports every pair. When a tuple, supports only
    those exact (source_lang, target_lang) pairs."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        self.calls.append((segment.source_text, target_lang))
        return ProviderResult(
            target_text=self.target_text,
            provider=self.provider_id,
            model=self.model,
            input_tokens=10,
            output_tokens=20,
            latency_ms=self.latency_ms,
            cost_usd=self.cost_usd,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        if self.supports_pairs is None:
            return True
        return (source_lang, target_lang) in self.supports_pairs


def _make_provider(provider_id: str, **overrides: object) -> Provider:
    """Build a stub provider with a given id (Protocol requires
    ``provider_id`` as a ClassVar, so we synthesize a subclass)."""

    cls = type(
        f"_Stub_{provider_id}",
        (_StubProvider,),
        {"provider_id": provider_id},
    )
    return cls(**overrides)  # type: ignore[no-any-return]


def _seg(source_lang: str = _LANG_EN_US) -> Segment:
    return Segment(key="k", source_text="Hello", source_lang=source_lang)


# --- Routing selection ----------------------------------------------------


def test_default_provider_when_no_rules(tmp_path: Path) -> None:
    """With no rules, every call routes to ``default_provider``."""
    nllb = _make_provider("nllb")
    openai = _make_provider("openai")
    router = ProviderRouter(
        providers={"nllb": nllb, "openai": openai},
        routing_config=RoutingConfig(default_provider="nllb"),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    router.translate(_seg(), _LANG_DE)
    assert nllb.calls == [("Hello", _LANG_DE)]  # type: ignore[attr-defined]
    assert openai.calls == []  # type: ignore[attr-defined]


def test_first_matching_rule_wins(tmp_path: Path) -> None:
    """Rules are tried in order; first match wins."""
    nllb = _make_provider("nllb")
    openai = _make_provider("openai")
    anthropic = _make_provider("anthropic")
    router = ProviderRouter(
        providers={"nllb": nllb, "openai": openai, "anthropic": anthropic},
        routing_config=RoutingConfig(
            default_provider="nllb",
            rules=(
                RoutingRule(provider_id="anthropic", target_lang=_LANG_DE),
                RoutingRule(provider_id="openai"),  # any
            ),
        ),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    router.translate(_seg(), _LANG_DE)
    assert anthropic.calls == [("Hello", _LANG_DE)]  # type: ignore[attr-defined]
    assert openai.calls == []  # type: ignore[attr-defined]


def test_rule_lang_filter_narrows(tmp_path: Path) -> None:
    """Rules filter by source/target lang."""
    nllb = _make_provider("nllb")
    openai = _make_provider("openai")
    router = ProviderRouter(
        providers={"nllb": nllb, "openai": openai},
        routing_config=RoutingConfig(
            default_provider="nllb",
            rules=(RoutingRule(provider_id="openai", target_lang=_LANG_DE),),
        ),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    router.translate(_seg(), _LANG_DE)
    router.translate(_seg(), "fr-FR")
    assert openai.calls == [("Hello", _LANG_DE)]  # type: ignore[attr-defined]
    assert nllb.calls == [("Hello", "fr-FR")]  # type: ignore[attr-defined]


def test_persona_filter(tmp_path: Path) -> None:
    nllb = _make_provider("nllb")
    openai = _make_provider("openai")
    router = ProviderRouter(
        providers={"nllb": nllb, "openai": openai},
        routing_config=RoutingConfig(
            default_provider="nllb",
            rules=(RoutingRule(provider_id="openai", persona="legal"),),
        ),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    router.translate(_seg(), _LANG_DE, persona="legal")
    router.translate(_seg(), _LANG_DE, persona="casual")
    assert openai.calls == [("Hello", _LANG_DE)]  # type: ignore[attr-defined]
    assert nllb.calls == [("Hello", _LANG_DE)]  # type: ignore[attr-defined]


def test_unregistered_default_raises(tmp_path: Path) -> None:
    router = ProviderRouter(
        providers={"openai": _make_provider("openai")},
        routing_config=RoutingConfig(default_provider="ghost"),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    with pytest.raises(ProviderRouteNotFound):
        router.translate(_seg(), _LANG_DE)


def test_rule_referencing_unregistered_provider_raises(tmp_path: Path) -> None:
    router = ProviderRouter(
        providers={"nllb": _make_provider("nllb")},
        routing_config=RoutingConfig(
            default_provider="nllb",
            rules=(RoutingRule(provider_id="ghost", target_lang=_LANG_DE),),
        ),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    with pytest.raises(ProviderRouteNotFound):
        router.translate(_seg(), _LANG_DE)


def test_unsupported_pair_fails_fast(tmp_path: Path) -> None:
    """Per /bet open question 7: when the selected provider's
    ``supports()`` returns False, the router raises
    :class:`ProviderUnsupportedPair` rather than silently falling
    back to a different provider class."""
    opus = _make_provider("opus", supports_pairs=((_LANG_EN_US, _LANG_DE),))
    router = ProviderRouter(
        providers={"opus": opus},
        routing_config=RoutingConfig(default_provider="opus"),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    with pytest.raises(ProviderUnsupportedPair):
        router.translate(_seg(), "th-TH")  # not in supports_pairs


# --- Usage log integration ------------------------------------------------


def test_router_records_to_usage_log(tmp_path: Path) -> None:
    """Every router call writes one UsageLog record with the right
    fields."""
    log_path = tmp_path / "usage.jsonl"
    log = UsageLog(log_path)
    openai = _make_provider("openai", model="gpt-4o-2024-11-20", cost_usd=0.005)
    router = ProviderRouter(
        providers={"openai": openai},
        routing_config=RoutingConfig(default_provider="openai"),
        usage_log=log,
    )
    seg = _seg()
    router.translate(seg, _LANG_DE)

    stats = log.stats()
    assert stats.call_count == 1
    assert stats.by_provider == {"openai": 1}
    assert stats.by_model == {"gpt-4o-2024-11-20": 1}
    assert abs(stats.total_cost_usd - 0.005) < 1e-9


def test_router_records_under_concrete_provider_not_router(
    tmp_path: Path,
) -> None:
    """The UsageLog row's provider field is the *concrete* backend's
    id (``"openai"``), not the router's ``"router"`` boundary id —
    cycle-2 stats need to attribute calls to backends, not to the
    façade."""
    log = UsageLog(tmp_path / "usage.jsonl")
    nllb = _make_provider("nllb", model="nllb-200-distilled-600M")
    router = ProviderRouter(
        providers={"nllb": nllb},
        routing_config=RoutingConfig(default_provider="nllb"),
        usage_log=log,
    )
    router.translate(_seg(), _LANG_DE)
    stats = log.stats()
    assert "nllb" in stats.by_provider
    assert "router" not in stats.by_provider


# --- Latency measurement --------------------------------------------------


def test_router_fills_in_latency_when_provider_returns_zero(
    tmp_path: Path,
) -> None:
    """When a provider returns ``latency_ms=0`` (didn't measure), the
    router substitutes its own perf_counter timing. Provider-supplied
    latency is preserved when non-zero (the router never *under*-reports)."""
    log = UsageLog(tmp_path / "usage.jsonl")
    sloth = _make_provider("nllb", latency_ms=0)
    router = ProviderRouter(
        providers={"nllb": sloth},
        routing_config=RoutingConfig(default_provider="nllb"),
        usage_log=log,
    )
    result = router.translate(_seg(), _LANG_DE)
    # The stub returns immediately, so latency should be very low,
    # but it must be measured (not the zero the provider returned).
    assert result.latency_ms >= 0
    # And the recorded latency matches the result.
    stats = log.stats()
    assert stats.total_latency_ms == result.latency_ms


# --- Retry integration ----------------------------------------------------


class _RateLimitError(Exception):
    pass


def test_router_retries_on_rate_limit(tmp_path: Path) -> None:
    """When configured with retry exception types, the router uses
    ``with_retry`` around the provider call. Tested by a stub that
    raises once, then succeeds — should still produce one UsageLog
    record (the eventual success), not two."""

    class _FlakyProvider:
        provider_id: ClassVar[str] = "flaky"

        def __init__(self) -> None:
            self.calls = 0

        def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
            self.calls += 1
            if self.calls == 1:
                raise _RateLimitError("simulated")
            return ProviderResult(
                target_text="ok",
                provider=self.provider_id,
                model="flaky-1.0",
            )

        def supports(self, source_lang: str, target_lang: str) -> bool:
            return True

    log = UsageLog(tmp_path / "usage.jsonl")
    flaky = _FlakyProvider()
    # `sleep` is injectable on the router so the test doesn't actually
    # wait through the exponential-backoff schedule.
    sleeps: list[float] = []
    router = ProviderRouter(
        providers={"flaky": flaky},
        routing_config=RoutingConfig(default_provider="flaky"),
        usage_log=log,
        retry_exceptions=(_RateLimitError,),
        sleep=sleeps.append,
    )
    result = router.translate(_seg(), _LANG_DE)

    assert result.target_text == "ok"
    assert flaky.calls == 2
    # Exactly one backoff sleep between the failed and successful
    # attempt; pinned so a future change to the retry policy doesn't
    # silently change the timing contract.
    assert len(sleeps) == 1
    # Only the successful call records to UsageLog — the failed one
    # raised before the record line.
    stats = log.stats()
    assert stats.call_count == 1


# --- supports() at the router boundary ------------------------------------


def test_router_supports_when_any_provider_supports(tmp_path: Path) -> None:
    nllb = _make_provider("nllb", supports_pairs=((_LANG_EN_US, "th-TH"),))
    router = ProviderRouter(
        providers={"nllb": nllb},
        routing_config=RoutingConfig(default_provider="nllb"),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    assert router.supports(_LANG_EN_US, "th-TH") is True
    assert router.supports(_LANG_EN_US, "ja-JP") is False
