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


opus_mt_language_models = {
    Language.AR: {
        "language_token": "ara",
        "model_id": "ar",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.DE: {
        "language_token": "deu",
        "model_id": "gem",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.EL: {
        "language_token": "el",
        "model_id": "el",
        "required_token": False,
        "model_prefix": "opus-mt-"
    },
    Language.EN_GB: {
        "language_token": "en",
        "model_id": "en",
        "required_token": False,
        "model_prefix": "opus-mt-"
    },
    Language.EN_US: {
        "language_token": "en",
        "model_id": "en",
        "required_token": False,
        "model_prefix": "opus-mt-"
    },
    Language.ES: {
        "language_token": "es",
        "model_id": "ROMANCE",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.FR_CA: {
        "language_token": "fr",
        "model_id": "ROMANCE",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.FR_CH: {
        "language_token": "fr",
        "model_id": "ROMANCE",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.FR_FR: {
        "language_token": "fr",
        "model_id": "ROMANCE",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.IT: {
        "language_token": "it",
        "model_id": "ROMANCE",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.HE: {
        "language_token": "he",
        "model_id": "he",
        "required_token": False,
        "model_prefix": "opus-mt-"
    },
    Language.JA: {
        "language_token": "jap",
        "model_id": "jap",
        "required_token": False,
        "model_prefix": "opus-mt-"
    },
    Language.KO: {
        "language_token": "ko",
        "model_id": "ko",
        "required_token": False,
        "model_prefix": "opus-mt-tc-big-"
    },
    Language.NL: {
        "language_token": "nld",
        "model_id": "gem",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.PL: {
        "language_token": "pol",
        "model_id": "sla",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.PT: {
        "language_token": "pt",
        "model_id": "ROMANCE",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.RU: {
        "language_token": "rus",
        "model_id": "sla",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.SV: {
        "language_token": "sv",
        "model_id": "sv",
        "required_token": False,
        "model_prefix": "opus-mt-"
    },
    Language.TH: {
        "language_token": "tha",
        "model_id": "mul",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.TR: {
        "language_token": "trk",
        "model_id": "trk",
        "required_token": False,
        "model_prefix": "opus-mt-"
    },
    Language.ZH_CH: {
        "language_token": "cmn_Hans",
        "model_id": "zh",
        "required_token": True,
        "model_prefix": "opus-mt-"
    },
    Language.ZH_HK: {
        "language_token": "cmn_Hant",
        "model_id": "zh",
        "required_token": True,
        "model_prefix": "opus-mt-"
    }
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
        
        models = {}
        start_time = time.time() 
        for target_lang in target_langs:
            model_identifier =  MarianTranslatorModel.get_model_name(from_language=source_lang, to_language=target_lang)
            if model_identifier: 
                MarianTranslatorModel.log_info(f"Loading  the '{model_identifier}' model ...")
                model = MarianMTModel.from_pretrained(model_identifier, cache_dir=cache_dir)            
                tokenizer = MarianTokenizer.from_pretrained(model_identifier, cache_dir=cache_dir)
                models[target_lang] = (model, tokenizer)

        end_time = time.time()
        elapsed_time = end_time - start_time
        MarianTranslatorModel.log_info(f"{len(models)} Language models were loaded in {elapsed_time:.2f} seconds.")
        return models  
    
    @staticmethod
    def get_model_name(from_language: Language, to_language: Language) -> str:
        # Retrieve configuration for both from_language and to_language
        from_lang_config = opus_mt_language_models[from_language]
        to_lang_config = opus_mt_language_models[to_language]

        if from_lang_config['language_token'] == to_lang_config['language_token']: 
            return None
        
        # Construct the model name
        model_name = f"Helsinki-NLP/{to_lang_config['model_prefix']}{from_lang_config['model_id']}-{to_lang_config['model_id']}"
    
        return model_name
    
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
            from_lang_config = opus_mt_language_models[translation_request.get_from_language()]
            for lang in translation_request.get_to_languages():
                to_lang_config = opus_mt_language_models[lang]
                if from_lang_config['language_token'] == to_lang_config['language_token']:
                    print(f"No need to translate from '{translation_request.get_from_language()}' to '{lang}'")
                    for translation in translation_request.get_translations():
                        translation.add_translated_text(to_text=translation.get_text_to_translate(), to_language=lang)
                else:    
                    model, tokenizer = self.lang_models[lang]
                    if model is None or tokenizer is None:
                        self.log_error(f"Cannot find a model for the translating from '{translation_request.get_from_language()}' to '{lang}")
                    else:    
                        for translation in translation_request.get_translations():
                            text_to_translate = translation.get_text_to_translate()
                            if to_lang_config['required_token']:
                                text_to_translate =f">>{to_lang_config['language_token']}<<{text_to_translate}"
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

