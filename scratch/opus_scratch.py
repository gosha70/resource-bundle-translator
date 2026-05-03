import unittest

from languages import Language
from models.model_types import ModelType
from translation_service import TranslationService

# Assuming these are the two functions in your module named `translation_module`
from cli.resource_bundle_generator import load_resource_bundle, save_translations

class TestTranslationNLLBC(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Called once for the entire class
        print('setUpClass: Initializes Translation Service using NLLB model ...')
        translator_model = ModelType.get_model_by_name(
            model_name='opus', 
            source_lang=Language.EN_US, 
            target_langs=None, 
            cache_dir="~/tmp/ai_cache", 
            logging=None)  
        glossary=[
            "EGOGE",
            "OK"
        ]
        cls.translation_service = TranslationService(
            model=translator_model, 
            glossary=glossary, 
            logging=None)

    def test_translation_without_to_languages(self):
        # GIVEN
        expected_translations = {
            Language.AR: "مرحبا عالم!",
            Language.DE: "Hallo Welt!",
            Language.EL: "Γεια σου Κόσμος!",
            Language.EN_GB: "Hello world!",
            Language.ES: "¡Hola al mundo!",
            Language.FR_CA: "Bonjour le monde !",
            Language.FR_CH: "Bonjour le monde !",
            Language.FR_FR: "Bonjour le monde !",
            Language.IT: "Ciao mondo!",
            Language.HE: "שלום לעולם!",
            Language.HI: "हैलो वर्ल्ड!",
            Language.JA: "こんにちは!",
            Language.KO: "안녕하세요!",
            Language.NL: "Hallo wereld!",
            Language.PL: "Witam Świat!",
            Language.PT: "Olá Mundo!",
            Language.RU: "Здравствуйте!",
            Language.SV: "Hej värld!",
            Language.TH: "สวัสดีโลก!",
            Language.TR: "Merhaba Dünya!",
            Language.ZH_CH: "你好世界!",
            Language.ZH_HK: "您好,世界!"
        }
        message_key = 'egoge.message.welcome'
        messages= {message_key: 'Hello World!'}

        # WHEN
        tanslation_request = self.translation_service.translate(
            from_language=Language.EN_US,  
            messages=messages, 
            to_languages=None)
        
        # THEN
        to_languages = tanslation_request.get_to_languages()
        self.assertEqual(len(expected_translations), len(to_languages))
        inaccurate_translations = 0
        for lang, translation in expected_translations.items():
            translated_text = tanslation_request.get_translation_by_message_id(message_id=message_key, to_language=lang)
            try:
                self.assertEqual(translation, translated_text)
            except AssertionError as e:
                print(f"Warning for '{lang.value}': {str(e)}")  
                inaccurate_translations += 1

        self.assertEqual(0, inaccurate_translations, f"{inaccurate_translations} inaccurate translation/s were detected!")
        
    def test_translation_with_glossary(self):
        # GIVEN
        expected_translations_map = {
            'egoge.message.welcome': {
                Language.FR_FR: 'Bonjour de EGOGE !',
                Language.HE: 'שלום מ EGOGE!',
                Language.RU: 'Привет от EGOGE!'
            },
            'egoge.message.button.ok': {
                Language.FR_FR: 'OK de {1} à {2}',
                Language.HE: 'OK מ {1} ל {2}',
                Language.RU: 'OK от {1} до {2}'
            }
        }
        messages= {
            'egoge.message.welcome': 'Hi from EGOGE!',
            'egoge.message.button.ok': 'OK from {1} to {2}'
        }

        # WHEN
        tanslation_request = self.translation_service.translate(
            from_language=Language.EN_US,  
            messages=messages, 
            to_languages={Language.FR_FR, Language.HE, Language.RU})
        
        # THEN
        to_languages = tanslation_request.get_to_languages()
        self.assertEqual(3, len(to_languages))
        self.assertEqual(2, len(tanslation_request.get_translations()))
        inaccurate_translations = 0
        for message_id in messages:
            expected_translations = expected_translations_map.get(message_id)
            for lang in expected_translations:
                translated_text = tanslation_request.get_translation_by_message_id(message_id=message_id, to_language=lang)
                try:
                    self.assertEqual(expected_translations.get(lang), translated_text)
                except AssertionError as e:
                    print(f"Warning for '{lang.value}': {str(e)}")  
                    inaccurate_translations += 1

        self.assertEqual(0, inaccurate_translations, f"{inaccurate_translations} inaccurate translation/s were detected!")
            

if __name__ == '__main__':
    unittest.main()
