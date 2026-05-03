"""Smoke tests for the cycle-1 ``nemo`` CLI dispatcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.cli import main
from ainemo.cli.commands import (
    CMD_NAME_TM,
    CMD_NAME_TRANSLATE,
    CMD_NAME_VALIDATE,
)


def test_no_args_prints_help_and_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 2
    captured = capsys.readouterr()
    assert "translate" in captured.err or "translate" in captured.out


def test_translate_with_real_bundle(tmp_path: Path) -> None:
    src = tmp_path / "messages_en_US.properties"
    src.write_text("greeting=Hello\n", encoding="utf-8")

    output_dir = tmp_path / "out"
    tm_path = tmp_path / "tm.sqlite"

    rc = main(
        [
            CMD_NAME_TRANSLATE,
            "--from",
            str(src),
            "--from-lang",
            "en-US",
            "--to-langs",
            "de-DE",
            "--output-dir",
            str(output_dir),
            "--tm-path",
            str(tm_path),
        ]
    )
    assert rc == 0
    assert (output_dir / "messages_de_DE.properties").exists()
    assert tm_path.exists()


def test_translate_explicit_format(tmp_path: Path) -> None:
    src = tmp_path / "messages.txt"  # Non-standard extension
    src.write_text("k=v\n", encoding="utf-8")

    rc = main(
        [
            CMD_NAME_TRANSLATE,
            "--from",
            str(src),
            "--to-langs",
            "de-DE",
            "--format",
            "java-properties",
            "--output-dir",
            str(tmp_path / "out"),
            "--tm-path",
            str(tmp_path / "tm.sqlite"),
        ]
    )
    assert rc == 0


def test_translate_unknown_extension_fails(tmp_path: Path) -> None:
    src = tmp_path / "messages.unknown"
    src.write_text("k=v\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(
            [
                CMD_NAME_TRANSLATE,
                "--from",
                str(src),
                "--to-langs",
                "de-DE",
                "--output-dir",
                str(tmp_path / "out"),
                "--tm-path",
                str(tmp_path / "tm.sqlite"),
            ]
        )


def test_translate_missing_source_file(tmp_path: Path) -> None:
    rc = main(
        [
            CMD_NAME_TRANSLATE,
            "--from",
            str(tmp_path / "does_not_exist.properties"),
            "--to-langs",
            "de-DE",
            "--output-dir",
            str(tmp_path / "out"),
            "--tm-path",
            str(tmp_path / "tm.sqlite"),
        ]
    )
    assert rc == 2


def test_tm_stats_with_populated_tm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Run a translate first, then `nemo tm stats` should show non-zero counts."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text("k1=v1\nk2=v2\n", encoding="utf-8")
    tm_path = tmp_path / "tm.sqlite"

    main(
        [
            CMD_NAME_TRANSLATE,
            "--from",
            str(src),
            "--to-langs",
            "de-DE",
            "--output-dir",
            str(tmp_path / "out"),
            "--tm-path",
            str(tm_path),
        ]
    )
    capsys.readouterr()  # drain translate output

    rc = main([CMD_NAME_TM, "stats", "--tm-path", str(tm_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "segments:" in captured.out
    assert "translations:" in captured.out


def test_tm_stats_missing_db(tmp_path: Path) -> None:
    rc = main([CMD_NAME_TM, "stats", "--tm-path", str(tmp_path / "nope.sqlite")])
    assert rc == 2


def test_validate_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "messages_en_US.properties"
    src.write_text("welcome=Hello {name}!\n", encoding="utf-8")
    target = tmp_path / "messages_de_DE.properties"
    # Target has the placeholder dropped — should trigger a violation
    target.write_text("welcome=Hallo!\n", encoding="utf-8")

    rc = main(
        [
            CMD_NAME_VALIDATE,
            "--source",
            str(src),
            "--target",
            str(target),
            "--from-lang",
            "en-US",
            "--to-lang",
            "de-DE",
        ]
    )
    assert rc == 1  # validation error
    captured = capsys.readouterr()
    assert "ERROR" in captured.out
    assert "placeholder-parity" in captured.out


def test_validate_clean_pair(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "messages_en_US.properties"
    src.write_text("welcome=Hello {name}!\n", encoding="utf-8")
    target = tmp_path / "messages_de_DE.properties"
    target.write_text("welcome=Hallo {name}!\n", encoding="utf-8")

    rc = main(
        [
            CMD_NAME_VALIDATE,
            "--source",
            str(src),
            "--target",
            str(target),
            "--to-lang",
            "de-DE",
        ]
    )
    assert rc == 0
