"""Universal data types for the AI-NEMO translation pipeline.

Adapters parse bundle files into :class:`Segment` objects. The translation
memory keys on :attr:`Segment.fingerprint`. Providers translate segments
and return :class:`TranslatedSegment` objects. Validators inspect
``(Segment, TranslatedSegment)`` pairs.

These types are the single contract that connects the four cycle-1 layers
(adapters / TM / providers / validators). Cycle 2+ providers implement
the :class:`ainemo.providers.base.Provider` Protocol against this same
``Segment`` type.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Literal, Mapping

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# The hashing function used to derive `Segment.fingerprint`. SHA-256 is
# stable across Python versions and OSes (unlike `hash()`, which uses
# per-process salts), and the 64-char hex digest is a comfortable TM
# primary-key length.
_FINGERPRINT_HASH = hashlib.sha256

# Field separator used inside the canonical fingerprint pre-image. The
# value is intentionally not a character that can occur in BCP-47 codes
# or placeholder shapes — null byte is a safe choice.
_FINGERPRINT_SEPARATOR = "\x00"

# Source-of-translation tags. Recorded on every TranslatedSegment so the
# pipeline and the reviewer UI can tell exact-cache hits from fuzzy hits
# from fresh provider calls from manual overrides. The `Final` typing
# narrows each constant to its specific Literal so callers can pass the
# constants directly to `TranslatedSegment(source=...)` without `cast`.
TRANSLATION_SOURCE_EXACT_TM: Final = "exact_tm"
TRANSLATION_SOURCE_FUZZY_TM: Final = "fuzzy_tm"
TRANSLATION_SOURCE_PROVIDER: Final = "provider"
TRANSLATION_SOURCE_MANUAL: Final = "manual"

TranslationSource = Literal["exact_tm", "fuzzy_tm", "provider", "manual"]


class PlaceholderKind(str, Enum):
    """Closed set of placeholder shapes the parser recognizes.

    Adapters and providers branch on this. Adding a new kind requires a
    parser update plus updated validators — the closed-enum design makes
    that ripple visible at type-check time.
    """

    POSITIONAL = "positional"  # {0}, {1}
    NAMED = "named"  # {name}, {user_id}
    ICU_PLURAL = "icu_plural"  # {count, plural, ...}
    ICU_SELECT = "icu_select"  # {gender, select, ...}
    ICU_SELECTORDINAL = "icu_selectordinal"  # {place, selectordinal, ...}


@dataclass(frozen=True)
class Placeholder:
    """A single placeholder discovered in a source string.

    ``raw`` is the original substring including its braces, so
    adapters can round-trip it back into output without reconstructing
    syntax. ``span`` is the (start, end) offset in the source string —
    half-open, like Python slicing.
    """

    kind: PlaceholderKind
    raw: str
    span: tuple[int, int]


@dataclass(frozen=True)
class Segment:
    """A unit of source text plus its placeholder structure and metadata.

    Segments are the universal currency of the pipeline. Adapters
    produce them; the TM keys on them; providers translate them;
    validators inspect them.
    """

    key: str
    """Bundle key (e.g. ``"login.button.submit"``). Adapter-defined."""

    source_text: str
    """The exact source-language text, including placeholders inline."""

    source_lang: str
    """BCP-47 language tag (e.g. ``"en-US"``)."""

    placeholders: tuple[Placeholder, ...] = ()
    """Placeholders parsed out of ``source_text``, in left-to-right order."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Adapter-specific metadata: comments, max-length, context hints."""

    @property
    def fingerprint(self) -> str:
        """Stable SHA-256 hex digest used as the TM primary key.

        The pre-image combines source text, source language, and the
        canonical placeholder shape (the kinds and their relative
        positions, not their offsets — so identical messages with
        whitespace differences inside placeholders still collide
        intentionally).
        """
        placeholder_shape = _FINGERPRINT_SEPARATOR.join(
            f"{ph.kind.value}:{ph.raw}" for ph in self.placeholders
        )
        preimage = _FINGERPRINT_SEPARATOR.join(
            (self.source_text, self.source_lang, placeholder_shape)
        )
        return _FINGERPRINT_HASH(preimage.encode("utf-8")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class TranslatedSegment:
    """A :class:`Segment` plus its translation into one target language.

    All fields are keyword-only (``kw_only=True``). This is intentional:
    cycle 2 added the ``model`` field, and silently inserting it among
    the existing fields in any other order would mis-bind positional
    arguments at every external call site (the reviewer flagged the
    P2 risk on PR #6). Forcing keyword-only construction means future
    field additions never silently corrupt existing code.
    """

    segment: Segment
    target_lang: str
    """BCP-47 target language tag."""

    target_text: str
    """Translated text. Placeholders restored to their source forms."""

    provider: str
    """Provider id that produced this translation (e.g. ``"openai"``,
    ``"nllb"``, ``"manual"``)."""

    confidence: float | None = None
    """Optional 0..1 confidence score. ``None`` when the provider does
    not expose one."""

    source: TranslationSource = TRANSLATION_SOURCE_PROVIDER
    """Where the translation came from — see ``TRANSLATION_SOURCE_*``."""

    model: str = ""
    """Model id within the provider — e.g. ``"gpt-4o-2024-11-20"`` for
    ``provider="openai"``, ``"claude-sonnet-4-5-20250929"`` for
    ``provider="anthropic"``, ``"nllb-200-distilled-600M"`` for
    ``provider="nllb"``. Cycle-2 introduced this so the TM keys on
    ``(fingerprint, target_lang, provider, model)`` — two models behind
    one provider id no longer overwrite each other's cached
    translations. Empty string for cycle-1-era TM rows or when the
    provider does not expose a model id (e.g. legacy ``manual`` source)."""


__all__ = [
    "PlaceholderKind",
    "Placeholder",
    "Segment",
    "TranslatedSegment",
    "TranslationSource",
    "TRANSLATION_SOURCE_EXACT_TM",
    "TRANSLATION_SOURCE_FUZZY_TM",
    "TRANSLATION_SOURCE_PROVIDER",
    "TRANSLATION_SOURCE_MANUAL",
]
