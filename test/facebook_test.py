from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from enum import Enum

class Language(str, Enum):
    AR = "ar"
    DE = "de"
    EL = "el"
    EN_GB = "en_GB"
    EN_US = "en_US"
    ES = "es"
    FR_CA = "fr_CA"
    FR_CH = "fr_CH"
    FR_FR = "fr_FR"
    IT = "it"
    HE = "he"
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

# https://huggingface.co/facebook/nllb-200-distilled-600M
model_name = "facebook/nllb-200-distilled-600M"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

# Mapping dictionary from Language enum to NLLB language codes
language_code_mapping = {
    Language.AR: "ara",   # Arabic
    Language.DE: "deu",   # German
    Language.EL: "ell",   # Greek
    Language.EN_GB: "eng", # English, assuming no distinction in model between GB and US
    Language.EN_US: "eng", # English
    Language.ES: "spa",   # Spanish
    Language.FR_CA: "fra", # French, assuming no distinction for Canadian French
    Language.FR_CH: "fra", # French
    Language.FR_FR: "fra", # French
    Language.IT: "ita",   # Italian
    Language.HE: "heb",   # Hebrew
    Language.JA: "jpn",   # Japanese
    Language.KO: "kor",   # Korean
    Language.NL: "nld",   # Dutch
    Language.PL: "pol",   # Polish
    Language.PT: "por",   # Portuguese
    Language.RU: "rus",   # Russian
    Language.SV: "swe",   # Swedish
    Language.TH: "tha",   # Thai
    Language.TR: "tur",   # Turkish
    Language.ZH_CH: "cmn", # Chinese Mandarin
    Language.ZH_HK: "cmn"  # Chinese Mandarin, assuming no distinction for Hong Kong
}

def translate(text, src_lang, tgt_lang_code):
    # Prepare the input text with source and target language codes
    inputs = tokenizer(f"{src_lang} {tgt_lang_code} {text}", return_tensors="pt")
    outputs = model.generate(**inputs)
    translated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return translated_text

# Example usage
text = "This is a test text from _EGOGE _Ltd. and _3 between _1"
src_lang_code = "eng"  # English ISO-639-3 code
# Iterate through non-English languages
for lang, lang_code in language_code_mapping.items():
    translated_text = translate(text, src_lang_code, lang_code)
    print(f"Translation to {lang.value} ({lang_code}): {translated_text}")
