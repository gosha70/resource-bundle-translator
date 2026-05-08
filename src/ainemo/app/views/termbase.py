# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Termbase curation — cycle-5 S4.

Routes
------
GET  /termbase                                 Paginated concept list with
                                               optional search filter.
GET  /termbase/<concept_id>/terms/<term_id>/edit  Edit form for one Term.
POST /termbase/<concept_id>/terms/<term_id>/edit  Apply edits; redirect to list.
GET  /termbase/export.tbx                     Stream termbase as TBX 3.0.
"""

from __future__ import annotations

import datetime
from typing import Final

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from ainemo.app._ids import ROUTE_TERMBASE_EDIT, ROUTE_TERMBASE_EXPORT, ROUTE_TERMBASE_LIST
from ainemo.core.termbase.base import ConceptEntry, Term, Termbase
from ainemo.core.termbase.tbx.exporter import TbxExporter

blueprint = Blueprint("termbase", __name__)

_PAGE_SIZE: Final = 25
_DEFAULT_SOURCE_LANG: Final = "en"
_DEFAULT_TARGET_LANG: Final = "de"

_TEMPLATE_LIST: Final = "termbase/list.html"
_TEMPLATE_EDIT: Final = "termbase/edit.html"

_REGISTER_OPTIONS: Final = ("", "formal", "casual", "neutral")


def _get_term(tb: Termbase, concept_id: str, term_id: str) -> Term | None:
    for entry in tb.iter_concept_entries():
        if entry.concept.concept_id != concept_id:
            continue
        for term in entry.terms:
            if term.term_id == term_id:
                return term
        return None
    return None


@blueprint.get("/termbase")
def termbase_list() -> str:
    ext = current_app.extensions["ainemo"]
    tb: Termbase = ext.termbase

    q: str = request.args.get("q", "").strip()
    source_lang: str = request.args.get("source_lang", _DEFAULT_SOURCE_LANG)
    target_lang: str = request.args.get("target_lang", _DEFAULT_TARGET_LANG)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    if q:
        hits = tb.lookup_concepts_for(q, source_lang, target_lang)
        matching_ids = {h.concept.concept_id for h in hits}
        all_entries: list[ConceptEntry] = [
            e for e in tb.iter_concept_entries() if e.concept.concept_id in matching_ids
        ]
    else:
        all_entries = list(tb.iter_concept_entries())

    total = len(all_entries)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * _PAGE_SIZE
    page_entries = all_entries[start : start + _PAGE_SIZE]

    return render_template(
        _TEMPLATE_LIST,
        entries=page_entries,
        total=total,
        page=page,
        total_pages=total_pages,
        q=q,
        source_lang=source_lang,
        target_lang=target_lang,
        has_results=bool(all_entries),
        search_performed=bool(q),
    )


@blueprint.get("/termbase/<concept_id>/terms/<term_id>/edit")
def termbase_edit_get(concept_id: str, term_id: str) -> str:
    ext = current_app.extensions["ainemo"]
    tb: Termbase = ext.termbase

    term = _get_term(tb, concept_id, term_id)
    if term is None:
        abort(400, description=f"term {term_id!r} does not belong to concept {concept_id!r}")

    return render_template(
        _TEMPLATE_EDIT,
        term=term,
        concept_id=concept_id,
        register_options=_REGISTER_OPTIONS,
    )


@blueprint.post("/termbase/<concept_id>/terms/<term_id>/edit")
def termbase_edit_post(concept_id: str, term_id: str) -> Response:
    ext = current_app.extensions["ainemo"]
    tb: Termbase = ext.termbase

    term = _get_term(tb, concept_id, term_id)
    if term is None:
        abort(400, description=f"term {term_id!r} does not belong to concept {concept_id!r}")

    surface: str = request.form.get("surface", "").strip()
    register_raw: str = request.form.get("register", "").strip()
    part_of_speech_raw: str = request.form.get("part_of_speech", "").strip()

    if not surface:
        abort(400, description="surface must be non-blank")

    register: str | None = register_raw if register_raw else None
    part_of_speech: str | None = part_of_speech_raw if part_of_speech_raw else None

    try:
        tb.update_term(term_id, surface=surface, register=register, part_of_speech=part_of_speech)
    except ValueError as exc:
        abort(400, description=str(exc))

    return redirect(url_for("termbase.termbase_list"))


@blueprint.get("/termbase/export.tbx")
def termbase_export() -> Response:
    ext = current_app.extensions["ainemo"]
    tb: Termbase = ext.termbase

    payload: bytes = TbxExporter(tb).export_bytes()
    today = datetime.date.today().isoformat()
    return Response(
        payload,
        mimetype="application/x-tbx",
        headers={"Content-Disposition": f'attachment; filename="termbase-{today}.tbx"'},
    )


termbase_list.__name__ = ROUTE_TERMBASE_LIST
termbase_edit_get.__name__ = ROUTE_TERMBASE_EDIT
termbase_export.__name__ = ROUTE_TERMBASE_EXPORT


def register_termbase(app: object) -> None:
    from flask import Flask

    if isinstance(app, Flask):
        app.register_blueprint(blueprint)


__all__ = ["blueprint", "register_termbase"]
