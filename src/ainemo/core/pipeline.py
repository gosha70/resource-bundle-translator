"""Translation pipeline orchestrator.

Cycle-1 :class:`TranslationPipeline` ties the four layers together:

1. **Adapter** parses the source file → list of Segments.
2. **TM** is consulted first for each Segment; exact + fuzzy.
3. **Provider** is called only for TM misses.
4. **Validators** check each translation; ``error`` violations block
   the write; ``warning`` violations are logged.
5. Successful translations are stored back to the TM.
6. **Adapter** serializes the translated segments → target file.

The pipeline is target-language-aware: a single source file fans out
into one output file per requested target language.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ainemo.core.adapters.base import BundleAdapter
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    Segment,
    TranslatedSegment,
)
from ainemo.core.tm.base import (
    DEFAULT_FUZZY_THRESHOLD,
    TM_MATCH_TYPE_EXACT,
    TranslationMemory,
)
from ainemo.core.validators.base import (
    VIOLATION_SEVERITY_ERROR,
    Validator,
    Violation,
)
from ainemo.providers.base import Provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SegmentOutcome:
    """Per-segment per-target-lang result captured for the run summary."""

    segment_key: str
    target_lang: str
    translated: TranslatedSegment | None
    """``None`` when an error-severity validator blocked the write."""

    violations: tuple[Violation, ...]
    """Every violation surfaced for this segment, both error and
    warning severity. The reviewer UI groups by segment."""


@dataclass(frozen=True)
class PipelineResult:
    """Aggregate result of one ``translate_file`` call."""

    source_path: Path
    target_lang_paths: dict[str, Path]
    """Map of target-lang → written output path."""

    outcomes: tuple[SegmentOutcome, ...]

    tm_hit_count: int
    """Number of segments served from TM (exact or fuzzy) — informs
    the cache-hit-rate benchmark in scope 11."""

    provider_call_count: int
    """Number of segments forwarded to the provider — the cost driver."""

    error_count: int = field(default=0)
    """Number of segments blocked by error-severity violations."""

    warning_count: int = field(default=0)


class TranslationPipeline:
    """Orchestrates the four-layer translation pipeline."""

    def __init__(
        self,
        adapter: BundleAdapter,
        tm: TranslationMemory,
        provider: Provider,
        validators: Sequence[Validator],
        target_langs: Sequence[str],
        *,
        source_lang: str,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
        strict: bool = False,
        expected_provider: str | None = None,
        expected_model: str | None = None,
    ) -> None:
        self._adapter = adapter
        self._tm = tm
        self._provider = provider
        self._validators = tuple(validators)
        self._target_langs = tuple(target_langs)
        self._source_lang = source_lang
        self._fuzzy_threshold = fuzzy_threshold
        self._strict = strict
        # Cycle-2 P1 fix (PR #7 review): when the caller commits to a
        # specific provider (e.g. ``nemo translate --provider openai``),
        # the TM lookup is scoped to rows produced by that provider.
        # Without this, a prior ``--provider noop`` (or a different
        # backend) run can satisfy a later run for a different
        # provider — silently bypassing the requested model. ``None``
        # preserves cycle-1 "any cached translation" semantics for
        # callers that haven't opted into a specific provider.
        self._expected_provider = expected_provider
        self._expected_model = expected_model

    def translate_file(self, source_path: Path, output_dir: Path) -> PipelineResult:
        segments = self._adapter.parse(source_path, self._source_lang)
        output_dir.mkdir(parents=True, exist_ok=True)

        outcomes: list[SegmentOutcome] = []
        target_lang_paths: dict[str, Path] = {}
        tm_hit_count = 0
        provider_call_count = 0
        error_count = 0
        warning_count = 0

        for target_lang in self._target_langs:
            translated_for_lang: list[TranslatedSegment] = []
            for segment in segments:
                outcome, was_tm_hit = self._translate_one(segment, target_lang)
                outcomes.append(outcome)
                if outcome.translated is not None:
                    translated_for_lang.append(outcome.translated)
                if was_tm_hit:
                    tm_hit_count += 1
                else:
                    provider_call_count += 1
                for v in outcome.violations:
                    if v.severity == VIOLATION_SEVERITY_ERROR:
                        error_count += 1
                    else:
                        warning_count += 1

            output_path = _output_path_for_lang(
                source_path=source_path,
                output_dir=output_dir,
                target_lang=target_lang,
                file_extensions=self._adapter.file_extensions,
            )
            self._adapter.serialize(output_path, tuple(translated_for_lang), target_lang)
            target_lang_paths[target_lang] = output_path

        return PipelineResult(
            source_path=source_path,
            target_lang_paths=target_lang_paths,
            outcomes=tuple(outcomes),
            tm_hit_count=tm_hit_count,
            provider_call_count=provider_call_count,
            error_count=error_count,
            warning_count=warning_count,
        )

    # --- Internals ---

    def _translate_one(self, segment: Segment, target_lang: str) -> tuple[SegmentOutcome, bool]:
        hit = self._tm.lookup(
            segment,
            target_lang,
            self._fuzzy_threshold,
            provider=self._expected_provider,
            model=self._expected_model,
        )
        if hit is not None and hit.match_type == TM_MATCH_TYPE_EXACT:
            translated = hit.translated
            tm_hit = True
        elif hit is not None:
            # Fuzzy hit — accept (cycle 1's design choice; cycle 5's
            # reviewer UI gates auto-promotion).
            translated = hit.translated
            tm_hit = True
        else:
            # Cycle-2: provider returns ProviderResult (rich payload
            # with concrete provider id, model id, tokens, latency,
            # cost). The pipeline threads ``result.provider`` and
            # ``result.model`` into the TranslatedSegment so TM rows
            # key on (fingerprint, target_lang, provider, model). When
            # ``self._provider`` is a ProviderRouter, its ``provider_id``
            # is the façade ``"router"``; the concrete backend that
            # actually translated names itself via ``result.provider``.
            # The router (scope 4) records the full ProviderResult to
            # UsageLog.
            result = self._provider.translate(segment, target_lang)
            translated = TranslatedSegment(
                segment=segment,
                target_lang=target_lang,
                target_text=result.target_text,
                provider=result.provider,
                model=result.model,
                confidence=result.confidence,
                source=TRANSLATION_SOURCE_PROVIDER,
            )
            tm_hit = False

        violations: list[Violation] = []
        for validator in self._validators:
            violations.extend(validator.check(segment, translated))

        has_blocking = any(self._is_blocking(v) for v in violations)

        if has_blocking:
            logger.warning(
                "Segment %r blocked by %d error-severity violation(s); skipping write.",
                segment.key,
                sum(1 for v in violations if v.severity == VIOLATION_SEVERITY_ERROR),
            )
            return (
                SegmentOutcome(
                    segment_key=segment.key,
                    target_lang=target_lang,
                    translated=None,
                    violations=tuple(violations),
                ),
                tm_hit,
            )

        # Successful translation — store back to TM if it came from the
        # provider (TM hits are already stored).
        if not tm_hit:
            self._tm.store(translated)

        return (
            SegmentOutcome(
                segment_key=segment.key,
                target_lang=target_lang,
                translated=translated,
                violations=tuple(violations),
            ),
            tm_hit,
        )

    def _is_blocking(self, violation: Violation) -> bool:
        if violation.severity == VIOLATION_SEVERITY_ERROR:
            return True
        # In strict mode, warnings escalate to blocking.
        return self._strict


_LOCALE_SUFFIX_PATTERN = re.compile(r"_(?:[a-z]{2,3})(?:_[A-Za-z][A-Za-z0-9]{1,3})?$")
"""Matches a trailing locale tag in a filename stem.

Recognized shapes (after the underscore separator):
- ``en``, ``deu`` — 2/3-letter language code
- ``en_US`` — language + region
- ``zh_Hant`` — language + script
The match is anchored to the end of the stem and is greedy on the
multi-part form: ``messages_en_US`` matches ``_en_US`` (not just
``_US``).
"""


def _output_path_for_lang(
    *,
    source_path: Path,
    output_dir: Path,
    target_lang: str,
    file_extensions: tuple[str, ...],
) -> Path:
    """Derive the per-language output path.

    Convention: ``messages_en_US.properties`` + target ``de-DE`` →
    ``messages_de_DE.properties`` (cycle 1 keeps the cycle-0
    convention of one file per language with the lang code in the
    stem).
    """
    extension = file_extensions[0] if file_extensions else source_path.suffix
    stem = source_path.stem
    safe_lang = _filename_safe_lang(target_lang)
    stripped = _LOCALE_SUFFIX_PATTERN.sub("", stem)
    if stripped == stem:
        # No locale tag detected — append target lang.
        new_stem = f"{stem}_{safe_lang}"
    else:
        new_stem = f"{stripped}_{safe_lang}"
    return output_dir / f"{new_stem}{extension}"


def _filename_safe_lang(lang: str) -> str:
    """Normalize BCP-47 to a filename-safe form: dashes → underscores."""
    return lang.replace("-", "_")


__all__ = [
    "PipelineResult",
    "SegmentOutcome",
    "TranslationPipeline",
]
