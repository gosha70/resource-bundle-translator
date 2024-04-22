# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from typing import List, Optional
from languages import Language
from translation import Translation, MISSING_TRANSLATION

class TranslationRequest:
    def __init__(self, from_language: Language, translations: List[Translation], to_languages: Optional[List[Language]]):
        """
        Initializes Translation to translate texts from the specified Language to either explcitly spcified 
        Languages or to all supported ones.

        Parameters:
        - from_language (Language): The language the specified 'from_texts' were written in.
        - translations (List[Translation]): The list of Translation stores text to transalte
        - to_languages (List[Language]): The optional list of languages for translation; 
                                         if the list is not specified, a text is translated 
                                         to all supported languages.
        """
        self.from_language = from_language
        self.translation_map = {item.get_message_id(): item for item in translations}  
        if to_languages is None:
            # If no target languages are specified, use all except the source language
            to_languages = [lang for lang in Language if lang != from_language]
        else:
            to_languages = list(filter(None.__ne__, to_languages))    

        self.to_languages = to_languages 
        print(f"From language {self.from_language} - To Languages: {self.to_languages}")
    
    def get_texts_to_translate(self) -> List[str]:
        return [translations.get_text_to_translate() for translations in self.translationss]    
    
    def get_from_language(self) -> Language:
        return self.from_language
        
    def get_to_languages(self) -> List[Language]:
        return self.to_languages 

    def get_translations(self) -> List[Translation]:
        return self.translation_map.values()
    
    def get_translation_by_message_id(self, message_id: str, to_language: Language) -> str:
        translation = self.translation_map.get(message_id)
        if translation is None:
            return MISSING_TRANSLATION        
        return translation.get_translated_text(language=to_language)

    def __str__(self):
        return str(self.translation_map)