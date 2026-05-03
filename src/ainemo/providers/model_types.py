# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from enum import Enum
from typing import List, Optional

from ainemo._legacy.languages import Language
from ainemo.providers.base import TranslatorModel
from ainemo.providers.opus.marian_mt_model import MarianTranslatorModel
from ainemo.providers.nllb.nllb_model import NLLBTranslatorModel
from ainemo.providers.openai.open_ai_model import OpenAITranslatorModel

class ModelType(str, Enum):  
    OPUS = "opus"       # OPUS via Marian MT
    NLLB = "nllb"       # (default) NLLB 200 via AutoModelForSeq2SeqLM  
    OPEN_AI = "openai"  # The OpenAI model demonstrates the use of external model as a managed service

    @staticmethod
    def get_model_type(model_name: str):
        try:
            return ModelType(model_name.lower())
        except ValueError:
            raise ValueError(f"Invalid model type specified. Choose from {[e.value for e in ModelType]}")

    @staticmethod
    def get_model_by_name(model_name: str, source_lang: Language, target_langs: Optional[List[Language]], cache_dir=None, logging=None) -> TranslatorModel:
        model_type = ModelType.get_model_type(model_name=model_name) 
        if model_type == ModelType.OPUS:
            return MarianTranslatorModel(source_lang=source_lang, target_langs=target_langs, cache_dir=cache_dir, logging=logging)   
        elif model_type == ModelType.OPEN_AI:
            return OpenAITranslatorModel(source_lang=source_lang, target_langs=target_langs, logging=logging)
        else:
            return NLLBTranslatorModel(source_lang=source_lang, target_langs=target_langs, cache_dir=cache_dir, logging=logging)
