# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import os
import sys
import argparse
import tempfile
import logging
from typing import Dict, Optional

from languages import Language
from config.config_loader import ConfigLoader
from models.model_types import ModelType
from translation_service import TranslationService
from translation_request import TranslationRequest

def load_resource_bundle(file_path: str, exclude_marker: Optional[str]) -> Dict[str, str]:
    """
    Load resource bundle from a file, excluding any keys that end with '###INST###'.

    Args:
    file_path (str): The path to the resource bundle file.
    exclude_marker (str): The optional suffix of the key of the instruction message which should not be translated 

    Returns:
    Dict[str, str]: A dictionary with the keys and values of messages to be translated.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        contents = file.readlines()
    
    messages = {}
    for line in contents:
        if '=' in line:
            key, value = line.split('=', 1)
            key = key.strip()
            # Check if the key ends with the instruction marker
            if exclude_marker is None or not key.endswith(exclude_marker):
                messages[key] = value.strip()
    return messages

def save_translations(messages: Dict[str, str], tanslation_request: TranslationRequest, target_directory: str, file_name_pattern: str): 
    for lang in tanslation_request.get_to_languages():        
        file_path = os.path.join(target_directory, file_name_pattern.replace("[LANG]", lang.name.lower()))
        with open(file_path, 'w', encoding='utf-8') as file:
            for message_id, message_text in messages.items():
                translated_text = tanslation_request.get_translation_by_message_id(message_id=message_id, to_language=lang)
                file.write(f"{message_id}={translated_text}\n")
       
def parse_arguments():
    parser = argparse.ArgumentParser(description="Translate resource bundle messages.")
    parser.add_argument(
        '--from_file', 
        type=str, 
        help='Path to the resource bundle file'
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
        '--output_dir', 
        type=str, 
        help='Directory to save translated resource bundles. Defaults to the system temp directory.',
        default=tempfile.gettempdir()
    )
    parser.add_argument(
        '--file_pattern', 
        type=str, 
        help='(Optional) Pattern for naming the translated files. The pattern must include [LANG] which will be replaced with the language code."',
        default='resources_[LANG].properties'
    )
    parser.add_argument(
        '--model_name', 
        type=str, 
        help='(Optional) The type of supported Translation models. By default: ModelType.NLLB.', 
        default='nllb'
    )
    parser.add_argument(
        '--exclude_marker', 
        type=str, 
        help='(Optional) The maeker for the message key for not translating that message.', 
        default=None
    )
    
    return parser.parse_args()

def main():
    # Set the logging level to INFO    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    args = parse_arguments()
    if args.from_file is None:
        logging.error("The resource bundle file with messages (by default written in English) must be specified.")
        sys.exit(1)

    from_lang_code = args.from_lang
    if from_lang_code is None:
        from_language = Language.EN_US  
    else:
        from_language = Language.get_language_by_code(value=from_lang_code)

    to_lang_codes  = args.to_langs
    if to_lang_codes is None:
        to_languages = None # This means a text will be translated to all supported Languages excluding 'from_language' 
    else:
        to_languages = Language.get_languages_by_codes(values=to_lang_codes)    

    app_config = ConfigLoader(config_file=None)  

    logging.info(f"Loading resource bundle message from {args.from_file}")
    messages = load_resource_bundle(file_path=args.from_file, exclude_marker=args.exclude_marker)

    logging.info(f"Creating '{args.model_name}' translation model")
    translator_model = ModelType.get_model_by_name(
        model_name=args.model_name, 
        source_lang=from_language, 
        target_langs=to_languages, 
        cache_dir=app_config.get_cache_dir(), 
        logging=logging)  
    logging.info(f"Creating Translation Service")
    translation_service = TranslationService(
        model=translator_model, 
        glossary=app_config.get_glossary(), 
        logging=logging)
    logging.info(f"Running translation from '{from_language}' to languages: {to_languages}")
    tanslation_request = translation_service.translate(
        from_language=from_language,  
        messages=messages, 
        to_languages=to_languages)
    logging.info(f"Saving translated messages to resource bundle files in {args.output_dir}")
    save_translations(
        messages=messages,
        tanslation_request=tanslation_request, 
        target_directory=args.output_dir,
        file_name_pattern=args.file_pattern)

if __name__ == "__main__":
    main()