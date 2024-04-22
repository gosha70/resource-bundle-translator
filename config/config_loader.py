# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import os
import json
from typing import List, Optional

from languages import Language

DEFAULT_CONFIG = 'config/translation_config.json'

class ConfigLoader:

    def __init__(self, config_file: Optional[str]):
        """
        Load the configuration with the global settings for the Translation model:
        - cache_dir: the directory where the downloaded LLM is cahced
        - from_language: (Optional) The language to translate from; the default is "en_US"
        - to_languages: (Optional) The list of languages to translate to; the default is all languages defined in the Language enum excluding the from_language one.
        - glossary: (Optional) the glossary of words which should be preserved/not translated
        
        Args:
        config_file (str): (Optional) the path to the configuration file; the default is 'config/translation_config.json'
        """
        if config_file is None:
            config_file = DEFAULT_CONFIG
                
        app_config = ConfigLoader.load_config(file_path=config_file)

        # System prompt muat be specified for embeddings
        dir_path = app_config["cache_dir"]
        if dir_path is None:
            dir_path = '~/tmp/ai-cache'
        ConfigLoader.ensure_directory_exists(path=dir_path)
        self.cache_dir = dir_path

        from_lang_code = app_config["from_language"]
        if from_lang_code is None:
            self.from_language = Language.EN_US  
        else:
            self.from_language = Language.get_language_by_code(value=from_lang_code)

        to_lang_codes = app_config["to_languages"]
        if to_lang_codes is None:
            self.to_languages = None # This means a text will be translated to all supported Languages excluding 'from_language' 
        else:
            self.to_languages = Language.get_languages_by_codes(values=to_lang_codes)    

        # Init glossary with configured items
        if "glossary" in app_config:
            self.glossary = app_config["glossary"]
        else:
            self.glossary = {}  

    def get_cache_dir(self) -> str:
        return self.cache_dir   
     
    def get_from_language(self) -> Language:
        return self.from_language    
     
    def get_to_languages(self) -> List[Language]:
        return self.to_languages   
     
    def get_glossary(self) ->List[str]:
        return self.glossary       

    @staticmethod
    def load_config(file_path: SystemError):
        with open(file_path, 'r') as file:
            return json.load(file)

    @staticmethod
    def ensure_directory_exists(path: str):
        try:
            # Expand the user's home directory in the path
            path = os.path.expanduser(path)

            os.makedirs(path, exist_ok=True)
            print(f"Directory ensured: {path}")
        except OSError as e:
            print(f"Error creating directory {path}: {e}")
            raise