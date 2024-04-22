# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from typing import Dict
from languages import Language

MISSING_TRANSLATION = "### NONE ###"

class Translation:
    def __init__(self, message_id: str, original_text: str, adjusted_text: str, preserved_words: Dict[str, str]):
        self.message_id = message_id
        self.original_text = original_text
        self.adjusted_text = adjusted_text
        self.preserved_words = preserved_words
        self.translation_per_lang = {}

    def get_message_id(self) -> str:
        return self.message_id    

    def get_text_to_translate(self) -> str:
        return self.adjusted_text

    def get_preserved_words(self) -> Dict[str, str]:
        return self.preserved_words
    
    def get_translated_text(self, language: Language) -> str:
         return self.translation_per_lang.get(language, MISSING_TRANSLATION)
    
    def add_translated_text(self, to_text: str, to_language: Language):
        """
        Adds the translated text for the specified Language.

        Parameters:
        - to_language (Language): The Language to transalte to.
        - to_text (str): The otranslated text.

        Returns:
        - (True) if the translated text was added; otherwise - (False)
        """
        self.translation_per_lang[to_language] = to_text
    

