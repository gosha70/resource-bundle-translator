"""Lazy MarianMT loader for the OPUS provider.

OPUS-MT models are pair-specific — one HF repo per (source, target)
route. The provider may translate to many targets in a single run, so
the loader caches one (tokenizer, model) pair per HF repo id, lazily
loaded on first use.
"""

from __future__ import annotations

from typing import Any


class MarianModelCache:
    """Per-repo lazy cache of (tokenizer, model) pairs.

    The provider holds one cache per instance; entries persist for the
    lifetime of the provider so a single ``nemo translate`` run that
    fans out to N target languages pays the model-load cost N times,
    not N×M segments.
    """

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir
        self._cache: dict[str, tuple[Any, Any]] = {}

    def get(self, hf_model_name: str) -> tuple[Any, Any]:
        """Return the (tokenizer, model) pair for ``hf_model_name``,
        loading on first request."""
        if hf_model_name not in self._cache:
            from transformers import MarianMTModel, MarianTokenizer

            tokenizer = MarianTokenizer.from_pretrained(hf_model_name, cache_dir=self._cache_dir)
            model = MarianMTModel.from_pretrained(hf_model_name, cache_dir=self._cache_dir)
            self._cache[hf_model_name] = (tokenizer, model)
        return self._cache[hf_model_name]


__all__ = ["MarianModelCache"]
