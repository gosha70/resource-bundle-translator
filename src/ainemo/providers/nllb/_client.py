"""Lazy HuggingFace-model loader for the NLLB provider.

The default NLLB-200 model (``facebook/nllb-200-distilled-600M``) is
~2.5 GB on disk and takes seconds to load. Constructing it at module
import time would penalize every code path that touches the providers
package (test collection, the OpenAI/Anthropic CLIs, etc.). The
:class:`NllbModelHolder` defers construction to the first translate
call.
"""

from __future__ import annotations

from typing import Any, Final

# Default model id. NLLB-200 distilled-600M is the cycle-1 baseline;
# users override via the constructor. Larger NLLB variants (1.3B, 3.3B)
# trade quality for inference time/memory.
DEFAULT_MODEL: Final = "facebook/nllb-200-distilled-600M"


class NllbModelHolder:
    """One-shot lazy holder for the (tokenizer, model) pair.

    The HuggingFace ``transformers`` library has no Protocol surface
    we can lean on for typing — its returned objects are typed Any
    via the cycle-1 mypy override. This class is the boundary where
    we hide that.
    """

    def __init__(self, model_id: str = DEFAULT_MODEL, cache_dir: str | None = None) -> None:
        self._model_id = model_id
        self._cache_dir = cache_dir
        self._loaded: tuple[Any, Any] | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    def load(self) -> tuple[Any, Any]:
        """Return the (tokenizer, model) pair, loading on first call."""
        if self._loaded is None:
            from transformers import (
                AutoConfig,
                AutoModelForSeq2SeqLM,
                AutoTokenizer,
            )

            config = AutoConfig.from_pretrained(self._model_id, cache_dir=self._cache_dir)
            tokenizer = AutoTokenizer.from_pretrained(
                self._model_id, config=config, cache_dir=self._cache_dir
            )
            model = AutoModelForSeq2SeqLM.from_pretrained(
                self._model_id, config=config, cache_dir=self._cache_dir
            )
            self._loaded = (tokenizer, model)
        return self._loaded


__all__ = ["DEFAULT_MODEL", "NllbModelHolder"]
