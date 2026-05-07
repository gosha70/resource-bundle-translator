# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Pydantic-strict YAML schema for `nemo termbase import-from-*`
field mapping.

Cycle-4 S1 — every field has its required-vs-optional + closed-set-
where-applicable + ``extra="forbid"`` decision baked in up-front per
the cycle-3 S4 cooldown lesson (*Schema-strictness audit pre-review*).

YAML shape:

```yaml
source_lang: en-US           # mandatory: fixed source language for this file
source_column: term_en       # mandatory: which CSV column / JSON key holds source-lang term
target_columns:              # mandatory: at least one target rendering
  de-DE: term_de
  fr-FR: term_fr
domain_column: category      # optional: per-row domain id column / key
definition_column: notes     # optional: per-row source-lang definition column / key
```

Rejected up-front:
- **Unknown fields.** ``extra="forbid"`` so a typo'd `source_columns`
  (with the trailing ``s``) surfaces as a load error instead of
  silently producing zero terms.
- **Empty ``target_columns``.** A mapping with no targets imports
  nothing useful; surfaced as a load error rather than a silent
  no-op.
- **Inline mapping.** The CLI accepts only a YAML file via
  ``--map-config`` per pre-resolved Q2 in the pitch — every team's
  mapping is reusable across many revisions of the same glossary, a
  YAML file the team commits alongside the data is the natural
  shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FieldMapping(BaseModel):
    """Maps source-file column / JSON-key names onto AI-NEMO's
    :class:`~ainemo.core.termbase.sources.base.ImportRecord` fields.

    Loaded from a YAML file via
    :meth:`FieldMapping.model_validate(yaml.safe_load(path.read_text()))`.
    Pydantic enforces every field's required-vs-optional contract;
    unknown keys raise.
    """

    model_config = ConfigDict(extra="forbid")

    source_lang: str
    """BCP-47 source language tag applied to every row from this
    file (e.g. ``"en-US"``). Single-valued per file — i18n teams'
    glossaries are nearly always single-source-lang in practice;
    multi-source-lang files split into one CSV per source-lang."""

    source_column: str
    """Name of the CSV column / JSON-Lines field that holds the
    source-language term."""

    target_columns: dict[str, str] = Field(min_length=1)
    """Mapping of BCP-47 target-lang tag → CSV column / JSON-Lines
    field name. At least one entry required (``min_length=1``);
    a mapping with no targets imports nothing useful."""

    domain_column: str | None = None
    """Optional CSV column / JSON-Lines field that holds the per-row
    domain id. When set and a row's value is non-blank, the row's
    ``domain_id`` participates in concept-id derivation as the
    highest-precedence namespace component (per pitch § Solution
    shape) — same source_term in different domains produces
    different concepts."""

    definition_column: str | None = None
    """Optional CSV column / JSON-Lines field that holds a source-
    language definition. Lands on :attr:`Concept.definition` when
    the row's value is non-blank."""

    # --- Non-blank string-field validators ---
    #
    # Each scalar string field must be non-blank when present. A
    # blank `source_lang` produces invalid BCP-47 tags on every
    # imported Term; a blank `source_column` would silently match
    # nothing on every row; a blank `domain_column` /
    # `definition_column` is a YAML-mistake (the user almost
    # certainly meant to omit the field entirely instead of setting
    # it to ""). Catching all of these at load time is the cycle-3
    # S4 schema-strictness lesson applied to every field, not just
    # `target_columns`.

    @field_validator("source_lang", "source_column")
    @classmethod
    def _non_blank_required_string(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-blank string")
        return value

    @field_validator("domain_column", "definition_column")
    @classmethod
    def _non_blank_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError(
                "must be a non-blank string when set; omit the field entirely to disable the column"
            )
        return value

    @field_validator("target_columns")
    @classmethod
    def _every_target_column_pair_non_blank(cls, value: dict[str, str]) -> dict[str, str]:
        # Pydantic's `min_length=1` on the dict catches an empty
        # mapping at parse time; this validator additionally rejects:
        # (a) any blank language-tag key (`{"": "term_de"}` →
        #     produces invalid Term.lang values),
        # (b) any blank column-name value (`{"de-DE": ""}` →
        #     silently drops the German target on every row), and
        # (c) the all-blank case where every entry has a blank
        #     column-name value.
        # Per cycle-4 S1 P2 review: partially-blank mappings used
        # to validate; one missing target rendering is silently lost.
        for lang, column in value.items():
            if not lang or not lang.strip():
                raise ValueError(
                    "target_columns: every key must be a non-blank BCP-47 language tag"
                )
            if not column or not column.strip():
                raise ValueError(
                    f"target_columns[{lang!r}]: column name must be "
                    "non-blank; omit the entry entirely to drop "
                    "this target"
                )
        return value

    def all_referenced_columns(self) -> tuple[str, ...]:
        """Return every CSV column / JSON-Lines field name the
        mapping references, in declaration order. Useful for the
        S2 CsvSource to validate that every column the mapping
        names actually exists in the file's header row."""
        cols: list[str] = [self.source_column, *self.target_columns.values()]
        if self.domain_column is not None:
            cols.append(self.domain_column)
        if self.definition_column is not None:
            cols.append(self.definition_column)
        return tuple(cols)


def field_mapping_from_yaml_dict(payload: Any) -> FieldMapping:
    """Build a :class:`FieldMapping` from a parsed YAML mapping.

    Wraps :meth:`FieldMapping.model_validate` so the cycle-4 S4/S5
    CLI can surface a single ``ValueError`` regardless of whether
    Pydantic raised :class:`pydantic.ValidationError` or the input
    was the wrong shape entirely (e.g. a YAML list at top level
    instead of a mapping).
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"Field-mapping YAML must be a mapping at the top level; got {type(payload).__name__}"
        )
    return FieldMapping.model_validate(payload)


__all__ = ["FieldMapping", "field_mapping_from_yaml_dict"]
