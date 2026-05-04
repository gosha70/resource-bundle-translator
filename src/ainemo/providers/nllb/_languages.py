"""BCP-47 → NLLB-200 language code mapping.

NLLB-200 (Facebook's No Language Left Behind) uses ISO 639-3 codes
plus a script tag (e.g. ``"eng_Latn"`` for English in Latin script,
``"zho_Hans"`` for Simplified Chinese). Cycle-2 segments key on
BCP-47 (``"en-US"``, ``"zh-CN"``, etc.); the table below translates.

Reference:
https://github.com/facebookresearch/flores/blob/main/flores200/README.md#languages-in-flores-200
"""

from __future__ import annotations

from typing import Final, Mapping

# Map keys are normalized — lowercase BCP-47 strings with `-` separators
# preserved. Lookup helper :func:`to_nllb_code` does case-folding.
# Region tags are stripped on lookup (en-US == en-GB == en for NLLB
# purposes — the model doesn't differentiate).
_BCP47_TO_NLLB: Final[Mapping[str, str]] = {
    "ar": "arb_Arab",  # Modern Standard Arabic
    "de": "deu_Latn",  # German
    "el": "ell_Grek",  # Greek
    "en": "eng_Latn",  # English (any region — model doesn't differentiate)
    "es": "spa_Latn",  # Spanish
    "fr": "fra_Latn",  # French (any region)
    "it": "ita_Latn",  # Italian
    "iw": "heb_Hebr",  # Hebrew (legacy code; Java's Locale uses "iw")
    "he": "heb_Hebr",  # Hebrew (modern code)
    "hi": "hin_Deva",  # Hindi
    "ja": "jpn_Jpan",  # Japanese
    "ko": "kor_Hang",  # Korean
    "nl": "nld_Latn",  # Dutch
    "pl": "pol_Latn",  # Polish
    "pt": "por_Latn",  # Portuguese
    "ru": "rus_Cyrl",  # Russian
    "sv": "swe_Latn",  # Swedish
    "th": "tha_Thai",  # Thai
    "tr": "tur_Latn",  # Turkish
    "zh-cn": "zho_Hans",  # Chinese, Simplified
    "zh-hans": "zho_Hans",  # Chinese, Simplified (script-tagged)
    "zh-hk": "zho_Hant",  # Chinese, Traditional (Hong Kong)
    "zh-tw": "zho_Hant",  # Chinese, Traditional (Taiwan)
    "zh-hant": "zho_Hant",  # Chinese, Traditional (script-tagged)
    "zh": "zho_Hans",  # Chinese, default to Simplified
}


def to_nllb_code(bcp47: str) -> str | None:
    """Translate a BCP-47 tag to an NLLB language code.

    Returns ``None`` for unknown tags (the caller — typically
    :meth:`NllbProvider.supports` — uses ``None`` as the "unsupported"
    signal). Case-insensitive; falls back to the language subtag when
    the full tag isn't mapped (e.g. ``"en-US"`` → ``"en"`` →
    ``"eng_Latn"``).
    """
    if not bcp47:
        return None
    normalized = bcp47.lower()
    if normalized in _BCP47_TO_NLLB:
        return _BCP47_TO_NLLB[normalized]
    # Strip region: "en-US" → "en"
    primary = normalized.split("-", 1)[0]
    return _BCP47_TO_NLLB.get(primary)


def supported_bcp47_tags() -> tuple[str, ...]:
    """Return the BCP-47 tags this provider knows. Used by the router
    config-validation pass and exposed via ``nemo provider list``."""
    return tuple(sorted(_BCP47_TO_NLLB.keys()))


__all__ = ["to_nllb_code", "supported_bcp47_tags"]
