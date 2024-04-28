# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import os
from openai import OpenAI
client = OpenAI()

from typing import List, Optional, Dict, Tuple
from languages import Language
from translation_request import TranslationRequest
from models.language_model import TranslatorModel, TRANSLATION_MAX_LENGTH

OPEN_AI_KEY_VAR = 'OPENAI_API_KEY'
SYSTEM_PROMPT='You are a professional multi language translator. Your main task is translate resource bundle messages used in Software and UI.'
GLOSSARY_PROMPT =' Preserved/do not translate the following words and phrases: '

class MissingEnvironmentVariableError(Exception):
    """Exception raised when a required environment variable is not set."""

    def __init__(self, env_var):
        self.env_var = env_var
        self.message = f"Required environment variable '{env_var}' is not set."
        super().__init__(self.message)

class OpenAITranslatorModel(TranslatorModel):
    def __init__(self, source_lang: Language, target_langs: Optional[List[Language]], logging=None):
        super().__init__(cache_dir=None, logging=logging)
        self.log_info(f"OpenAI Translator initialized for source language: {source_lang}")
        self.source_lang = source_lang
        self.target_langs = target_langs
        self.api_key = OpenAITranslatorModel.get_api_key()
        if not self.api_key:
            raise EnvironmentError("OPENAI_API_KEY is not set in environment variables.")

    @staticmethod 
    def get_api_key() -> str:
        api_key = os.getenv(OPEN_AI_KEY_VAR)
        if api_key is None:
            raise MissingEnvironmentVariableError(OPEN_AI_KEY_VAR)
        return api_key         
   

    def encode_placeholders(self, text: str, preserved_words: Dict[str, str]) -> str:
        # NOOP
        return text    
    
    def preserve_glossary_words(self, text: str, glossary: List[Tuple[str,str]], preserved_words: Dict[str, str]) -> str:
        # NOOP
        return text 

    def restore_preserved_words(self, text: str, preserved_words: Dict[str, str]) -> str:
        # NOOP
        return text    

    def translate(self, translation_request: TranslationRequest):
        from_lang = self.source_lang.name
        translations = translation_request.get_translations()
        glossary = translation_request.get_glossary()
        if not glossary:
            system_prompt_with_glossary = SYSTEM_PROMPT
        else: 
            glossary_text = ', '.join([element[0] for element in glossary])
            system_prompt_with_glossary = SYSTEM_PROMPT + GLOSSARY_PROMPT + glossary_text

        try:
            for translation in translations:
                texts_to_translate = translation.get_text_to_translate()
                for target_lang in translation_request.get_to_languages():
                    to_lang = target_lang.name   
                    messages=[
                        {"role": "system", "content": system_prompt_with_glossary},
                        {"role": "user", "content": f"Translate the following text from {from_lang} to {to_lang}: '{texts_to_translate}'"}
                    ]
                    response = client.chat.completions.create(
                        model="gpt-3.5-turbo", #"gpt-4", 
                        messages=messages,
                        max_tokens=TRANSLATION_MAX_LENGTH,
                        temperature=0.2,
                        top_p=1.0,
                        frequency_penalty=0.0,
                        presence_penalty=0.0
                    )
                    translated_text = response.choices[0].message.content.strip("'")
                    self.log_info(f"Translated from {from_lang} to {to_lang}: ({texts_to_translate}) -> ({translated_text})")

                    translation.add_translated_text(to_text=translated_text, to_language=target_lang)
        except Exception as error:
            self.log_error(f"Exception during translation: {str(error)}")
