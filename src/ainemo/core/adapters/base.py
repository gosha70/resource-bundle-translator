"""The :class:`BundleAdapter` Protocol and shared adapter helpers.

Every cycle-1 adapter implements this Protocol exactly. The pipeline
(scope 9) and the CLI (scope 10) operate on the Protocol surface only —
they don't import concrete adapter classes directly.

Design notes
------------

The pitch's original interface listed ``preserve_placeholders`` /
``restore_placeholders`` on the adapter. Those concerns moved to the
:class:`ainemo.providers.base.Provider` Protocol (cycle 2), since
LLM-tokenization is provider-shaped, not file-format-shaped — different
providers want different token shapes for the same placeholder. The
adapter's job ends at producing a Segment with its placeholders parsed
into structured form; tokenizing them for a specific model is the
provider's call.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from ainemo.core.segment import Segment, TranslatedSegment


@runtime_checkable
class BundleAdapter(Protocol):
    """Convert one bundle-file format to and from
    :class:`ainemo.core.segment.Segment` objects.

    The contract every implementation must satisfy:

    1. ``parse(path, source_lang)`` returns Segments preserving the
       original key order. Each Segment has placeholders parsed into
       structured form via :func:`ainemo.core.icu.parse_placeholders`.
    2. ``serialize(path, translated, target_lang)`` writes a file in
       the same format. Round-trip identity holds:
       ``parse → serialize → parse`` produces the same Segment list
       (modulo translated text) for every adapter-specific fixture.
    3. ``format_id`` is a stable, kebab-cased identifier used by the
       pipeline to look up the right adapter.
    4. ``file_extensions`` lists extensions (with leading dot) the
       adapter handles, for auto-detection by the CLI.
    """

    format_id: ClassVar[str]
    """Stable kebab-cased identifier (e.g. ``"java-properties"``,
    ``"i18next-json"``)."""

    file_extensions: ClassVar[tuple[str, ...]]
    """File extensions including the leading dot (e.g.
    ``(".properties",)``)."""

    def parse(self, path: Path, source_lang: str) -> tuple[Segment, ...]:
        """Read ``path`` and return Segments in original key order."""
        ...

    def serialize(
        self,
        path: Path,
        translated: tuple[TranslatedSegment, ...],
        target_lang: str,
    ) -> None:
        """Write ``translated`` to ``path`` in this adapter's format.

        ``target_lang`` is supplied explicitly (rather than read off the
        TranslatedSegments) so adapters that need it for filename or
        in-file metadata (e.g. XLIFF's ``trgLang`` attribute) have
        access without iterating the list. Implementations should
        cross-check that every TranslatedSegment's ``target_lang``
        matches and raise on mismatch.
        """
        ...


__all__ = ["BundleAdapter"]
