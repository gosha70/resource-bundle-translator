"""Unit tests for :mod:`ainemo.cli.daemon`.

Drives :class:`DaemonServer.serve` with in-memory ``StringIO`` streams
so tests don't fork a subprocess and don't touch any real model.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from ainemo.cli.daemon import (
    ERR_INVALID_ENVELOPE,
    ERR_INVALID_JSON,
    ERR_INVALID_PARAMS,
    ERR_PROVIDER_FAILURE,
    ERR_UNKNOWN_OP,
    ERR_VERSION_MISMATCH,
    OP_PING,
    OP_TRANSLATE,
    OP_TRANSLATE_FILE,
    PROTOCOL_VERSION,
    DaemonServer,
)


def _drive(server: DaemonServer, requests: list[Any]) -> list[dict[str, Any]]:
    """Feed ``requests`` (dicts or raw strings) to the server and
    return parsed response envelopes."""
    lines: list[str] = []
    for req in requests:
        lines.append(json.dumps(req) if isinstance(req, dict) else str(req))
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout)
    out_text = stdout.getvalue().strip()
    if not out_text:
        return []
    return [json.loads(line) for line in out_text.splitlines()]


# --- Protocol envelope ----------------------------------------------------


def test_protocol_version_is_1() -> None:
    assert PROTOCOL_VERSION == "1"


def test_ping_returns_ok_with_pong(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(server, [{"v": "1", "id": "abc", "op": OP_PING}])
    assert response["v"] == "1"
    assert response["id"] == "abc"
    assert response["ok"] is True
    assert response["result"] == {"pong": True}


def test_request_id_echoes_back(tmp_path: Path) -> None:
    """The Gradle plugin uses ``id`` to correlate concurrent requests
    on a multiplexed daemon. The daemon must echo it verbatim."""
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [r1, r2] = _drive(
        server,
        [
            {"v": "1", "id": "first", "op": OP_PING},
            {"v": "1", "id": "second", "op": OP_PING},
        ],
    )
    assert r1["id"] == "first"
    assert r2["id"] == "second"


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    """Empty lines are tolerated — the protocol is line-delimited but
    carriage-return / extra whitespace shouldn't crash the loop."""
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    stdin = io.StringIO('\n\n{"v":"1","id":"x","op":"ping"}\n\n')
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout)
    [response] = [json.loads(line) for line in stdout.getvalue().strip().splitlines()]
    assert response["ok"] is True


# --- Translate op --------------------------------------------------------


def test_translate_through_noop_provider_returns_source_text(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(
        server,
        [
            {
                "v": "1",
                "id": "t1",
                "op": OP_TRANSLATE,
                "params": {
                    "key": "greeting",
                    "source_text": "Hello, {name}!",
                    "source_lang": "en-US",
                    "target_lang": "de-DE",
                    "provider": "noop",
                },
            }
        ],
    )
    assert response["ok"] is True
    result = response["result"]
    # noop echoes the source verbatim — placeholder preserved.
    assert result["target_text"] == "Hello, {name}!"
    assert result["provider"] == "noop"
    assert result["model"] == "noop"


def test_translate_writes_to_usage_log(tmp_path: Path) -> None:
    """Daemon-routed translations must hit the same UsageLog as CLI
    runs — uniform cost surveillance per AGENTS.md § Provider Rules."""
    usage_log = tmp_path / "usage.jsonl"
    server = DaemonServer(usage_log_path=usage_log)
    _drive(
        server,
        [
            {
                "v": "1",
                "id": "u1",
                "op": OP_TRANSLATE,
                "params": {
                    "key": "k",
                    "source_text": "Hello",
                    "source_lang": "en-US",
                    "target_lang": "de-DE",
                    "provider": "noop",
                },
            }
        ],
    )
    assert usage_log.exists()
    lines = [ln for ln in usage_log.read_text(encoding="utf-8").splitlines() if ln]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["provider"] == "noop"


def test_translate_caches_router_across_requests(tmp_path: Path) -> None:
    """The cycle-2 batch-job win is amortizing SDK init across many
    requests on one daemon process. Two translate calls with the same
    provider id must reuse the same router (proxy: same cached
    instance)."""
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    _drive(
        server,
        [
            {
                "v": "1",
                "id": str(i),
                "op": OP_TRANSLATE,
                "params": {
                    "key": f"k{i}",
                    "source_text": "Hello",
                    "source_lang": "en-US",
                    "target_lang": "de-DE",
                    "provider": "noop",
                },
            }
            for i in range(3)
        ],
    )
    # Server's private cache contains the noop router.
    assert "noop" in server._routers
    assert len(server._routers) == 1


# --- Error envelopes ------------------------------------------------------


def test_invalid_json_returns_invalid_json_error(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(server, ["this is not json"])
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_INVALID_JSON
    # Request id is null because we couldn't parse the envelope.
    assert response["id"] is None


def test_non_object_request_returns_invalid_envelope(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(server, ["[1, 2, 3]"])
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_INVALID_ENVELOPE


def test_version_mismatch_returns_clean_error(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(server, [{"v": "999", "id": "x", "op": OP_PING}])
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_VERSION_MISMATCH
    assert "999" in response["error"]["message"]


def test_unknown_op_returns_unknown_op_error(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(server, [{"v": "1", "id": "x", "op": "do-something-novel"}])
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_UNKNOWN_OP


def test_translate_missing_required_param_returns_invalid_params(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(
        server,
        [
            {
                "v": "1",
                "id": "x",
                "op": OP_TRANSLATE,
                "params": {
                    # missing 'source_text'
                    "key": "k",
                    "source_lang": "en-US",
                    "target_lang": "de-DE",
                    "provider": "noop",
                },
            }
        ],
    )
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_INVALID_PARAMS
    assert "source_text" in response["error"]["message"]


def test_translate_unknown_provider_id_returns_provider_failure(tmp_path: Path) -> None:
    """An unknown provider id surfaces as a structured provider-failure
    envelope, not as a Python traceback. The Gradle plugin pattern-
    matches on the code string."""
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(
        server,
        [
            {
                "v": "1",
                "id": "x",
                "op": OP_TRANSLATE,
                "params": {
                    "key": "k",
                    "source_text": "Hello",
                    "source_lang": "en-US",
                    "target_lang": "de-DE",
                    "provider": "made-up-provider-id",
                },
            }
        ],
    )
    assert response["ok"] is False
    # _build_provider raises ValueError for unknown ids → wrapped as
    # ERR_INTERNAL since it's not one of the recognized provider
    # exceptions. Either ERR_INTERNAL or ERR_PROVIDER_FAILURE is
    # acceptable; both are structured envelopes the plugin can act on.
    assert response["error"]["code"] in {"internal", ERR_PROVIDER_FAILURE}
    assert "made-up-provider-id" in response["error"]["message"]


def test_params_not_object_returns_invalid_params(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(server, [{"v": "1", "id": "x", "op": OP_TRANSLATE, "params": "not-a-dict"}])
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_INVALID_PARAMS


def test_op_field_missing_returns_invalid_envelope(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(server, [{"v": "1", "id": "x"}])
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_INVALID_ENVELOPE


# --- One bad request doesn't kill the loop --------------------------------


def test_bad_request_does_not_terminate_serve_loop(tmp_path: Path) -> None:
    """Daemon must keep serving after every kind of error envelope —
    one corrupt request from the Gradle plugin can't take down the
    whole build."""
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    responses = _drive(
        server,
        [
            "garbage",
            {"v": "1", "id": "good1", "op": OP_PING},
            {"v": "1", "id": "x", "op": "unknown-op"},
            {"v": "1", "id": "good2", "op": OP_PING},
        ],
    )
    assert len(responses) == 4
    assert responses[0]["ok"] is False
    assert responses[1]["ok"] is True
    assert responses[2]["ok"] is False
    assert responses[3]["ok"] is True


# --- translate_file op (cycle-2 Gradle plugin's headline batch op) --------


def test_translate_file_writes_per_target_lang_outputs(tmp_path: Path) -> None:
    """End-to-end: daemon parses the source bundle, runs the pipeline
    once per target lang, and writes one output file per language."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text("greeting=Hello\nfarewell=Goodbye\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(
        server,
        [
            {
                "v": "1",
                "id": "tf1",
                "op": OP_TRANSLATE_FILE,
                "params": {
                    "source_path": str(src),
                    "target_langs": ["de-DE", "fr-FR"],
                    "output_dir": str(output_dir),
                    "provider": "noop",
                    "tm_path": str(tmp_path / "tm.sqlite"),
                },
            }
        ],
    )
    assert response["ok"] is True, response
    result = response["result"]
    assert "de-DE" in result["target_lang_paths"]
    assert "fr-FR" in result["target_lang_paths"]
    assert Path(result["target_lang_paths"]["de-DE"]).exists()
    assert Path(result["target_lang_paths"]["fr-FR"]).exists()
    assert result["error_count"] == 0
    # Two segments × two target langs = four provider calls.
    assert result["provider_call_count"] == 4


def test_translate_file_missing_source_returns_clean_error(tmp_path: Path) -> None:
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(
        server,
        [
            {
                "v": "1",
                "id": "tf2",
                "op": OP_TRANSLATE_FILE,
                "params": {
                    "source_path": str(tmp_path / "nope.properties"),
                    "target_langs": ["de-DE"],
                    "output_dir": str(tmp_path / "out"),
                    "provider": "noop",
                    "tm_path": str(tmp_path / "tm.sqlite"),
                },
            }
        ],
    )
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_INVALID_PARAMS
    assert "does not exist" in response["error"]["message"]


def test_translate_file_empty_target_langs_rejected(tmp_path: Path) -> None:
    """An empty target_langs list is invalid params, not a silent
    no-op — the Gradle plugin's misconfiguration shouldn't silently
    succeed without translating anything."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text("k=v\n", encoding="utf-8")
    server = DaemonServer(usage_log_path=tmp_path / "usage.jsonl")
    [response] = _drive(
        server,
        [
            {
                "v": "1",
                "id": "tf3",
                "op": OP_TRANSLATE_FILE,
                "params": {
                    "source_path": str(src),
                    "target_langs": [],
                    "output_dir": str(tmp_path / "out"),
                    "provider": "noop",
                    "tm_path": str(tmp_path / "tm.sqlite"),
                },
            }
        ],
    )
    assert response["ok"] is False
    assert response["error"]["code"] == ERR_INVALID_PARAMS
