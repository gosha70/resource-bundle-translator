"""Regression test for the cycle-0 audit-bug fix in
:mod:`ainemo._legacy.translation_request`.

The pre-cycle-0 code had ``self.translationss`` (typo) inside
``get_texts_to_translate``, which raised ``AttributeError`` whenever the
method was called. The fix routes the iteration through
``self.translation_map.values()`` (the actual storage). This test pins
that contract so the typo cannot return.
"""

from __future__ import annotations

from ainemo._legacy.languages import Language
from ainemo._legacy.translation import Translation
from ainemo._legacy.translation_request import TranslationRequest


def _make_request() -> TranslationRequest:
    return TranslationRequest(
        glossary=[],
        from_language=Language.EN_US,
        translations=[
            Translation(
                message_id="welcome",
                original_text="Hello",
                adjusted_text="Hello",
                preserved_words={},
            ),
            Translation(
                message_id="goodbye",
                original_text="Goodbye",
                adjusted_text="Goodbye",
                preserved_words={},
            ),
        ],
        to_languages=[Language.DE, Language.FR_FR],
    )


def test_get_texts_to_translate_returns_each_translations_text() -> None:
    request = _make_request()
    texts = request.get_texts_to_translate()
    assert sorted(texts) == ["Goodbye", "Hello"]


def test_get_texts_to_translate_does_not_reference_misspelled_attribute() -> None:
    """Guard against a recurrence of the original `translationss` typo."""
    request = _make_request()
    # A literal grep on the source would also work, but importing the
    # method and exercising it gives us a runtime guarantee.
    request.get_texts_to_translate()  # must not raise AttributeError
