"""``nemo daemon`` — JSON-over-stdio service for the Gradle plugin.

Per cycle-2 pitch scope 9: the Gradle plugin shells out to a
long-lived Python process and exchanges newline-delimited JSON over
stdin / stdout. This module hosts the daemon main loop and the
request / response envelope.

Wire shape (per cycle-2 pitch open-question 2: semver in the
envelope, evolves additively):

Request:  ``{"v": "1", "id": "<call-id>", "op": "<op>", "params": {...}}\n``
Response (ok): ``{"v": "1", "id": "<call-id>", "ok": true, "result": {...}}\n``
Response (err):
``{"v": "1", "id": "<call-id>", "ok": false, "error": {"code": "...", "message": "..."}}\n``

Operations (cycle-2 minimum surface):

- ``ping`` — health check; returns ``{"pong": true}``
- ``translate`` — single-segment translation through the router; the
  Gradle plugin batches by issuing many requests on one daemon
  process, amortizing model load + SDK init across the build.

Errors are line-delimited JSON envelopes — never raw stack traces on
stdout. Stderr is reserved for human-readable diagnostics that the
plugin can surface to the Gradle build log.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Final, Mapping, TextIO

from ainemo.core.segment import Segment
from ainemo.providers._usage_log import DEFAULT_USAGE_LOG_PATH, UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import (
    ProviderRouteNotFound,
    ProviderRouter,
    ProviderUnsupportedPair,
    RoutingConfig,
)

logger = logging.getLogger(__name__)

# --- Wire constants (no magic strings) ------------------------------------

PROTOCOL_VERSION: Final = "1"

ENVELOPE_KEY_VERSION: Final = "v"
ENVELOPE_KEY_ID: Final = "id"
ENVELOPE_KEY_OP: Final = "op"
ENVELOPE_KEY_PARAMS: Final = "params"
ENVELOPE_KEY_OK: Final = "ok"
ENVELOPE_KEY_RESULT: Final = "result"
ENVELOPE_KEY_ERROR: Final = "error"
ERROR_KEY_CODE: Final = "code"
ERROR_KEY_MESSAGE: Final = "message"

# Operation names — the public daemon surface. Adding a new op =
# adding an entry below + a handler in :data:`_HANDLERS`. The Gradle
# plugin's IPC contract pins these strings.
OP_PING: Final = "ping"
OP_TRANSLATE: Final = "translate"

# Error codes — the Gradle plugin pattern-matches on ``error.code``
# strings rather than message text; codes are stable, messages can
# evolve.
ERR_INVALID_JSON: Final = "invalid-json"
ERR_INVALID_ENVELOPE: Final = "invalid-envelope"
ERR_VERSION_MISMATCH: Final = "version-mismatch"
ERR_UNKNOWN_OP: Final = "unknown-op"
ERR_INVALID_PARAMS: Final = "invalid-params"
ERR_PROVIDER_FAILURE: Final = "provider-failure"
ERR_INTERNAL: Final = "internal"

# Translate-op param keys.
PARAM_KEY: Final = "key"
PARAM_SOURCE_TEXT: Final = "source_text"
PARAM_SOURCE_LANG: Final = "source_lang"
PARAM_TARGET_LANG: Final = "target_lang"
PARAM_PROVIDER: Final = "provider"

# Translate-op result keys.
RESULT_TARGET_TEXT: Final = "target_text"
RESULT_PROVIDER: Final = "provider"
RESULT_MODEL: Final = "model"
RESULT_INPUT_TOKENS: Final = "input_tokens"
RESULT_OUTPUT_TOKENS: Final = "output_tokens"
RESULT_LATENCY_MS: Final = "latency_ms"
RESULT_COST_USD: Final = "cost_usd"


# --- Argparse registration ------------------------------------------------

CMD_NAME_DAEMON: Final = "daemon"


def register_daemon(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    parser = subparsers.add_parser(
        CMD_NAME_DAEMON,
        help=(
            "Run a long-lived JSON-over-stdio daemon for the Gradle plugin "
            "or any other batch caller. Reads newline-delimited JSON from "
            "stdin; writes responses to stdout."
        ),
    )
    parser.add_argument(
        "--usage-log",
        dest="usage_log_path",
        type=Path,
        default=DEFAULT_USAGE_LOG_PATH,
    )


def run_daemon(args: argparse.Namespace) -> int:
    """Drive the request / response loop. Returns 0 on clean stdin
    EOF, non-zero only on unrecoverable startup failure."""
    server = DaemonServer(usage_log_path=args.usage_log_path)
    server.serve(stdin=sys.stdin, stdout=sys.stdout)
    return 0


# --- Daemon server --------------------------------------------------------


class DaemonServer:
    """JSON-over-stdio request handler.

    Construction is cheap; the real work happens in :meth:`serve`. The
    server keeps a small per-provider cache so repeated translate
    requests against the same provider id don't rebuild the SDK
    client (the cycle-2 win for batch jobs like the Gradle plugin).
    """

    def __init__(self, *, usage_log_path: Path = DEFAULT_USAGE_LOG_PATH) -> None:
        self._usage_log_path = usage_log_path
        # Cache: provider_id → built ProviderRouter (each router wraps
        # one concrete backend + a UsageLog handle). Built lazily so a
        # daemon only ever connects to providers the caller asks for.
        self._routers: dict[str, ProviderRouter] = {}

    def serve(self, *, stdin: TextIO, stdout: TextIO) -> None:
        """Read newline-delimited JSON requests from ``stdin`` and
        write responses to ``stdout``. Returns when ``stdin`` reaches
        EOF — the caller (Gradle plugin) closes its end."""
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            response = self._handle_line(line)
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()

    def _handle_line(self, line: str) -> dict[str, Any]:
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            return _error_envelope(
                request_id=None,
                code=ERR_INVALID_JSON,
                message=f"could not parse request as JSON: {exc.msg}",
            )
        if not isinstance(request, dict):
            return _error_envelope(
                request_id=None,
                code=ERR_INVALID_ENVELOPE,
                message="request must be a JSON object",
            )

        request_id_value = request.get(ENVELOPE_KEY_ID)
        request_id = str(request_id_value) if request_id_value is not None else None

        version = request.get(ENVELOPE_KEY_VERSION)
        if version != PROTOCOL_VERSION:
            return _error_envelope(
                request_id=request_id,
                code=ERR_VERSION_MISMATCH,
                message=(
                    f"protocol version mismatch — daemon speaks "
                    f"{PROTOCOL_VERSION!r}, request was {version!r}"
                ),
            )

        op = request.get(ENVELOPE_KEY_OP)
        if not isinstance(op, str):
            return _error_envelope(
                request_id=request_id,
                code=ERR_INVALID_ENVELOPE,
                message="missing or non-string 'op' field",
            )

        params_raw = request.get(ENVELOPE_KEY_PARAMS, {})
        if not isinstance(params_raw, dict):
            return _error_envelope(
                request_id=request_id,
                code=ERR_INVALID_PARAMS,
                message="'params' must be a JSON object",
            )
        params: Mapping[str, Any] = params_raw

        handler = _HANDLERS.get(op)
        if handler is None:
            return _error_envelope(
                request_id=request_id,
                code=ERR_UNKNOWN_OP,
                message=f"unknown op {op!r}; known ops: {sorted(_HANDLERS)}",
            )
        try:
            result = handler(self, params)
        except _DaemonRequestError as exc:
            return _error_envelope(request_id=request_id, code=exc.code, message=str(exc))
        except (ProviderRouteNotFound, ProviderUnsupportedPair) as exc:
            return _error_envelope(
                request_id=request_id,
                code=ERR_PROVIDER_FAILURE,
                message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 — daemon must never crash on caller input
            logger.exception("daemon op %r raised", op)
            return _error_envelope(
                request_id=request_id,
                code=ERR_INTERNAL,
                message=f"{type(exc).__name__}: {exc}",
            )

        return _ok_envelope(request_id=request_id, result=result)

    # --- Op handlers ---

    def _op_ping(self, params: Mapping[str, Any]) -> dict[str, Any]:
        return {"pong": True}

    def _op_translate(self, params: Mapping[str, Any]) -> dict[str, Any]:
        key = params.get(PARAM_KEY)
        source_text = params.get(PARAM_SOURCE_TEXT)
        source_lang = params.get(PARAM_SOURCE_LANG)
        target_lang = params.get(PARAM_TARGET_LANG)
        provider_id = params.get(PARAM_PROVIDER)
        for required, name in (
            (key, PARAM_KEY),
            (source_text, PARAM_SOURCE_TEXT),
            (source_lang, PARAM_SOURCE_LANG),
            (target_lang, PARAM_TARGET_LANG),
            (provider_id, PARAM_PROVIDER),
        ):
            if not isinstance(required, str) or not required:
                raise _DaemonRequestError(
                    code=ERR_INVALID_PARAMS,
                    message=f"translate requires a non-empty string {name!r}",
                )

        # mypy: the loop above narrowed every value to non-empty str.
        assert isinstance(key, str)
        assert isinstance(source_text, str)
        assert isinstance(source_lang, str)
        assert isinstance(target_lang, str)
        assert isinstance(provider_id, str)

        router = self._get_or_build_router(provider_id)
        segment = Segment(key=key, source_text=source_text, source_lang=source_lang)
        result = router.translate(segment, target_lang)
        return _provider_result_to_dict(result)

    def _get_or_build_router(self, provider_id: str) -> ProviderRouter:
        cached = self._routers.get(provider_id)
        if cached is not None:
            return cached
        # Local import avoids pulling the provider's SDK at module
        # import time. Mirrors the cycle-2 CLI's lazy provider build.
        from ainemo.cli.commands import _build_provider

        provider = _build_provider(provider_id)
        router = ProviderRouter(
            providers={provider_id: provider},
            routing_config=RoutingConfig(default_provider=provider_id),
            usage_log=UsageLog(self._usage_log_path),
        )
        self._routers[provider_id] = router
        return router


# --- Helpers --------------------------------------------------------------


class _DaemonRequestError(Exception):
    """Internal — surfaces as a structured error envelope. Carries the
    error-code string the daemon should report to the caller. Any
    other exception is wrapped with ``ERR_INTERNAL``."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _ok_envelope(*, request_id: str | None, result: dict[str, Any]) -> dict[str, Any]:
    return {
        ENVELOPE_KEY_VERSION: PROTOCOL_VERSION,
        ENVELOPE_KEY_ID: request_id,
        ENVELOPE_KEY_OK: True,
        ENVELOPE_KEY_RESULT: result,
    }


def _error_envelope(*, request_id: str | None, code: str, message: str) -> dict[str, Any]:
    return {
        ENVELOPE_KEY_VERSION: PROTOCOL_VERSION,
        ENVELOPE_KEY_ID: request_id,
        ENVELOPE_KEY_OK: False,
        ENVELOPE_KEY_ERROR: {ERROR_KEY_CODE: code, ERROR_KEY_MESSAGE: message},
    }


def _provider_result_to_dict(result: ProviderResult) -> dict[str, Any]:
    return {
        RESULT_TARGET_TEXT: result.target_text,
        RESULT_PROVIDER: result.provider,
        RESULT_MODEL: result.model,
        RESULT_INPUT_TOKENS: result.input_tokens,
        RESULT_OUTPUT_TOKENS: result.output_tokens,
        RESULT_LATENCY_MS: result.latency_ms,
        RESULT_COST_USD: result.cost_usd,
    }


# --- Op dispatch table ---------------------------------------------------

# Defined after the methods exist so type-checkers don't trip on the
# forward reference. Each entry is keyed on the wire op name.
_HANDLERS: dict[str, Callable[["DaemonServer", Mapping[str, Any]], dict[str, Any]]] = {
    OP_PING: DaemonServer._op_ping,
    OP_TRANSLATE: DaemonServer._op_translate,
}


# Provider Protocol satisfaction sanity for the cached provider type.
_: type[Provider]  # noqa: F841 — placeholder for symmetry with sibling modules


__all__ = [
    "CMD_NAME_DAEMON",
    "DaemonServer",
    "PROTOCOL_VERSION",
    "register_daemon",
    "run_daemon",
]
