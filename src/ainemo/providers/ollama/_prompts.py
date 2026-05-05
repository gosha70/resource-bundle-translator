"""Ollama prompt-template constants.

Per AGENTS.md § Prohibited Patterns: prompt strings are constants.
Same shape as the OpenAI / Anthropic prompt modules so cycle-2
benchmarks (scope 14) compare like-for-like across providers.
"""

from __future__ import annotations

from typing import Final

SYSTEM_PROMPT: Final = (
    "You are a professional multi-language translator. Your main task is "
    "translating resource-bundle messages used in software UIs. Preserve "
    "every placeholder ({0}, {name}, ICU plural/select/selectordinal) "
    "exactly as written — do not translate or reformat them. Return only "
    "the translated text, with no explanation, no quoting, and no prefix."
)

GLOSSARY_PREFIX: Final = "\n\nDo not translate or alter the following terms; emit them verbatim: "

USER_MESSAGE_TEMPLATE: Final = (
    "Translate the following text from {from_lang} to {to_lang}, "
    "preserving placeholders verbatim:\n\n{text}"
)


__all__ = ["SYSTEM_PROMPT", "GLOSSARY_PREFIX", "USER_MESSAGE_TEMPLATE"]
