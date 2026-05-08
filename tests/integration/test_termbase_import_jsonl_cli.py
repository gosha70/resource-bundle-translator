# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Cycle-4 S5 — `nemo termbase import-from-jsonl` CLI integration
tests.

Mirrors the cycle-4 S4 ``test_termbase_import_csv_cli.py`` shape
minus the CSV-dialect overrides (no ``--delimiter``, no shell-
escape normalization). JSONL has no field separator and the
encoding default is utf-8 by convention.
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
        "source_lang: en-US\nsource_column: source\ntarget_columns:\n  de-DE: de\n",
        encoding="utf-8",
    )


def _import_argv(
    *,
    jsonl_path: Path,
    map_config: Path,
    termbase_path: Path,
    namespace: str | None = None,
    encoding: str | None = None,
    import_skip_store: Path | None = None,
) -> list[str]:
    argv = [
        "termbase",
        "import-from-jsonl",
        str(jsonl_path),
        "--map-config",
        str(map_config),
        "--termbase-path",
        str(termbase_path),
    ]
    if namespace is not None:
        argv += ["--namespace", namespace]
    if encoding is not None:
        argv += ["--encoding", encoding]
    if import_skip_store is not None:
        argv += ["--import-skip-store", str(import_skip_store)]
    return argv


# --- Happy path ---


def test_import_from_jsonl_writes_concepts_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    jsonl_path.write_text(
        '{"source": "login", "de": "Anmeldung"}\n'
        '{"source": "logout", "de": "Abmeldung"}\n'
        '{"source": "cancel", "de": "Abbrechen"}\n',
        encoding="utf-8",
    )
    _write_minimal_mapping(map_path)

    rc = cli_main(_import_argv(jsonl_path=jsonl_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 0
    captured = capsys.readouterr()
    assert "Imported 3 concepts" in captured.out
    assert "6 terms" in captured.out

    tb = KuzuTermbase(tb_path)
    try:
        stats = tb.stats()
        assert stats.concept_count == 3
        assert dict(stats.term_count_by_lang) == {"de-DE": 3, "en-US": 3}
    finally:
        tb.close()


def test_import_from_jsonl_persists_skipped_rows_to_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    skip_store_path = tmp_path / "skips.sqlite"
    jsonl_path.write_text(
        '{"source": "", "de": "Anmeldung"}\n{"source": "login", "de": "Anmeldung"}\n',
        encoding="utf-8",
    )
    _write_minimal_mapping(map_path)

    rc = cli_main(
        _import_argv(
            jsonl_path=jsonl_path,
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
        assert rows[0].source_path == str(jsonl_path)
        assert rows[0].source_format == "jsonl"
        assert rows[0].row_index == 1
        assert "blank" in rows[0].skip_reason
    finally:
        store.close()


def test_import_round_trips_to_termbase_stats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    jsonl_path.write_text('{"source": "login", "de": "Anmeldung"}\n', encoding="utf-8")
    _write_minimal_mapping(map_path)

    cli_main(_import_argv(jsonl_path=jsonl_path, map_config=map_path, termbase_path=tb_path))
    capsys.readouterr()

    rc = cli_main(["termbase", "stats", "--termbase-path", str(tb_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "concepts: 1" in captured.out
    assert "en-US: 1" in captured.out
    assert "de-DE: 1" in captured.out


# --- Idempotency on re-run ---


def test_import_from_jsonl_is_idempotent_on_rerun(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    jsonl_path.write_text(
        '{"source": "login", "de": "Anmeldung"}\n{"source": "logout", "de": "Abmeldung"}\n',
        encoding="utf-8",
    )
    _write_minimal_mapping(map_path)
    argv = _import_argv(jsonl_path=jsonl_path, map_config=map_path, termbase_path=tb_path)

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


def test_namespace_disambiguates_two_jsonls_sharing_source_surface(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    _write_minimal_mapping(map_path)

    marketing = tmp_path / "marketing.jsonl"
    legal = tmp_path / "legal.jsonl"
    marketing.write_text('{"source": "cancel", "de": "Abbrechen"}\n', encoding="utf-8")
    legal.write_text('{"source": "cancel", "de": "Stornieren"}\n', encoding="utf-8")

    cli_main(
        _import_argv(
            jsonl_path=marketing,
            map_config=map_path,
            termbase_path=tb_path,
            namespace="marketing",
        )
    )
    cli_main(
        _import_argv(
            jsonl_path=legal,
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
        de_surfaces = sorted(
            term.surface
            for entry in tb.iter_concept_entries()
            for term in entry.terms
            if term.lang == "de-DE"
        )
        assert de_surfaces == ["Abbrechen", "Stornieren"]
    finally:
        tb.close()


# --- Skipped-row reporting (the JSONL-specific case: malformed lines) ---


def test_malformed_line_skip_surfaces_in_summary_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cycle-4 S3 contract: a malformed JSON line yields SkippedRow
    # with `"row N: malformed JSON ..."`; the rest of the file
    # still imports. The CLI summary surfaces the skip reason
    # verbatim so the operator can edit the bad line and re-run.
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    jsonl_path.write_text(
        '{"source": "login", "de": "Anmeldung"}\n'
        "not-valid-json\n"
        '{"source": "logout", "de": "Abmeldung"}\n',
        encoding="utf-8",
    )
    _write_minimal_mapping(map_path)

    rc = cli_main(_import_argv(jsonl_path=jsonl_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 0
    captured = capsys.readouterr()
    assert "Imported 2 concepts" in captured.out
    assert "1 rows skipped" in captured.out
    assert "row 2" in captured.out
    assert "malformed JSON" in captured.out


def test_strict_string_skips_surface_in_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cycle-4 S3 P2 strict-string contract pushed through the CLI:
    # a Boolean target value yields SkippedRow with the type
    # named, surfaced in the summary stdout.
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    jsonl_path.write_text(
        '{"source": "yes", "de": true}\n{"source": "login", "de": "Anmeldung"}\n',
        encoding="utf-8",
    )
    _write_minimal_mapping(map_path)

    rc = cli_main(_import_argv(jsonl_path=jsonl_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 0
    captured = capsys.readouterr()
    assert "Imported 1 concepts" in captured.out
    assert "1 rows skipped" in captured.out
    assert "bool" in captured.out
    assert "expected string" in captured.out


# --- File-level error paths (exit 2) ---


def test_missing_jsonl_file_returns_usage_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    map_path = tmp_path / "m.yaml"
    _write_minimal_mapping(map_path)
    rc = cli_main(
        _import_argv(
            jsonl_path=tmp_path / "does-not-exist.jsonl",
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
    jsonl_path = tmp_path / "g.jsonl"
    jsonl_path.write_text('{"source": "login", "de": "Anmeldung"}\n', encoding="utf-8")
    rc = cli_main(
        _import_argv(
            jsonl_path=jsonl_path,
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
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    jsonl_path.write_text('{"source": "login", "de": "Anmeldung"}\n', encoding="utf-8")
    map_path.write_text(
        "source_lang: en-US\n"
        "source_column: source\n"
        "target_columns:\n"
        "  de-DE: de\n"
        "rogue_field: nope\n",
        encoding="utf-8",
    )
    rc = cli_main(
        _import_argv(
            jsonl_path=jsonl_path,
            map_config=map_path,
            termbase_path=tmp_path / "tb.kuzu",
        )
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "invalid field-mapping" in captured.err.lower()
    assert "rogue_field" in captured.err


def test_decode_error_surfaces_encoding_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cycle-4 S3 JsonlDecodeError surfaces via the CLI with the
    # `--encoding latin-1` hint preserved end-to-end. Parity with
    # the cycle-4 S4 CsvDecodeError CLI test.
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    jsonl_path.write_text('{"source": "Café", "de": "Kaffeehaus"}\n', encoding="latin-1")
    _write_minimal_mapping(map_path)

    rc = cli_main(_import_argv(jsonl_path=jsonl_path, map_config=map_path, termbase_path=tb_path))
    assert rc == 2
    captured = capsys.readouterr()
    assert "--encoding" in captured.err
    assert "latin-1" in captured.err


def test_custom_encoding_via_cli_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    jsonl_path = tmp_path / "g.jsonl"
    map_path = tmp_path / "m.yaml"
    tb_path = tmp_path / "tb.kuzu"
    jsonl_path.write_text('{"source": "Café", "de": "Kaffeehaus"}\n', encoding="latin-1")
    _write_minimal_mapping(map_path)

    rc = cli_main(
        _import_argv(
            jsonl_path=jsonl_path,
            map_config=map_path,
            termbase_path=tb_path,
            encoding="latin-1",
        )
    )
    assert rc == 0


# --- Help / dispatcher coverage ---


def test_import_from_jsonl_appears_in_termbase_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli_main(["termbase", "--help"])
    captured = capsys.readouterr()
    assert "import-from-jsonl" in captured.out
