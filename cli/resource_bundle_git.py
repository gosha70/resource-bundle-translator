# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import os
import sys
import argparse
import logging
import subprocess
import json
from typing import Dict, Optional

from enum import Enum
from languages import Language
from config.config_loader import ConfigLoader
from models.model_types import ModelType
from translation_service import TranslationService
from translation_request import TranslationRequest
from utils.analyze_last_commit import FileChanges, get_git_commit_diff

class CHANGE(Enum):
    ADDED = 1
    REMOVED = 2
    UPDATED = 3

def get_messages(git_diff: FileChanges, exclude_marker: Optional[str]) -> Dict[str, str]:
    if git_diff is None:
        return None    
    messages = {}
    for file, modifications in git_diff.items():
        for key, value, change_type in modifications:
            key = key.strip()        
            # Check if the key ends with the instruction marker
            if exclude_marker is None or not key.endswith(exclude_marker):
                messages[key] = value.strip()
            else:
                logging.info(f"Skip the message: {key}={value}")   
    return messages

def save_translations(git_diff: FileChanges, tanslation_request: TranslationRequest, repo_path: str):
    for lang in tanslation_request.get_to_languages():
        lang_code = lang.get_language_type()
        for file, modifications in git_diff.items():
            target_file = file.replace('_en_US', f'_{lang_code}')
            target_path = os.path.join(repo_path, target_file)

            # Load the existing resource bundle if it exists
            if os.path.exists(target_path):
                with open(target_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            else:
                lines = []

            # Update the content with new translations
            content = {}
            for line in lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    content[key] = value.strip() 

            # Apply new translations or add new entries
            updated_lines = []
            keys_handled = set()
            for line in lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    if key in modifications:
                        translated_text = tanslation_request.get_translation_by_message_id(key, lang)
                        updated_lines.append(f"{key}={translated_text}\n")
                        keys_handled.add(key)
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)     

            # Add new keys that were not in the original file
            for key, value, is_new in modifications:
                if is_new and key not in keys_handled:
                    translated_text = tanslation_request.get_translation_by_message_id(key, lang)
                    updated_lines.append(f"{key}={translated_text}\n")

            # Write the updated content back to the file
            with open(target_path, 'w', encoding='utf-8') as f:
                f.writelines(updated_lines)

            print(f"Updated translations saved to {target_path}") 

            # Optionally, add file to git
            subprocess.run(['git', 'add', target_path], cwd=repo_path)

    # Commit changes if any files were updated
    commit_message = f"Translation update to: {', '.join([lang.name for lang in tanslation_request.get_to_languages()])}"
    subprocess.run(['git', 'commit', '-m', commit_message], cwd=repo_path)            
       
'''Returns a mapping from key to CHANGE which is the type of change being applied, either the key is ADDED, UPDATED or DELETED.'''
def get_keys_to_change_type(git_diff: FileChanges, exclude_marker: Optional[str]) -> Dict[str, CHANGE]:
    if git_diff is None:
        return None
    key_to_change_bool = {}
    changed_keys = []
    for file, modifications in git_diff.items():
        for key, value, change_type in modifications:
            key = key.strip()
            # Check if the key ends with the instruction marker
            if exclude_marker is None or not key.endswith(exclude_marker):
                if key in key_to_change_bool:
                    if key_to_change_bool[key] != change_type:
                        changed_keys.append(key)
                        del key_to_change_bool[key]
                else:
                    key_to_change_bool[key] = change_type
    added_keys = [changed_key for changed_key, type in enumerate(key_to_change_bool) if type == True]
    removed_keys = [changed_key for changed_key, type in enumerate(key_to_change_bool) if type == False]

    key_to_change_type = {}
    for added_key in added_keys:
        key_to_change_type[added_key] = CHANGE.ADDED
    for removed_key in removed_keys:
        key_to_change_type[removed_key] = CHANGE.REMOVED
    for changed_key in changed_keys:
        key_to_change_type[changed_key] = CHANGE.UPDATED
    return key_to_change_type

'''Retrieves the xml/json encoded string from the literal string which we need to write to the properties files.'''
def get_translated_string(translation_request: TranslationRequest, key: str, lang: Language):

    translated_text = translation_request.get_translation_by_message_id(key, lang)
    return json.dumps(translated_text).strip('\"')

def save_translations(git_diff: FileChanges, translation_request: TranslationRequest, repo_path: str, exclude_marker: str):

    key_to_change = get_keys_to_change_type(git_diff=git_diff, exclude_marker=exclude_marker)

    for lang in translation_request.get_to_languages():
        lang_code = lang.get_language_type()
        for file, modifications in git_diff.items():
            target_file = file.replace('_en_US', f'_{lang_code}')
            target_path = os.path.join(repo_path, target_file)

            # Load the existing resource bundle if it exists
            if os.path.exists(target_path):
                with open(target_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            else:
                lines = []

            # Apply new translations or add new entries
            updated_lines = []
            keys_handled = set()
            for line in lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    if key in key_to_change and key_to_change[key] == CHANGE.UPDATED:
                        encoded_translation_text = get_translated_string(translation_request, key, lang)
                        updated_lines.append(f"{key}={encoded_translation_text}\n")
                        keys_handled.add(key)
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)

            # Add new keys that were not in the original file
            for key, value, is_new in modifications:
                if is_new and key not in keys_handled:
                    encoded_translation_text = get_translated_string(translation_request, key, lang)
                    updated_lines.append(f"{key}={encoded_translation_text}\n")

            # Write the updated content back to the file
            with open(target_path, 'w', encoding='utf-8') as f:
                f.writelines(updated_lines)

            print(f"Updated translations saved to {target_path}")

            # Optionally, add file to git
            subprocess.run(['git', 'add', target_path], cwd=repo_path)

    # Commit changes if any files were updated
    commit_message = f"Translation update to: {', '.join([lang.name for lang in translation_request.get_to_languages()])}"
    subprocess.run(['git', 'commit', '-m', commit_message], cwd=repo_path)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Translate resource bundle messages in the last local Git commit.")   

    parser.add_argument(
        '--repo_path', 
        type=str, 
        help='Path to the git repo'
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
    parser.add_argument(
        '--exclude_marker', 
        type=str, 
        help='(Optional) The marker for the message key for not translating that message.', 
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

    if args.repo_path is None:
        logging.error("The Git repo must be specified.")
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

    logging.info(f"Loading resource bundle message from {args.repo_path}")
    
    git_diff = get_git_commit_diff(repo_path=args.repo_path) # FileChanges
    messages = get_messages(git_diff=git_diff, exclude_marker=args.exclude_marker)
    if messages is None: 
       logging.warn(f"No git changes were detected")
       sys.exit()

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
    translation_request = translation_service.translate(
        from_language=from_language,  
        messages=messages, 
        to_languages=to_languages)
    logging.info(f"Saving translated messages to resource bundle files ...")    
    save_translations(
        git_diff=git_diff,
        translation_request=translation_request,
        repo_path=args.repo_path,
        exclude_marker=args.exclude_marker)
        
if __name__ == "__main__":
    main()