# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import re
import sys
import time
from typing import List, Dict, Optional, Tuple
from transformers import MarianMTModel, MarianTokenizer
from models.language_model import TranslatorModel
from languages import Language
from translation_request import TranslationRequest

language_to_helsinki_map = {
    Language.EN_GB: "uk",
    Language.EN_US: "en",
    Language.FR_CA: "fr",
    Language.FR_CH: "fr",
    Language.FR_FR: "fr",
    Language. HE: "he",
    Language.JA: "jap",
    Language.TR: "trk",
    Language.ZH_CH: "zh",
    Language. ZH_HK: "zh"
}    
        

class MarianTranslatorModel(TranslatorModel):

    def __init__(self, source_lang: Language, target_langs: Optional[List[Language]], cache_dir=None, logging=None):
        super().__init__(cache_dir=cache_dir, logging=logging)
        self.lang_models = MarianTranslatorModel.build_translation_models(source_lang=source_lang, target_langs=target_langs, cache_dir=cache_dir, logging=logging)
        
    @staticmethod
    def build_translation_models(source_lang: Language, target_langs: Optional[List[Language]], cache_dir=None, logging=None) -> Dict[Language, Tuple[MarianMTModel, MarianTokenizer]]:
        """
        Build a dictionary of translation models from a source language to multiple target languages.
        
        Args:
            source_lang (Language): The source language.
            target_langs (Optional[List[Language]]): The list of target languages. If None, uses all languages except the source.
            cache_dir (Optional[str]): Optional cache directory for model storage.
            logging (Optional): the logging framework
        
        Returns:
            Dict[Language, Tuple[str, Tuple[MarianMTModel, MarianTokenizer]]]: A dictionary mapping each target language to a tuple 
            containing the model identifier and a tuple of MarianMTModel and MarianTokenizer.
        """
        if target_langs is None:
            # If no target languages are specified, use all except the source language
            target_langs = [lang for lang in Language if lang != source_lang]

        MarianTranslatorModel.log_info(f"Start the loading Models for languages: {target_langs} ...")    
        source_lang_code = MarianTranslatorModel.convert_language_to_code(language=source_lang)
        models = {}
        start_time = time.time() 
        for target_lang in target_langs:
            target_lang_code = MarianTranslatorModel.convert_language_to_code(language=target_lang)  
            model_identifier = f"Helsinki-NLP/opus-mt-{source_lang_code}-{target_lang_code}"
            MarianTranslatorModel.log_info(f"Loading  the '{model_identifier}' model ...")
            model = MarianMTModel.from_pretrained(model_identifier, cache_dir=cache_dir)
            tokenizer = MarianTokenizer.from_pretrained(model_identifier, cache_dir=cache_dir)
            models[target_lang] = (model, tokenizer)

        end_time = time.time()
        elapsed_time = end_time - start_time
        MarianTranslatorModel.log_info(f"{len(models)} Language models were loaded in {elapsed_time:.2f} seconds.")
        return models  
    
    @staticmethod 
    def convert_language_to_code(language: Language) -> str:
        # Try to get the Helsinki-NLP code from the map
        languag_code = language_to_helsinki_map.get(language)
        
        # If the code isn't found in the map, default to a modified value of the enum (assuming some manipulation might be necessary)
        if languag_code is None:
            # Default to the lower-case version of the enum value after replacing '_' with '-'
            # This is just an example and might need adjustment based on actual Helsinki-NLP codes
            languag_code = language.value.lower().replace('_', '-')
        
        return languag_code
    
    @staticmethod 
    def log_info(message: str, logging=None):
        if logging is None: 
            print(message)
        else:
            logging.info(message) 

    def encode_placeholders(self, text: str, glossary: Dict[str, str]) -> str:
        placeholders = re.findall(r'\{\d+\}', text)
        for i, placeholder in enumerate(placeholders):
            token = f"_{i}"
            glossary[token] = placeholder
            text = text.replace(placeholder, token)

        return text    
    
    def decode_placeholders(self, text: str, glossary: Dict[str, str]) -> str:
        for token, placeholder in glossary.items():
            text = text.replace(token, placeholder)

        return text    

    def translate(self, translation_request: TranslationRequest):
        """
        Translates the texts specified in the 'translation' object. 
        The translated texts are stored directly in the 'Translation' object via the Translation.add_translated_text() method.

        Parameters:
        - translation_request (TranslationRequest): Stores the texts to translate and the list of Languages for translation.
       
        See: https://huggingface.co/transformers/v4.0.1/model_doc/marian.html
        """
        try:
            print(f"Languages: {translation_request.get_to_languages()}")
            print(f"Translations: {translation_request.get_translations()}")
            for lang in translation_request.get_to_languages():
                model, tokenizer = self.lang_models[lang]
                if model is None or tokenizer is None:
                    self.log_error(f"Cannot find a model for the translating from '{translation_request.get_from_language()}' to '{lang}")
                else:    
                    for translation in translation_request.get_translations():
                        text_to_translate = translation.get_text_to_translate()
                        print(f"Translationing '{text_to_translate}' to '{lang}' ... ")
                        translated = model.generate(**tokenizer(text_to_translate, return_tensors="pt", padding=True, max_length=512, truncation=True))
                        translated_text = tokenizer.decode(translated[0], skip_special_tokens=True)
                        self.log_info(f"Translated '{text_to_translate}' from '{translation_request.get_from_language()}' to '{lang}': '{translated_text}'")
                        translation.add_translated_text(to_text=translated_text, to_language=lang)
        except Exception as error:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print("Exception type:", exc_type)
            print("Exception value:", exc_value)
            print("Traceback object:", exc_traceback)
            self.log_error(f"Failed to translate '{translation_request}': {str(error)}")

