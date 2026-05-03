
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, MarianMTModel, MarianTokenizer

# Example of sequential usage
def process_with_marian():
    tokenizer = MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-en-he')
    model = MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-en-he')
    

def process_with_nllb():
    tokenizer = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
    model = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")
    

# Use them sequentially
process_with_marian()
process_with_nllb()