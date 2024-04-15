# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import re
import json
from typing import Dict, List, Optional

from language_model import TranslatorModel
from languages import Language
from translation_text import TranslationText
from translation import Translation

class TranslationService:

    def __init__(self, model: TranslatorModel, glossary: Dict[str, str], logging=None):
        """Initializes TranslatorModel with optional Logging."""
        self.logging = logging
        self.model = model
        self.glossary = glossary

    def translate(self, from_language: Language, from_texts: List[str], to_languages: Optional[List[Language]]) -> str:
        translation_texts = []
        for from_text in from_texts:
            translation_text = self.prepare_text_for_translation(orig_text=from_text)
            translation_texts.append(translation_text)

        translation = Translation(from_language=from_language, translation_textss=translation_texts, to_languages=to_languages)
        self.model.translate(translation=translation)

        results = []
        for translation_text in translation_texts:
            translations = [
                {
                    'language': lang.value, 
                    'translation': self.restore_text_from_translation(translation_text.get_translation(langugae=lang), translation_text)
                }
                for lang in to_languages]
            
            result = {
                'from_text': translation_text.original_text,
                'translation_per_language': translations
            }
            results.append(result)

        return json.dumps(results, indent=2)

    def restore_placeholders(self, translated_text: str, token_map):
        for token, placeholder in token_map.items():
            translated_text = translated_text.replace(token, placeholder)
        return translated_text
    
    def prepare_text_for_translation(self, orig_text: str) -> TranslationText:
        used_glossary = {}
        
        ajusted_text = orig_text

        # Apply glossary substitutions if they appear in the text
        for term, placeholder in self.glossary.items():
            if term in ajusted_text:
                used_glossary[placeholder] = term
                ajusted_text = ajusted_text.replace(term, placeholder)
        
        # Protect placeholders
        placeholders = re.findall(r'\{\d+\}', ajusted_text)
        for i, placeholder in enumerate(placeholders):
            token = f"PLACEHOLDER_{i}"
            used_glossary[token] = placeholder
            ajusted_text = ajusted_text.replace(placeholder, token)
        
        return TranslationText(orig_text=orig_text, ajusted_text=ajusted_text, glossary=used_glossary)

    def restore_text_from_translation(self, transalted_text: str, translation_text: TranslationText) -> str:
        if not transalted_text:
            return "### NONE ###"
       
        # Restore placeholders
        for token, placeholder in translation_text.get_glossary().items():
            transalted_text = transalted_text.replace(token, placeholder)
        
        # Restore glossary terms
        for placeholder, term in translation_text.get_glossary().items():
            transalted_text = transalted_text.replace(placeholder, term)
        
        return transalted_text
