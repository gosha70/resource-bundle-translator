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
from typing import Literal, Mapping

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
# from fresh provider calls from manual overrides.
TRANSLATION_SOURCE_EXACT_TM = "exact_tm"
TRANSLATION_SOURCE_FUZZY_TM = "fuzzy_tm"
TRANSLATION_SOURCE_PROVIDER = "provider"
TRANSLATION_SOURCE_MANUAL = "manual"

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


@dataclass(frozen=True)
class TranslatedSegment:
    """A :class:`Segment` plus its translation into one target language."""

    segment: Segment
    target_lang: str
    """BCP-47 target language tag."""

    target_text: str
    """Translated text. Placeholders restored to their source forms."""

    provider: str
    """Provider id that produced this translation (e.g. ``"openai"``,
    ``"nllb"``, ``"manual"``)."""

    confidence: float | None
    """Optional 0..1 confidence score. ``None`` when the provider does
    not expose one."""

    source: TranslationSource
    """Where the translation came from — see ``TRANSLATION_SOURCE_*``."""


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
