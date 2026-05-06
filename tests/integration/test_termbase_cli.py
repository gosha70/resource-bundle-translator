# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-3 S5 — `nemo termbase` CLI integration tests.

Each test invokes :func:`ainemo.cli.main` (the `nemo` console-script
entry point) with an explicit argv list, against an isolated
temporary termbase / TM directory so the test suite does not touch
any real `.ainemo/` state.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from ainemo.cli import main as cli_main
from ainemo.cli.termbase_commands import run_termbase
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    Segment,
    TranslatedSegment,
)
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.tm.sqlite import SqliteTranslationMemory

pytestmark = pytest.mark.integration


_PACKAGE_PERSONA_DIR = Path(__file__).parent.parent.parent / "src" / "ainemo" / "personas"
_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tbx"


# --- Init ---


def test_init_creates_termbase_with_starter_personas(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tb_path = tmp_path / "tb.kuzu"
    rc = cli_main(
        [
            "termbase",
            "init",
            "--termbase-path",
            str(tb_path),
            "--persona-dir",
            str(_PACKAGE_PERSONA_DIR),
        ]
    )
    assert rc == 0
    assert tb_path.exists()
    captured = capsys.readouterr()
    assert "Initialized termbase" in captured.out
    assert "3 starter personas" in captured.out

    tb = KuzuTermbase(tb_path)
    try:
        assert tb.stats().persona_count == 3
    finally:
        tb.close()


def test_init_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tb_path = tmp_path / "tb.kuzu"
    args = [
        "termbase",
        "init",
        "--termbase-path",
        str(tb_path),
        "--persona-dir",
        str(_PACKAGE_PERSONA_DIR),
    ]
    assert cli_main(args) == 0
    capsys.readouterr()
    assert cli_main(args) == 0  # second run is a no-op

    tb = KuzuTermbase(tb_path)
    try:
        assert tb.stats().persona_count == 3
    finally:
        tb.close()


# --- Import / Export ---


def test_import_loads_tbx_into_termbase(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tb_path = tmp_path / "tb.kuzu"
    rc = cli_main(
        [
            "termbase",
            "import",
            str(_FIXTURE_DIR / "weblate-software-en-de.tbx"),
            "--termbase-path",
            str(tb_path),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Imported 3 concepts" in captured.out
    assert "6 terms" in captured.out

    tb = KuzuTermbase(tb_path)
    try:
        assert tb.stats().concept_count == 3
    finally:
        tb.close()


def test_import_missing_file_fails_with_usage_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli_main(
        [
            "termbase",
            "import",
            str(tmp_path / "does-not-exist.tbx"),
            "--termbase-path",
            str(tmp_path / "tb.kuzu"),
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


def test_export_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tb_path = tmp_path / "tb.kuzu"
    out_path = tmp_path / "out.tbx"
    # Import first to populate.
    cli_main(
        [
            "termbase",
            "import",
            str(_FIXTURE_DIR / "weblate-software-en-de.tbx"),
            "--termbase-path",
            str(tb_path),
        ]
    )
    capsys.readouterr()
    rc = cli_main(
        [
            "termbase",
            "export",
            str(out_path),
            "--termbase-path",
            str(tb_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    payload = out_path.read_bytes()
    assert payload.startswith(b"<?xml")
    assert b"conceptEntry" in payload


# --- Stats ---


def test_stats_after_import(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tb_path = tmp_path / "tb.kuzu"
    cli_main(
        [
            "termbase",
            "import",
            str(_FIXTURE_DIR / "weblate-software-en-de.tbx"),
            "--termbase-path",
            str(tb_path),
        ]
    )
    capsys.readouterr()
    rc = cli_main(["termbase", "stats", "--termbase-path", str(tb_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "concepts: 3" in captured.out
    assert "domains:  1" in captured.out


def test_stats_missing_termbase_fails_with_usage_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli_main(["termbase", "stats", "--termbase-path", str(tmp_path / "missing.kuzu")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


# --- Promote ---


def _seed_tm(tm_path: Path) -> None:
    """Seed a synthetic TM where 'login' appears in 6 segments and
    consistently maps to 'Anmeldung' — meets default thresholds."""
    tm = SqliteTranslationMemory(tm_path)
    try:
        for index in range(6):
            seg = Segment(
                key=f"k{index}",
                source_text=f"login row {index}",
                source_lang="en",
            )
            tm.store(
                TranslatedSegment(
                    segment=seg,
                    target_lang="de",
                    target_text="Anmeldung",
                    provider="noop",
                    model="",
                    confidence=None,
                    source=TRANSLATION_SOURCE_PROVIDER,
                )
            )
    finally:
        tm.close()


def test_promote_accept_all_writes_concepts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tm_path = tmp_path / "tm.sqlite"
    tb_path = tmp_path / "tb.kuzu"
    _seed_tm(tm_path)
    rc = cli_main(
        [
            "termbase",
            "promote",
            "--source-lang",
            "en",
            "--target-lang",
            "de",
            "--tm-path",
            str(tm_path),
            "--termbase-path",
            str(tb_path),
            "--accept-all",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Promoted" in captured.out

    tb = KuzuTermbase(tb_path)
    try:
        # At least one concept landed (the "login" n-gram).
        assert tb.stats().concept_count >= 1
    finally:
        tb.close()


def test_promote_accept_all_is_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Regression for the cycle-3 S5 P2 finding: re-running
    # `nemo termbase promote --accept-all` against unchanged TM
    # data must NOT duplicate concepts/terms. The fix replaces the
    # previous UUID4 fallback with a content-addressed
    # `tm-promo-<sha256>` derived from
    # (source_lang, target_lang, source_ngram, suggested_target).
    tm_path = tmp_path / "tm.sqlite"
    tb_path = tmp_path / "tb.kuzu"
    _seed_tm(tm_path)
    args = [
        "termbase",
        "promote",
        "--source-lang",
        "en",
        "--target-lang",
        "de",
        "--tm-path",
        str(tm_path),
        "--termbase-path",
        str(tb_path),
        "--accept-all",
    ]
    assert cli_main(args) == 0
    capsys.readouterr()

    tb = KuzuTermbase(tb_path)
    try:
        first = tb.stats()
    finally:
        tb.close()

    # Second run on identical TM: must be a no-op at the row level.
    assert cli_main(args) == 0
    capsys.readouterr()
    tb = KuzuTermbase(tb_path)
    try:
        second = tb.stats()
    finally:
        tb.close()

    assert first.concept_count == second.concept_count
    assert first.term_count_by_lang == second.term_count_by_lang


def test_promote_no_candidates_when_thresholds_not_met(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tm_path = tmp_path / "tm.sqlite"
    tb_path = tmp_path / "tb.kuzu"
    # Only 2 rows — under default min_frequency=5.
    tm = SqliteTranslationMemory(tm_path)
    try:
        for index in range(2):
            seg = Segment(
                key=f"k{index}",
                source_text=f"login row {index}",
                source_lang="en",
            )
            tm.store(
                TranslatedSegment(
                    segment=seg,
                    target_lang="de",
                    target_text="Anmeldung",
                    provider="noop",
                    model="",
                    confidence=None,
                    source=TRANSLATION_SOURCE_PROVIDER,
                )
            )
    finally:
        tm.close()

    rc = cli_main(
        [
            "termbase",
            "promote",
            "--source-lang",
            "en",
            "--target-lang",
            "de",
            "--tm-path",
            str(tm_path),
            "--termbase-path",
            str(tb_path),
            "--accept-all",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "No promotion candidates" in captured.out
    # Termbase should not have been opened/created.
    assert not tb_path.exists()


def test_promote_review_loop_accepts_y_skips_n_quits_q(tmp_path: Path) -> None:
    # Drives the review loop directly via run_termbase so we can
    # inject a stdin stream. argparse + cli_main also works but
    # exercising the lower-level surface keeps the test focused on
    # the prompt/response contract.
    import argparse as _argparse

    tm_path = tmp_path / "tm.sqlite"
    tb_path = tmp_path / "tb.kuzu"

    # Seed two distinct n-grams (login + logout), each with 5+ rows
    # of consistent translation so both pass thresholds.
    tm = SqliteTranslationMemory(tm_path)
    try:
        for index in range(6):
            seg_in = Segment(
                key=f"in{index}",
                source_text=f"login row {index}",
                source_lang="en",
            )
            tm.store(
                TranslatedSegment(
                    segment=seg_in,
                    target_lang="de",
                    target_text="Anmeldung",
                    provider="noop",
                    model="",
                    confidence=None,
                    source=TRANSLATION_SOURCE_PROVIDER,
                )
            )
            seg_out = Segment(
                key=f"out{index}",
                source_text=f"logout row {index}",
                source_lang="en",
            )
            tm.store(
                TranslatedSegment(
                    segment=seg_out,
                    target_lang="de",
                    target_text="Abmeldung",
                    provider="noop",
                    model="",
                    confidence=None,
                    source=TRANSLATION_SOURCE_PROVIDER,
                )
            )
    finally:
        tm.close()

    args = _argparse.Namespace(
        termbase_subcommand="promote",
        source_lang="en",
        target_lang="de",
        tm_path=tm_path,
        termbase_path=tb_path,
        review=True,
        accept_all=False,
        min_frequency=5,
        min_consistency=0.9,
    )

    # Accept first candidate (y), skip second (n), quit on third (q).
    stdin = io.StringIO("y\nn\nq\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    rc = run_termbase(args, stdin=stdin, stdout=stdout, stderr=stderr)
    assert rc == 0
    output = stdout.getvalue()
    assert "Promoted 1 candidates" in output

    tb = KuzuTermbase(tb_path)
    try:
        # Exactly one concept landed (the y-accepted candidate).
        assert tb.stats().concept_count == 1
    finally:
        tb.close()


# --- Help / dispatcher ---


def test_termbase_help_lists_all_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli_main(["termbase", "--help"])
    captured = capsys.readouterr()
    for sub in ("init", "import", "export", "promote", "stats"):
        assert sub in captured.out


def test_unknown_termbase_subcommand_returns_usage_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # argparse rejects unknown subcommand at parse time.
    with pytest.raises(SystemExit):
        cli_main(["termbase", "bogus"])
