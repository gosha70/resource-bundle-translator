# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from abc import ABC, abstractmethod
from translation import Translation

class TranslatorModel(ABC):

    def __init__(self, cache_dir=None, logging=None):
        """Initializes TranslatorModel with optional Logging."""
        self.logging = logging
        self.cache_dir = cache_dir

    @abstractmethod
    def translate(self, translation: Translation):
        """
        Translates the texts in the specified 'translation'. 
        The translated texts are stored directly in 'translation' via the Translation.add_translation() method.

        Parameters:
        - translation (Translation): Stores the texts to translate and the list of Languages for translation.
        """
        pass

    def log_info(self, messsage: str):
        if self.logging is None: 
            print(messsage)
        else:
            self.logging.info(messsage)

    
    def log_error(self, messsage: str):
        if self.logging is None: 
            print(messsage)
        else:
            self.logging.error(messsage)        