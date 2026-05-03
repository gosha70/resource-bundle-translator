# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import json
import logging
import os
from importlib import resources
from typing import List, Optional

from ainemo._legacy.languages import Language

logger = logging.getLogger(__name__)

# --- Module constants (no magic strings rule, AGENTS.md § Prohibited Patterns) ---

# Package that owns the bundled JSON config. Used for `importlib.resources` lookup.
CONFIG_PACKAGE: str = "ainemo.config"

# Filename of the bundled config inside CONFIG_PACKAGE.
CONFIG_FILENAME: str = "translation_config.json"

# JSON keys read out of the config file. Define once; reference everywhere a
# read happens. If the schema ever moves to a Pydantic model the keys still
# come from this list.
CONFIG_KEY_CACHE_DIR: str = "cache_dir"
CONFIG_KEY_FROM_LANGUAGE: str = "from_language"
CONFIG_KEY_TO_LANGUAGES: str = "to_languages"
CONFIG_KEY_GLOSSARY: str = "glossary"

# Fallback cache directory when the config does not specify one. The legacy
# `~/tmp/ai-cache` value is kept verbatim during cycle 0 (move-don't-refactor);
# cycle 1's pipeline rewrite picks the AI-NEMO standard `~/.ainemo/`.
DEFAULT_CACHE_DIR: str = "~/tmp/ai-cache"


def _default_config_path() -> str:
    """Resolve the bundled config file via package resources.

    Using `importlib.resources` instead of a hard-coded relative path means
    the file is found regardless of the caller's CWD and works in both
    editable (`pip install -e .`) and wheel installations.
    """
    resource = resources.files(CONFIG_PACKAGE).joinpath(CONFIG_FILENAME)
    return str(resource)


# Backwards-compat constant. Prefer calling :func:`_default_config_path()`
# at point-of-use; this module-level value resolves once at import time
# and is exposed for any pre-cycle-0 callers that imported the symbol.
DEFAULT_CONFIG: str = _default_config_path()


class ConfigLoader:

    def __init__(self, config_file: Optional[str] = None):
        """
        Load the configuration with the global settings for the Translation model:
        - cache_dir: the directory where the downloaded LLM is cahced
        - from_language: (Optional) The language to translate from; the default is "en_US"
        - to_languages: (Optional) The list of languages to translate to; the default is all languages defined in the Language enum excluding the from_language one.
        - glossary: (Optional) the glossary of words which should be preserved/not translated

        Args:
        config_file: (Optional) the path to the configuration file. When
            ``None`` (the default), falls back to the package-bundled
            ``ainemo/config/translation_config.json`` resolved via
            :mod:`importlib.resources`.
        """
        if config_file is None:
            config_file = _default_config_path()

        app_config = ConfigLoader.load_config(file_path=config_file)

        dir_path = app_config[CONFIG_KEY_CACHE_DIR]
        if dir_path is None:
            dir_path = DEFAULT_CACHE_DIR
        ConfigLoader.ensure_directory_exists(path=dir_path)
        self.cache_dir = dir_path

        from_lang_code = app_config[CONFIG_KEY_FROM_LANGUAGE]
        if from_lang_code is None:
            self.from_language = Language.EN_US
        else:
            self.from_language = Language.get_language_by_code(value=from_lang_code)

        to_lang_codes = app_config[CONFIG_KEY_TO_LANGUAGES]
        if to_lang_codes is None:
            # None means "translate to every supported language except from_language".
            self.to_languages = None
        else:
            self.to_languages = Language.get_languages_by_codes(values=to_lang_codes)

        if CONFIG_KEY_GLOSSARY in app_config:
            self.glossary = app_config[CONFIG_KEY_GLOSSARY]
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
            logger.info("Directory ensured: %s", path)
        except OSError as e:
            logger.exception("Error creating directory %s: %s", path, e)
            raise