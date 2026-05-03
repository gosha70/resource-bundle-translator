from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from transformers import pipeline

model_name = "facebook/nllb-200-distilled-600M"
tokenizer = AutoTokenizer.from_pretrained(model_name)
tokenizer2 = AutoTokenizer.from_pretrained(model_name)

# Define special tokens
special_tokens_dict = {'additional_special_tokens': ['<<Appian>>', '{0}', '{1}']}
word_map = {
    'Appian': '001SPECIALTOKEN001', 
    '{0}': '002SPECIALTOKEN002',
    '{1}': '003SPECIALTOKEN003'
}

tokenizer.add_special_tokens(special_tokens_dict)

# Load the model
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
model.resize_token_embeddings(len(tokenizer))
model2 = AutoModelForSeq2SeqLM.from_pretrained(model_name)

def translate_with_special_tokens(from_lang: str, to_lang: str, text: str):
    translator = pipeline(task='translation', model=model, tokenizer=tokenizer, src_lang=from_lang, tgt_lang=to_lang, max_length = 400)
    output = translator(text)
    translated_text = output[0]['translation_text']
    print(f"Translation (tokens)from {from_lang} to {to_lang}: '{translated_text}'")

def preserve_special_words(text):
    for word, placeholder in word_map.items():
        text = text.replace(word, placeholder)
    return text

def revert_special_words(translated_text):
    for word, placeholder in word_map.items():
        translated_text = translated_text.replace(placeholder, word)
    return translated_text

def translate_with_special_words(from_lang: str, to_lang: str, text: str):
    # Replace special words with placeholders
    prepared_text = preserve_special_words(text)
    print(f"Adjusted: '{prepared_text}'")

    translator = pipeline(task='translation', model=model2, tokenizer=tokenizer2, src_lang=from_lang, tgt_lang=to_lang, max_length = 400)
    output = translator(prepared_text)
    translated_text = output[0]['translation_text']

    # Revert placeholders to special words
    final_text = revert_special_words(translated_text)
    print(f"Translation (special words) from {from_lang} to {to_lang}: '{final_text}'")



text_to_translates = [
    "OK ",
    "Cancel",
    "Let's go to France with Appian, and see the eiffel tower.",
    "Hello Appian!",
    "Hello world! Happy meet you this morning at {0}:{1} my place.",
    "Let is meet at 12AM."
]

to_langs = [
    "heb_Hebr",
    "rus_Cyrl",
    "fra_Latn",
    "kor_Hang"
]

for text in text_to_translates:
    print(f"Translating: '{text}'")
    for lang in to_langs:
        #translate_with_special_tokens(from_lang="eng_Latn",to_lang=lang, text=text)
        translate_with_special_words(from_lang="eng_Latn",to_lang=lang, text=text)
        print("\n\n")