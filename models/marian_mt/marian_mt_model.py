# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from typing import List, Dict, Optional, Tuple
from transformers import MarianMTModel, MarianTokenizer
from models.language_model import TranslatorModel
from models.languages import Language
from models.translation import Translation

class MarianTranslatorModel(TranslatorModel):

    def __init__(self, source_lang: Language, target_langs: Optional[List[Language]], cache_dir=None, logging=None):
        super().__init__(cache_dir=cache_dir, logging=logging)
        self.lang_models = MarianTranslatorModel.build_translation_models(source_lang=source_lang, target_langs=target_langs)
        
    @staticmethod
    def build_translation_models(source_lang: Language, target_langs: Optional[List[Language]], cache_dir=None) -> Dict[Language, Tuple[str, Tuple[MarianMTModel, MarianTokenizer]]]:
        """
        Build a dictionary of translation models from a source language to multiple target languages.
        
        Args:
            source_lang (Language): The source language.
            target_langs (Optional[List[Language]]): A list of target languages. If None, uses all languages except the source.
            cache_dir (Optional[str]): Optional cache directory for model storage.
        
        Returns:
            Dict[Language, Tuple[str, Tuple[MarianMTModel, MarianTokenizer]]]: A dictionary mapping each target language to a tuple containing the model identifier and a tuple of MarianMTModel and MarianTokenizer.
        """
        if target_langs is None:
            # If no target languages are specified, use all except the source language
            target_langs = [lang for lang in Language if lang != source_lang]
        
        models = {}
        for target_lang in target_langs:
            model_identifier = f"Helsinki-NLP/opus-mt-{source_lang.value}-{target_lang.value}"
            model = MarianMTModel.from_pretrained(model_identifier, cache_dir=cache_dir)
            tokenizer = MarianTokenizer.from_pretrained(model_identifier, cache_dir=cache_dir)
            models[target_lang] = (model_identifier, (model, tokenizer))
        return models  

    def translate(self, translation: Translation):
        """
        Translates the texts in the specified 'translation'. 
        The translated texts are store =d directly in 'translation' via the Translation.add_translation() method.

        Parameters:
        - translation (Translation): Stores the texts to translate and the list of Languages for translation.
       
        See: https://huggingface.co/transformers/v4.0.1/model_doc/marian.html
        """
        try:
            for lang in translation.get_to_languages():
                model, tokenizer = self.lang_models[lang]
                for text in translation.get_original_texts():
                    translated = model.generate(**tokenizer(text, return_tensors="pt", padding=True, max_length=512, truncation=True))
                    translation = tokenizer.decode(translated[0], skip_special_tokens=True)
                    self.log_info(f"translated '{text}' from '{translation.get_from_language()}' to '{lang}': '{translation}'")
                    translation.add_translation(from_text=text, to_language=lang, to_text=translation)
        except Exception as error:
            self.log_error(f"Failed to translate '{translation}': {str(error)}", exc_info=False)

