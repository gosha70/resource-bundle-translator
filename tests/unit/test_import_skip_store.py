# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S3 ``ImportSkipStore`` contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.app.store.import_skips import ImportSkipRow, SqliteImportSkipStore, _derive_skip_id

pytestmark = pytest.mark.unit


def _row(*, reason: str = "row 2: blank source") -> ImportSkipRow:
    payload = '{"source": "", "target": "Anmeldung"}'
    return ImportSkipRow(
        skip_id=_derive_skip_id(source_path="terms.csv", row_index=2, row_payload=payload),
        source_path="terms.csv",
        source_format="csv",
        row_index=2,
        row_payload=payload,
        skip_reason=reason,
        created_at=100,
        last_retried_at=None,
    )


def test_skip_id_is_stable() -> None:
    payload = '{"source": "", "target": "Anmeldung"}'
    first = _derive_skip_id(source_path="terms.csv", row_index=2, row_payload=payload)
    second = _derive_skip_id(source_path="terms.csv", row_index=2, row_payload=payload)
    assert first == second
    assert first.startswith("skip-")


def test_sqlite_store_add_list_get_filter_remove(tmp_path: Path) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    try:
        row = _row()
        store.add(row)

        assert store.list() == (row,)
        assert store.list(source_path="terms.csv") == (row,)
        assert store.list(source_path="other.csv") == ()
        assert store.get(row.skip_id) == row

        store.remove(row.skip_id)
        assert store.get(row.skip_id) is None
    finally:
        store.close()


def test_sqlite_store_upsert_preserves_created_at_and_updates_reason(tmp_path: Path) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    try:
        row = _row()
        store.add(row)
        store.add(
            ImportSkipRow(
                skip_id=row.skip_id,
                source_path=row.source_path,
                source_format=row.source_format,
                row_index=row.row_index,
                row_payload=row.row_payload,
                skip_reason="row 2: still blank",
                created_at=999,
                last_retried_at=123,
            )
        )

        updated = store.get(row.skip_id)
        assert updated is not None
        assert updated.created_at == 100
        assert updated.skip_reason == "row 2: still blank"
        assert updated.last_retried_at == 123
    finally:
        store.close()


def test_sqlite_store_update_retry_success_removes_row(tmp_path: Path) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    try:
        row = _row()
        store.add(row)
        store.update_retry(row.skip_id, success=True, new_reason=None)
        assert store.get(row.skip_id) is None
    finally:
        store.close()


def test_sqlite_store_update_retry_failure_updates_reason(tmp_path: Path) -> None:
    store = SqliteImportSkipStore(tmp_path / "skips.sqlite")
    try:
        row = _row()
        store.add(row)
        store.update_retry(row.skip_id, success=False, new_reason="row 2: still invalid")
        updated = store.get(row.skip_id)
        assert updated is not None
        assert updated.skip_reason == "row 2: still invalid"
        assert updated.last_retried_at is not None
    finally:
        store.close()


def test_store_works_across_threads(tmp_path: Path) -> None:
    """Cycle-5 dogfood regression — the reviewer Flask app shares one
    SqliteImportSkipStore across werkzeug worker threads. Without
    `check_same_thread=False`, the second-thread call would raise
    ``sqlite3.ProgrammingError: SQLite objects created in a thread can
    only be used in that same thread``."""
    import threading

    store = SqliteImportSkipStore(tmp_path / "skips.db")
    store.add(_row())

    listed: list[tuple[ImportSkipRow, ...]] = []
    error: list[BaseException] = []

    def _worker() -> None:
        try:
            listed.append(store.list())
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=5.0)

    assert not error, f"store.list raised on worker thread: {error[0]!r}"
    assert len(listed) == 1
    assert len(listed[0]) == 1

    store.close()
