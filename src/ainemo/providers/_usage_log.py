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
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Iterator, Mapping

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

    def estimate_for(
        self,
        provider_id: str,
        model: str | None,
        total_tokens: int,
    ) -> float | None:
        """Return an estimated USD cost for a call that consumes
        ``total_tokens`` (input + output) via ``(provider_id, model)``.

        Computed from the **median** cost-per-token of historical records
        on the same JSONL log, multiplied by ``total_tokens``.  Median
        is used rather than mean because a single anomalous batch (e.g.
        a very large segment sent during a benchmark run) would inflate
        the mean and over-estimate every subsequent display.

        Callers that have a character count rather than a token count
        should use :func:`estimate_tokens_from_chars` to convert first
        — token / character ratios are model-specific, but ~4 chars per
        token is a defensible English default.

        Parameters
        ----------
        provider_id:
            The provider id to filter on (must match ``FIELD_PROVIDER``).
        model:
            When not ``None``, also filters by ``FIELD_MODEL == model``.
            When ``None``, matches **any** model for ``provider_id`` —
            useful when the caller knows the provider but not the model
            it will select.
        total_tokens:
            Estimated total tokens (input + output) for the call.  Used
            as the multiplier: ``estimate = median_cost_per_token * total_tokens``.

        Returns
        -------
        float
            Estimated USD cost.
        None
            When no historical records exist for this
            ``(provider_id, model)`` combination, when all matching
            records have a null or non-positive ``cost_usd``, or when
            token counts imply a zero-length call.
        """
        cost_per_token_samples: list[float] = []
        for record in self._iter_records():
            if str(record.get(FIELD_PROVIDER, "")) != provider_id:
                continue
            if model is not None and str(record.get(FIELD_MODEL, "")) != model:
                continue
            cost_raw = record.get(FIELD_COST_USD)
            if cost_raw is None:
                continue
            cost = _as_float(cost_raw)
            if cost <= 0.0:
                continue
            tokens_in_record = _as_int(record.get(FIELD_INPUT_TOKENS)) + _as_int(
                record.get(FIELD_OUTPUT_TOKENS)
            )
            if tokens_in_record <= 0:
                continue
            cost_per_token_samples.append(cost / tokens_in_record)

        if not cost_per_token_samples:
            return None

        median_cost_per_token = statistics.median(cost_per_token_samples)
        return median_cost_per_token * total_tokens

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


# Default token-per-character ratio for English text.
# 4 characters per token is the GPT-3/4 OpenAI rule of thumb; other
# tokenizers vary 2.5–5. Used by ``estimate_tokens_from_chars`` when the
# caller has only a character count (e.g. the QA layer's segment view).
_DEFAULT_CHARS_PER_TOKEN: Final[float] = 4.0


_PROVIDER_CHARS_PER_TOKEN: Final[Mapping[str, float]] = {
    # OpenAI tiktoken cl100k — ~4 chars/token for English; documented at
    # platform.openai.com/tokenizer.
    "openai": 4.0,
    # Anthropic Claude — no published ratio; 3.5 chars/token is a defensible
    # English estimate from public tokenizer comparisons. Treat as ±50%.
    "anthropic": 3.5,
    # NLLB-200 SentencePiece — averages ~2.5 chars/subword on European
    # languages per the FLORES-200 evaluation set.
    "nllb": 2.5,
    # Helsinki-NLP OPUS-MT — SentencePiece, similar density.
    "opus": 2.5,
    # Ollama covers many local models with very different tokenizers;
    # 4.0 is a conservative default that errs on under-counting tokens
    # (and therefore under-estimating cost — local providers are usually
    # zero-cost anyway).
    "ollama": 4.0,
}


def estimate_tokens_from_chars(
    char_count: int,
    *,
    provider_id: str | None = None,
    chars_per_token: float | None = None,
) -> int:
    """Convert a character count to an approximate token count.

    Token-per-character ratios are tokenizer-specific. This helper does
    a best-effort conversion in three layers, in priority order:

    1. ``chars_per_token`` (caller-supplied override) — used as-is.
    2. ``provider_id`` (when provided and known) — looked up in
       :data:`_PROVIDER_CHARS_PER_TOKEN`. OpenAI, Anthropic, NLLB, OPUS,
       Ollama have entries; unknown ids fall through.
    3. The English default ``_DEFAULT_CHARS_PER_TOKEN = 4.0`` (OpenAI
       tiktoken rule of thumb) when neither is supplied.

    The result is a **rough order-of-magnitude estimate**, not a binding
    figure. Callers surfacing this value to users should frame it as
    "estimated cost (±50%)" rather than imply precision — token /
    character ratios fluctuate per language, per content shape, and per
    tokenizer minor version.
    """
    if char_count <= 0:
        return 0
    if chars_per_token is None:
        if provider_id is not None and provider_id in _PROVIDER_CHARS_PER_TOKEN:
            chars_per_token = _PROVIDER_CHARS_PER_TOKEN[provider_id]
        else:
            chars_per_token = _DEFAULT_CHARS_PER_TOKEN
    return max(1, int(round(char_count / chars_per_token)))


__all__ = [
    "DEFAULT_USAGE_LOG_PATH",
    "UsageLog",
    "UsageStats",
    "estimate_tokens_from_chars",
]
