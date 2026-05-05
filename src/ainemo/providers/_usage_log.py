"""Append-only JSONL log of every provider call.

Per AGENTS.md § Provider Rules: "All LLM provider calls wrapped with
cost + latency tracking. Every call records (provider, model,
input_tokens, output_tokens, latency_ms, cost). No bare provider
invocations." The router (scope 4) calls :meth:`UsageLog.record` after
every successful provider call; ``nemo provider stats`` (scope 8) reads
the same file back via :meth:`UsageLog.stats`.

The log is local-first by design — no telemetry, no phone-home (per
AGENTS.md). Default path is ``~/.ainemo/usage.jsonl``; users opt
elsewhere via the router config.

JSONL was chosen over a SQLite table because:
- Build-time tool, no concurrent writers (a single ``nemo translate``
  or ``nemo daemon`` process appends).
- Append-only writes are cheap and crash-safe even under
  ``SIGKILL`` — the worst case is a partial last line, which is
  trivial to detect and skip on read.
- Users can grep/jq/wc the log without a DB driver. Cycle 5+ may
  surface it through the reviewer UI, which would still read the
  JSONL.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Iterator

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Default location for the log. Per AGENTS.md, ``.ainemo/`` is in
# .gitignore — not committed.
DEFAULT_USAGE_LOG_PATH: Final = Path.home() / ".ainemo" / "usage.jsonl"

# JSON field names. Defined as constants so `record()` and `stats()`
# stay in lockstep when fields evolve, and so future cycles (cooldown
# reports, reviewer UI) can import the same names.
FIELD_TIMESTAMP: Final = "timestamp"
FIELD_PROVIDER: Final = "provider"
FIELD_MODEL: Final = "model"
FIELD_SOURCE_LANG: Final = "source_lang"
FIELD_TARGET_LANG: Final = "target_lang"
FIELD_SEGMENT_FINGERPRINT: Final = "segment_fingerprint"
FIELD_INPUT_TOKENS: Final = "input_tokens"
FIELD_OUTPUT_TOKENS: Final = "output_tokens"
FIELD_LATENCY_MS: Final = "latency_ms"
FIELD_COST_USD: Final = "cost_usd"


@dataclass(frozen=True)
class UsageStats:
    """Aggregate counts over a window of UsageLog records."""

    call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_latency_ms: int
    total_cost_usd: float
    by_provider: dict[str, int]
    """call_count grouped by provider id."""

    by_model: dict[str, int]
    """call_count grouped by model id."""


class UsageLog:
    """Single-writer JSONL log. Construct with the path; methods are
    file-IO so they're cheap to call once per provider invocation."""

    def __init__(self, path: Path = DEFAULT_USAGE_LOG_PATH) -> None:
        self._path = path
        # Lazy mkdir on first record() / stats() call so importing the
        # module is side-effect-free.

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int,
        cost_usd: float | None,
        source_lang: str,
        target_lang: str,
        segment_fingerprint: str,
    ) -> None:
        """Append one provider-call record. ``None`` token/cost values
        are stored as JSON null so the read side can distinguish
        "not measured" from zero."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            FIELD_TIMESTAMP: _utc_now_iso(),
            FIELD_PROVIDER: provider,
            FIELD_MODEL: model,
            FIELD_SOURCE_LANG: source_lang,
            FIELD_TARGET_LANG: target_lang,
            FIELD_SEGMENT_FINGERPRINT: segment_fingerprint,
            FIELD_INPUT_TOKENS: input_tokens,
            FIELD_OUTPUT_TOKENS: output_tokens,
            FIELD_LATENCY_MS: latency_ms,
            FIELD_COST_USD: cost_usd,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def stats(self, since: datetime | None = None) -> UsageStats:
        """Read the log and aggregate. ``since`` filters by timestamp
        (ISO-format comparison; UTC). Missing log file returns zeros."""
        call_count = 0
        total_input = 0
        total_output = 0
        total_latency = 0
        total_cost = 0.0
        by_provider: dict[str, int] = {}
        by_model: dict[str, int] = {}
        since_iso = since.isoformat() if since is not None else None
        for record in self._iter_records():
            if since_iso is not None and str(record.get(FIELD_TIMESTAMP, "")) < since_iso:
                continue
            call_count += 1
            total_input += _as_int(record.get(FIELD_INPUT_TOKENS))
            total_output += _as_int(record.get(FIELD_OUTPUT_TOKENS))
            total_latency += _as_int(record.get(FIELD_LATENCY_MS))
            total_cost += _as_float(record.get(FIELD_COST_USD))
            provider = str(record.get(FIELD_PROVIDER, ""))
            model = str(record.get(FIELD_MODEL, ""))
            by_provider[provider] = by_provider.get(provider, 0) + 1
            by_model[model] = by_model.get(model, 0) + 1
        return UsageStats(
            call_count=call_count,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_latency_ms=total_latency,
            total_cost_usd=total_cost,
            by_provider=by_provider,
            by_model=by_model,
        )

    def _iter_records(self) -> Iterator[dict[str, object]]:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Partial-write at SIGKILL time — skip. The JSONL
                    # design tolerates exactly this case.
                    continue


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_int(value: object) -> int:
    """Coerce a JSON-decoded value to int. ``None`` and missing fields
    become 0 so partial records (e.g. local providers without token
    counts) sum cleanly. Non-numeric values become 0 rather than
    raising — the log is best-effort observability."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _as_float(value: object) -> float:
    """Same shape as :func:`_as_int` for float-typed fields."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _now_ms() -> int:
    """Wall-clock ms since epoch — handy for callers timing provider
    calls before they have a result to record."""
    return int(time.time() * 1000)


__all__ = [
    "DEFAULT_USAGE_LOG_PATH",
    "UsageLog",
    "UsageStats",
]
