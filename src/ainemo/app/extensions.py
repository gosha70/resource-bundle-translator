# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Flask extension wiring for the AI-NEMO reviewer app.

Kept intentionally thin: actual Flask app instantiation and route
registration happen in :func:`~ainemo.app.create_app` (``__init__.py``).
This module only handles cross-cutting concerns that need to be
available in Jinja templates — specifically the HTMX static URL helper
so templates never hardcode ``/static/htmx.min.js``.
"""

from __future__ import annotations

from flask import Flask, url_for

_HTMX_STATIC_FILENAME: str = "htmx.min.js"


def htmx_static_url() -> str:
    """Return the Flask-routed URL for the vendored ``htmx.min.js``.

    Registered as a Jinja global by :func:`register_jinja_globals` so
    templates can call ``{{ htmx_static_url() }}`` without knowing the
    static-files mount path.
    """
    return url_for("static", filename=_HTMX_STATIC_FILENAME)


def register_jinja_globals(app: Flask) -> None:
    """Attach app-wide Jinja globals to *app*.

    Called once inside ``create_app`` after the Flask instance is
    created.  Idempotent — safe to call multiple times (later calls
    overwrite earlier values with the same objects).
    """
    app.jinja_env.globals["htmx_static_url"] = htmx_static_url


__all__ = ["htmx_static_url", "register_jinja_globals"]
