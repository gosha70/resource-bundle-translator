# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Persona inspector — cycle-5 S6.

Read-only Flask view onto the cycle-3 persona system. Lists the personas
synced into the termbase, shows each persona's read-only fields, and
exposes a preview-hits form that calls
:func:`~ainemo.core.termbase.glossary.build_glossary_block` so the
reviewer can see *exactly* the system-prompt addendum the pipeline would
inject for a candidate segment.

Persona editing is explicitly out of scope per the cycle-5 pitch
(``rabbit-hole`` rule: persona authoring is a deployment / packaging
question deferred to cycle-6+ if real users ask).
"""

from __future__ import annotations

from typing import Final

from flask import Blueprint, abort, current_app, render_template, request

from ainemo.app._ids import (
    ROUTE_PERSONA_DETAIL,
    ROUTE_PERSONA_LIST,
    ROUTE_PERSONA_PREVIEW,
)
from ainemo.core.termbase.base import Persona, Termbase
from ainemo.core.termbase.glossary import build_glossary_block

# Default language pair shown in the preview-hits form when query params
# / form fields are absent.
_DEFAULT_SOURCE_LANG: Final = "en"
_DEFAULT_TARGET_LANG: Final = "de"

# Template paths.
_TEMPLATE_LIST: Final = "personas/list.html"
_TEMPLATE_DETAIL: Final = "personas/detail.html"
_TEMPLATE_PREVIEW: Final = "personas/_preview.html"

blueprint = Blueprint("personas", __name__)


@blueprint.get("/personas")
def personas_list() -> str:
    """Render the read-only persona list."""
    ext = current_app.extensions["ainemo"]
    tb: Termbase = ext.termbase
    personas = tb.list_personas()
    return render_template(_TEMPLATE_LIST, personas=personas)


@blueprint.get("/personas/<persona_id>")
def personas_detail(persona_id: str) -> str:
    """Render a single persona's detail page + preview-hits form."""
    ext = current_app.extensions["ainemo"]
    tb: Termbase = ext.termbase
    persona = tb.get_persona(persona_id)
    if persona is None:
        abort(404, description=f"Persona {persona_id!r} is not synced into the termbase.")
    return render_template(
        _TEMPLATE_DETAIL,
        persona=persona,
        default_source_lang=_DEFAULT_SOURCE_LANG,
        default_target_lang=_DEFAULT_TARGET_LANG,
    )


@blueprint.post("/personas/<persona_id>/preview-hits")
def personas_preview(persona_id: str) -> str:
    """Render the byte-equivalent glossary block the pipeline would
    inject for the posted segment, via the shared
    :func:`build_glossary_block` builder.

    Form fields: ``source_text`` (required), ``source_lang``,
    ``target_lang``. Unknown ``persona_id`` -> 404; blank
    ``source_text`` -> 400 (defensive against direct POSTs that bypass
    the rendered form).

    CSRF-exempt: the route performs a read-only termbase lookup with
    no state mutation, and the cycle-5 reviewer app is single-user-
    localhost by design (CLAUDE.md § Architecture Rules: *Local-first*).
    Multi-user / cross-origin protection lands when the cycle-6+
    auth surface lands, alongside Flask-WTF wiring for every cycle-5
    POST route.
    """
    ext = current_app.extensions["ainemo"]
    tb: Termbase = ext.termbase
    persona: Persona | None = tb.get_persona(persona_id)
    if persona is None:
        abort(404, description=f"Persona {persona_id!r} is not synced into the termbase.")

    source_text: str = request.form.get("source_text", "").strip()
    source_lang: str = request.form.get("source_lang", _DEFAULT_SOURCE_LANG).strip()
    target_lang: str = request.form.get("target_lang", _DEFAULT_TARGET_LANG).strip()

    if not source_text:
        abort(400, description="source_text is required for preview-hits.")
    if not source_lang or not target_lang:
        abort(400, description="source_lang and target_lang must be non-blank.")

    block = build_glossary_block(
        tb,
        persona,
        source_text=source_text,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    return render_template(
        _TEMPLATE_PREVIEW,
        persona=persona,
        source_text=source_text,
        source_lang=source_lang,
        target_lang=target_lang,
        block=block,
    )


personas_list.__name__ = ROUTE_PERSONA_LIST
personas_detail.__name__ = ROUTE_PERSONA_DETAIL
personas_preview.__name__ = ROUTE_PERSONA_PREVIEW


def register_personas(app: object) -> None:
    """Register the personas blueprint on *app*. Called from
    :func:`ainemo.app.create_app` once S6 is active."""
    from flask import Flask

    if isinstance(app, Flask):
        app.register_blueprint(blueprint)


__all__ = ["blueprint", "register_personas"]
