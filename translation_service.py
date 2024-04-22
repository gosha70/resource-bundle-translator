# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import re
import json
import time
from typing import Dict, List, Optional

from models.language_model import TranslatorModel
from languages import Language
from translation import Translation, MISSING_TRANSLATION
from translation_request import TranslationRequest

class TranslationService:

    def __init__(self, model: TranslatorModel, glossary: List[str], logging=None):
        """Initializes TranslatorModel with optional Logging."""
        self.logging = logging
        self.model = model
        self.glossary = TranslationService.prepare_glossary(glossary=glossary)

    @staticmethod
    def prepare_glossary(glossary: List[str]) -> List[str]:
        """
        Prepare the glossary by sorting the terms by length in descending order and escaping them for regex.
        
        Args:
        glossary (set): A set of glossary terms.
        
        Returns:
        list of tuples: Each tuple contains the original term and the escaped term.
        """
        # Sort by length (longest first) and escape terms for regex
        sorted_escaped_glossary = sorted(
            ((term, re.escape(term)) for term in glossary),
            key=lambda x: len(x[0]), 
            reverse=True
        )
        return sorted_escaped_glossary    

    def translate(self, from_language: Language, messages: Dict[str, str], to_languages: Optional[List[Language]]) -> TranslationRequest:
        translations = []
        for msg_key, msg_value in messages.items():
            translation = self.prepare_text_for_translation(message_id=msg_key, orig_text=msg_value)
            translations.append(translation)

        translation_request = TranslationRequest(from_language=from_language, translations=translations, to_languages=to_languages)
        
        start_time = time.time() 
        self.model.translate(translation_request=translation_request)
        end_time = time.time()
        elapsed_time = end_time - start_time
        self.log_info(f"Finished translation of {len(messages)} texts from {from_language} to {len(translation_request.get_to_languages())} languages in {elapsed_time:.2f} seconds.")
        return translation_request
    
    def translate_to_json(self, from_language: Language, messages: Dict[str, str], to_languages: Optional[List[Language]]) -> str:
        translation_request = self.translate(from_language=from_language, messages=messages, to_languages=to_languages)
        return self.generate_json_respsonse(
            translations=translation_request.get_translations(), 
            from_language=from_language, 
            to_languages=translation_request.get_to_languages())
    
    def generate_json_respsonse(self, translations: List[Translation], from_language: Language, to_languages: List[Language]) -> str:
        results = []        
        for translation in translations:
            translations_per_language = [
                {
                    'language': lang.get_language_type(), 
                    'translation': translation.get_translated_text(language=lang)
                }
                for lang in to_languages]
            
            result = {
                'from_text': translation.get_text_to_translate(),
                'from_language': from_language.get_language_type(),
                'translation_per_language': translations_per_language
            }
            results.append(result)

        return json.dumps(results, indent=2)

    def log_info(self, messsage: str):
        if self.logging is None: 
            print(messsage)
        else:
            self.logging.info(messsage)
    
    def prepare_text_for_translation(self, message_id: str, orig_text: str) -> Translation:
        preserved_words_map = {}
        
        adjusted_text = orig_text

        # Apply glossary substitutions if they appear in the text
        adjusted_text = self.model.preserve_glossary_words(text=adjusted_text, glossary=self.glossary, preserved_words=preserved_words_map)

        # Protect placeholders
        adjusted_text = self.model.encode_placeholders(text=adjusted_text, preserved_words=preserved_words_map)

        print(f"Original text: '{orig_text}' ======= adjusted text: '{adjusted_text}'")
        
        return Translation(
            message_id=message_id,
            original_text=orig_text, 
            adjusted_text=adjusted_text, 
            preserved_words=preserved_words_map)