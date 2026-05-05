"""OpenAI prompt-template constants.

Per AGENTS.md § Prohibited Patterns: prompt strings are constants.
The cycle-2 OpenAI provider uses these to build the chat-completion
messages — never inlines a prompt at the call site.
"""

from __future__ import annotations

from typing import Final

# System message — establishes the translation persona. Same shape as
# the cycle-0 prototype's prompt; cycle-3+ persona work may swap this
# for a persona-keyed selection.
SYSTEM_PROMPT: Final = (
    "You are a professional multi-language translator. Your main task is "
    "translating resource-bundle messages used in software UIs. Preserve "
    "every placeholder ({0}, {name}, ICU plural/select/selectordinal) "
    "exactly as written — do not translate or reformat them. Return only "
    "the translated text, with no explanation, no quoting, and no prefix."
)

# Glossary-injection suffix appended to the system prompt when a
# routing layer supplies a forbidden-words / brand-stem list. Cycle-2's
# router does not yet inject glossary; cycle 3 + 4 (termbase + domain
# packs) will.
GLOSSARY_PREFIX: Final = "\n\nDo not translate or alter the following terms; emit them verbatim: "

# Per-segment user-message template. ``{from_lang}`` / ``{to_lang}``
# are full BCP-47 tags; ``{text}`` is the source text with placeholders
# inline.
USER_MESSAGE_TEMPLATE: Final = (
    "Translate the following text from {from_lang} to {to_lang}, "
    "preserving placeholders verbatim:\n\n{text}"
)


__all__ = ["SYSTEM_PROMPT", "GLOSSARY_PREFIX", "USER_MESSAGE_TEMPLATE"]
