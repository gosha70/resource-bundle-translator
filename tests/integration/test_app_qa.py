# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S5 — Flask /qa integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Iterator

import pytest

from ainemo.app import create_app
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    Segment,
    TranslatedSegment,
)
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.tm.base import TmHit, TmStats
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_provider(provider_id: str, calls: list[str]) -> Provider:
    pid = provider_id

    class _Stub:
        provider_id: ClassVar[str] = pid

        def translate(
            self,
            segment: Segment,
            target_lang: str,
            *,
            system_prompt_addendum: str | None = None,
        ) -> ProviderResult:
            del system_prompt_addendum
            calls.append(self.provider_id)
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
            return True

    instance: Provider = _Stub()
    return instance


class _SeededTm:
    """Minimal TM stub returning a fixed list of TranslatedSegment rows."""

    def __init__(self, pairs: list[tuple[str, str, str]]) -> None:
        # pairs: (source_text, target_text, provider_id)
        self._pairs = pairs

    def lookup(self, *args: object, **kwargs: object) -> TmHit | None:
        return None

    def store(self, translated: TranslatedSegment) -> None:
        pass

    def stats(self) -> TmStats:
        return TmStats(
            segment_count=len(self._pairs),
            translation_count=len(self._pairs),
            target_lang_count=1,
            embedding_count=0,
        )

    def iter_translations(
        self, *, source_lang: str, target_lang: str
    ) -> Iterator[TranslatedSegment]:
        for idx, (source, target, provider_id) in enumerate(self._pairs):
            seg = Segment(key=f"k{idx}", source_text=source, source_lang=source_lang)
            yield TranslatedSegment(
                segment=seg,
                target_lang=target_lang,
                target_text=target,
                provider=provider_id,
                model=f"{provider_id}-model",
                confidence=None,
                source=TRANSLATION_SOURCE_PROVIDER,
            )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _kuzu_tb(tmp_path: Path) -> Iterator[KuzuTermbase]:
    tb = KuzuTermbase(tmp_path / "termbase.kuzu")
    yield tb
    tb.close()


@pytest.fixture()
def _two_provider_router(tmp_path: Path) -> tuple[ProviderRouter, list[str]]:
    calls: list[str] = []
    providers: dict[str, Provider] = {
        "alpha": _make_provider("alpha", calls),
        "beta": _make_provider("beta", calls),
    }
    log = UsageLog(tmp_path / "usage.jsonl")
    router = ProviderRouter(
        providers=providers,
        routing_config=RoutingConfig(default_provider="alpha"),
        usage_log=log,
    )
    return router, calls


@pytest.fixture()
def _single_provider_router(tmp_path: Path) -> ProviderRouter:
    calls: list[str] = []
    providers: dict[str, Provider] = {"alpha": _make_provider("alpha", calls)}
    log = UsageLog(tmp_path / "usage.jsonl")
    return ProviderRouter(
        providers=providers,
        routing_config=RoutingConfig(default_provider="alpha"),
        usage_log=log,
    )


def _seed_tm() -> _SeededTm:
    return _SeededTm(
        [
            ("hello world", "hallo welt", "alpha"),
            ("good morning", "guten morgen", "alpha"),
        ]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_qa_returns_200(
    _kuzu_tb: KuzuTermbase, _two_provider_router: tuple[ProviderRouter, list[str]]
) -> None:
    from flask import Flask

    router, _ = _two_provider_router
    app = create_app(termbase=_kuzu_tb, tm=_seed_tm(), router=router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        resp = client.get("/qa?source_lang=en&target_lang=de")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "hallo welt" in body or "hello world" in body


def test_get_qa_does_not_invoke_any_provider(
    _kuzu_tb: KuzuTermbase, _two_provider_router: tuple[ProviderRouter, list[str]]
) -> None:
    """GET /qa is pure cheap-signal computation — must not trigger a
    provider call. The opt-in flag does not run on page load."""
    from flask import Flask

    router, calls = _two_provider_router
    app = create_app(termbase=_kuzu_tb, tm=_seed_tm(), router=router)
    assert isinstance(app, Flask)
    with app.test_client() as client:
        client.get("/qa?source_lang=en&target_lang=de")
    assert calls == []


def test_segment_detail_estimates_only_selectable_providers(
    tmp_path: Path, _kuzu_tb: KuzuTermbase
) -> None:
    """Cycle-5 S5 P2 regression — the segment detail view's cost estimate
    must apply to providers the reviewer can actually choose, not the
    original (excluded-from-dropdown) provider.

    Before the fix, the route called estimate_for(row.provider, ...) — the
    same provider the dropdown explicitly excludes. After the fix, the
    route computes per-option estimates for the SELECTABLE set and the
    template renders them inside each <option>.
    """
    from flask import Flask

    calls: list[str] = []
    providers: dict[str, Provider] = {
        "alpha": _make_provider("alpha", calls),
        "beta": _make_provider("beta", calls),
    }
    log = UsageLog(tmp_path / "usage.jsonl")
    # Seed UsageLog with one beta call so estimate_for(beta, ...) returns
    # a real number (not None / "no historical cost data").
    log.record(
        provider="beta",
        model="beta-model",
        input_tokens=10,
        output_tokens=10,
        latency_ms=5,
        cost_usd=0.002,
        source_lang="de",
        target_lang="en",
        segment_fingerprint="seed",
    )
    router = ProviderRouter(
        providers=providers,
        routing_config=RoutingConfig(default_provider="alpha"),
        usage_log=log,
    )
    tm = _seed_tm()  # rows are stored with provider="alpha"
    app = create_app(termbase=_kuzu_tb, tm=tm, router=router)
    assert isinstance(app, Flask)
    rows = list(tm.iter_translations(source_lang="en", target_lang="de"))
    fp = rows[0].segment.fingerprint

    with app.test_client() as client:
        resp = client.get(f"/qa/segment/{fp}?source_lang=en&target_lang=de")

    assert resp.status_code == 200
    body = resp.data.decode()
    # The dropdown <option> for beta carries the per-provider estimate;
    # it MUST appear because beta is selectable. The original provider
    # alpha must NOT appear as a selectable <option>.
    assert "beta" in body
    assert "est. $" in body, "expected per-option estimate text, got: " + body[:500]
    # The estimate text must accompany beta (not alpha — alpha is the
    # original provider and is excluded from the dropdown).
    # We can check this loosely: the option block for alpha as a
    # selectable provider should not exist.
    assert '<option value="alpha"' not in body


def test_back_translate_rejects_same_provider(
    _kuzu_tb: KuzuTermbase, _two_provider_router: tuple[ProviderRouter, list[str]]
) -> None:
    from flask import Flask

    router, _ = _two_provider_router
    tm = _seed_tm()
    app = create_app(termbase=_kuzu_tb, tm=tm, router=router)
    assert isinstance(app, Flask)

    # Find the fingerprint of the first row.
    rows = list(tm.iter_translations(source_lang="en", target_lang="de"))
    fp = rows[0].segment.fingerprint
    original_provider = rows[0].provider

    with app.test_client() as client:
        resp = client.post(
            "/qa/back-translate",
            data={
                "segment_fingerprint": fp,
                "provider_id": original_provider,
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    assert resp.status_code == 400
    assert "different provider" in resp.data.decode().lower()


def test_back_translate_rejects_when_only_one_provider_registered(
    _kuzu_tb: KuzuTermbase, _single_provider_router: ProviderRouter
) -> None:
    from flask import Flask

    tm = _seed_tm()
    app = create_app(termbase=_kuzu_tb, tm=tm, router=_single_provider_router)
    assert isinstance(app, Flask)
    rows = list(tm.iter_translations(source_lang="en", target_lang="de"))
    fp = rows[0].segment.fingerprint

    with app.test_client() as client:
        resp = client.post(
            "/qa/back-translate",
            data={
                "segment_fingerprint": fp,
                "provider_id": "anything",
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    assert resp.status_code == 400
    assert "second provider" in resp.data.decode().lower()


def test_back_translate_rejects_unknown_provider(
    _kuzu_tb: KuzuTermbase, _two_provider_router: tuple[ProviderRouter, list[str]]
) -> None:
    from flask import Flask

    router, _ = _two_provider_router
    tm = _seed_tm()
    app = create_app(termbase=_kuzu_tb, tm=tm, router=router)
    assert isinstance(app, Flask)
    rows = list(tm.iter_translations(source_lang="en", target_lang="de"))
    fp = rows[0].segment.fingerprint

    with app.test_client() as client:
        resp = client.post(
            "/qa/back-translate",
            data={
                "segment_fingerprint": fp,
                "provider_id": "not-registered",
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    assert resp.status_code == 400
    body = resp.data.decode()
    body_lower = body.lower()
    # The error must name the unknown provider AND list the available
    # providers so an operator can debug a client-side dropdown desync.
    assert "not-registered" in body_lower
    assert "registered" in body_lower or "available" in body_lower
    # Must NOT leak Python tracebacks or internal SDK details.
    assert "Traceback" not in body
    assert "providers/router.py" not in body


def test_back_translate_records_cost_to_usage_log(
    tmp_path: Path,
    _kuzu_tb: KuzuTermbase,
) -> None:
    """Valid back-translation: records cost in UsageLog + refreshes the row
    fragment with the back-translation cosine."""
    from flask import Flask

    calls: list[str] = []
    providers: dict[str, Provider] = {
        "alpha": _make_provider("alpha", calls),
        "beta": _make_provider("beta", calls),
    }
    log_path = tmp_path / "usage.jsonl"
    router = ProviderRouter(
        providers=providers,
        routing_config=RoutingConfig(default_provider="alpha"),
        usage_log=UsageLog(log_path),
    )
    tm = _seed_tm()
    app = create_app(termbase=_kuzu_tb, tm=tm, router=router)
    assert isinstance(app, Flask)
    rows = list(tm.iter_translations(source_lang="en", target_lang="de"))
    fp = rows[0].segment.fingerprint

    with app.test_client() as client:
        resp = client.post(
            "/qa/back-translate",
            data={
                "segment_fingerprint": fp,
                "provider_id": "beta",  # different from alpha
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    assert resp.status_code == 200
    # beta provider was invoked for the back-translation.
    assert calls == ["beta"]
    # UsageLog recorded the call.
    contents = log_path.read_text(encoding="utf-8")
    assert "beta" in contents
    # Row fragment was returned (not full page); should contain the
    # back-translation surface or evidence the swap succeeded.
    body = resp.data.decode()
    assert fp in body


def test_back_translate_unsupported_pair_returns_400(
    tmp_path: Path, _kuzu_tb: KuzuTermbase
) -> None:
    """Cycle-5 S5 P2 regression — when the selected back-translation provider
    does not support the reverse language pair, ProviderRouter.translate_with
    raises ProviderUnsupportedPair. The route must catch that and surface
    400 with a concise message, not 500."""
    from flask import Flask

    calls: list[str] = []
    pid_alpha = "alpha"
    pid_strict = "strict"

    def _make_strict() -> Provider:
        class _Strict:
            provider_id: ClassVar[str] = pid_strict

            def translate(
                self,
                segment: Segment,
                target_lang: str,
                *,
                system_prompt_addendum: str | None = None,
            ) -> ProviderResult:
                del system_prompt_addendum
                calls.append(self.provider_id)
                return ProviderResult(
                    target_text="x",
                    provider=self.provider_id,
                    model="m",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=1,
                    cost_usd=0.0,
                    confidence=None,
                )

            def supports(self, source_lang: str, target_lang: str) -> bool:
                return False

        instance: Provider = _Strict()
        return instance

    providers: dict[str, Provider] = {
        pid_alpha: _make_provider(pid_alpha, calls),
        pid_strict: _make_strict(),
    }
    log = UsageLog(tmp_path / "usage.jsonl")
    router = ProviderRouter(
        providers=providers,
        routing_config=RoutingConfig(default_provider=pid_alpha),
        usage_log=log,
    )
    tm = _seed_tm()
    app = create_app(termbase=_kuzu_tb, tm=tm, router=router)
    assert isinstance(app, Flask)
    rows = list(tm.iter_translations(source_lang="en", target_lang="de"))
    fp = rows[0].segment.fingerprint

    with app.test_client() as client:
        resp = client.post(
            "/qa/back-translate",
            data={
                "segment_fingerprint": fp,
                "provider_id": pid_strict,
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    assert resp.status_code == 400
    body = resp.data.decode()
    # Pin the operator-facing message shape: provider id + reversed pair
    # must both appear so a future refactor of the abort message that
    # drops one of them trips the test.
    assert pid_strict in body
    assert "does not support" in body.lower()
    assert "de" in body and "en" in body, "expected reversed lang pair in error"
    # No Python traceback / SDK leak.
    assert "Traceback" not in body
    assert "providers/router.py" not in body


def test_back_translate_blank_fingerprint_rejected(
    _kuzu_tb: KuzuTermbase, _two_provider_router: tuple[ProviderRouter, list[str]]
) -> None:
    from flask import Flask

    router, _ = _two_provider_router
    app = create_app(termbase=_kuzu_tb, tm=_seed_tm(), router=router)
    assert isinstance(app, Flask)

    with app.test_client() as client:
        resp = client.post(
            "/qa/back-translate",
            data={
                "segment_fingerprint": "",
                "provider_id": "beta",
                "source_lang": "en",
                "target_lang": "de",
            },
        )
    assert resp.status_code == 400
