# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from typing import List, Optional
from languages import Language
from translation_text import TranslationText

class Translation:
    def __init__(self, from_language: Language, translation_textss: List[TranslationText], to_languages: Optional[List[Language]]):
        """
        Initializes Translation to translate texts from the specified Language to either explcitly spcified 
        Languages or to all supported ones.

        Parameters:
        - from_language (Language): The language the specified 'from_texts' were written in.
        - translation_textss (List[TranslationText]): The list of TranslationText stores text to transalte
        - to_languages (List[Language]): The optional list of languages for translation; 
                                         if the list is not specified, a text is translated 
                                         to all supported languages.
        """
        self.from_language = from_language
        self.translation_textss = translation_textss
        if to_languages is None:
            to_languages = [lang.value for lang in Language]  # Use all available languages if none are specified

        self.to_languages = to_languages 
    
    def get_texts_to_translate(self) -> List[str]:
        return [translation_texts.get_text_to_translate() for translation_texts in self.translation_textss]    
    
    def get_from_language(self) -> Language:
        return self.to_languages
        
    def get_to_languages(self) -> List[Language]:
        return self.from_language

    def add_translation(self, from_text: str, to_language: Language, to_text: str) -> bool:
        """
        Adds the text in 'to_language' translated from 'from_text'.  

        Parameters:
        - from_text (str): The original text.
        - to_language (Language): The Language to transalte to.
        - to_text (str): The otranslated text.

        Returns:
        - (True) if the translated text was added; otherwise - (False)
        """
        translation_texts = self.find_translation_texts(from_text=from_text)
        if translation_texts: 
            translation_texts.add_translation(to_text=to_text, to_language=to_language)   
            return True
        else:
            print(f"Error: Cannot find TranslationText by '{from_text}'.")

        return False    
    
    def find_translation_texts(self, from_text: str) -> Optional[TranslationText]:
        """Finds a TranslationText by its adjusted text."""
        for result in self.results:
            if result.adjusted_text == from_text:
                return result
        return None  # Return None if no matching result is found

    def get_translations(self, from_text: str):
        return self.translations.get(from_text, [])

    def get_all_translations(self):
        return self.translations

    def __str__(self):
        return str(self.translations)