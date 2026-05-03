# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import logging
import re
import time
from typing import List, Dict, Optional, Tuple
from transformers import MarianMTModel, MarianTokenizer
from ainemo.providers.base import TranslatorModel
from ainemo._legacy.languages import Language
from ainemo._legacy.translation_request import TranslationRequest

_module_logger = logging.getLogger(__name__)


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
    Language.HI: {
        "language_token": "hi",
        "model_id": "hi",
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
        "model_prefix": "opus-mt-tc-big-" #No very good translation to Korean; but right now, there is no other OPUS model is available
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
            _module_logger.info(message)
        else:
            logging.info(message)

    def preserve_glossary_words(self, text: str, glossary: List[Tuple[str,str]], preserved_words: Dict[str, str]) -> str:
        def replace_and_record(match):
            term = match.group(0)
            token = MarianTranslatorModel.create_placeholder(text=term)
            preserved_words[token] = term
            return token

        for key, escaped_term in glossary:
            # Boundary handling depends on whether the term's last char is a word character.
            # Plain `\b` does not assert a boundary after punctuation, so terms ending in
            # punctuation use a negative lookahead to require a non-word character (or end
            # of string) on the right.
            if escaped_term[-1].isalnum():
                pattern = fr'\b{escaped_term}\b'
            else:
                pattern = fr'\b{escaped_term}(?!\w)'
            text = re.sub(pattern, replace_and_record, text)

        return text

    @staticmethod 
    def create_placeholder(text: str) -> str:
        # Remove non-alphabetic characters using regular expression
        cleaned_text = re.sub(r'[^a-zA-Z]', '', text)
        # Convert the cleaned text to uppercase
        return f"_{cleaned_text.upper()}"      

    def encode_placeholders(self, text: str, preserved_words: Dict[str, str]) -> str:
        placeholders = re.findall(r'\{\d+\}', text)
        for i, placeholder in enumerate(placeholders):
            token = f"_{i}"
            preserved_words[token] = placeholder
            text = text.replace(placeholder, token)
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
            _module_logger.debug("Languages: %s", translation_request.get_to_languages())
            _module_logger.debug("Translations: %s", translation_request.get_translations())
            from_lang_config = opus_mt_language_models[translation_request.get_from_language()]
            for lang in translation_request.get_to_languages():
                to_lang_config = opus_mt_language_models[lang]
                if from_lang_config['language_token'] == to_lang_config['language_token']:
                    _module_logger.info(
                        "No need to translate from '%s' to '%s'",
                        translation_request.get_from_language(), lang,
                    )
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
                            _module_logger.debug("Translating %r to '%s' ...", text_to_translate, lang)
                            translated = model.generate(**tokenizer(text_to_translate, return_tensors="pt", padding=True, max_length=TranslatorModel.TRANSLATION_MAX_LENGTH, truncation=True))
                            translated_text = tokenizer.decode(translated[0], skip_special_tokens=True)
                            translated_text = self.restore_preserved_words(text=translated_text, preserved_words=translation.get_preserved_words())
                            self.log_info(f"Translated '{text_to_translate}' from '{translation_request.get_from_language()}' to '{lang}': '{translated_text}'")
                            translation.add_translated_text(to_text=translated_text, to_language=lang)
        except Exception as error:
            _module_logger.exception("Failed to translate %r", translation_request)
            self.log_error(f"Failed to translate '{translation_request}': {str(error)}")

