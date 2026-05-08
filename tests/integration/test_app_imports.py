# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S3 — Flask /imports integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Iterator

import pytest

from ainemo.app import create_app
from ainemo.app.store.import_skips import ImportSkipRow, SqliteImportSkipStore, _derive_skip_id
from ainemo.core.segment import Segment, TranslatedSegment
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.tm.base import TmHit, TmStats
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

pytestmark = pytest.mark.integration


class _NoOpProvider:
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


class _EmptyTm:
    def lookup(self, *args: object, **kwargs: object) -> TmHit | None:
        return None

    def store(self, translated: TranslatedSegment) -> None:
        pass

    def stats(self) -> TmStats:
        return TmStats(segment_count=0, translation_count=0, target_lang_count=0, embedding_count=0)

    def iter_translations(
        self, *, source_lang: str, target_lang: str
    ) -> Iterator[TranslatedSegment]:
        return
        yield


@pytest.fixture()
def _router(tmp_path: Path) -> ProviderRouter:
    noop: Provider = _NoOpProvider()
    return ProviderRouter(
        providers={PROVIDER_ID_NOOP: noop},
        routing_config=RoutingConfig(default_provider=PROVIDER_ID_NOOP),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )


@pytest.fixture()
def _mapping_path(tmp_path: Path) -> Path:
    path = tmp_path / "mapping.yaml"
    path.write_text(
        "source_lang: en\nsource_column: source\ntarget_columns:\n  de: target\n",
        encoding="utf-8",
    )
    return path


def _skip_row(*, payload: str) -> ImportSkipRow:
    return ImportSkipRow(
        skip_id=_derive_skip_id(source_path="terms.csv", row_index=2, row_payload=payload),
        source_path="terms.csv",
        source_format="csv",
        row_index=2,
        row_payload=payload,
        skip_reason="row 2: blank 'source' cell",
        created_at=100,
        last_retried_at=None,
    )


def _app(
    tmp_path: Path,
    router: ProviderRouter,
    *,
    store: SqliteImportSkipStore | None,
) -> tuple[object, KuzuTermbase]:
    tb = KuzuTermbase(tmp_path / "termbase.kuzu")
    app = create_app(termbase=tb, tm=_EmptyTm(), router=router, import_skips=store)
    return app, tb


def test_get_imports_lists_skip_rows(tmp_path: Path, _router: ProviderRouter) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    row = _skip_row(payload='{"source": "", "target": "Anmeldung"}')
    store.add(row)
    app, tb = _app(tmp_path, _router, store=store)
    try:
        from flask import Flask

        assert isinstance(app, Flask)
        with app.test_client() as client:
            resp = client.get("/imports")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert row.skip_id in body
        assert "blank" in body
    finally:
        tb.close()
        store.close()


def test_get_imports_without_store_renders_message(tmp_path: Path, _router: ProviderRouter) -> None:
    app, tb = _app(tmp_path, _router, store=None)
    try:
        from flask import Flask

        assert isinstance(app, Flask)
        with app.test_client() as client:
            resp = client.get("/imports")
        assert resp.status_code == 200
        assert "not configured" in resp.data.decode()
    finally:
        tb.close()


def test_retry_success_removes_row_and_imports_concept(
    tmp_path: Path, _router: ProviderRouter, _mapping_path: Path
) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    row = _skip_row(payload='{"source": "", "target": "Anmeldung"}')
    store.add(row)
    app, tb = _app(tmp_path, _router, store=store)
    try:
        from flask import Flask

        assert isinstance(app, Flask)
        with app.test_client() as client:
            resp = client.post(
                "/imports/retry",
                data={
                    "skip_id": row.skip_id,
                    "map_config": str(_mapping_path),
                    "row_payload": '{"source": "login", "target": "Anmeldung"}',
                },
            )

        assert resp.status_code == 200
        assert resp.data == b""
        assert store.get(row.skip_id) is None
        assert tb.stats().concept_count == 1
    finally:
        tb.close()
        store.close()


def test_retry_failure_updates_reason(
    tmp_path: Path, _router: ProviderRouter, _mapping_path: Path
) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    row = _skip_row(payload='{"source": "", "target": "Anmeldung"}')
    store.add(row)
    app, tb = _app(tmp_path, _router, store=store)
    try:
        from flask import Flask

        assert isinstance(app, Flask)
        with app.test_client() as client:
            resp = client.post(
                "/imports/retry",
                data={
                    "skip_id": row.skip_id,
                    "map_config": str(_mapping_path),
                    "row_payload": '{"source": "", "target": "Anmeldung"}',
                },
            )

        assert resp.status_code == 200
        updated = store.get(row.skip_id)
        assert updated is not None
        assert "blank" in updated.skip_reason
        assert updated.last_retried_at is not None
        assert tb.stats().concept_count == 0
    finally:
        tb.close()
        store.close()


def test_retry_missing_mapping_returns_400_and_keeps_row(
    tmp_path: Path, _router: ProviderRouter
) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    row = _skip_row(payload='{"source": "", "target": "Anmeldung"}')
    store.add(row)
    app, tb = _app(tmp_path, _router, store=store)
    try:
        from flask import Flask

        assert isinstance(app, Flask)
        with app.test_client() as client:
            resp = client.post(
                "/imports/retry",
                data={
                    "skip_id": row.skip_id,
                    "map_config": str(tmp_path / "missing.yaml"),
                    "row_payload": '{"source": "login", "target": "Anmeldung"}',
                },
            )

        assert resp.status_code == 400
        assert store.get(row.skip_id) is not None
        assert tb.stats().concept_count == 0
    finally:
        tb.close()
        store.close()


def test_retry_unknown_skip_id_returns_404(
    tmp_path: Path, _router: ProviderRouter, _mapping_path: Path
) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    app, tb = _app(tmp_path, _router, store=store)
    try:
        from flask import Flask

        assert isinstance(app, Flask)
        with app.test_client() as client:
            resp = client.post(
                "/imports/retry",
                data={
                    "skip_id": "skip-missing",
                    "map_config": str(_mapping_path),
                    "row_payload": '{"source": "login", "target": "Anmeldung"}',
                },
            )
        assert resp.status_code == 404
    finally:
        tb.close()
        store.close()
