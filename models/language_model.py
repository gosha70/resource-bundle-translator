# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from typing import Dict, List, Tuple
from abc import ABC, abstractmethod
from translation_request import TranslationRequest

TRANSLATION_MAX_LENGTH = 2000

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

    def preserve_glossary_words(self, text: str, glossary: List[Tuple[str,str]], preserved_words: Dict[str, str]) -> str:
        pass

    def encode_placeholders(self, text: str, preserved_words: Dict[str, str]) -> str:
        pass

    def restore_preserved_words(self, text: str, preserved_words: Dict[str, str]) -> str:
        for token, placeholder in preserved_words.items():
            text = text.replace(token, placeholder)
        return text    

    def log_info(self, message: str):
        if self.logging is None: 
            print(message)
        else:
            self.logging.info(message)
    
    def log_error(self, message: str):
        if self.logging is None: 
            print(message)
        else:
            self.logging.error(message)        