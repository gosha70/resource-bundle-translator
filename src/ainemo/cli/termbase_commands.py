# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""``nemo termbase`` subcommand — cycle-3 S5 + cycle-4 S4 + S5.

Seven sub-subcommands:

- ``nemo termbase init`` — create a fresh Kuzu termbase + sync the
  three starter personas (cycle-3 S4).
- ``nemo termbase import <file.tbx>`` — import a TBX 3.0 file
  (cycle-3 S2).
- ``nemo termbase export <file.tbx>`` — export to TBX 3.0
  (cycle-3 S3).
- ``nemo termbase promote`` — run the auto-promotion algorithm
  over the cycle-1 TM. ``--accept-all`` writes every candidate to
  the termbase; ``--review`` (default) walks them interactively.
- ``nemo termbase stats`` — print termbase counts.
- ``nemo termbase import-from-csv <file.csv>`` — import a CSV via
  a YAML field-mapping (cycle-4 S4). Supports ``--encoding``,
  ``--delimiter``, ``--namespace``.
- ``nemo termbase import-from-jsonl <file.jsonl>`` — same shape
  as ``import-from-csv`` but for JSON-Lines (cycle-4 S5).

The ``register_*`` / ``run_*`` split mirrors
:mod:`ainemo.cli.commands` so the dispatcher in
:mod:`ainemo.cli` stays consistent.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
from pathlib import Path
from typing import Final, Sequence, TextIO

from ainemo.core.termbase._ids import (
    DEFAULT_PROMOTION_CONSISTENCY_MIN,
    DEFAULT_PROMOTION_FREQUENCY_MIN,
    DEFAULT_TERMBASE_PATH,
    TERM_SOURCE_TM_PROMOTION,
)
from ainemo.core.termbase.base import Concept, Term, Termbase
from ainemo.core.termbase.kuzu.store import KuzuTermbase
from ainemo.core.termbase.persona_loader import sync_personas_into_termbase
from ainemo.core.termbase.promotion import PromotionCandidate, find_candidates
from ainemo.core.termbase.sources._ids import (
    DEFAULT_CSV_DELIMITER,
    DEFAULT_CSV_ENCODING,
)
from ainemo.core.termbase.sources.csv_source import (
    CsvDecodeError,
    CsvSource,
    MissingColumnError,
)
from ainemo.core.termbase.sources.jsonl_source import (
    JsonlDecodeError,
    JsonLinesSource,
)
from ainemo.core.termbase.sources.loader import load_into_termbase
from ainemo.core.termbase.sources.mapping import (
    field_mapping_from_yaml_dict,
)
from ainemo.core.termbase.tbx.exporter import TbxExporter
from ainemo.core.termbase.tbx.importer import TbxImporter
from ainemo.core.tm.sqlite import DEFAULT_TM_PATH, SqliteTranslationMemory

logger = logging.getLogger(__name__)


# --- Subcommand names (no magic strings; AGENTS.md § Prohibited Patterns) ---

CMD_NAME_TERMBASE: Final = "termbase"

_TB_SUBCMD_INIT: Final = "init"
_TB_SUBCMD_IMPORT: Final = "import"
_TB_SUBCMD_EXPORT: Final = "export"
_TB_SUBCMD_PROMOTE: Final = "promote"
_TB_SUBCMD_STATS: Final = "stats"
_TB_SUBCMD_IMPORT_FROM_CSV: Final = "import-from-csv"
_TB_SUBCMD_IMPORT_FROM_JSONL: Final = "import-from-jsonl"

# --- Review-loop input tokens ---

_REVIEW_ACCEPT: Final = "y"
_REVIEW_SKIP: Final = "n"
_REVIEW_QUIT: Final = "q"
_REVIEW_PROMPT: Final = "[y]es / [n]o / [q]uit > "

# --- Exit codes (mirror commands.py) ---

_EXIT_OK: Final = 0
_EXIT_USAGE: Final = 2


def register_termbase(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    parser = subparsers.add_parser(
        CMD_NAME_TERMBASE,
        help="Manage the concept-oriented termbase (init / import / export / promote / stats).",
    )
    tb_sub = parser.add_subparsers(dest="termbase_subcommand")

    init_parser = tb_sub.add_parser(
        _TB_SUBCMD_INIT,
        help=(
            "Create a fresh Kuzu termbase and sync the starter personas. "
            "Idempotent — re-running on an existing termbase is a no-op."
        ),
    )
    _add_termbase_path(init_parser)
    init_parser.add_argument(
        "--persona-dir",
        dest="persona_dir",
        type=Path,
        default=None,
        help=(
            "Override the persona directory (default: the package's bundled "
            "personas under src/ainemo/personas/)."
        ),
    )

    import_parser = tb_sub.add_parser(
        _TB_SUBCMD_IMPORT,
        help="Import a TBX 3.0 file into the termbase.",
    )
    import_parser.add_argument("tbx_path", type=Path)
    _add_termbase_path(import_parser)

    export_parser = tb_sub.add_parser(
        _TB_SUBCMD_EXPORT,
        help="Export the termbase contents to a TBX 3.0 file.",
    )
    export_parser.add_argument("tbx_path", type=Path)
    export_parser.add_argument(
        "--domain-id",
        dest="domain_id",
        default=None,
        help="Restrict export to concepts attached to this domain.",
    )
    _add_termbase_path(export_parser)

    promote_parser = tb_sub.add_parser(
        _TB_SUBCMD_PROMOTE,
        help=(
            "Scan the TM for promotable n-grams and write accepted "
            "candidates as Concept + Term rows."
        ),
    )
    promote_parser.add_argument("--source-lang", dest="source_lang", required=True)
    promote_parser.add_argument("--target-lang", dest="target_lang", required=True)
    _add_termbase_path(promote_parser)
    promote_parser.add_argument("--tm-path", dest="tm_path", type=Path, default=DEFAULT_TM_PATH)
    mode_group = promote_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--review",
        dest="review",
        action="store_true",
        help="Default mode — walk each candidate and ask y/n/q.",
    )
    mode_group.add_argument(
        "--accept-all",
        dest="accept_all",
        action="store_true",
        help="Write every candidate to the termbase without prompting.",
    )
    promote_parser.add_argument(
        "--min-frequency",
        dest="min_frequency",
        type=int,
        default=DEFAULT_PROMOTION_FREQUENCY_MIN,
        help=f"Minimum n-gram frequency (default: {DEFAULT_PROMOTION_FREQUENCY_MIN}).",
    )
    promote_parser.add_argument(
        "--min-consistency",
        dest="min_consistency",
        type=float,
        default=DEFAULT_PROMOTION_CONSISTENCY_MIN,
        help=(
            "Minimum agreement-rate across the n-gram's TM rows "
            f"(default: {DEFAULT_PROMOTION_CONSISTENCY_MIN})."
        ),
    )

    stats_parser = tb_sub.add_parser(
        _TB_SUBCMD_STATS,
        help="Print termbase concept / term / domain / persona counts.",
    )
    _add_termbase_path(stats_parser)

    # Cycle-4 S4 — import-from-csv. Takes a positional CSV path,
    # mandatory --map-config (YAML mapping file per cycle-4 S1 +
    # pre-resolved Q2: no inline --map flags), optional CSV-dialect
    # overrides, optional --namespace for collision-disambiguation
    # when the mapping has no `domain_column`.
    import_csv_parser = tb_sub.add_parser(
        _TB_SUBCMD_IMPORT_FROM_CSV,
        help=(
            "Import a CSV file into the termbase via a YAML field-mapping "
            "config (e.g. a team's brand glossary, a Google Sheet export)."
        ),
    )
    import_csv_parser.add_argument("csv_path", type=Path)
    import_csv_parser.add_argument(
        "--map-config",
        dest="map_config",
        type=Path,
        required=True,
        help="Path to the YAML field-mapping file (see docs/importers.md, S6).",
    )
    import_csv_parser.add_argument(
        "--encoding",
        dest="encoding",
        default=DEFAULT_CSV_ENCODING,
        help=(
            "CSV file encoding (default: utf-8). Use `--encoding latin-1` "
            "for legacy European exports."
        ),
    )
    import_csv_parser.add_argument(
        "--delimiter",
        dest="delimiter",
        default=DEFAULT_CSV_DELIMITER,
        help=(
            "CSV field delimiter (default: ','). Use `--delimiter '\\t'` for tab-separated files."
        ),
    )
    import_csv_parser.add_argument(
        "--namespace",
        dest="namespace",
        default=None,
        help=(
            "Per-import namespace tag for concept-id derivation. Disambiguates "
            "two imports that share source surfaces (e.g. `marketing` vs "
            "`legal`) when the mapping has no `domain_column`. Row-level "
            "`domain_id` overrides this flag."
        ),
    )
    _add_termbase_path(import_csv_parser)

    # Cycle-4 S5 — import-from-jsonl. Same shape as
    # import-from-csv minus the CSV-dialect overrides
    # (--delimiter doesn't apply to JSONL; --encoding stays for
    # parity but JSONL is conventionally utf-8).
    import_jsonl_parser = tb_sub.add_parser(
        _TB_SUBCMD_IMPORT_FROM_JSONL,
        help=(
            "Import a JSON-Lines file into the termbase via a YAML "
            "field-mapping config (e.g. an `npm run extract-terms` "
            "dump or any one-record-per-line JSON dump)."
        ),
    )
    import_jsonl_parser.add_argument("jsonl_path", type=Path)
    import_jsonl_parser.add_argument(
        "--map-config",
        dest="map_config",
        type=Path,
        required=True,
        help="Path to the YAML field-mapping file (see docs/importers.md, S6).",
    )
    import_jsonl_parser.add_argument(
        "--encoding",
        dest="encoding",
        default=DEFAULT_CSV_ENCODING,
        help=(
            "JSONL file encoding (default: utf-8). JSONL is utf-8 by "
            "convention; the override exists for parity with "
            "`import-from-csv`."
        ),
    )
    import_jsonl_parser.add_argument(
        "--namespace",
        dest="namespace",
        default=None,
        help=(
            "Per-import namespace tag for concept-id derivation. Same "
            "semantics as `import-from-csv --namespace`."
        ),
    )
    _add_termbase_path(import_jsonl_parser)


def run_termbase(
    args: argparse.Namespace,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    sub = args.termbase_subcommand
    if sub == _TB_SUBCMD_INIT:
        return _run_init(args, out=out, err=err)
    if sub == _TB_SUBCMD_IMPORT:
        return _run_import(args, out=out, err=err)
    if sub == _TB_SUBCMD_EXPORT:
        return _run_export(args, out=out, err=err)
    if sub == _TB_SUBCMD_PROMOTE:
        return _run_promote(args, stdin=stdin, out=out, err=err)
    if sub == _TB_SUBCMD_STATS:
        return _run_stats(args, out=out, err=err)
    if sub == _TB_SUBCMD_IMPORT_FROM_CSV:
        return _run_import_from_csv(args, out=out, err=err)
    if sub == _TB_SUBCMD_IMPORT_FROM_JSONL:
        return _run_import_from_jsonl(args, out=out, err=err)
    known = (
        _TB_SUBCMD_INIT,
        _TB_SUBCMD_IMPORT,
        _TB_SUBCMD_EXPORT,
        _TB_SUBCMD_PROMOTE,
        _TB_SUBCMD_STATS,
        _TB_SUBCMD_IMPORT_FROM_CSV,
        _TB_SUBCMD_IMPORT_FROM_JSONL,
    )
    err.write(f"Unknown `nemo termbase` subcommand: {sub!r}. Try one of {', '.join(known)}.\n")
    return _EXIT_USAGE


# --- Sub-runners ---


def _run_init(args: argparse.Namespace, *, out: TextIO, err: TextIO) -> int:
    tb_path: Path = args.termbase_path
    tb = KuzuTermbase(tb_path)
    try:
        n = sync_personas_into_termbase(tb, args.persona_dir)
        out.write(f"Initialized termbase at {tb_path} ({n} starter personas synced).\n")
    finally:
        tb.close()
    return _EXIT_OK


def _run_import(args: argparse.Namespace, *, out: TextIO, err: TextIO) -> int:
    tbx_path: Path = args.tbx_path
    if not tbx_path.exists():
        err.write(f"TBX file not found: {tbx_path}\n")
        return _EXIT_USAGE
    tb = KuzuTermbase(args.termbase_path)
    try:
        report = TbxImporter(tb).import_file(tbx_path)
        out.write(
            f"Imported {report.concepts_added} concepts, "
            f"{report.terms_added} terms, "
            f"{report.domains_added} domains.\n"
        )
        if report.synthesized_id_count:
            out.write(
                f"  ({report.synthesized_id_count} ids derived from the source — "
                "@id was absent on those rows).\n"
            )
        if report.skipped_unsupported:
            out.write(
                f"  {len(report.skipped_unsupported)} elements outside the "
                "documented subset were skipped:\n"
            )
            for entry in report.skipped_unsupported:
                out.write(f"    - {entry}\n")
    finally:
        tb.close()
    return _EXIT_OK


def _run_export(args: argparse.Namespace, *, out: TextIO, err: TextIO) -> int:
    tb = KuzuTermbase(args.termbase_path)
    try:
        TbxExporter(tb).export_file(args.tbx_path, domain_id=args.domain_id)
        out.write(f"Exported termbase to {args.tbx_path}.\n")
    finally:
        tb.close()
    return _EXIT_OK


def _run_promote(
    args: argparse.Namespace,
    *,
    stdin: TextIO | None,
    out: TextIO,
    err: TextIO,
) -> int:
    tm_path: Path = args.tm_path
    if not tm_path.exists():
        err.write(f"TM database not found: {tm_path}\n")
        return _EXIT_USAGE
    tm = SqliteTranslationMemory(tm_path)
    try:
        candidates = find_candidates(
            tm,
            args.source_lang,
            args.target_lang,
            min_frequency=args.min_frequency,
            min_consistency=args.min_consistency,
        )
    finally:
        tm.close()

    if not candidates:
        out.write("No promotion candidates met the thresholds.\n")
        return _EXIT_OK

    if args.accept_all:
        accepted = candidates
    else:
        # Default to review mode — `--review` is implicit when neither
        # flag is present so a bare `nemo termbase promote` is the
        # safe interactive default.
        input_stream = stdin if stdin is not None else sys.stdin
        accepted = _review_loop(candidates, input_stream=input_stream, out=out)

    if not accepted:
        out.write("No candidates accepted; termbase unchanged.\n")
        return _EXIT_OK

    tb = KuzuTermbase(args.termbase_path)
    try:
        for candidate in accepted:
            _write_candidate(tb, candidate)
    finally:
        tb.close()
    out.write(f"Promoted {len(accepted)} candidates into the termbase.\n")
    return _EXIT_OK


def _run_stats(args: argparse.Namespace, *, out: TextIO, err: TextIO) -> int:
    tb_path: Path = args.termbase_path
    if not tb_path.exists():
        err.write(f"Termbase not found: {tb_path}\n")
        return _EXIT_USAGE
    tb = KuzuTermbase(tb_path)
    try:
        stats = tb.stats()
        out.write(
            f"Termbase at {tb_path}\n"
            f"  concepts: {stats.concept_count}\n"
            f"  domains:  {stats.domain_count}\n"
            f"  personas: {stats.persona_count}\n"
            f"  terms by language:\n"
        )
        for lang, count in stats.term_count_by_lang:
            out.write(f"    {lang}: {count}\n")
    finally:
        tb.close()
    return _EXIT_OK


def _run_import_from_csv(args: argparse.Namespace, *, out: TextIO, err: TextIO) -> int:
    """Cycle-4 S4 — drain a CSV file through CsvSource +
    load_into_termbase into the configured Kuzu termbase."""
    csv_path: Path = args.csv_path
    if not csv_path.exists():
        err.write(f"CSV file not found: {csv_path}\n")
        return _EXIT_USAGE

    map_config_path: Path = args.map_config
    if not map_config_path.exists():
        err.write(
            f"Field-mapping file not found: {map_config_path}. "
            "See docs/importers.md for the YAML schema.\n"
        )
        return _EXIT_USAGE

    # Load mapping. yaml.safe_load + the cycle-4 S1 helper give us
    # one ValueError surface for both shape errors (top-level not a
    # mapping) and Pydantic validation errors (unknown field, blank
    # value, missing mandatory field).
    import yaml
    from pydantic import ValidationError

    try:
        raw = yaml.safe_load(map_config_path.read_text(encoding="utf-8"))
        mapping = field_mapping_from_yaml_dict(raw)
    except (ValueError, ValidationError, yaml.YAMLError) as exc:
        err.write(f"Invalid field-mapping in {map_config_path}: {exc}\n")
        return _EXIT_USAGE

    # Normalize common shell escapes for `--delimiter` before
    # handing to csv.DictReader, which requires exactly one
    # character. The help text says `--delimiter '\t'`, but most
    # shells pass that through as the two-character string `\t`
    # (the shell doesn't expand backslash escapes inside single or
    # plain double quotes — only $'...' ANSI-C quoting does, and
    # most users don't know that). Without normalization, the
    # operator gets a stdlib TypeError they have to debug.
    try:
        delimiter = _normalize_delimiter(args.delimiter)
    except ValueError as exc:
        err.write(f"Invalid --delimiter value: {exc}\n")
        return _EXIT_USAGE

    source = CsvSource(
        csv_path,
        mapping,
        encoding=args.encoding,
        delimiter=delimiter,
    )
    tb = KuzuTermbase(args.termbase_path)
    try:
        try:
            report = load_into_termbase(tb, source, namespace=args.namespace)
        except (MissingColumnError, CsvDecodeError) as exc:
            # File-level errors per the TermbaseSource contract —
            # surface them on stderr with exit 2 so the operator
            # doesn't have to read a Python traceback.
            err.write(f"{exc}\n")
            return _EXIT_USAGE
    finally:
        tb.close()

    out.write(
        f"Imported {report.concepts_added} concepts, "
        f"{report.terms_added} terms, "
        f"{report.domains_added} domains.\n"
    )
    if report.rows_skipped:
        out.write(f"  ({report.rows_skipped} rows skipped:)\n")
        for entry in report.skipped_details:
            out.write(f"    - {entry}\n")
    return _EXIT_OK


def _run_import_from_jsonl(args: argparse.Namespace, *, out: TextIO, err: TextIO) -> int:
    """Cycle-4 S5 — drain a JSON-Lines file through JsonLinesSource +
    load_into_termbase into the configured Kuzu termbase.

    Mirrors :func:`_run_import_from_csv` minus the CSV-dialect
    overrides (no `--delimiter`, no shell-escape normalization);
    JSONL has no field separator and the encoding default is utf-8
    by convention.
    """
    jsonl_path: Path = args.jsonl_path
    if not jsonl_path.exists():
        err.write(f"JSONL file not found: {jsonl_path}\n")
        return _EXIT_USAGE

    map_config_path: Path = args.map_config
    if not map_config_path.exists():
        err.write(
            f"Field-mapping file not found: {map_config_path}. "
            "See docs/importers.md for the YAML schema.\n"
        )
        return _EXIT_USAGE

    import yaml
    from pydantic import ValidationError

    try:
        raw = yaml.safe_load(map_config_path.read_text(encoding="utf-8"))
        mapping = field_mapping_from_yaml_dict(raw)
    except (ValueError, ValidationError, yaml.YAMLError) as exc:
        err.write(f"Invalid field-mapping in {map_config_path}: {exc}\n")
        return _EXIT_USAGE

    source = JsonLinesSource(jsonl_path, mapping, encoding=args.encoding)
    tb = KuzuTermbase(args.termbase_path)
    try:
        try:
            report = load_into_termbase(tb, source, namespace=args.namespace)
        except JsonlDecodeError as exc:
            err.write(f"{exc}\n")
            return _EXIT_USAGE
    finally:
        tb.close()

    out.write(
        f"Imported {report.concepts_added} concepts, "
        f"{report.terms_added} terms, "
        f"{report.domains_added} domains.\n"
    )
    if report.rows_skipped:
        out.write(f"  ({report.rows_skipped} rows skipped:)\n")
        for entry in report.skipped_details:
            out.write(f"    - {entry}\n")
    return _EXIT_OK


# --- Review loop ---


def _review_loop(
    candidates: Sequence[PromotionCandidate],
    *,
    input_stream: TextIO,
    out: TextIO,
) -> tuple[PromotionCandidate, ...]:
    accepted: list[PromotionCandidate] = []
    for index, candidate in enumerate(candidates, start=1):
        out.write(
            f"\n[{index}/{len(candidates)}] {candidate.source_ngram!r} → "
            f"{candidate.suggested_target!r}\n"
            f"  frequency={candidate.frequency} "
            f"consistency={candidate.consistency:.2f}\n"
        )
        out.write(_REVIEW_PROMPT)
        out.flush()
        line = input_stream.readline()
        if not line:
            # EOF — treat as quit so a piped empty stdin doesn't loop.
            break
        choice = line.strip().lower()
        if choice == _REVIEW_QUIT:
            break
        if choice == _REVIEW_ACCEPT:
            accepted.append(candidate)
            continue
        # Anything other than `y` (including `n`, blank, typos) is a
        # skip. The prompt advertises only y/n/q, but treating
        # ambiguous input as skip is the safer default than silently
        # accepting.
    return tuple(accepted)


def _write_candidate(tb: Termbase, candidate: PromotionCandidate) -> None:
    # Deterministic concept id derived from the candidate's natural
    # key — (source_lang, target_lang, source_ngram, suggested_target).
    # Re-running `nemo termbase promote --accept-all` against
    # unchanged TM data must upsert onto the same concept_id rather
    # than write a duplicate Concept + Term triple. Same content-
    # addressed-id pattern as the cycle-3 S2 TBX importer fix.
    concept_id = _derive_promotion_concept_id(candidate)
    now = int(time.time())
    concept = Concept(
        concept_id=concept_id,
        qid=None,
        definition=None,
        created_at=now,
    )
    source_term = Term(
        term_id=f"{concept_id}-{candidate.source_lang}",
        concept_id=concept_id,
        lang=candidate.source_lang,
        surface=candidate.source_ngram,
        register=None,
        part_of_speech=None,
        source=TERM_SOURCE_TM_PROMOTION,
    )
    target_term = Term(
        term_id=f"{concept_id}-{candidate.target_lang}",
        concept_id=concept_id,
        lang=candidate.target_lang,
        surface=candidate.suggested_target,
        register=None,
        part_of_speech=None,
        source=TERM_SOURCE_TM_PROMOTION,
    )
    tb.add_concept(concept, [source_term, target_term])


# --- Helpers ---


def _derive_promotion_concept_id(candidate: PromotionCandidate) -> str:
    """Stable, content-addressed concept id for an auto-promoted
    candidate.

    Re-running ``nemo termbase promote --accept-all`` against
    unchanged TM data must upsert onto the same concept rather than
    write a duplicate. The hash is over the natural key —
    ``(source_lang, target_lang, source_ngram, suggested_target)`` —
    joined by the ASCII unit separator (``\\x1f``) so the four
    fields cannot collide via delimiter ambiguity. Truncated to 16
    hex chars (64 bits): more than enough for the cycle-3 termbase
    scale and matches the cycle-3 S2 TBX-importer term-id pattern.
    """
    payload = "\x1f".join(
        (
            candidate.source_lang,
            candidate.target_lang,
            candidate.source_ngram,
            candidate.suggested_target,
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"tm-promo-{digest[:16]}"


_DELIMITER_ESCAPES: Final = {
    "\\t": "\t",
    "\\n": "\n",
    "\\r": "\r",
    "\\v": "\v",
    "\\f": "\f",
    "\\0": "\0",
}


def _normalize_delimiter(value: str) -> str:
    """Resolve common shell-escaped CSV delimiter inputs to a single
    character. Cycle-4 S4 P1 fix.

    The help text says ``--delimiter '\\t'``. In most shells that
    string lands here verbatim as the two-character sequence ``\\t``
    (Bash, zsh, fish all leave backslash escapes literal inside
    single and plain double quotes; only ``$'\\t'`` ANSI-C quoting
    expands). Without this normalization, csv.DictReader raises
    ``TypeError: "delimiter" must be a 1-character string`` on
    every tab-separated import.

    Resolution order: known escape sequence → resolved char; single
    character → returned as-is; anything else → ``ValueError`` with
    a useful message. We do NOT use ``codecs.decode("unicode_escape")``
    because that pulls in surprising semantics for unrelated escapes
    (e.g. ``\\u``); the closed set of supported escapes is more
    predictable.
    """
    if value in _DELIMITER_ESCAPES:
        return _DELIMITER_ESCAPES[value]
    if len(value) == 1:
        return value
    raise ValueError(
        f"{value!r} must be exactly one character (or a recognized "
        f"escape: {sorted(_DELIMITER_ESCAPES)}). "
        "Most shells pass `--delimiter '\\t'` through verbatim — "
        "use ANSI-C quoting `$'\\t'` for a literal tab, or rely on "
        "the recognized-escape normalization."
    )


def _add_termbase_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--termbase-path",
        dest="termbase_path",
        type=Path,
        default=Path(DEFAULT_TERMBASE_PATH),
        help=f"Path to the Kuzu termbase directory (default: {DEFAULT_TERMBASE_PATH}).",
    )


__all__ = [
    "CMD_NAME_TERMBASE",
    "register_termbase",
    "run_termbase",
]
