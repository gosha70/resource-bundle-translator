# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import json
import time
from typing import Dict, List, Optional

from models.language_model import TranslatorModel
from languages import Language
from translation import Translation, MISSING_TRANSLATION
from translation_request import TranslationRequest

class TranslationService:

    def __init__(self, model: TranslatorModel, glossary: Dict[str, str], logging=None):
        """Initializes TranslatorModel with optional Logging."""
        self.logging = logging
        self.model = model
        self.glossary = glossary

    def translate(self, from_language: Language, from_texts: List[str], to_languages: Optional[List[Language]]) -> str:
        translations = []
        for from_text in from_texts:
            translation = self.prepare_text_for_translation(orig_text=from_text)
            translations.append(translation)

        translation_request = TranslationRequest(from_language=from_language, translations=translations, to_languages=to_languages)
        
        start_time = time.time() 
        self.model.translate(translation_request=translation_request)
        end_time = time.time()
        elapsed_time = end_time - start_time
        self.log_info(f"Finished translation of {len(from_texts)} texts from {from_language} to {len(translation_request.get_to_languages())} languages in {elapsed_time:.2f} seconds.")

        return self.generate_json_respsonse(translations=translations, from_language=from_language, to_languages=translation_request.get_to_languages())
    
    def generate_json_respsonse(self, translations: List[Translation], from_language: Language, to_languages: List[Language]) -> str:
        results = []        
        for translation in translations:
            translations_per_language = [
                {
                    'language': lang.get_language_type(), 
                    'translation': self.restore_text_from_translation(translation=translation, to_language=lang)
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
    
    def prepare_text_for_translation(self, orig_text: str) -> Translation:
        used_glossary = {}
        
        adjusted_text = orig_text

        # Apply glossary substitutions if they appear in the text
        for term, placeholder in self.glossary.items():
            if term in adjusted_text:
                used_glossary[placeholder] = term
                adjusted_text = adjusted_text.replace(term, placeholder)
        
        # Protect placeholders
        adjusted_text = self.model.encode_placeholders(text=adjusted_text, glossary=used_glossary)
        
        return Translation(original_text=orig_text, adjusted_text=adjusted_text, glossary=used_glossary)

    def restore_text_from_translation(self, translation: Translation, to_language: Language) -> str:    
        translated_text=translation.get_translated_text(language=to_language)   
        if not translated_text or translated_text == MISSING_TRANSLATION:
            return "### NONE ###"
        
        print(f"Adjusting translation {translated_text} - To Languages: {to_language}")
       
        # Restore placeholders
        translated_text = self.model.encode_placeholders(text=translated_text, glossary=translation.get_glossary())
        
        # Restore glossary terms
        for placeholder, term in translation.get_glossary().items():
            translated_text = translated_text.replace(placeholder, term)
        
        return translated_text
