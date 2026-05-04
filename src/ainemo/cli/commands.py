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
from ainemo.providers._ids import PROVIDER_ID_NOOP
from ainemo.providers.base import Provider, ProviderResult

logger = logging.getLogger(__name__)

# --- Subcommand names (no magic strings) ----------------------------------

CMD_NAME_TRANSLATE: Final = "translate"
CMD_NAME_TM: Final = "tm"
CMD_NAME_VALIDATE: Final = "validate"

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
        # Cycle-1 CLI ships without a real provider — translation
        # against a live model is provider-shaped and lands in cycle 2
        # via `nemo daemon`. For cycle-1 the CLI is wired end-to-end
        # against a `_NoOpProvider` that returns the source text
        # unchanged; this validates the full pipeline plumbing
        # (parse → TM → provider → validators → serialize) on real
        # files and surfaces TM cache hits on second runs. Real
        # translation is a `--provider` flag in cycle 2.
        provider: Provider = _NoOpProvider()
        validators = _build_validators(args.forbidden_terms)
        pipeline = TranslationPipeline(
            adapter=adapter,
            tm=tm,
            provider=provider,
            validators=validators,
            target_langs=target_langs,
            source_lang=args.source_lang,
            strict=args.strict,
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


class _NoOpProvider:
    """Cycle-1 placeholder provider. Returns source text unchanged.

    Cycle-2 scope 5 migrates the real backends to the new Provider
    Protocol; until then the CLI ships with this no-op so the pipeline
    runs end-to-end. Validators pass trivially, the TM fills with
    placeholder entries, and the router (once wired) records zero-cost
    zero-latency calls.
    """

    provider_id: ClassVar[str] = PROVIDER_ID_NOOP

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
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


__all__ = [
    "CMD_NAME_TRANSLATE",
    "CMD_NAME_TM",
    "CMD_NAME_VALIDATE",
    "register_translate",
    "register_tm",
    "register_validate",
    "run_translate",
    "run_tm",
    "run_validate",
]
