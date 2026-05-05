"""Smoke tests for the cycle-1 ``nemo`` CLI dispatcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainemo.cli import main
from ainemo.cli.commands import (
    CMD_NAME_PROVIDER,
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


def test_translate_default_provider_is_noop_and_records_usage(
    tmp_path: Path,
) -> None:
    """The CLI defaults to ``--provider noop`` and routes through
    :class:`ProviderRouter`, which means every call appends to the
    usage log even on a noop run."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text("greeting=Hello\nfarewell=Goodbye\n", encoding="utf-8")
    usage_log = tmp_path / "usage.jsonl"

    rc = main(
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
            "--usage-log",
            str(usage_log),
        ]
    )
    assert rc == 0
    assert usage_log.exists()
    lines = [ln for ln in usage_log.read_text(encoding="utf-8").splitlines() if ln]
    # Two segments × one target lang = two usage records.
    assert len(lines) == 2
    import json

    record = json.loads(lines[0])
    assert record["provider"] == "noop"


def test_translate_explicit_noop_provider_argument_accepted(tmp_path: Path) -> None:
    """``--provider noop`` is the default but must also be accepted as
    an explicit choice — argparse choices wiring sanity check."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text("greeting=Hello\n", encoding="utf-8")
    rc = main(
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
            "--usage-log",
            str(tmp_path / "usage.jsonl"),
            "--provider",
            "noop",
        ]
    )
    assert rc == 0


def test_translate_unknown_provider_choice_is_rejected(tmp_path: Path) -> None:
    """argparse should reject any provider id not in the choices list."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text("greeting=Hello\n", encoding="utf-8")
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
                "--provider",
                "made-up-provider",
            ]
        )


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


# --- nemo provider list / stats (cycle-2 scope 8) -------------------------


def test_provider_list_prints_all_six_providers(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main([CMD_NAME_PROVIDER, "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "noop" in out
    assert "nllb" in out
    assert "opus" in out
    assert "openai" in out
    assert "anthropic" in out
    assert "ollama" in out


def test_provider_list_marks_cloud_providers_missing_key_when_unset(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main([CMD_NAME_PROVIDER, "list"])
    assert rc == 0
    out = capsys.readouterr().out
    # Each cloud provider's row has "missing-key" when env unset.
    openai_line = next(line for line in out.splitlines() if line.strip().startswith("openai"))
    anthropic_line = next(line for line in out.splitlines() if line.strip().startswith("anthropic"))
    assert "missing-key" in openai_line
    assert "missing-key" in anthropic_line


def test_provider_list_marks_cloud_providers_available_when_keys_set(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    rc = main([CMD_NAME_PROVIDER, "list"])
    assert rc == 0
    out = capsys.readouterr().out
    openai_line = next(line for line in out.splitlines() if line.strip().startswith("openai"))
    anthropic_line = next(line for line in out.splitlines() if line.strip().startswith("anthropic"))
    assert "available" in openai_line
    assert "available" in anthropic_line


def test_provider_stats_missing_log_returns_zero_with_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(
        [
            CMD_NAME_PROVIDER,
            "stats",
            "--usage-log",
            str(tmp_path / "no-such-log.jsonl"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "No usage log" in out


def test_provider_stats_aggregates_real_log(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End-to-end: a translate run populates the log; ``provider stats``
    reads it back and reports the call count + per-provider breakdown."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text("k1=Hello\nk2=World\n", encoding="utf-8")
    usage_log = tmp_path / "usage.jsonl"
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
            "--usage-log",
            str(usage_log),
        ]
    )
    capsys.readouterr()  # drain translate output

    rc = main([CMD_NAME_PROVIDER, "stats", "--usage-log", str(usage_log)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "calls:" in out
    # Two segments → two provider calls under the noop default.
    assert "2" in out
    assert "noop" in out


def test_provider_stats_invalid_since_raises(tmp_path: Path) -> None:
    """``--since`` must be parseable as ISO-8601; bad input surfaces a
    clear error rather than silently filtering everything out."""
    log = tmp_path / "usage.jsonl"
    log.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="ISO-8601"):
        main(
            [
                CMD_NAME_PROVIDER,
                "stats",
                "--usage-log",
                str(log),
                "--since",
                "not-a-date",
            ]
        )


def test_provider_unknown_subcommand_returns_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``nemo provider`` with no subcommand should fall through to the
    unknown-subcommand branch and exit non-zero."""
    rc = main([CMD_NAME_PROVIDER])
    assert rc == 2
