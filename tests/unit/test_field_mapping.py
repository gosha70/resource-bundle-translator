# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Unit tests for
:class:`ainemo.core.termbase.sources.mapping.FieldMapping`.

Cycle-4 S1 contract:

- Mandatory fields raise on omission (``source_lang``,
  ``source_column``, ``target_columns``).
- Unknown fields raise (``extra="forbid"``).
- ``target_columns`` rejects empty dicts and dicts of all-blank
  values.
- Optional fields default to ``None`` and round-trip cleanly.
- ``all_referenced_columns()`` returns every column the mapping
  references in declaration order.

Pin the schema-strictness audit lessons from the cycle-3 S4
cooldown: every Pydantic field has its required-vs-optional +
``extra="forbid"`` decision documented and tested up-front, before
the loader / CLI scopes consume the schema.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from ainemo.core.termbase.sources.mapping import (
    FieldMapping,
    field_mapping_from_yaml_dict,
)

pytestmark = pytest.mark.unit


# --- Builders ---


def _minimal_yaml() -> str:
    return "source_lang: en-US\nsource_column: term_en\ntarget_columns:\n  de-DE: term_de\n"


def _full_yaml() -> str:
    return (
        "source_lang: en-US\n"
        "source_column: term_en\n"
        "target_columns:\n"
        "  de-DE: term_de\n"
        "  fr-FR: term_fr\n"
        "  es-ES: term_es\n"
        "domain_column: category\n"
        "definition_column: notes\n"
    )


# --- Mandatory-field rejection ---


def test_minimal_mapping_loads_with_optional_fields_defaulting_to_none() -> None:
    mapping = FieldMapping.model_validate(yaml.safe_load(_minimal_yaml()))
    assert mapping.source_lang == "en-US"
    assert mapping.source_column == "term_en"
    assert mapping.target_columns == {"de-DE": "term_de"}
    assert mapping.domain_column is None
    assert mapping.definition_column is None


def test_full_mapping_loads_every_field() -> None:
    mapping = FieldMapping.model_validate(yaml.safe_load(_full_yaml()))
    assert mapping.target_columns == {
        "de-DE": "term_de",
        "fr-FR": "term_fr",
        "es-ES": "term_es",
    }
    assert mapping.domain_column == "category"
    assert mapping.definition_column == "notes"


def test_missing_source_lang_raises() -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload.pop("source_lang")
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "source_lang" in str(excinfo.value)


def test_missing_source_column_raises() -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload.pop("source_column")
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "source_column" in str(excinfo.value)


def test_missing_target_columns_raises() -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload.pop("target_columns")
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "target_columns" in str(excinfo.value)


# --- target_columns shape validation ---


def test_empty_target_columns_raises() -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload["target_columns"] = {}
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "target_columns" in str(excinfo.value)


def test_target_columns_all_blank_values_raises() -> None:
    # Even though min_length=1 catches structurally-empty dicts, an
    # all-blank dict is semantically empty and would silently produce
    # zero terms per row. Pin the validator that rejects it.
    payload = yaml.safe_load(_minimal_yaml())
    payload["target_columns"] = {"de-DE": "", "fr-FR": "   "}
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "target_columns" in str(excinfo.value)


# --- extra="forbid" ---


def test_unknown_field_rejected() -> None:
    # Per cycle-3 S4 lesson: typos must surface as load errors, not
    # silent data loss. A user typing `source_columns` (with the
    # trailing `s`) would otherwise produce zero terms on every row.
    payload = yaml.safe_load(_minimal_yaml())
    payload["source_columns"] = "term_en"
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    msg = str(excinfo.value)
    assert "source_columns" in msg
    assert "extra" in msg.lower() or "forbidden" in msg.lower()


# --- Helper: all_referenced_columns ---


def test_all_referenced_columns_minimal() -> None:
    mapping = FieldMapping.model_validate(yaml.safe_load(_minimal_yaml()))
    assert mapping.all_referenced_columns() == ("term_en", "term_de")


def test_all_referenced_columns_full() -> None:
    mapping = FieldMapping.model_validate(yaml.safe_load(_full_yaml()))
    cols = mapping.all_referenced_columns()
    # source first; target columns next; domain + definition last.
    assert cols[0] == "term_en"
    assert set(cols[1:4]) == {"term_de", "term_fr", "term_es"}
    assert cols[-2:] == ("category", "notes")


# --- Top-level shape via field_mapping_from_yaml_dict ---


def test_top_level_must_be_mapping() -> None:
    # YAML lists at top level are a common typo when authoring
    # mapping files; surface as a clear ValueError.
    with pytest.raises(ValueError) as excinfo:
        field_mapping_from_yaml_dict(["not", "a", "mapping"])
    assert "mapping" in str(excinfo.value).lower()


def test_helper_round_trips_minimal_yaml() -> None:
    mapping = field_mapping_from_yaml_dict(yaml.safe_load(_minimal_yaml()))
    assert isinstance(mapping, FieldMapping)
    assert mapping.target_columns == {"de-DE": "term_de"}


# --- Cycle-4 S1 P2 regressions: every string field must be non-blank ---


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_source_lang_raises(value: str) -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload["source_lang"] = value
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "source_lang" in str(excinfo.value)


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_source_column_raises(value: str) -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload["source_column"] = value
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "source_column" in str(excinfo.value)


def test_blank_domain_column_raises() -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload["domain_column"] = ""
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    msg = str(excinfo.value)
    assert "domain_column" in msg
    # Hint nudges the user toward the right fix.
    assert "omit" in msg.lower()


def test_blank_definition_column_raises() -> None:
    payload = yaml.safe_load(_minimal_yaml())
    payload["definition_column"] = "   "
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "definition_column" in str(excinfo.value)


def test_partially_blank_target_columns_raises() -> None:
    # The reviewer's repro: one target column is blank, another is
    # populated. Without the per-pair validator, the German target
    # silently drops on every row and only French lands.
    payload = yaml.safe_load(_minimal_yaml())
    payload["target_columns"] = {"de-DE": "", "fr-FR": "term_fr"}
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    msg = str(excinfo.value)
    assert "target_columns" in msg
    assert "de-DE" in msg


def test_blank_target_columns_key_raises() -> None:
    # YAML lets you write `"": term_de` as a mapping key; the
    # resulting Term.lang would be empty. Reject up-front.
    payload = yaml.safe_load(_minimal_yaml())
    payload["target_columns"] = {"": "term_de"}
    with pytest.raises(ValidationError) as excinfo:
        FieldMapping.model_validate(payload)
    assert "target_columns" in str(excinfo.value)


def test_optional_columns_omitted_still_validates() -> None:
    # Confirm the optional-field validator only triggers on blank
    # values, not on omitted fields (which default to None).
    mapping = FieldMapping.model_validate(yaml.safe_load(_minimal_yaml()))
    assert mapping.domain_column is None
    assert mapping.definition_column is None
