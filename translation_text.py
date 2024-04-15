# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from typing import Dict
from languages import Language

class TranslationText:
    def __init__(self, original_text: str, adjusted_text: str, glossary: Dict[str, str]):
        self.original_text = original_text
        self.adjusted_text = adjusted_text
        self.glossary = glossary
        self.translation_per_lang = {}

    def get_text_to_translate(self) -> str:
        return self.adjusted_text

    def get_glossary(self) -> Dict[str, str]:
        return self.glossary
    
    def get_translation(self, language: Language) -> str:
        return self.translation_per_lang[language]
    
    def add_translation(self, to_text: str, to_language: Language):
        """
        Adds the translated text for the specified Language.

        Parameters:
        - to_language (Language): The Language to transalte to.
        - to_text (str): The otranslated text.

        Returns:
        - (True) if the translated text was added; otherwise - (False)
        """
        self.translation_per_lang[to_language] = to_text
    

