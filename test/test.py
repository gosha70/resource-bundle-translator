from transformers import MarianMTModel, MarianTokenizer

# Load the tokenizer
model_name = 'Helsinki-NLP/opus-mt-en-he'

# Load the model
model = MarianMTModel.from_pretrained(model_name)

tokenizer = MarianTokenizer.from_pretrained(model_name)
text_to_translate = "This is a test text from _EGOGE _Ltd. and _3 between _1"

encoded_input = tokenizer.encode(text_to_translate, return_tensors="pt")
decoded_tokens = tokenizer.convert_ids_to_tokens(encoded_input[0])
print(f"Decoded tokens: {decoded_tokens}")

# Generate translation
translated_tokens = model.generate(encoded_input)
translation = tokenizer.decode(translated_tokens[0], skip_special_tokens=True)
print(f"Translation: '{translation}')")
