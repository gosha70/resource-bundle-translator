# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import os
import argparse
import json
import logging

from flask import Flask, request, jsonify

from languages import Language
from translation_service import TranslationService
from models.marian_mt.marian_mt_model import MarianTranslatorModel

with open('app/translation_config.json', 'r') as file:
    app_config = json.load(file)

# System prompt muat be specified for embeddings
cache_dir = app_config["cache_dir"]
if cache_dir is not None:
    try:
        # Expand the user's home directory in the path
        cache_dir = os.path.expanduser('~/tmp/ai-cache')

        # Ensure the cache directory exists or create it
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
            
        print(f"Cache Directory: {cache_dir}")
    except OSError as e:
        print(f"Error: {e.strerror}, cannot create the cache directory {cache_dir}")
        cache_dir = None

from_lang_code = app_config["from_language"]
if from_lang_code is None:
    from_language = Language.EN_US  
else:
    from_language = Language.get_language_by_code(value=from_lang_code)

to_lang_codes = app_config["to_languages"]
if to_lang_codes is None:
    to_languages = None # This means a text will be translated to all supported Languages excluding 'from_language' 
else:
    to_languages = Language.get_languages_by_codes(values=to_lang_codes)    

# Init glossary with configured items
glossary = {}
if "glossary" in app_config:
    for item in app_config["glossary"]:
        glossary[item["key"]] = item["value"]

translation_service = None

app = Flask(__name__)
    
@app.route('/translate', methods=['POST'])
def translate():
    if translation_service is None:
        return jsonify({'Error': 'Translation Service is not initialized.'})
    
    data = request.get_json()
    from_texts = data['resource_bundles']
    from_lang_name = data['language']
    to_lang_names = data['to_languages']

    to_languages = Language.get_languages_by_codes(values=to_lang_names)  

    print('Request: text - [%s]; lang - [%s]: %s' % (from_texts, from_lang_name, to_lang_names))
    
    try:
        translated = translation_service.translate(from_language=from_language, from_texts=from_texts, to_languages=to_languages)
        print(f"translated: {translated}")

        return jsonify(translated)
    except Exception as error:
        error_message = f"Failed to translate: {str(error)}"
        print(error_message)
        return jsonify({'Error': error_message})
    

if __name__ == '__main__':
    if translation_service is None:
        # Set the logging level to INFO    
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Create the parser
        parser = argparse.ArgumentParser(description="Starting Resource Bundle Translator Application")

        # Add the arguments
        parser.add_argument(
            '--port', 
            type=int, 
            help='(Optional) Port for Resource Bundle Translator Application. Defaults to 5001.', 
            default=5001
        )
        parser.add_argument(
            '--from_lang', 
            type=str, 
            help='(Optional) The Language abbreviation for the input text is written in.', 
            default='en_US'
        )
        parser.add_argument(
            '--to_langs', 
            type=str, 
            nargs='+', 
            help='(Optional) List of Language abbreviations for translation. If it is not specified, then it is all Languages, excluding the from_lang one.', 
            default=None
        )

        # Parse the arguments
        args = parser.parse_args()       
    
        translator_model = MarianTranslatorModel(source_lang=from_language, target_langs=to_languages, cache_dir=cache_dir, logging=logging)
        translation_service = TranslationService(model=translator_model, glossary=glossary, logging=logging)

    app.run(debug=True, port=args.port)