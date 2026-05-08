# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S1 — Flask app smoke tests.

Tests:
1. ``create_app`` returns a Flask instance with the expected routes.
2. ``GET /`` returns 200 and renders the landing page.
3. ``GET /static/htmx.min.js`` returns 200 and bytes match
   ``HTMX_VENDORED_SHA256`` (no-CDN regression test).
4. ``nemo app run --help`` exits 0 with expected flags.
5. ``AppConfig`` rejects unknown fields (``extra="forbid"`` regression).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from ainemo.app import create_app
from ainemo.app._ids import HTMX_VENDORED_SHA256, ROUTE_INDEX
from ainemo.app.config import AppConfig
from ainemo.core.segment import Segment
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.tm.sqlite import SqliteTranslationMemory
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test-doubles
# ---------------------------------------------------------------------------


class _NoOpProvider:
    """Minimal stub provider — echoes source text, zero cost."""

    provider_id: ClassVar[str] = PROVIDER_ID_NOOP

    def translate(
        self,
        segment: Segment,
        target_lang: str,
        *,
        system_prompt_addendum: str | None = None,
    ) -> ProviderResult:
        del system_prompt_addendum
        return ProviderResult(
            target_text=segment.source_text,
            provider=PROVIDER_ID_NOOP,
            model=PROVIDER_ID_NOOP,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
            cost_usd=None,
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _deps(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Yield (termbase, tm, router) backed by isolated tmp dirs."""
    tb_path = tmp_path / "termbase.kuzu"
    tm_path = tmp_path / "tm.sqlite"
    log_path = tmp_path / "usage.jsonl"

    termbase = KuzuTermbase(tb_path)
    tm = SqliteTranslationMemory(tm_path)
    noop: Provider = _NoOpProvider()
    router = ProviderRouter(
        providers={PROVIDER_ID_NOOP: noop},
        routing_config=RoutingConfig(default_provider=PROVIDER_ID_NOOP),
        usage_log=UsageLog(log_path),
    )
    yield termbase, tm, router
    tm.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_app_returns_flask_instance(_deps):  # type: ignore[no-untyped-def]
    """create_app() must return a Flask app without raising."""
    from flask import Flask

    termbase, tm, router = _deps
    app = create_app(termbase=termbase, tm=tm, router=router)
    assert isinstance(app, Flask)


def test_create_app_registers_index_route(_deps):  # type: ignore[no-untyped-def]
    """The index route must be registered under the ROUTE_INDEX name."""
    termbase, tm, router = _deps
    app = create_app(termbase=termbase, tm=tm, router=router)
    # url_for requires a request context (not just app context) to build
    # URLs without SERVER_NAME configured.
    with app.test_request_context():
        from flask import url_for

        url = url_for(ROUTE_INDEX)
    assert url == "/"


def test_get_index_returns_200(_deps):  # type: ignore[no-untyped-def]
    """GET / must return HTTP 200 with HTML containing the landing copy."""
    termbase, tm, router = _deps
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "AI-NEMO" in body


def test_get_index_references_htmx(_deps):  # type: ignore[no-untyped-def]
    """The landing page HTML must load HTMX from the static path, not a CDN."""
    termbase, tm, router = _deps
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get("/")
    body = resp.data.decode("utf-8")
    # Must reference the local static file, not any CDN domain.
    assert "htmx.min.js" in body
    assert "unpkg.com" not in body
    assert "cdn.jsdelivr.net" not in body


def test_get_static_htmx_returns_200_and_matches_sha256(_deps):  # type: ignore[no-untyped-def]
    """GET /static/htmx.min.js must be served by Flask (not redirected to
    a CDN) and its sha256 must equal HTMX_VENDORED_SHA256 declared in _ids.py.

    This is the no-CDN regression test required by S1: if someone swaps the
    vendored file for a CDN script tag the sha256 assertion fails immediately.
    """
    termbase, tm, router = _deps
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get("/static/htmx.min.js")
    assert resp.status_code == 200
    actual_sha256 = hashlib.sha256(resp.data).hexdigest()
    assert actual_sha256 == HTMX_VENDORED_SHA256, (
        f"htmx.min.js sha256 mismatch — expected {HTMX_VENDORED_SHA256!r}, "
        f"got {actual_sha256!r}. "
        "Did someone replace the vendored file with a CDN link?"
    )


def test_nemo_app_run_help_exits_zero() -> None:
    """``nemo app run --help`` must exit 0 and list the expected flags."""
    result = subprocess.run(
        [sys.executable, "-m", "ainemo.cli", "app", "run", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    help_text = result.stdout + result.stderr
    assert "--host" in help_text
    assert "--port" in help_text
    assert "--debug" in help_text
    assert "--termbase-path" in help_text
    assert "--tm-path" in help_text


def test_app_config_rejects_unknown_fields() -> None:
    """AppConfig with extra="forbid" must raise on unknown keyword args."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AppConfig(unknown_field="oops")  # type: ignore[call-arg]


def test_app_config_rejects_out_of_range_port() -> None:
    """AppConfig must reject port values outside 1–65535."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AppConfig(port=0)

    with pytest.raises(pydantic.ValidationError):
        AppConfig(port=99999)


def test_app_config_defaults_are_correct() -> None:
    """AppConfig() defaults must match the constants declared in _ids.py."""
    from ainemo.app._ids import DEFAULT_HOST, DEFAULT_IMPORT_SKIPS_PATH, DEFAULT_PORT

    cfg = AppConfig()
    assert cfg.host == DEFAULT_HOST
    assert cfg.port == DEFAULT_PORT
    assert cfg.debug is False
    assert cfg.secret_key is None
    assert str(cfg.import_skips_path) == DEFAULT_IMPORT_SKIPS_PATH


def test_ainemo_ext_stored_on_app_extensions(_deps):  # type: ignore[no-untyped-def]
    """Injected deps must be reachable via app.extensions['ainemo']."""
    termbase, tm, router = _deps
    app = create_app(termbase=termbase, tm=tm, router=router)
    ext = app.extensions["ainemo"]
    assert ext.termbase is termbase
    assert ext.tm is tm
    assert ext.router is router
    assert ext.import_skips is None


def test_nemo_app_run_invalid_port_exits_usage(tmp_path: Path) -> None:
    """`nemo app run --port 99999` must exit 2 with a clean stderr message
    and no Python traceback.

    Regression for the S1 review finding: AppConfig validation errors used
    to leak Pydantic tracebacks at the CLI boundary. Mirrors the cycle-4
    importer-CLI operator-error pattern (clean stderr, exit 2).
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ainemo.cli",
            "app",
            "run",
            "--port",
            "99999",
            "--termbase-path",
            str(tmp_path / "termbase.kuzu"),
            "--tm-path",
            str(tmp_path / "tm.sqlite"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, (
        f"expected exit 2 for invalid port, got {result.returncode}; stderr={result.stderr!r}"
    )
    # No Python traceback in stderr.
    assert "Traceback" not in result.stderr
    assert "ValidationError" not in result.stderr
    # Operator-friendly message.
    assert "Invalid `nemo app run` configuration" in result.stderr
