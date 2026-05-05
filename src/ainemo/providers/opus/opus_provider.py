"""OPUS-MT provider — cycle-2 Provider Protocol.

Implements :class:`ainemo.providers.base.Provider` over Helsinki-NLP's
OPUS-MT family of pair-specific MarianMT models. **English source
only** in cycle 2 (matching the cycle-1 prototype scope); cycle 3+
extends to other source languages by populating per-source maps.

OPUS-MT semantics that the cycle-2 wrapping handles:

- Pair-specific model loading: each ``en→<target>`` route uses a
  different HF repo; :class:`MarianModelCache` caches per-repo.
- Target-language token prefixing: grouped models (Romance, Slavic,
  Germanic, Multilingual) require ``>>{token}<<`` at the start of
  the input to disambiguate the desired target language.
- Per-target model-prefix override (Korean uses
  ``opus-mt-tc-big-`` because the standard Korean model is
  unusable).
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Final

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_OPUS
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.opus._client import MarianModelCache
from ainemo.providers.opus._languages import (
    OpusTargetConfig,
    is_supported_source,
    to_opus_config,
)

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Maximum output tokens for the Marian generation. Resource-bundle
# strings are short; 400 matches the cycle-1 prototype headroom and
# is well under MarianMT's 512-token context.
DEFAULT_MAX_LENGTH: Final = 400

# Token-prefix template for grouped models. Inserted at the start of
# the source text when the target's :attr:`OpusTargetConfig.required_token`
# is True.
_TOKEN_PREFIX_TEMPLATE: Final = ">>{token}<<{text}"


class OpusProvider:
    """Local OPUS-MT translator behind the cycle-2 Provider Protocol."""

    provider_id: ClassVar[str] = PROVIDER_ID_OPUS

    def __init__(
        self,
        *,
        max_length: int = DEFAULT_MAX_LENGTH,
        cache_dir: str | None = None,
        cache: MarianModelCache | None = None,
    ) -> None:
        self._max_length = max_length
        # `cache` is injectable so unit tests pass a stub without
        # downloading any HF model. Production leaves it None and the
        # provider builds its own cache.
        self._cache = cache or MarianModelCache(cache_dir=cache_dir)

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        if not is_supported_source(segment.source_lang):
            raise ValueError(
                f"OpusProvider supports English source only in cycle 2; "
                f"got source_lang={segment.source_lang!r}. Route to "
                f"NllbProvider for non-English sources, or extend the "
                f"OPUS source-language map in cycle 3+."
            )
        config = to_opus_config(target_lang)
        if config is None:
            raise ValueError(
                f"OpusProvider has no en→{target_lang} model registered. "
                f"Use `supports()` to gate before calling, or extend "
                f"`ainemo.providers.opus._languages._TARGETS`."
            )

        prepared_text = _prepare_input(segment.source_text, config)
        tokenizer, model = self._cache.get(config.hf_model_name)

        started = time.perf_counter()
        target_text = _translate_with_marian(
            tokenizer=tokenizer,
            model=model,
            text=prepared_text,
            max_length=self._max_length,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        return ProviderResult(
            target_text=target_text,
            provider=self.provider_id,
            model=config.hf_model_name,
            input_tokens=None,  # OPUS-MT doesn't expose token counts.
            output_tokens=None,
            latency_ms=elapsed_ms,
            cost_usd=None,  # Local model, no per-call cost.
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return is_supported_source(source_lang) and to_opus_config(target_lang) is not None


def _prepare_input(text: str, config: OpusTargetConfig) -> str:
    """Apply the target-language token prefix when the config requires
    one. Otherwise the input is passed through verbatim."""
    if config.required_token and config.language_token:
        return _TOKEN_PREFIX_TEMPLATE.format(token=config.language_token, text=text)
    return text


def _translate_with_marian(
    *,
    tokenizer: Any,
    model: Any,
    text: str,
    max_length: int,
) -> str:
    """Run a MarianMT generate cycle. Pulled into a free function so
    tests can mock the HF call without standing up MarianMT types."""
    inputs = tokenizer(
        text,
        return_tensors="pt",
        padding=True,
        max_length=max_length,
        truncation=True,
    )
    translated = model.generate(**inputs)
    return str(tokenizer.decode(translated[0], skip_special_tokens=True))


_: type[Provider] = OpusProvider  # Protocol-conformance check at load time.


__all__ = ["DEFAULT_MAX_LENGTH", "OpusProvider"]
