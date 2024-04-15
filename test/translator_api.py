from flask import Flask, request, jsonify
from transformers import MarianMTModel, MarianTokenizer
from typing import List

app = Flask(__name__)

# Load models for French, German, and Hebrew
models = {
    'fr': ('Helsinki-NLP/opus-mt-en-fr', None),
    'de': ('Helsinki-NLP/opus-mt-en-de', None),
    'he': ('Helsinki-NLP/opus-mt-en-he', None)
}

# Initialize models and tokenizers
#for lang, (model_name, _) in models.items():
#    tokenizer = MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-en-fr')
#    model = MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-en-fr')
#    models[lang] = (model, tokenizer)

@app.route('/translate', methods=['POST'])
def translate():
    data = request.get_json()
    src_text = data['text']
    lang = data['lang']

    print('Request: text - [%s]; lang - [%s]' % (src_text, lang))
    
    try:
        model_name = 'Helsinki-NLP/opus-mt-en-fr'
        cache_dir = "/Users/gosha/dev/ai_cache"
        model = MarianMTModel.from_pretrained(model_name, cache_dir=cache_dir)
        tokenizer = MarianTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
        print(f"supported languages: {tokenizer.supported_language_codes}")

        translated = model.generate(**tokenizer(src_text, return_tensors="pt", padding=True))
        print(f"translated: {translated}")

        if translated.numel() == 0:
            tgt_text = "N/A"
            print("No output from translation model!")
        else:
            tgt_text = tokenizer.decode(translated[0], skip_special_tokens=True)
            print(f"translated text: {tgt_text}")

        tgt_text = tokenizer.decode(translated[0], skip_special_tokens=True)
        print(f"translated text: {tgt_text}")

    except Exception as e:
        print(f"An error occurred: {e}")
    
    return jsonify({'translated_text': tgt_text})

if __name__ == '__main__':
    app.run(debug=True, port=5005)
