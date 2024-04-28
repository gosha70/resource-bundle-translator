# Resource Bundle Translator
The main goal of this LLM-based translator is translate English messages used in software applications to other languages.
The translator preserves message placeholders (for example: `{0}`) and preserved words. 

Currently the following languages are supported:
- AR = "ar"      : Modern Standard Arabic 
- DE = "de"      : German
- EL = "el"      : Greek
- EN_GB ="en_GB" : English, assuming no distinction in model between GB and US
- EN_US = "en_US": English
- ES = "es"      : Spanish
- FR_CA = "fr_CA": French, assuming no distinction for Canadian French
- FR_CH = "fr_CH": French
- FR_FR = "fr_FR": French
- IT = "it"      : Italian
- HE = "iw"      : Hebrew
- HI = "hi"      : Hindi
- JA = "ja"      : Japanese
- KO = "ko"      : Korean
- NL = "nl"      : Dutch
- PL = "pl"      : Polish
- PT = "pt"      : Portuguese
- RU = "ru"      : Russian
- SV = "sv"      : Swedish
- TH = "th"      : Thai
- TR = "tr"      : Turkish
- ZH_CH = "zh_CN": Chinese Mandarin
- ZH_HK = "zh_HK": Chinese Mandarin, assuming no distinction for Hong Kong 
    
## API
**Resource Bundle Translator** supports two endpoints:

### The **Flask** application which can be start locally:
```
> python -m app.translator.app
```

#### Setup
Install the required libraries:
```
> python -m pip install -r requirements.txt
```

The following arguments can be specified to the standalone application:
  -  `--port`: _(Optional)_ Port for Resource Bundle Translator Application. Defaults to `5001`.
  -  `--from_lang`: _(Optional)_ The Language abbreviation for the input text is written in.. Default is `'en_US'`.
  -  `--to_langs`: _(Optional)_ The Llist of Language abbreviations for translation. If it is not specified, then it is all Languages, excluding the from_lang one.
  -  `--model_name`: _(Optional)_ The type of supported Translation models. By default: `nllb` (right now the other option is `opus`). 

The application reads the configuration where a user can specify supported translations (`from_language` to `to_languages`), and the `glossary` of preserved words:
```
{
    "cache_dir": "~/tmp/ai_cache",
    "from_language": "en_US",
    "to_languages": [
        "ar",
        "de",
        "el",
        "en_GB",
        "es",
        "fr_CA",
        "fr_CH",
        "fr_FR",
        "it",
        "iw",
        "ja",
        "ko",
        "nl",
        "pl",
        "pt",
        "ru",
        "sv",
        "th",
        "tr",
        "zh_CN",
        "zh_HK"
    ],
    "glossary": [
        "EGOGE",
        "Ltd."
    ]
}
```
#### Translation Models
##### Local Models
###### NLLB 200 
[NLLB 200](https://github.com/facebookresearch/flores/blob/main/flores200/README.md#languages-in-flores-200) (No Language Left Behind) demonstrates the use of local LLM to auto-translate resource bundle messages.
In order to perform translation of resource bundle messages in the local Git commit, you need specify the path to a local repo and the language model name, which is “nllb”; here is example for translating to Hebrew:
```
> python -m cli.resource_bundle_git --repo_path .../repo/ae --model_name nllb --to_lang iw
```
###### OPUS
[Helsinki-NLP/OPUS](https://huggingface.co/transformers/v4.0.1/model_doc/marian.html) is another model which can be used locally; however, there a few languages (such as Turkey, Thai) 
are not very well supported by this model:
```
> python -m cli.resource_bundle_git --repo_path .../repo/ae --model_name opus --to_lang iw
```

##### External Models
###### Open AI 
[Open AI](https://openai.com/product) demonstrates the use of managed services/external models; run the following command to translate messages using `https://api.openai.com/v1/chat/completions`: 
```
> python -m cli.resource_bundle_git --repo_path .../repo/ae --model_name openai --to_lang iw
```

#### Use
Once application is up, the `/translate` POST can be called with a request containg the following JSON structure:
```
{
    "to_languages": ["fr_FR", "HE"]
    "messages": ["Hello world!", "This is a test text."]
}
``` 

Example of calling the application via `curl`:
```
> curl -X POST http://localhost:5005/translate -H "Content-Type: application/json" -d '{
    "messages": ["Hello world!", "This is a test text."],
    "to_languages": ["fr_FR", "HE"]
}'
```

### Translator CLI
For ease of use, the Resource Bundle Translator provides a command-line interface (CLI) tool. 
This tool facilitates the batch generation of resource bundle files directly from properties files, making it ideal for projects requiring frequent updates across multiple locales.
#### Per File Translation
You can translate all messages in the specified resource bundle file.
The script which generates resource bundles files with messages in requested languages (`--to_langs`) from the specified file (`--from_file`):
```
> python -m cli.resource_bundle_generator --from_file  ../resources_en_US.properties --to_langs he it
```
#### Per Git Commit Translation
In order to perform translation of resource bundle messages in the local **Git** commit, you need specify the path to a local repo and the language model name, which is `"nllb"`; 
here is example for translating to Hebrew:
```
> python -m cli.resource_bundle_git --repo_path .../repo/ae --model_name nllb --to_lang iw
```


### Unit Testing
You can test both models by running the following unit tests:
```
> python -m unittest test/nllb_test.py
> python -m unittest test/open_ai_test.py
```



