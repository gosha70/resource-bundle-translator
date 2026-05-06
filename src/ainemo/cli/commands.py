"""Cycle-1 ``nemo`` subcommand implementations.

Each subcommand has a ``register_*`` function that wires its parser
into the top-level dispatcher and a ``run_*`` function that executes
it. Splitting registration from execution keeps the entry-point
module (``ainemo.cli.__init__``) cheap to import — the heavy
dependencies (sentence-transformers, lxml, polib) only load when the
relevant subcommand actually runs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Final

from ainemo.core.adapters.base import BundleAdapter
from ainemo.core.adapters.gettext_po import GettextPoAdapter
from ainemo.core.adapters.i18next_json import I18NextJsonAdapter
from ainemo.core.adapters.java_properties import JavaPropertiesAdapter
from ainemo.core.adapters.xliff import XliffAdapter
from ainemo.core.pipeline import TranslationPipeline
from ainemo.core.segment import Segment
from ainemo.core.tm.sqlite import DEFAULT_TM_PATH, SqliteTranslationMemory
from ainemo.core.validators.base import VIOLATION_SEVERITY_ERROR, Validator
from ainemo.core.validators.forbidden import ForbiddenTermsValidator
from ainemo.core.validators.icu import IcuSyntaxValidator
from ainemo.core.validators.length import LengthBudgetValidator
from ainemo.core.validators.placeholder import PlaceholderParityValidator
from ainemo.providers._ids import (
    PROVIDER_ID_ANTHROPIC,
    PROVIDER_ID_NLLB,
    PROVIDER_ID_NOOP,
    PROVIDER_ID_OLLAMA,
    PROVIDER_ID_OPENAI,
    PROVIDER_ID_OPUS,
)
from ainemo.providers._usage_log import DEFAULT_USAGE_LOG_PATH, UsageLog
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.router import ProviderRouter, RoutingConfig

logger = logging.getLogger(__name__)

# --- Subcommand names (no magic strings) ----------------------------------

CMD_NAME_TRANSLATE: Final = "translate"
CMD_NAME_TM: Final = "tm"
CMD_NAME_VALIDATE: Final = "validate"
CMD_NAME_PROVIDER: Final = "provider"

# --- Adapter registry -----------------------------------------------------

# Format ID → adapter class. Add a new format = add a row.
_ADAPTERS: dict[str, type[BundleAdapter]] = {
    JavaPropertiesAdapter.format_id: JavaPropertiesAdapter,
    I18NextJsonAdapter.format_id: I18NextJsonAdapter,
    GettextPoAdapter.format_id: GettextPoAdapter,
    XliffAdapter.format_id: XliffAdapter,
}

# File extension → format ID, for auto-detection from the source path.
_EXTENSION_TO_FORMAT_ID: dict[str, str] = {
    ext: cls.format_id for cls in _ADAPTERS.values() for ext in cls.file_extensions
}

# Exit codes
_EXIT_OK: Final = 0
_EXIT_VALIDATION_ERROR: Final = 1
_EXIT_USAGE: Final = 2

# --- Provider registry (CLI --provider flag) -----------------------------

# Cycle-2 CLI providers. Order = the choices list shown in `--help`.
# noop is first because it's the safe default for offline pipeline runs.
_PROVIDER_CHOICES: Final = (
    PROVIDER_ID_NOOP,
    PROVIDER_ID_NLLB,
    PROVIDER_ID_OPUS,
    PROVIDER_ID_OPENAI,
    PROVIDER_ID_ANTHROPIC,
    PROVIDER_ID_OLLAMA,
)


# ---------------------------------------------------------------------------
# `nemo translate`
# ---------------------------------------------------------------------------


def register_translate(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    parser = subparsers.add_parser(
        CMD_NAME_TRANSLATE,
        help="Translate a single bundle file to one or more target languages.",
    )
    parser.add_argument("--from", dest="source_path", type=Path, required=True)
    parser.add_argument(
        "--from-lang",
        dest="source_lang",
        default="en-US",
        help="BCP-47 source language tag (default: en-US).",
    )
    parser.add_argument(
        "--to-langs",
        dest="target_langs",
        required=True,
        help="Comma-separated BCP-47 target language tags (e.g. de-DE,fr-FR).",
    )
    parser.add_argument(
        "--format",
        dest="format_id",
        choices=sorted(_ADAPTERS.keys()),
        default=None,
        help="Bundle format. When omitted, inferred from the source path's extension.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=Path("./.ainemo/output"),
    )
    parser.add_argument(
        "--tm-path",
        dest="tm_path",
        type=Path,
        default=DEFAULT_TM_PATH,
    )
    parser.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        help="Escalate validator warnings to errors for this run.",
    )
    parser.add_argument(
        "--forbidden-term",
        dest="forbidden_terms",
        action="append",
        default=[],
        help="Forbidden term to flag in target text. May be repeated.",
    )
    parser.add_argument(
        "--provider",
        dest="provider_id",
        choices=_PROVIDER_CHOICES,
        default=PROVIDER_ID_NOOP,
        help=(
            "Translation provider to use. ``noop`` (default) echoes the "
            "source text and exercises the pipeline without any model. "
            "``nllb`` and ``opus`` are local; ``openai`` requires "
            "OPENAI_API_KEY; ``anthropic`` requires ANTHROPIC_API_KEY; "
            "``ollama`` requires a running Ollama daemon (OLLAMA_HOST or "
            "the localhost:11434 default)."
        ),
    )
    parser.add_argument(
        "--usage-log",
        dest="usage_log_path",
        type=Path,
        default=DEFAULT_USAGE_LOG_PATH,
        help=(
            "JSONL path the router appends per-call usage records to. "
            f"Default: {DEFAULT_USAGE_LOG_PATH}."
        ),
    )


def run_translate(args: argparse.Namespace) -> int:
    _configure_logging()
    source_path: Path = args.source_path
    if not source_path.exists():
        logger.error("Source file not found: %s", source_path)
        return _EXIT_USAGE

    adapter = _resolve_adapter(args.format_id, source_path)
    target_langs = tuple(lang.strip() for lang in args.target_langs.split(",") if lang.strip())
    if not target_langs:
        logger.error("--to-langs must specify at least one language.")
        return _EXIT_USAGE

    tm = SqliteTranslationMemory(args.tm_path)
    try:
        # Cycle-2 CLI: the requested ``--provider`` is built lazily and
        # wrapped in a :class:`ProviderRouter` so every call records to
        # the UsageLog (per AGENTS.md § Provider Rules). The pipeline
        # always sees a router — there is no bare-provider path from the
        # CLI any more, even for the noop default.
        provider: Provider = _build_router(args.provider_id, args.usage_log_path)
        validators = _build_validators(args.forbidden_terms)
        pipeline = TranslationPipeline(
            adapter=adapter,
            tm=tm,
            provider=provider,
            validators=validators,
            target_langs=target_langs,
            source_lang=args.source_lang,
            strict=args.strict,
            # P1 fix (PR #7 review): scope TM lookups to the requested
            # provider so a prior ``--provider noop`` run does not
            # satisfy a later ``--provider openai`` run. Model is left
            # unconstrained — callers who want per-model scoping pass
            # it through the routes-config layer (cycle 3).
            expected_provider=args.provider_id,
        )
        result = pipeline.translate_file(source_path, args.output_dir)
        _print_translate_summary(result)
        if result.error_count > 0:
            return _EXIT_VALIDATION_ERROR
        return _EXIT_OK
    finally:
        tm.close()


# ---------------------------------------------------------------------------
# `nemo tm stats`
# ---------------------------------------------------------------------------


_TM_SUBCMD_STATS: Final = "stats"


def register_tm(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    parser = subparsers.add_parser(CMD_NAME_TM, help="Inspect or maintain the translation memory.")
    tm_sub = parser.add_subparsers(dest="tm_subcommand")
    stats_parser = tm_sub.add_parser(
        _TM_SUBCMD_STATS, help="Print TM size and hit-rate statistics."
    )
    stats_parser.add_argument("--tm-path", dest="tm_path", type=Path, default=DEFAULT_TM_PATH)


def run_tm(args: argparse.Namespace) -> int:
    _configure_logging()
    if args.tm_subcommand != _TM_SUBCMD_STATS:
        logger.error(
            "Unknown `nemo tm` subcommand: %r. Try `nemo tm stats`.",
            args.tm_subcommand,
        )
        return _EXIT_USAGE
    tm_path: Path = args.tm_path
    if not tm_path.exists():
        logger.error("TM database not found: %s", tm_path)
        return _EXIT_USAGE
    tm = SqliteTranslationMemory(tm_path)
    try:
        stats = tm.stats()
        sys.stdout.write(
            f"TM at {tm_path}\n"
            f"  segments:     {stats.segment_count}\n"
            f"  translations: {stats.translation_count}\n"
            f"  target langs: {stats.target_lang_count}\n"
            f"  embeddings:   {stats.embedding_count}\n"
        )
    finally:
        tm.close()
    return _EXIT_OK


# ---------------------------------------------------------------------------
# `nemo validate`
# ---------------------------------------------------------------------------


def register_validate(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    parser = subparsers.add_parser(
        CMD_NAME_VALIDATE,
        help="Re-run validators on an existing translation pair.",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--from-lang", dest="source_lang", default="en-US")
    parser.add_argument("--to-lang", dest="target_lang", required=True)
    parser.add_argument(
        "--format", dest="format_id", choices=sorted(_ADAPTERS.keys()), default=None
    )
    parser.add_argument(
        "--forbidden-term",
        dest="forbidden_terms",
        action="append",
        default=[],
    )


def run_validate(args: argparse.Namespace) -> int:
    _configure_logging()
    source_path: Path = args.source
    target_path: Path = args.target
    if not source_path.exists() or not target_path.exists():
        logger.error("Source or target file not found.")
        return _EXIT_USAGE
    adapter = _resolve_adapter(args.format_id, source_path)
    source_segments = adapter.parse(source_path, args.source_lang)
    target_segments = adapter.parse(target_path, args.source_lang)
    target_by_key = {seg.key: seg for seg in target_segments}
    validators = _build_validators(args.forbidden_terms)

    error_count = 0
    warning_count = 0
    for source_segment in source_segments:
        target_segment = target_by_key.get(source_segment.key)
        if target_segment is None:
            sys.stdout.write(f"[MISSING] {source_segment.key}: no entry in target file\n")
            error_count += 1
            continue
        from ainemo.core.segment import (
            TRANSLATION_SOURCE_MANUAL,
            TranslatedSegment,
        )

        translated = TranslatedSegment(
            segment=source_segment,
            target_lang=args.target_lang,
            target_text=target_segment.source_text,  # the "value" in the target file
            provider="manual",
            confidence=None,
            source=TRANSLATION_SOURCE_MANUAL,
        )
        for validator in validators:
            for violation in validator.check(source_segment, translated):
                sys.stdout.write(
                    f"[{violation.severity.upper()}] {source_segment.key} "
                    f"({violation.validator}): {violation.message}\n"
                )
                if violation.severity == VIOLATION_SEVERITY_ERROR:
                    error_count += 1
                else:
                    warning_count += 1
    sys.stdout.write(f"\nDone. errors={error_count} warnings={warning_count}\n")
    return _EXIT_VALIDATION_ERROR if error_count > 0 else _EXIT_OK


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_provider(provider_id: str) -> Provider:
    """Construct a single concrete provider for the CLI's ``--provider``
    choice. Real-SDK providers (NLLB, OPUS, OpenAI) build their lazy
    clients inside their constructors, so module import stays cheap and
    the CLI prints ``--help`` without reaching for any model weights or
    API keys."""
    if provider_id == PROVIDER_ID_NOOP:
        return _NoOpProvider()
    if provider_id == PROVIDER_ID_NLLB:
        from ainemo.providers.nllb.nllb_provider import NllbProvider

        return NllbProvider()
    if provider_id == PROVIDER_ID_OPUS:
        from ainemo.providers.opus.opus_provider import OpusProvider

        return OpusProvider()
    if provider_id == PROVIDER_ID_OPENAI:
        from ainemo.providers.openai.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if provider_id == PROVIDER_ID_ANTHROPIC:
        from ainemo.providers.anthropic.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if provider_id == PROVIDER_ID_OLLAMA:
        from ainemo.providers.ollama.ollama_provider import OllamaProvider

        return OllamaProvider()
    raise ValueError(f"Unknown provider id: {provider_id!r}. Known ids: {list(_PROVIDER_CHOICES)}.")


def _build_router(provider_id: str, usage_log_path: Path) -> ProviderRouter:
    """Wrap one concrete provider behind a :class:`ProviderRouter`. Even
    a single-provider CLI call goes through the router so cost/latency
    surveillance is uniform across CLI, daemon, and Gradle plugin
    invocations (per AGENTS.md § Provider Rules)."""
    provider = _build_provider(provider_id)
    return ProviderRouter(
        providers={provider_id: provider},
        routing_config=RoutingConfig(default_provider=provider_id),
        usage_log=UsageLog(usage_log_path),
    )


class _NoOpProvider:
    """Cycle-1 placeholder provider. Returns source text unchanged.

    Cycle-2 scope 5 migrates the real backends to the new Provider
    Protocol; until then the CLI ships with this no-op so the pipeline
    runs end-to-end. Validators pass trivially, the TM fills with
    placeholder entries, and the router (once wired) records zero-cost
    zero-latency calls.
    """

    provider_id: ClassVar[str] = PROVIDER_ID_NOOP

    def translate(
        self,
        segment: Segment,
        target_lang: str,
        *,
        system_prompt_addendum: str | None = None,
    ) -> ProviderResult:
        # No-op echoes the source. Cycle-3 S6 system_prompt_addendum
        # has no effect on a passthrough; accepted to satisfy the
        # Provider Protocol.
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
        # No-op accepts every pair — it just echoes input.
        return True


def _resolve_adapter(format_id: str | None, source_path: Path) -> BundleAdapter:
    if format_id is not None:
        return _ADAPTERS[format_id]()
    inferred = _EXTENSION_TO_FORMAT_ID.get(source_path.suffix.lower())
    if inferred is None:
        known = ", ".join(sorted(_EXTENSION_TO_FORMAT_ID.keys()))
        raise SystemExit(
            f"Cannot infer bundle format from extension {source_path.suffix!r}. "
            f"Known extensions: {known}. Pass --format explicitly."
        )
    return _ADAPTERS[inferred]()


def _build_validators(forbidden_terms: list[str]) -> tuple[Validator, ...]:
    validators: list[Validator] = [
        PlaceholderParityValidator(),
        IcuSyntaxValidator(),
        LengthBudgetValidator(),
    ]
    if forbidden_terms:
        validators.append(ForbiddenTermsValidator(forbidden_terms=tuple(forbidden_terms)))
    return tuple(validators)


def _print_translate_summary(result) -> None:  # type: ignore[no-untyped-def]
    sys.stdout.write(
        f"\nTranslation summary:\n"
        f"  source:     {result.source_path}\n"
        f"  TM hits:    {result.tm_hit_count}\n"
        f"  provider:   {result.provider_call_count}\n"
        f"  errors:     {result.error_count}\n"
        f"  warnings:   {result.warning_count}\n"
    )
    for lang, path in result.target_lang_paths.items():
        sys.stdout.write(f"  → {lang}: {path}\n")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# `nemo provider list / stats`
# ---------------------------------------------------------------------------

# Per cycle-2 pitch scope 8: ``nemo provider list`` shows registered
# providers and their availability; ``nemo provider stats`` summarizes
# the UsageLog. ``--since`` filters stats by ISO timestamp.

_PROVIDER_SUBCMD_LIST: Final = "list"
_PROVIDER_SUBCMD_STATS: Final = "stats"


def register_provider(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    parser = subparsers.add_parser(
        CMD_NAME_PROVIDER,
        help="Inspect registered translation providers and call statistics.",
    )
    provider_sub = parser.add_subparsers(dest="provider_subcommand")

    provider_sub.add_parser(
        _PROVIDER_SUBCMD_LIST,
        help="List registered providers and their environment-availability.",
    )

    stats_parser = provider_sub.add_parser(
        _PROVIDER_SUBCMD_STATS,
        help="Aggregate the UsageLog: call counts, tokens, latency, cost.",
    )
    stats_parser.add_argument(
        "--usage-log",
        dest="usage_log_path",
        type=Path,
        default=DEFAULT_USAGE_LOG_PATH,
    )
    stats_parser.add_argument(
        "--since",
        dest="since_iso",
        default=None,
        help="ISO-format timestamp; only count records with timestamp >= this.",
    )


def run_provider(args: argparse.Namespace) -> int:
    _configure_logging()
    sub = args.provider_subcommand
    if sub == _PROVIDER_SUBCMD_LIST:
        return _run_provider_list()
    if sub == _PROVIDER_SUBCMD_STATS:
        return _run_provider_stats(args.usage_log_path, args.since_iso)
    logger.error(
        "Unknown `nemo provider` subcommand: %r. Try `nemo provider list` or "
        "`nemo provider stats`.",
        sub,
    )
    return _EXIT_USAGE


def _run_provider_list() -> int:
    """Print every cycle-2 provider id alongside its environment-
    availability. Availability is best-effort: env-var presence for
    cloud providers, "always" for local providers (NLLB / OPUS / Ollama
    where the precondition is a daemon or a downloaded model rather
    than an env var)."""
    rows = list(_provider_availability_rows())
    sys.stdout.write("Registered providers:\n")
    for provider_id, status, detail in rows:
        sys.stdout.write(f"  {provider_id:<10} {status:<14} {detail}\n")
    return _EXIT_OK


def _provider_availability_rows() -> list[tuple[str, str, str]]:
    import os

    rows: list[tuple[str, str, str]] = []
    rows.append((PROVIDER_ID_NOOP, "available", "always (echoes source text)"))
    rows.append(
        (PROVIDER_ID_NLLB, "available", "local model (downloads from HuggingFace on first use)")
    )
    rows.append(
        (PROVIDER_ID_OPUS, "available", "local model (downloads from HuggingFace on first use)")
    )

    openai_key = os.getenv("OPENAI_API_KEY")
    rows.append(
        (
            PROVIDER_ID_OPENAI,
            "available" if openai_key else "missing-key",
            "OPENAI_API_KEY " + ("set" if openai_key else "not set"),
        )
    )
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    rows.append(
        (
            PROVIDER_ID_ANTHROPIC,
            "available" if anthropic_key else "missing-key",
            "ANTHROPIC_API_KEY " + ("set" if anthropic_key else "not set"),
        )
    )

    ollama_host = os.getenv("OLLAMA_HOST")
    rows.append(
        (
            PROVIDER_ID_OLLAMA,
            "available",
            f"daemon at {ollama_host or 'http://localhost:11434 (default)'}",
        )
    )
    return rows


def _run_provider_stats(usage_log_path: Path, since_iso: str | None) -> int:
    if not usage_log_path.exists():
        sys.stdout.write(f"No usage log at {usage_log_path}; no provider calls recorded yet.\n")
        return _EXIT_OK
    log = UsageLog(usage_log_path)
    since = _parse_iso(since_iso) if since_iso else None
    stats = log.stats(since=since)
    sys.stdout.write(f"Usage log: {usage_log_path}\n")
    if since_iso:
        sys.stdout.write(f"Since:     {since_iso}\n")
    sys.stdout.write(
        f"  calls:               {stats.call_count}\n"
        f"  total input tokens:  {stats.total_input_tokens}\n"
        f"  total output tokens: {stats.total_output_tokens}\n"
        f"  total latency (ms):  {stats.total_latency_ms}\n"
        f"  total cost (USD):    {stats.total_cost_usd:.6f}\n"
    )
    if stats.by_provider:
        sys.stdout.write("  by provider:\n")
        for provider, count in sorted(stats.by_provider.items()):
            sys.stdout.write(f"    {provider:<12} {count}\n")
    if stats.by_model:
        sys.stdout.write("  by model:\n")
        for model, count in sorted(stats.by_model.items()):
            sys.stdout.write(f"    {model:<32} {count}\n")
    return _EXIT_OK


def _parse_iso(s: str) -> datetime:
    """Best-effort ISO-8601 parse. Bare dates accepted as midnight UTC."""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise SystemExit(
            f"--since must be ISO-8601 (e.g. 2026-05-01 or 2026-05-01T12:00:00). Got: {s!r}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


__all__ = [
    "CMD_NAME_TRANSLATE",
    "CMD_NAME_TM",
    "CMD_NAME_VALIDATE",
    "CMD_NAME_PROVIDER",
    "register_translate",
    "register_tm",
    "register_validate",
    "register_provider",
    "run_translate",
    "run_tm",
    "run_validate",
    "run_provider",
]
