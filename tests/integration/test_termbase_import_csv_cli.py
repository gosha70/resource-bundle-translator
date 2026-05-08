# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-4 S4 — `nemo termbase import-from-csv` CLI integration
tests.

Each test invokes :func:`ainemo.cli.main` (the `nemo` console-script
entry point) with an explicit argv list against an isolated tmp
termbase + tmp CSV + tmp YAML mapping, so the suite never touches
any real ``.ainemo/`` state. Mirrors the cycle-3
``test_termbase_cli.py`` shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.app.store.import_skips import SqliteImportSkipStore
from ainemo.cli import main as cli_main
from ainemo.core.termbase.kuzu.store import KuzuTermbase

pytestmark = pytest.mark.integration


# --- Builders ---


def _write_minimal_mapping(path: Path) -> None:
    path.write_text(
        "source_lang: en-US\nsource_column: term_en\ntarget_columns:\n  de-DE: term_de\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, contents: str, *, encoding: str = "utf-8") -> None:
    path.write_text(contents, encoding=encoding)


def _import_argv(
    *,
    csv_path: Path,
    map_config: Path,
    termbase_path: Path,
    namespace: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    import_skip_store: Path | None = None,
) -> list[str]:
    argv = [
        "termbase",
        "import-from-csv",
        str(csv_path),
        "--map-config",
        str(map_config),
        "--termbase-path",
        str(termbase_path),
    ]
    if namespace is not None:
        argv += ["--namespace", namespace]
    if encoding is not None:
        argv += ["--encoding", encoding]
    if delimiter is not None:
        argv += ["--delimiter", delimiter]
    if import_skip_store is not None:
        argv += ["--import-skip-store", str(import_skip_store)]
    return argv


# --- Happy path ---


def test_import_from_csv_writes_concepts_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(
        csv_path,
        "term_en,term_de\nlogin,Anmeldung\nlogout,Abmeldung\ncancel,Abbrechen\n",
    )
    _write_minimal_mapping(map_path)

    rc = cli_main(_import_argv(csv_path=csv_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 0
    captured = capsys.readouterr()
    assert "Imported 3 concepts" in captured.out
    assert "6 terms" in captured.out  # 3 source + 3 target

    tb = KuzuTermbase(tb_path)
    try:
        stats = tb.stats()
        assert stats.concept_count == 3
        assert dict(stats.term_count_by_lang) == {"de-DE": 3, "en-US": 3}
    finally:
        tb.close()


def test_import_from_csv_persists_skipped_rows_to_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    skip_store_path = tmp_path / "skips.sqlite"
    _write_csv(csv_path, "term_en,term_de\n,Anmeldung\nlogin,Anmeldung\n")
    _write_minimal_mapping(map_path)

    rc = cli_main(
        _import_argv(
            csv_path=csv_path,
            map_config=map_path,
            termbase_path=tb_path,
            import_skip_store=skip_store_path,
        )
    )

    assert rc == 0
    capsys.readouterr()
    store = SqliteImportSkipStore(skip_store_path)
    try:
        rows = store.list()
        assert len(rows) == 1
        assert rows[0].source_path == str(csv_path)
        assert rows[0].source_format == "csv"
        assert rows[0].row_index == 2
        assert "blank" in rows[0].skip_reason
    finally:
        store.close()


def test_import_round_trips_to_termbase_stats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(csv_path, "term_en,term_de\nlogin,Anmeldung\n")
    _write_minimal_mapping(map_path)

    cli_main(_import_argv(csv_path=csv_path, map_config=map_path, termbase_path=tb_path))
    capsys.readouterr()

    rc = cli_main(["termbase", "stats", "--termbase-path", str(tb_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "concepts: 1" in captured.out
    assert "en-US: 1" in captured.out
    assert "de-DE: 1" in captured.out


# --- Idempotency on re-run ---


def test_import_from_csv_is_idempotent_on_rerun(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cycle-4 S2 P2 contract: re-running the same import upserts on
    # the same content-addressed concept ids; concept count + term
    # count stay stable.
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(
        csv_path,
        "term_en,term_de\nlogin,Anmeldung\nlogout,Abmeldung\n",
    )
    _write_minimal_mapping(map_path)
    argv = _import_argv(csv_path=csv_path, map_config=map_path, termbase_path=tb_path)

    cli_main(argv)
    capsys.readouterr()
    tb = KuzuTermbase(tb_path)
    try:
        first = tb.stats()
    finally:
        tb.close()

    cli_main(argv)
    capsys.readouterr()
    tb = KuzuTermbase(tb_path)
    try:
        second = tb.stats()
    finally:
        tb.close()

    assert first.concept_count == second.concept_count
    assert first.term_count_by_lang == second.term_count_by_lang


# --- --namespace collision-disambiguation ---


def test_namespace_disambiguates_two_csvs_sharing_source_surface(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Two CSVs both have a `cancel` row mapping to a different
    # German rendering. Without namespace, both rows hash to the
    # same concept_id and the second import overwrites the first.
    # With `--namespace marketing` and `--namespace legal`, both
    # renderings land as distinct concepts.
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_minimal_mapping(map_path)

    marketing_csv = tmp_path / "marketing.csv"
    legal_csv = tmp_path / "legal.csv"
    _write_csv(marketing_csv, "term_en,term_de\ncancel,Abbrechen\n")
    _write_csv(legal_csv, "term_en,term_de\ncancel,Stornieren\n")

    cli_main(
        _import_argv(
            csv_path=marketing_csv,
            map_config=map_path,
            termbase_path=tb_path,
            namespace="marketing",
        )
    )
    cli_main(
        _import_argv(
            csv_path=legal_csv,
            map_config=map_path,
            termbase_path=tb_path,
            namespace="legal",
        )
    )
    capsys.readouterr()

    tb = KuzuTermbase(tb_path)
    try:
        stats = tb.stats()
        assert stats.concept_count == 2
        # Both German renderings preserved.
        de_surfaces = sorted(
            term.surface
            for entry in tb.iter_concept_entries()
            for term in entry.terms
            if term.lang == "de-DE"
        )
        assert de_surfaces == ["Abbrechen", "Stornieren"]
    finally:
        tb.close()


# --- Skipped-row reporting ---


def test_skipped_rows_surface_in_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(
        csv_path,
        "term_en,term_de\n"
        "login,Anmeldung\n"
        ",blank-source\n"  # row 3 — blank source
        "logout,\n"  # row 4 — blank target
        "cancel,Abbrechen\n",
    )
    _write_minimal_mapping(map_path)

    rc = cli_main(_import_argv(csv_path=csv_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 0
    captured = capsys.readouterr()
    assert "Imported 2 concepts" in captured.out
    assert "2 rows skipped" in captured.out
    assert "row 3" in captured.out
    assert "row 4" in captured.out


# --- File-level error paths (exit 2) ---


def test_missing_csv_file_returns_usage_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    map_path = tmp_path / "m.yaml"
    _write_minimal_mapping(map_path)
    rc = cli_main(
        _import_argv(
            csv_path=tmp_path / "does-not-exist.csv",
            map_config=map_path,
            termbase_path=tmp_path / "tb.kuzu",
        )
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


def test_missing_mapping_file_returns_usage_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "g.csv"
    _write_csv(csv_path, "term_en,term_de\nlogin,Anmeldung\n")
    rc = cli_main(
        _import_argv(
            csv_path=csv_path,
            map_config=tmp_path / "missing.yaml",
            termbase_path=tmp_path / "tb.kuzu",
        )
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "field-mapping file not found" in captured.err.lower()


def test_invalid_mapping_yaml_surfaces_validation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cycle-4 S1 strict-schema regression at the CLI level: a
    # mapping with an unknown field (`extra="forbid"`) must surface
    # the Pydantic error on stderr, not crash with a traceback.
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    _write_csv(csv_path, "term_en,term_de\nlogin,Anmeldung\n")
    map_path.write_text(
        "source_lang: en-US\n"
        "source_column: term_en\n"
        "target_columns:\n"
        "  de-DE: term_de\n"
        "rogue_field: nope\n",  # extra="forbid" rejects this
        encoding="utf-8",
    )

    rc = cli_main(
        _import_argv(
            csv_path=csv_path,
            map_config=map_path,
            termbase_path=tmp_path / "tb.kuzu",
        )
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "invalid field-mapping" in captured.err.lower()
    assert "rogue_field" in captured.err


def test_missing_referenced_csv_column_returns_usage_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # File-level error from CsvSource: the CSV header doesn't have
    # the `term_de` column the mapping references. Surfaces as a
    # MissingColumnError on stderr with exit 2.
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(csv_path, "term_en,term_fr\nlogin,connexion\n")  # no term_de
    _write_minimal_mapping(map_path)  # references term_de

    rc = cli_main(_import_argv(csv_path=csv_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 2
    captured = capsys.readouterr()
    assert "term_de" in captured.err


def test_decode_error_surfaces_encoding_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cycle-4 S2 CsvDecodeError surfaces via the CLI with the
    # `--encoding latin-1` hint preserved. Pinned so the operator's
    # actionable error path stays end-to-end.
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(csv_path, "term_en,term_de\nCafé,Kaffeehaus\n", encoding="latin-1")
    _write_minimal_mapping(map_path)

    rc = cli_main(_import_argv(csv_path=csv_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 2
    captured = capsys.readouterr()
    assert "--encoding" in captured.err
    assert "latin-1" in captured.err


# --- Custom dialect overrides via CLI ---


def test_custom_delimiter_escape_form_via_cli_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cycle-4 S4 P1 regression: previously the test passed a literal
    # tab character, which is NOT what the documented invocation
    # `--delimiter '\t'` produces in any common shell — most shells
    # leave the backslash-t pair verbatim. The CLI normalizes the
    # two-char escape to a real tab so the operator path matches the
    # help text. Without this, csv.DictReader raised a stdlib
    # TypeError the operator had to debug.
    csv_path = tmp_path / "g.tsv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(csv_path, "term_en\tterm_de\nlogin\tAnmeldung\n")
    _write_minimal_mapping(map_path)

    rc = cli_main(
        _import_argv(
            csv_path=csv_path,
            map_config=map_path,
            termbase_path=tb_path,
            delimiter=r"\t",  # the literal two-char string a shell sends
        )
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Imported 1 concepts" in captured.out


def test_custom_delimiter_real_tab_char_via_cli_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # ANSI-C-quoted form `--delimiter $'\t'` resolves to a real tab
    # before reaching argparse. Both shapes (escaped + actual) must
    # work — covered separately so a regression on either path is
    # visible.
    csv_path = tmp_path / "g.tsv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(csv_path, "term_en\tterm_de\nlogin\tAnmeldung\n")
    _write_minimal_mapping(map_path)
    rc = cli_main(
        _import_argv(
            csv_path=csv_path,
            map_config=map_path,
            termbase_path=tb_path,
            delimiter="\t",  # actual tab char (ANSI-C $'\t' style)
        )
    )
    assert rc == 0


def test_invalid_multi_char_delimiter_returns_usage_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Anything other than a recognized escape or a single character
    # surfaces as a clean usage error mentioning the recognized set,
    # not a stdlib TypeError from csv.DictReader.
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(csv_path, "term_en,term_de\nlogin,Anmeldung\n")
    _write_minimal_mapping(map_path)
    rc = cli_main(
        _import_argv(
            csv_path=csv_path,
            map_config=map_path,
            termbase_path=tb_path,
            delimiter=";;",  # multi-char, not a recognized escape
        )
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "--delimiter" in captured.err.lower()
    assert "exactly one character" in captured.err


def test_custom_encoding_via_cli_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = tmp_path / "g.csv"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_csv(csv_path, "term_en,term_de\nCafé,Kaffeehaus\n", encoding="latin-1")
    _write_minimal_mapping(map_path)

    rc = cli_main(
        _import_argv(
            csv_path=csv_path,
            map_config=map_path,
            termbase_path=tb_path,
            encoding="latin-1",
        )
    )
    assert rc == 0


# --- Help / dispatcher coverage ---


def test_import_from_csv_appears_in_termbase_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli_main(["termbase", "--help"])
    captured = capsys.readouterr()
    assert "import-from-csv" in captured.out
