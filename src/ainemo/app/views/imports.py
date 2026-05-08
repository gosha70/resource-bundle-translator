# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Import-skip queue — cycle-5 S3."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, request

from ainemo.app._ids import ROUTE_IMPORT_REPLAY, ROUTE_IMPORT_SKIPS
from ainemo.app.store.import_skips import ImportSkipStore, single_row_source
from ainemo.core.termbase.sources.loader import load_into_termbase
from ainemo.core.termbase.sources.mapping import FieldMapping, field_mapping_from_yaml_dict

blueprint = Blueprint("imports", __name__)

_TEMPLATE_LIST = "imports/list.html"
_TEMPLATE_ROW = "imports/_row.html"


@blueprint.get("/imports")
def import_skips() -> str:
    """Render the import-skip retry queue."""
    store = _store_or_none()
    source_path = request.args.get("source_path") or None
    rows = store.list(source_path=source_path) if store is not None else ()
    return render_template(
        _TEMPLATE_LIST,
        rows=rows,
        source_path=source_path or "",
        store_configured=store is not None,
    )


@blueprint.post("/imports/retry")
def import_replay() -> str:
    """Retry one skipped row with optional payload edits."""
    store = _store_or_400()
    skip_id = request.form.get("skip_id", "").strip()
    map_config = request.form.get("map_config", "").strip()
    row_payload = request.form.get("row_payload", "")
    namespace = request.form.get("namespace", "").strip() or None

    if not skip_id:
        abort(400, description="skip_id is required")
    if not map_config:
        abort(400, description="map_config is required")

    row = store.get(skip_id)
    if row is None:
        abort(404, description=f"import skip row not found: {skip_id}")

    mapping = _load_mapping(Path(map_config))
    edited_row = replace(row, row_payload=row_payload)
    try:
        source = single_row_source(edited_row, mapping)
    except ValueError as exc:
        abort(400, description=str(exc))
    report = load_into_termbase(
        current_app.extensions["ainemo"].termbase,
        source,
        namespace=namespace,
    )

    if report.rows_skipped:
        reason = report.skipped_details[0]
        store.update_retry(skip_id, success=False, new_reason=reason)
        updated = store.get(skip_id)
        if updated is None:
            abort(500, description="retry failed but skip row disappeared")
        return render_template(_TEMPLATE_ROW, row=updated, status="retry failed")

    store.update_retry(skip_id, success=True, new_reason=None)
    return ""


def _load_mapping(path: Path) -> FieldMapping:
    import yaml
    from pydantic import ValidationError

    if not path.exists():
        abort(400, description=f"map_config does not exist: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return field_mapping_from_yaml_dict(raw)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        abort(400, description=f"invalid map_config {path}: {exc}")


def _store_or_none() -> ImportSkipStore | None:
    store = current_app.extensions["ainemo"].import_skips
    return store if isinstance(store, ImportSkipStore) else None


def _store_or_400() -> ImportSkipStore:
    store = _store_or_none()
    if store is None:
        abort(400, description="ImportSkipStore is not configured")
    return store


import_skips.__name__ = ROUTE_IMPORT_SKIPS
import_replay.__name__ = ROUTE_IMPORT_REPLAY


def register_imports(app: object) -> None:
    """Register the import-skip queue blueprint."""
    from flask import Flask

    if isinstance(app, Flask):
        app.register_blueprint(blueprint)


__all__ = ["blueprint", "register_imports"]
