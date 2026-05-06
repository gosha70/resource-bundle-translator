"""NLLB-200 provider — cycle-2 Provider Protocol.

Implements :class:`ainemo.providers.base.Provider` over Facebook's
NLLB-200 model via HuggingFace ``transformers``. NLLB is a local
neural-machine-translation model — no API calls, no token billing.
``cost_usd`` and token counts are always ``None`` on the
ProviderResult; latency is measured wall-clock.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Final, cast

from ainemo.core.segment import Segment
from ainemo.providers._ids import PROVIDER_ID_NLLB
from ainemo.providers.base import Provider, ProviderResult
from ainemo.providers.nllb._client import DEFAULT_MODEL, NllbModelHolder
from ainemo.providers.nllb._languages import to_nllb_code

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Maximum output tokens for the HF generation pipeline. Resource-bundle
# strings are short; NLLB's encoder/decoder context is 1024 tokens, so
# 400 is a safe headroom for the longest single segment we'd realistically
# translate (matches the cycle-0 prototype).
DEFAULT_MAX_LENGTH: Final = 400


class NllbProvider:
    """Local NLLB-200 translator behind the cycle-2 Provider Protocol."""

    provider_id: ClassVar[str] = PROVIDER_ID_NLLB

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        max_length: int = DEFAULT_MAX_LENGTH,
        cache_dir: str | None = None,
        model_holder: NllbModelHolder | None = None,
    ) -> None:
        self._model_id = model
        self._max_length = max_length
        # `model_holder` is injectable so unit tests pass a stub
        # without downloading 2.5GB. Production leaves it None and
        # the provider builds a real holder on first translate.
        self._holder = model_holder or NllbModelHolder(model_id=model, cache_dir=cache_dir)

    def translate(
        self,
        segment: Segment,
        target_lang: str,
        *,
        system_prompt_addendum: str | None = None,
    ) -> ProviderResult:
        # NLLB-200 is a seq2seq model with no system-prompt surface,
        # so the cycle-3 S6 `system_prompt_addendum` is accepted-and-
        # ignored here. The pipeline still injects the addendum for
        # LLM providers in the same call site.
        del system_prompt_addendum
        from_code = to_nllb_code(segment.source_lang)
        to_code = to_nllb_code(target_lang)
        if from_code is None or to_code is None:
            raise ValueError(
                f"NllbProvider does not support {segment.source_lang!r} → "
                f"{target_lang!r}. Use `supports()` to gate before "
                f"calling, or extend the BCP-47 → NLLB-200 map in "
                f"`ainemo.providers.nllb._languages`."
            )

        tokenizer, model = self._holder.load()

        started = time.perf_counter()
        target_text = _translate_with_pipeline(
            tokenizer=tokenizer,
            model=model,
            text=segment.source_text,
            from_code=from_code,
            to_code=to_code,
            max_length=self._max_length,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        return ProviderResult(
            target_text=target_text,
            provider=self.provider_id,
            model=self._model_id,
            input_tokens=None,  # NLLB doesn't expose token counts.
            output_tokens=None,
            latency_ms=elapsed_ms,
            cost_usd=None,  # Local model — no per-call cost.
            confidence=None,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return to_nllb_code(source_lang) is not None and to_nllb_code(target_lang) is not None


def _translate_with_pipeline(
    *,
    tokenizer: Any,
    model: Any,
    text: str,
    from_code: str,
    to_code: str,
    max_length: int,
) -> str:
    """Build a one-shot translation pipeline and return the target
    text. Pulled into a free function so tests can mock it cheaply
    without standing up the HF transformers types."""
    from transformers import pipeline

    # The cycle-2 transformers stubs enumerate every task name as a
    # Literal overload, but ``"translation"`` is missing despite being
    # supported at runtime (transformers maps it onto a TextGeneration-
    # like translation pipeline). Cast through Any so mypy stops trying
    # to find a matching overload.
    pipeline_factory = cast(Any, pipeline)
    translator = pipeline_factory(
        task="translation",
        model=model,
        tokenizer=tokenizer,
        src_lang=from_code,
        tgt_lang=to_code,
        max_length=max_length,
    )
    output = translator(text)
    if not output:
        raise RuntimeError("NLLB translation pipeline returned empty output.")
    return str(output[0]["translation_text"])


_: type[Provider] = NllbProvider  # Protocol-conformance check at load time.


__all__ = ["DEFAULT_MAX_LENGTH", "NllbProvider"]
