import unittest
from unittest.mock import mock_open, patch, MagicMock

from languages import Language

# Assuming these are the two functions in your module named `translation_module`
from cli.resource_bundle_generator import load_resource_bundle, save_translations

class TestTranslationCLI(unittest.TestCase):

    def test_load_resource_bundle_excludes_instructions(self):
        # Sample data simulating the contents of a resource bundle file
        resource_data = """egoge.message.welcome=Hello World!
egoge.message.welcome.###INST###=This is a greeting message.
egoge.button.ok=OK
egoge.button.cancel=CANCEL"""

        # Use mock_open to simulate file reading
        m = mock_open(read_data=resource_data)
        with patch('builtins.open', m):
            result = load_resource_bundle('dummy_path', '###INST###')
            self.assertNotIn('egoge.message.welcome.###INST###', result)
            self.assertIn('egoge.message.welcome', result)
            self.assertEqual(result['egoge.message.welcome'], 'Hello World!')

    def test_save_translations(self):
        # Prepare a mock for the translation request object
        translation_request = MagicMock()
        translation_request. get_from_language.return_value = Language.EN_US
        translation_request.get_to_languages.return_value = [Language.DE, Language.HE]
        translation_request.get_translation_by_message_id.side_effect = lambda message_id, to_language: 'Translated Text'

        messages = {'egoge.message.welcome': 'Hello World!'}

        # Mock for file operations
        m = mock_open()
        with patch('builtins.open', m) as mocked_file:
            save_translations(messages, translation_request, '/fake_directory', 'resources_[LANG].properties')

            # Check if open was called correctly
            self.assertEqual(mocked_file.call_args_list[0][0][0], '/fake_directory/resources_de.properties')
            self.assertEqual(mocked_file.call_args_list[1][0][0], '/fake_directory/resources_he.properties')

            # Check if write was called correctly
            handle = mocked_file()
            handle.write.assert_any_call('egoge.message.welcome=Translated Text\n')

if __name__ == '__main__':
    unittest.main()
