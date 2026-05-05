"""BCP-47 → OPUS-MT model configuration map.

Helsinki-NLP's OPUS-MT models are pair-specific (one HF model per
``en-<target>`` route). Cycle-2 OPUS provider supports **English
source only** — the same scope as the cycle-1 prototype. Each target
language has:

- A model id segment (used to build the HF model name as
  ``Helsinki-NLP/{prefix}en-{model_id}``).
- An optional language-token prefix (some grouped models — Romance,
  Slavic, Germanic — require ``>>token<<`` at the start of the input
  to disambiguate the desired target).
- A model prefix override (Korean uses ``opus-mt-tc-big-`` because
  the standard OPUS-MT Korean model is unusable).

Reference: https://huggingface.co/Helsinki-NLP
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping

# Cycle-2 source-language scope — English only, matching the cycle-1
# prototype. Cycle 3+ may extend by populating per-source maps.
SOURCE_LANG_BCP47: Final = "en"

_DEFAULT_PREFIX: Final = "opus-mt-"


@dataclass(frozen=True)
class OpusTargetConfig:
    """One target-language entry for the en→target OPUS-MT family."""

    bcp47: str
    model_id: str
    """The post-``en-`` segment of the HF model name. For grouped
    models this is the family code (``ROMANCE``, ``gem``, ``sla``,
    ``trk``, ``mul``); for single-language models it's the language
    code (``ar``, ``de``, ``el``, …)."""

    language_token: str = ""
    """Token to prefix the input with as ``>>{language_token}<<`` —
    required for grouped models so they pick the right output
    language. Empty for single-language models."""

    required_token: bool = False
    """When True, the provider must inject ``>>{language_token}<<`` at
    the start of every source string passed to this target."""

    model_prefix: str = _DEFAULT_PREFIX
    """Override for the model-name prefix. Standard is ``opus-mt-``;
    Korean uses ``opus-mt-tc-big-``."""

    @property
    def hf_model_name(self) -> str:
        """Full HuggingFace repo id for this en→target route."""
        return f"Helsinki-NLP/{self.model_prefix}{SOURCE_LANG_BCP47}-{self.model_id}"


# Map keyed on lowercased BCP-47 target tag. Region-tagged variants
# (``en-US`` ↔ ``en-GB``, ``fr-CA`` ↔ ``fr-FR``, ``zh-CN`` ↔
# ``zh-HK``) are handled in :func:`to_opus_config` via primary-subtag
# fallback or explicit entries.
_TARGETS: Final[Mapping[str, OpusTargetConfig]] = {
    "ar": OpusTargetConfig(bcp47="ar", model_id="ar", language_token="ara", required_token=True),
    "de": OpusTargetConfig(bcp47="de", model_id="gem", language_token="deu", required_token=True),
    "el": OpusTargetConfig(bcp47="el", model_id="el"),
    "es": OpusTargetConfig(
        bcp47="es", model_id="ROMANCE", language_token="es", required_token=True
    ),
    "fr": OpusTargetConfig(
        bcp47="fr", model_id="ROMANCE", language_token="fr", required_token=True
    ),
    "it": OpusTargetConfig(
        bcp47="it", model_id="ROMANCE", language_token="it", required_token=True
    ),
    # Hebrew aliases: 'iw' (Java Locale legacy) and 'he' (modern).
    "he": OpusTargetConfig(bcp47="he", model_id="he"),
    "iw": OpusTargetConfig(bcp47="iw", model_id="he"),
    "hi": OpusTargetConfig(bcp47="hi", model_id="hi"),
    "ja": OpusTargetConfig(bcp47="ja", model_id="jap"),
    "ko": OpusTargetConfig(
        bcp47="ko",
        model_id="ko",
        model_prefix="opus-mt-tc-big-",
    ),
    "nl": OpusTargetConfig(bcp47="nl", model_id="gem", language_token="nld", required_token=True),
    "pl": OpusTargetConfig(bcp47="pl", model_id="sla", language_token="pol", required_token=True),
    "pt": OpusTargetConfig(
        bcp47="pt", model_id="ROMANCE", language_token="pt", required_token=True
    ),
    "ru": OpusTargetConfig(bcp47="ru", model_id="sla", language_token="rus", required_token=True),
    "sv": OpusTargetConfig(bcp47="sv", model_id="sv"),
    "th": OpusTargetConfig(bcp47="th", model_id="mul", language_token="tha", required_token=True),
    "tr": OpusTargetConfig(bcp47="tr", model_id="trk"),
    # Chinese variants — the OPUS-MT Chinese model takes the script
    # token to choose between Simplified and Traditional output.
    "zh-cn": OpusTargetConfig(
        bcp47="zh-cn",
        model_id="zh",
        language_token="cmn_Hans",
        required_token=True,
    ),
    "zh-hk": OpusTargetConfig(
        bcp47="zh-hk",
        model_id="zh",
        language_token="cmn_Hant",
        required_token=True,
    ),
    # Default 'zh' to Simplified (matches NLLB convention).
    "zh": OpusTargetConfig(
        bcp47="zh",
        model_id="zh",
        language_token="cmn_Hans",
        required_token=True,
    ),
}


def is_supported_source(bcp47: str) -> bool:
    """Cycle-2 OPUS supports English source only."""
    if not bcp47:
        return False
    return bcp47.lower().split("-", 1)[0] == SOURCE_LANG_BCP47


def to_opus_config(bcp47: str) -> OpusTargetConfig | None:
    """Resolve a BCP-47 target tag to an :class:`OpusTargetConfig`.

    Case-insensitive. Falls back to the primary subtag when the full
    tag isn't mapped (so ``fr-CA`` → ``fr``); explicit region entries
    (``zh-CN`` vs ``zh-HK``) take precedence."""
    if not bcp47:
        return None
    normalized = bcp47.lower()
    if normalized in _TARGETS:
        return _TARGETS[normalized]
    primary = normalized.split("-", 1)[0]
    return _TARGETS.get(primary)


def supported_target_tags() -> tuple[str, ...]:
    """Return the BCP-47 target tags this provider supports (sorted).
    Surfaced via ``nemo provider list`` (scope 8)."""
    return tuple(sorted(_TARGETS.keys()))


__all__ = [
    "SOURCE_LANG_BCP47",
    "OpusTargetConfig",
    "is_supported_source",
    "to_opus_config",
    "supported_target_tags",
]
