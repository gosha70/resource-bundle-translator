# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import logging
from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Protocol, Tuple, runtime_checkable

from ainemo._legacy.translation_request import TranslationRequest
from ainemo.core.segment import Segment

logger = logging.getLogger(__name__)

TRANSLATION_MAX_LENGTH = 2000


@runtime_checkable
class Provider(Protocol):
    """Cycle-1 minimal :class:`Segment`-shaped translation provider.

    Cycle 2 expands this Protocol (cost + latency tracking, retry,
    routing, multi-method) and migrates every concrete backend
    (NLLB/OPUS/OpenAI/Anthropic/Ollama) to it. For cycle 1 the pipeline
    only needs ``translate(segment, target_lang) -> str``; that is the
    minimum surface required by the pipeline orchestrator and the
    tests that mock providers.

    Concrete implementations may also subclass :class:`TranslatorModel`
    for the legacy ``translation_request`` path until cycle 2 deletes
    that surface; the two contracts coexist for one cycle.
    """

    provider_id: ClassVar[str]
    """Stable identifier (e.g. ``"nllb"``, ``"openai"``). The TM stores
    this on every TranslatedSegment so caching keys on (segment,
    target_lang, provider)."""

    def translate(self, segment: Segment, target_lang: str) -> str:
        """Return the translated text for ``segment`` in
        ``target_lang``. Implementations are responsible for
        placeholder preservation if the underlying model needs it
        (cycle-2 router lifts this concern up the stack)."""
        ...


class TranslatorModel(ABC):
    def __init__(self, cache_dir=None, logging=None):
        """Initializes TranslatorModel with optional Logging."""
        self.logging = logging
        self.cache_dir = cache_dir

    @abstractmethod
    def translate(self, translation_request: TranslationRequest):
        """
        Translates the texts specified in the 'translation' object.
        The translated texts are stored directly in the 'Translation' object via the Translation.add_translated_text() method.

        Parameters:
        - translation_request (TranslationRequest): Stores the texts to translate and the list of Languages for translation.
        """
        pass

    def preserve_glossary_words(
        self, text: str, glossary: List[Tuple[str, str]], preserved_words: Dict[str, str]
    ) -> str:
        pass

    def encode_placeholders(self, text: str, preserved_words: Dict[str, str]) -> str:
        pass

    def restore_preserved_words(self, text: str, preserved_words: Dict[str, str]) -> str:
        for token, placeholder in preserved_words.items():
            text = text.replace(token, placeholder)
        return text

    def log_info(self, message: str):
        if self.logging is None:
            logger.info(message)
        else:
            self.logging.info(message)

    def log_error(self, message: str):
        if self.logging is None:
            logger.error(message)
        else:
            self.logging.error(message)
