# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
from enum import Enum
from typing import List

class Language(str, Enum):    
    AR = "ar"       # Modern Standard Arabic 
    DE = "de"       # German
    EL = "el"       # Greek
    EN_GB ="en_GB"  # English, assuming no distinction in model between GB and US
    EN_US = "en_US" # English
    ES = "es"       # Spanish
    FR_CA = "fr_CA" # French, assuming no distinction for Canadian French
    FR_CH = "fr_CH" # French
    FR_FR = "fr_FR" # French
    IT = "it"       # Italian
    HE = "iw"       # Hebrew
    HI = "hi"       # Hindi
    JA = "ja"       # Japanese
    KO = "ko"       # Korean
    NL = "nl"       # Dutch
    PL = "pl"       # Polish
    PT = "pt"       # Portuguese
    RU = "ru"       # Russian
    SV = "sv"       # Swedish
    TH = "th"       # Thai
    TR = "tr"       # Turkish
    ZH_CH = "zh_CN" # Chinese Mandarin
    ZH_HK = "zh_HK" # Chinese Mandarin, assuming no distinction for Hong Kong
        
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
