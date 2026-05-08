# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Flask reviewer + admin app — cycle-5 DI factory.

The public surface of this package is :func:`create_app`, a
protocol-first factory that wires the reviewer app without depending
on any concrete backend class.  Concrete types (``KuzuTermbase``,
``SqliteTranslationMemory``, ``ProviderRouter``) are constructed in
:mod:`ainemo.cli.app_commands` and injected here so tests can swap in
doubles.

Dependency namespace:
    All injected dependencies are stored on ``app.extensions["ainemo"]``
    as a frozen :class:`_AinemoExtensions` dataclass so later scopes
    (S2–S6 views) can reach them via ``current_app.extensions["ainemo"]``
    without importing the factory.

Route registration (S1 only):
    S1 registers ``GET /`` → renders ``_index.html`` landing page.
    S2–S6 views register their own routes in their respective
    ``views/`` modules; they call a thin ``register_<view>(app)``
    helper to keep this file small.

``ImportSkipStore`` forward declaration:
    ``import_skips`` is typed ``object | None`` in S1 because
    ``ImportSkipStore`` (the Protocol) lives in S3.  S3 narrows the
    type annotation once the Protocol exists; S1 ships without S3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from flask import Flask, render_template

from ainemo.app._ids import ROUTE_INDEX
from ainemo.app.config import AppConfig
from ainemo.app.extensions import register_jinja_globals
from ainemo.core.termbase.base import Termbase
from ainemo.core.tm.base import TranslationMemory
from ainemo.providers.router import ProviderRouter

if TYPE_CHECKING:
    from ainemo.app.store.import_skips import ImportSkipStore

_AINEMO_EXT_KEY: str = "ainemo"
_TEMPLATE_INDEX: str = "_index.html"


@dataclass(frozen=True)
class _AinemoExtensions:
    """Frozen namespace for injected dependencies on ``app.extensions``.

    Stored under ``app.extensions["ainemo"]`` so S2–S6 view modules can
    access dependencies via ``current_app.extensions["ainemo"].<field>``
    without re-importing the factory.

    ``import_skips`` is the cycle-5 S3 store behind the ``/imports`` queue.
    """

    termbase: Termbase
    tm: TranslationMemory
    router: ProviderRouter
    import_skips: ImportSkipStore | None
    config: AppConfig


def create_app(
    *,
    termbase: Termbase,
    tm: TranslationMemory,
    router: ProviderRouter,
    import_skips: ImportSkipStore | None = None,
    config: AppConfig | None = None,
) -> Flask:
    """Create and return a configured Flask app instance.

    Parameters
    ----------
    termbase:
        The cycle-3 ``Termbase`` Protocol implementation.  Tests pass a
        ``MemoryTermbase`` double; the CLI passes ``KuzuTermbase``.
    tm:
        The cycle-1 ``TranslationMemory`` Protocol implementation.
    router:
        The cycle-2 ``ProviderRouter``.
    import_skips:
        The cycle-5 S3 ``ImportSkipStore`` implementation, or ``None``
        (default) when the store is not needed (S1/S2 usage).  S3
        populates this with a ``SqliteImportSkipStore``.
    config:
        Runtime configuration.  ``None`` → ``AppConfig()`` defaults
        (``127.0.0.1:5050``, no debug, no persistent secret_key).

    Returns
    -------
    Flask
        A fully configured Flask app ready for ``app.run()`` or the
        Flask test client.
    """
    resolved_config = config if config is not None else AppConfig()

    app = Flask(__name__)

    # Flask session secret: use the configured value if provided; otherwise
    # Flask will generate a random secret per process (fine for
    # single-user-localhost — see AppConfig.secret_key docstring).
    if resolved_config.secret_key is not None:
        app.secret_key = resolved_config.secret_key

    # Store injected dependencies on the Flask extensions dict so view
    # modules (S2–S6) can reach them via current_app.extensions["ainemo"].
    app.extensions[_AINEMO_EXT_KEY] = _AinemoExtensions(
        termbase=termbase,
        tm=tm,
        router=router,
        import_skips=import_skips,
        config=resolved_config,
    )

    register_jinja_globals(app)
    _register_routes(app)

    from ainemo.app.views.promote import register_promote

    register_promote(app)
    from ainemo.app.views.imports import register_imports

    register_imports(app)

    from ainemo.app.views.termbase import register_termbase

    register_termbase(app)

    from ainemo.app.views.qa import register_qa

    register_qa(app)

    return app


def _register_routes(app: Flask) -> None:
    """Register S1 routes.  S2–S6 add their own via register_<view>(app)."""

    @app.get("/")
    def index() -> str:
        return render_template(_TEMPLATE_INDEX)

    # Assign the Flask endpoint name declared in _ids.py so url_for() works.
    index.__name__ = ROUTE_INDEX


__all__ = ["AppConfig", "create_app"]
