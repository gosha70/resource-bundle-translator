# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-5 S4 — Flask /termbase integration tests.

Test inventory (>= 9 cases):
1.  GET /termbase with empty termbase → 200 + empty-state message.
2.  GET /termbase with seeded concepts → 200 + concept rendered.
3.  GET /termbase?q=login → narrows to matching concepts only.
4.  GET /termbase?page=2 → paginates correctly (seed > 25 concepts).
5.  GET /termbase/<cid>/terms/<tid>/edit → 200 + form pre-filled.
6.  POST /termbase/<cid>/terms/<tid>/edit with new surface → updates Term, redirects.
7.  POST /termbase/<cid>/terms/<tid>/edit with blank surface → 400.
8.  POST /termbase/<cid>/terms/<tid>/edit where term_id from different concept → 400.
9.  GET /termbase/export.tbx → 200 + valid TBX XML + correct concept count.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from lxml import etree

from ainemo.app import create_app
from ainemo.core.segment import Segment
from ainemo.core.termbase._ids import TERM_SOURCE_MANUAL
from ainemo.core.termbase.base import Concept, Term
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.tm.sqlite import SqliteTranslationMemory
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

pytestmark = pytest.mark.integration

_TBX_NS: str = "urn:iso:std:iso:30042:ed-2"


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


@pytest.fixture()
def _deps(tmp_path: Path):  # type: ignore[no-untyped-def]
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


def _seed_concept(
    tb: KuzuTermbase,
    concept_id: str,
    en_surface: str,
    de_surface: str,
) -> tuple[str, str]:
    """Seed one concept with an en + de term. Returns (en_term_id, de_term_id)."""
    en_tid = f"{concept_id}-en"
    de_tid = f"{concept_id}-de"
    tb.add_concept(
        Concept(concept_id=concept_id, qid=None, definition=None, created_at=1),
        [
            Term(
                term_id=en_tid,
                concept_id=concept_id,
                lang="en",
                surface=en_surface,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            ),
            Term(
                term_id=de_tid,
                concept_id=concept_id,
                lang="de",
                surface=de_surface,
                register=None,
                part_of_speech=None,
                source=TERM_SOURCE_MANUAL,
            ),
        ],
    )
    return en_tid, de_tid


def test_get_termbase_empty(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get("/termbase")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "empty" in body.lower() or "no concept" in body.lower() or "0 concept" in body.lower()


def test_get_termbase_with_seeded_concepts(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    _seed_concept(termbase, "c-login", "login", "Anmeldung")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get("/termbase")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "c-login" in body
    assert "login" in body
    assert "Anmeldung" in body


def test_get_termbase_search_narrows(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    _seed_concept(termbase, "c-login", "login", "Anmeldung")
    _seed_concept(termbase, "c-logout", "logout", "Abmeldung")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get("/termbase?q=login&source_lang=en&target_lang=de")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "c-login" in body
    assert "c-logout" not in body


def test_get_termbase_pagination(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    for i in range(30):
        _seed_concept(termbase, f"c-{i:03d}", f"widget{i:03d}", f"Widget{i:03d}DE")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp1 = client.get("/termbase?page=1")
        resp2 = client.get("/termbase?page=2")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = resp1.data.decode()
    body2 = resp2.data.decode()
    assert "c-000" in body1
    assert "c-024" in body1
    assert "c-025" not in body1
    assert "c-025" in body2


def test_get_termbase_edit_form(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    en_tid, _ = _seed_concept(termbase, "c-login", "login", "Anmeldung")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get(f"/termbase/c-login/terms/{en_tid}/edit")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "login" in body
    assert "c-login" in body


def test_post_termbase_edit_updates_term(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    en_tid, _ = _seed_concept(termbase, "c-login", "login", "Anmeldung")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.post(
            f"/termbase/c-login/terms/{en_tid}/edit",
            data={"surface": "sign in", "register": "formal", "part_of_speech": "verb"},
        )
    assert resp.status_code in (302, 303)
    updated = next(
        t for entry in termbase.iter_concept_entries() for t in entry.terms if t.term_id == en_tid
    )
    assert updated.surface == "sign in"
    assert updated.register == "formal"
    assert updated.part_of_speech == "verb"


def test_post_termbase_edit_blank_surface_400(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    en_tid, _ = _seed_concept(termbase, "c-login", "login", "Anmeldung")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.post(
            f"/termbase/c-login/terms/{en_tid}/edit",
            data={"surface": "   ", "register": "", "part_of_speech": ""},
        )
    assert resp.status_code == 400


def test_post_termbase_edit_wrong_concept_400(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    _seed_concept(termbase, "c-login", "login", "Anmeldung")
    _, de_tid = _seed_concept(termbase, "c-logout", "logout", "Abmeldung")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.post(
            f"/termbase/c-login/terms/{de_tid}/edit",
            data={"surface": "hacked", "register": "", "part_of_speech": ""},
        )
    assert resp.status_code == 400
    term = next(
        t
        for entry in termbase.iter_concept_entries()
        if entry.concept.concept_id == "c-logout"
        for t in entry.terms
        if t.term_id == de_tid
    )
    assert term.surface == "Abmeldung"


def test_get_termbase_export_tbx(_deps):  # type: ignore[no-untyped-def]
    termbase, tm, router = _deps
    _seed_concept(termbase, "c-login", "login", "Anmeldung")
    _seed_concept(termbase, "c-logout", "logout", "Abmeldung")
    app = create_app(termbase=termbase, tm=tm, router=router)
    with app.test_client() as client:
        resp = client.get("/termbase/export.tbx")
    assert resp.status_code == 200
    assert "tbx" in resp.headers.get("Content-Disposition", "").lower()
    root = etree.fromstring(resp.data)
    body = root.find(f"{{{_TBX_NS}}}text/{{{_TBX_NS}}}body")
    assert body is not None
    concept_entries = body.findall(f"{{{_TBX_NS}}}conceptEntry")
    assert len(concept_entries) == 2
