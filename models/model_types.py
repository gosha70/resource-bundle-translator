# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from enum import Enum
from typing import List, Optional

from languages import Language
from models.language_model import TranslatorModel
from models.marian_mt.marian_mt_model import MarianTranslatorModel
from models.facebook.nllb_model import NLLBTranslatorModel

class ModelType(str, Enum):  
    OPUS = "opus"       # OPUS via Marian MT
    NLLB = "nllb"       # (default) NLLB 200 via AutoModelForSeq2SeqLM  

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
        else:
            return NLLBTranslatorModel(source_lang=source_lang, target_langs=target_langs, cache_dir=cache_dir, logging=logging)
