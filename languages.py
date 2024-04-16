# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from enum import Enum
from typing import List

class Language(str, Enum):    
    AR = "ar"
    DE = "de"
    EL = "el"
    EN_GB ="en_GB"
    EN_US = "en_US"
    ES = "es"
    FR_CA = "fr_CA"
    FR_CH = "fr_CH"
    FR_FR = "fr_FR"
    IT = "it"
    HE = "iw"
    JA = "ja"
    KO = "ko"
    NL = "nl"
    PL = "pl"
    PT = "pt"
    RU = "ru"
    SV = "sv"
    TH = "th"
    TR = "tr"
    ZH_CH = "zh_CN"
    ZH_HK = "zh_HK"
        
    @staticmethod
    def get_language_by_code(value: str):
        try:
            return Language(value)
        except ValueError:
            print(f"Error: There is no Language corresponding to '{value}'.")
            return None
        
    @staticmethod
    def get_languages_by_codes(values: List[str]):
        if values is None or len(values) == 0: 
            return None
        
        to_languages = [] 
        for to_lang_name in values: 
            to_lang = Language.get_language_by_code(value=to_lang_name)
            if to_lang_name is not None:                
                to_languages.append(to_lang)
            
        return to_languages        

    def get_language_type(self) -> str:
        return f"{self.value}"
