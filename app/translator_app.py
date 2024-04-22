# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import argparse
import logging
from typing import Dict, List
from flask import Flask, request, jsonify

from languages import Language
from config.config_loader import ConfigLoader
from models.model_types import ModelType
from translation_service import TranslationService

app_config = ConfigLoader()

translation_service = None

app = Flask(__name__)
    
@app.route('/translate', methods=['POST'])
def translate():
    if translation_service is None:
        return jsonify({'Error': 'Translation Service is not initialized.'})
    
    data = request.get_json()
    from_texts = list_to_dict(messages=data['messages'])    
    to_lang_names = data['to_languages']

    to_languages = Language.get_languages_by_codes(values=to_lang_names)  

    print('Request: text - [%s]; lang - [%s]: %s' % (from_texts, app_config.get_from_language(), to_lang_names))
    
    try:
        json_with_translations = translation_service.translate_to_json(
            from_language=app_config.get_from_language(), 
            from_texts=from_texts, 
            to_languages=to_languages)
        print(f"translated: {json_with_translations}")

        return jsonify(json_with_translations)
    except Exception as error:
        error_message = f"Failed to translate: {str(error)}"
        print(error_message)
        return jsonify({'Error': error_message})
    
def list_to_dict(messages: List[str]) -> Dict[str, str]:
    return {str(i): message for i, message in enumerate(messages)}    

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
        parser.add_argument(
            '--model_name', 
            type=str, 
            help='(Optional) The type of supported Translation models. By default: ModelType.NLLB.', 
            default='nllb'
        )

        # Parse the arguments
        args = parser.parse_args() 
        translator_model = ModelType.get_model_by_name(
            model_name=args.model_name, 
            source_lang=app_config.get_from_language(), 
            target_langs=app_config.get_to_languages(), 
            cache_dir=app_config.get_cache_dir(), 
            logging=logging)  
        translation_service = TranslationService(
            model=translator_model, 
            glossary=app_config.get_glossary(), 
            logging=logging)

    app.run(debug=True, port=args.port)