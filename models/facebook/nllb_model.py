# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import re
import os
import sys
import time
import uuid
from typing import List, Dict, Optional, Tuple
from transformers import AutoConfig, AutoModelForSeq2SeqLM, AutoTokenizer, pipeline
from models.language_model import TranslatorModel, TRANSLATION_MAX_LENGTH
from languages import Language
from translation_request import TranslationRequest


# Mapping dictionary from Language enum to NLLB language codes
# Language abbreviations used in NLLB can be found:
# https://github.com/facebookresearch/flores/blob/main/flores200/README.md#languages-in-flores-200
LANGUAGE_CODE_MAP = {
    Language.AR: "arb_Arab",    # Modern Standard Arabic
    Language.DE: "deu_Latn",    # German
    Language.EL: "ell_Grek",    # Greek
    Language.EN_GB: "eng_Latn", # English, assuming no distinction in model between GB and US
    Language.EN_US: "eng_Latn", # English
    Language.ES: "spa_Latn",    # Spanish
    Language.FR_CA: "fra_Latn", # French, assuming no distinction for Canadian French
    Language.FR_CH: "fra_Latn", # French
    Language.FR_FR: "fra_Latn", # French
    Language.IT: "ita_Latn",    # Italian
    Language.HE: "heb_Hebr",    # Hebrew
    Language.HI: "hin_Deva",    # Hindi
    Language.JA: "jpn_Jpan",    # Japanese
    Language.KO: "kor_Hang",    # Korean
    Language.NL: "nld_Latn",    # Dutch
    Language.PL: "pol_Latn",    # Polish
    Language.PT: "por_Latn",    # Portuguese
    Language.RU: "rus_Cyrl",    # Russian
    Language.SV: "swe_Latn",    # Swedish
    Language.TH: "tha_Thai",    # Thai
    Language.TR: "tur_Latn",    # Turkish
    Language.ZH_CH: "zho_Hans", # Chinese (Simplified)
    Language.ZH_HK: "zho_Hant"  # Chinese (Traditional)
}

NLLB_MODEL_NAME = "facebook/nllb-200-distilled-600M"

class NLLBTranslatorModel(TranslatorModel):

    def __init__(self, source_lang: Language, target_langs: Optional[List[Language]], cache_dir=None, logging=None):
        super().__init__(cache_dir=cache_dir, logging=logging)
        cache_dir="~/tmp/ai_cache/"
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
        self.log_info(f"Start the loading {NLLB_MODEL_NAME} Language model with the cache dir: '{cache_dir}'")  
        self.source_lang = source_lang
        self.target_langs = target_langs
        start_time = time.time() 

        # Load the configuration from the pretrained model
        config = AutoConfig.from_pretrained(NLLB_MODEL_NAME) #, cache_dir=cache_dir)

        # Initialize the tokenizer and model with the loaded configuration
        self.tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL_NAME, config=config) #, cache_dir=cache_dir)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL_NAME, config=config) #, cache_dir=cache_dir)

        end_time = time.time()
        elapsed_time = end_time - start_time
        self.log_info(f"{NLLB_MODEL_NAME} Language model was loaded in {elapsed_time:.2f} seconds.")           

    def preserve_glossary_words(self, text: str, glossary: List[Tuple[str,str]], preserved_words: Dict[str, str]) -> str:
        def replace_and_record(match):
            term = match.group(0)
            dict_size = len(preserved_words)
            token = self.create_placeholder(index=dict_size)
            # Only add to the dictionary if the term was actually found and replaced
            preserved_words[token] = term
            return token
        
        # Regex to find whole words only, avoiding partial matches
        for key, escaped_term in glossary:
            # Custom boundary handling: Adjust depending on if term ends with non-word character
            if escaped_term[-1].isalnum():  # Ends with an alphanumeric character
                pattern = fr'\b{escaped_term}\b'
            else:  # Ends with non-alphanumeric, such as punctuation
                pattern = fr'\b{escaped_term}(?!\w)'
            # Directly use `escaped_term` which is already prepared for regex use
            text = re.sub(pattern, replace_and_record, text)

        return text 

    @staticmethod 
    def create_placeholder(index: int) -> str:
        # Convert the cleaned text to uppercase
        return f"[{index}~~{index}]"

    def encode_placeholders(self, text: str, preserved_words: Dict[str, str]) -> str:
        placeholders = re.findall(r'\{\d+\}', text)
        for i, placeholder in enumerate(placeholders):
            token = f"[{i}~{i}]"
            preserved_words[token] = placeholder
            text = text.replace(placeholder, token)
        return text

    def translate(self, translation_request: TranslationRequest):
        """
        Translates the texts specified in the 'translation' object. 
        The translated texts are stored directly in the 'Translation' object via the Translation.add_translated_text() method.

        Parameters:
        - translation_request (TranslationRequest): Stores the texts to translate and the list of Languages for translation.
       
        See: https://huggingface.co/facebook/nllb-200-distilled-600M
        """
        from_lang = LANGUAGE_CODE_MAP[translation_request.get_from_language()]
        translations = translation_request.get_translations()
        texts_to_translate = [text.get_text_to_translate() for text in translations]

        try:
            for target_lang in translation_request.get_to_languages():
                to_lang = LANGUAGE_CODE_MAP[target_lang]
                translator = pipeline(
                    'translation', 
                    model=self.model, 
                    tokenizer=self.tokenizer, 
                    src_lang=from_lang, 
                    tgt_lang=to_lang, 
                    max_length=TRANSLATION_MAX_LENGTH,
                    num_beams=5,
                    temperature=0.9,
                    length_penalty=1.0,
                    early_stopping=True,
                    do_sample=True)

                # Perform batch translation
                translated_items = translator(texts_to_translate)

                # Log and store translations
                for translated_item, translation in zip(translated_items, translations):
                    translated_text = translated_item['translation_text']
                    original_text = translation.get_text_to_translate()
                    translated_text = self.tune_translated_text(orig_text=translation.get_text_to_translate(), translated_text=translated_text) 
                    translated_text = self.restore_preserved_words(text=translated_text, preserved_words=translation.get_preserved_words())
                    self.log_info(f"Translated from {from_lang} to {to_lang}: '{original_text}' -> '{translated_text}'")
                    translation.add_translated_text(to_text=translated_text, to_language=target_lang)
        except Exception as error:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.log_error(f"Exception during translation: {error}, Traceback: {exc_traceback}")

    def tune_translated_text(self, orig_text: str, translated_text: str) -> str:
        if translated_text.endswith('.') and not orig_text.endswith('.'):
            return translated_text[:-1]  

        return translated_text

