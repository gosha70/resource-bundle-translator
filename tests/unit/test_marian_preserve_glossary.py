"""Regression test for the cycle-0 audit-bug fix in
:meth:`ainemo.providers.opus.marian_mt_model.MarianTranslatorModel.preserve_glossary_words`.

The pre-cycle-0 code defined ``preserve_glossary_words`` twice in the same
class; the second definition shadowed the first and used a plain
``\\b{key}\\b`` regex. ``\\b`` does not assert a boundary after a
punctuation character, so terms that end in punctuation (e.g. ``"Inc."``)
were not matched correctly, and the first (correct) definition was dead.

Cycle 0 deletes the second definition and keeps the first, with a
boundary-handling branch that uses ``(?!\\w)`` lookahead for terms ending
in non-word characters. These tests pin the corrected behavior so a
future re-introduction breaks visibly.
"""
from __future__ import annotations

import re

from ainemo.providers.opus.marian_mt_model import MarianTranslatorModel


def _new_model() -> MarianTranslatorModel:
    """Build a Marian model instance without invoking the network-heavy
    ``__init__`` (which downloads tokenizers). ``preserve_glossary_words``
    is independent of model state, so we instantiate via ``__new__``."""
    return MarianTranslatorModel.__new__(MarianTranslatorModel)


def _escaped(term: str) -> tuple[str, str]:
    return (term, re.escape(term))


def test_word_boundary_does_not_match_substring() -> None:
    model = _new_model()
    preserved: dict[str, str] = {}
    out = model.preserve_glossary_words(
        text="Click OK to confirm and avoid being JOKEY.",
        glossary=[_escaped("OK")],
        preserved_words=preserved,
    )
    # `OK` matches; the OK inside JOKEY does not.
    assert "OK" not in out.replace("_OK", "")
    assert "JOKEY" in out
    assert preserved == {"_OK": "OK"}


def test_term_ending_in_punctuation_is_matched() -> None:
    """The original (working) definition special-cases punctuation-ending
    terms with a lookahead, since plain `\\b.` does not assert a boundary
    after `.`. This is exactly the divergence the deleted shadow lacked."""
    model = _new_model()
    preserved: dict[str, str] = {}
    out = model.preserve_glossary_words(
        text="Acme Inc. is a company.",
        glossary=[_escaped("Inc.")],
        preserved_words=preserved,
    )
    assert "Inc." not in out
    assert "_INC" in out
    assert preserved == {"_INC": "Inc."}


def test_glossary_term_replaced_with_deterministic_token() -> None:
    """The token is ``_<UPPERCASE_LETTERS_OF_TERM>`` — i.e. punctuation
    is stripped and letters uppercased. Same term → same token, so the
    method is idempotent over repeat occurrences."""
    model = _new_model()
    preserved: dict[str, str] = {}
    out = model.preserve_glossary_words(
        text="EGOGE is a brand. EGOGE rocks.",
        glossary=[_escaped("EGOGE")],
        preserved_words=preserved,
    )
    assert out.count("_EGOGE") == 2
    assert "EGOGE" not in out.replace("_EGOGE", "")
    assert preserved == {"_EGOGE": "EGOGE"}


def test_only_one_preserve_glossary_words_definition_exists() -> None:
    """Pin the cycle-0 fix: the second (buggy) shadow definition must not
    return. If both definitions exist again, the class body declares the
    name twice; we detect that by reading the source.

    A direct AST/inspect check is overkill; counting source occurrences
    of ``def preserve_glossary_words`` in the file is sufficient and
    breaks if anyone re-introduces the shadow."""
    import inspect

    source = inspect.getsource(MarianTranslatorModel)
    occurrences = source.count("def preserve_glossary_words")
    assert occurrences == 1, (
        f"Expected exactly one preserve_glossary_words definition; "
        f"found {occurrences}. The cycle-0 fix removed a duplicate that "
        f"shadowed the correct word-boundary version."
    )
