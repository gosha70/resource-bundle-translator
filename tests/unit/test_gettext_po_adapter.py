"""Unit + contract tests for
:class:`ainemo.core.adapters.gettext_po.GettextPoAdapter`."""

from __future__ import annotations

from pathlib import Path

import polib
import pytest

from ainemo.core.adapters.base import BundleAdapter
from ainemo.core.adapters.gettext_po import (
    METADATA_KEY_EXTRACTED_COMMENT,
    METADATA_KEY_MSGCTXT,
    METADATA_KEY_PLURAL_BASE_KEY,
    METADATA_KEY_PLURAL_FORM_INDEX,
    METADATA_KEY_REFERENCE,
    METADATA_KEY_TRANSLATOR_COMMENT,
    GettextPoAdapter,
)
from ainemo.core.segment import (
    TRANSLATION_SOURCE_PROVIDER,
    PlaceholderKind,
    Segment,
    TranslatedSegment,
)

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"
_PROVIDER_TEST = "test"


def _ts(seg: Segment, target_text: str, target_lang: str = _LANG_DE) -> TranslatedSegment:
    return TranslatedSegment(
        segment=seg,
        target_lang=target_lang,
        target_text=target_text,
        provider=_PROVIDER_TEST,
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )


def _write_po(path: Path, body: str) -> None:
    """Write a PO header + ``body`` content. Header sets UTF-8 + a
    plural-form rule so polib accepts plural entries."""
    header = (
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Content-Transfer-Encoding: 8bit\\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n'
        "\n"
    )
    path.write_text(header + body, encoding="utf-8")


# --- Protocol conformance --------------------------------------------------


def test_adapter_satisfies_protocol() -> None:
    adapter = GettextPoAdapter()
    assert isinstance(adapter, BundleAdapter)
    assert adapter.format_id == "gettext-po"
    assert adapter.file_extensions == (".po",)


# --- Singular entries ------------------------------------------------------


def test_parse_singular_entry(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(src, 'msgid "Hello world"\nmsgstr ""\n')

    segments = GettextPoAdapter().parse(src, _LANG_EN_US)
    assert len(segments) == 1
    assert segments[0].source_text == "Hello world"
    assert segments[0].key == "Hello world"


def test_parse_with_msgctxt(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(
        src,
        'msgctxt "menu"\nmsgid "File"\nmsgstr ""\n\nmsgctxt "verb"\nmsgid "File"\nmsgstr ""\n',
    )

    segments = GettextPoAdapter().parse(src, _LANG_EN_US)
    assert len(segments) == 2
    # Different msgctxt → different keys, even though msgid is the same
    assert segments[0].key != segments[1].key
    assert segments[0].metadata[METADATA_KEY_MSGCTXT] == "menu"
    assert segments[1].metadata[METADATA_KEY_MSGCTXT] == "verb"


def test_parse_extracts_placeholders(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(
        src,
        'msgid "Hello {name}!"\nmsgstr ""\n\n'
        'msgid "{count, plural, one {1 item} other {# items}}"\nmsgstr ""\n',
    )

    segments = GettextPoAdapter().parse(src, _LANG_EN_US)
    by_text = {s.source_text: s for s in segments}
    assert by_text["Hello {name}!"].placeholders[0].kind is PlaceholderKind.NAMED
    assert (
        by_text["{count, plural, one {1 item} other {# items}}"].placeholders[0].kind
        is PlaceholderKind.ICU_PLURAL
    )


def test_parse_preserves_comments(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(
        src,
        "# Translator note\n"
        "#. Extracted from src/ui.py\n"
        "#: src/ui.py:42\n"
        "#, fuzzy\n"
        'msgid "Welcome"\n'
        'msgstr ""\n',
    )

    segments = GettextPoAdapter().parse(src, _LANG_EN_US)
    seg = segments[0]
    assert seg.metadata[METADATA_KEY_TRANSLATOR_COMMENT] == "Translator note"
    assert seg.metadata[METADATA_KEY_EXTRACTED_COMMENT] == "Extracted from src/ui.py"
    assert seg.metadata[METADATA_KEY_REFERENCE] == "src/ui.py:42"


def test_parse_skips_obsolete_entries(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(
        src,
        '#~ msgid "Old key"\n#~ msgstr ""\n\nmsgid "Active key"\nmsgstr ""\n',
    )

    segments = GettextPoAdapter().parse(src, _LANG_EN_US)
    assert [s.source_text for s in segments] == ["Active key"]


# --- Plural entries --------------------------------------------------------


def test_serialize_passes_through_n_form_plurals(tmp_path: Path) -> None:
    """Cycle-1 contract pin: ``_plural_entry_from_translated`` writes
    *every* form-index supplied in the TranslatedSegment list. Cycle 1
    only ever supplies forms 0 and 1 (gettext source has only msgid +
    msgid_plural), but a future N-form-aware caller passing forms
    2..N must get them written verbatim. Otherwise cycle 3+ will need
    to revisit the serialize logic *and* the test contract together,
    instead of just adding the caller-side N-form generation."""
    src = tmp_path / "messages.po"
    _write_po(
        src,
        'msgid "{count} item"\nmsgid_plural "{count} items"\nmsgstr[0] ""\nmsgstr[1] ""\n',
    )

    adapter = GettextPoAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)

    # Synthesize a 4-form Russian-style translation: forms 0..3.
    # Form 0/1 come from the parsed source segments; forms 2/3 are
    # injected as if a future cycle-3+ provider produced them.
    extra_form_2 = TranslatedSegment(
        segment=Segment(
            key=parsed[0].key.replace("#0", "#2"),
            source_text=parsed[0].source_text,
            source_lang=parsed[0].source_lang,
            placeholders=parsed[0].placeholders,
            metadata={
                **parsed[0].metadata,
                "po.plural_form_index": "2",
            },
        ),
        target_lang="ru-RU",
        target_text="{count} элементов",  # Russian "many"
        provider=_PROVIDER_TEST,
        confidence=None,
        source=TRANSLATION_SOURCE_PROVIDER,
    )
    translated = (
        _ts(parsed[0], "{count} элемент", target_lang="ru-RU"),
        _ts(parsed[1], "{count} элемента", target_lang="ru-RU"),
        extra_form_2,
    )
    out = tmp_path / "messages.ru.po"
    adapter.serialize(out, translated, "ru-RU")

    written = polib.pofile(str(out))
    plural_entry = written[0]
    assert plural_entry.msgstr_plural[0] == "{count} элемент"
    assert plural_entry.msgstr_plural[1] == "{count} элемента"
    assert plural_entry.msgstr_plural[2] == "{count} элементов"


def test_parse_plural_entry_yields_two_segments(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(
        src,
        'msgid "{count} item"\nmsgid_plural "{count} items"\nmsgstr[0] ""\nmsgstr[1] ""\n',
    )

    segments = GettextPoAdapter().parse(src, _LANG_EN_US)
    assert len(segments) == 2
    assert segments[0].source_text == "{count} item"
    assert segments[1].source_text == "{count} items"
    # Both share the same plural-base-key
    base0 = segments[0].metadata[METADATA_KEY_PLURAL_BASE_KEY]
    base1 = segments[1].metadata[METADATA_KEY_PLURAL_BASE_KEY]
    assert base0 == base1
    assert segments[0].metadata[METADATA_KEY_PLURAL_FORM_INDEX] == "0"
    assert segments[1].metadata[METADATA_KEY_PLURAL_FORM_INDEX] == "1"


# --- Serialize -------------------------------------------------------------


def test_serialize_singular(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(src, 'msgid "Hello"\nmsgstr ""\n')

    adapter = GettextPoAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (_ts(parsed[0], "Hallo"),)
    out = tmp_path / "messages.de.po"
    adapter.serialize(out, translated, _LANG_DE)

    written = polib.pofile(str(out))
    assert len(written) == 1
    assert written[0].msgid == "Hello"
    assert written[0].msgstr == "Hallo"


def test_serialize_plural(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(
        src,
        'msgid "{count} item"\nmsgid_plural "{count} items"\nmsgstr[0] ""\nmsgstr[1] ""\n',
    )

    adapter = GettextPoAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (
        _ts(parsed[0], "{count} Eintrag"),
        _ts(parsed[1], "{count} Einträge"),
    )
    out = tmp_path / "messages.de.po"
    adapter.serialize(out, translated, _LANG_DE)

    written = polib.pofile(str(out))
    assert len(written) == 1
    plural_entry = written[0]
    assert plural_entry.msgid == "{count} item"
    assert plural_entry.msgid_plural == "{count} items"
    assert plural_entry.msgstr_plural[0] == "{count} Eintrag"
    assert plural_entry.msgstr_plural[1] == "{count} Einträge"


def test_serialize_preserves_comments(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(
        src,
        '# Translator note\n#. Extracted comment\n#: src/ui.py:42\nmsgid "Welcome"\nmsgstr ""\n',
    )

    adapter = GettextPoAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    translated = (_ts(parsed[0], "Willkommen"),)
    out = tmp_path / "messages.de.po"
    adapter.serialize(out, translated, _LANG_DE)

    written = polib.pofile(str(out))
    entry = written[0]
    assert entry.tcomment == "Translator note"
    assert entry.comment == "Extracted comment"
    assert entry.occurrences == [("src/ui.py", "42")]


def test_serialize_rejects_target_lang_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "messages.po"
    _write_po(src, 'msgid "k"\nmsgstr ""\n')

    adapter = GettextPoAdapter()
    parsed = adapter.parse(src, _LANG_EN_US)
    wrong = (_ts(parsed[0], "x", target_lang="fr-FR"),)
    out = tmp_path / "messages.de.po"
    with pytest.raises(ValueError):
        adapter.serialize(out, wrong, _LANG_DE)


# --- Round-trip identity --------------------------------------------------


@pytest.mark.parametrize(
    "fixture_body",
    [
        'msgid "Hello"\nmsgstr ""\n',
        'msgid "Hello {name}!"\nmsgstr ""\n',
        'msgid "{count, plural, one {1 item} other {# items}}"\nmsgstr ""\n',
        'msgctxt "menu"\nmsgid "File"\nmsgstr ""\n',
        '# Translator comment\nmsgid "Welcome"\nmsgstr ""\n',
        '#: src/ui.py:42\nmsgid "Welcome"\nmsgstr ""\n',
        'msgid "{count} item"\nmsgid_plural "{count} items"\nmsgstr[0] ""\nmsgstr[1] ""\n',
        'msgid "Unicode こんにちは"\nmsgstr ""\n',
        'msgid ""\nmsgstr ""\nmsgid "second"\nmsgstr ""\n',  # header + one entry
        'msgid "k1"\nmsgstr ""\n\nmsgid "k2"\nmsgstr ""\n',
    ],
    ids=[
        "simple",
        "with-named-placeholder",
        "with-icu-plural",
        "with-msgctxt",
        "with-translator-comment",
        "with-reference-comment",
        "plural-entry",
        "unicode",
        "with-explicit-header",
        "two-entries",
    ],
)
def test_round_trip_identity(tmp_path: Path, fixture_body: str) -> None:
    src = tmp_path / "messages.po"
    _write_po(src, fixture_body)

    adapter = GettextPoAdapter()
    first_parse = adapter.parse(src, _LANG_EN_US)
    translated = tuple(_ts(seg, seg.source_text) for seg in first_parse)
    out = tmp_path / "messages.de.po"
    adapter.serialize(out, translated, _LANG_DE)
    second_parse = adapter.parse(out, _LANG_EN_US)

    assert len(first_parse) == len(second_parse)
    for first, second in zip(first_parse, second_parse, strict=True):
        assert first.source_text == second.source_text
        assert first.key == second.key
