# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Persona YAML loader.

Cycle-3 S4 — reads ``*.yaml`` files from a persona directory and
returns :class:`~ainemo.core.termbase.base.Persona` dataclasses.
The on-disk schema is enforced by Pydantic so a malformed YAML
fails fast with a clear error rather than producing a Persona
with surprising defaults.

Schema (resolved at /bet, 2026-05-05; pitch § Open questions Q2)
----------------------------------------------------------------

Mandatory:
- ``persona_id`` (string)
- ``name`` (string)
- ``forbidden_terms`` (list of strings; may be empty)
- ``prompt_addendum`` (string, free-text — concatenated into the
  provider system prompt by cycle-3 S6)

Optional:
- ``domain_id`` (string, FK to a Domain row)
- ``register`` (``"formal"`` | ``"casual"`` | ``"neutral"`` | null)
- ``style_guide_url`` (string)
- ``glossary_overrides`` (list of ``{source_term, target_lang,
  target_term}`` records)

Unknown fields are rejected (``extra='forbid'``) so a YAML carrying
the dropped ``provider_hints`` field surfaces as a load error rather
than a silent data loss. Persona-aware routing lives in cycle-2's
:class:`~ainemo.providers.router.RoutingConfig` ``persona`` /
``domain`` matchers; do not duplicate the routing concern on the
persona schema.

Idempotency
-----------

:func:`sync_personas_into_termbase` calls :meth:`Termbase.add_persona`
for every loaded persona. Because ``add_persona`` upserts on
``persona_id``, calling ``sync`` twice in a row with an unchanged
persona directory is a no-op (the second call refreshes properties
without duplicating rows).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ainemo.core.termbase._ids import (
    DEFAULT_PERSONA_DIR,
    PERSONA_FILE_EXTENSION,
)
from ainemo.core.termbase.base import GlossaryOverride, Persona, Termbase

# Reject anything outside the documented schema so the dropped
# `provider_hints` field surfaces as a clear load error.
_FORBID_EXTRA: Final = ConfigDict(extra="forbid")


class _GlossaryOverrideSchema(BaseModel):
    """YAML schema for one persona ``glossary_overrides`` entry."""

    model_config = _FORBID_EXTRA

    source_term: str
    target_lang: str
    target_term: str


class _PersonaSchema(BaseModel):
    """Pydantic schema for one persona YAML file.

    Field order mirrors the public :class:`Persona` dataclass — four
    mandatory, four optional. The ``Field(default=...)`` pattern keeps
    omitted fields stable rather than raising.
    """

    # The on-disk YAML key `register` maps to the python attribute
    # `register_value` because Pydantic's BaseModel reserves the bare
    # `register` name and emits a UserWarning on shadowing. The
    # `alias` keeps the YAML key human-friendly; `populate_by_name`
    # is on so the schema accepts the field by either name (defensive
    # against a future caller passing kwargs).
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    persona_id: str
    name: str
    # `forbidden_terms` is one of the four mandatory persona fields
    # per the pitch (an *empty* list is fine and explicit; an *omitted*
    # field is a malformed persona). No default — Pydantic raises if
    # the YAML omits it.
    forbidden_terms: tuple[str, ...]
    prompt_addendum: str

    domain_id: str | None = None
    # Constrained to the four documented values per pitch § Open
    # questions Q2: ``formal | casual | neutral | null``. A YAML
    # carrying any other value (e.g. ``pirate``) fails load rather
    # than landing on Persona.register and silently breaking
    # downstream prompt injection / routing.
    register_value: Literal["formal", "casual", "neutral"] | None = Field(
        default=None, alias="register"
    )
    style_guide_url: str | None = None
    glossary_overrides: tuple[_GlossaryOverrideSchema, ...] = Field(default_factory=tuple)

    def to_persona(self) -> Persona:
        return Persona(
            persona_id=self.persona_id,
            name=self.name,
            forbidden_terms=tuple(self.forbidden_terms),
            prompt_addendum=self.prompt_addendum,
            domain_id=self.domain_id,
            register=self.register_value,
            style_guide_url=self.style_guide_url,
            glossary_overrides=tuple(
                GlossaryOverride(
                    source_term=ovr.source_term,
                    target_lang=ovr.target_lang,
                    target_term=ovr.target_term,
                )
                for ovr in self.glossary_overrides
            ),
        )


class PersonaLoadError(RuntimeError):
    """Raised when a persona YAML file is malformed.

    Wraps the underlying Pydantic / YAML error so callers can
    distinguish persona-loader failures from generic IO errors.
    """


def load_personas(persona_dir: Path | None = None) -> tuple[Persona, ...]:
    """Read every ``*.yaml`` file in ``persona_dir``.

    Files are processed in ``persona_id`` ascending order (sorted by
    filename stem for deterministic startup order). The filename
    stem MUST match the file's ``persona_id`` field so a directory
    listing is the same as the persona-id listing — sync errors
    surface as a clear filename mismatch rather than a silent
    rename.

    Raises :class:`PersonaLoadError` when a YAML file fails schema
    validation, with the offending path in the message so the
    operator can find it without grep.
    """
    persona_dir = persona_dir or _default_persona_dir()
    if not persona_dir.is_dir():
        raise PersonaLoadError(f"Persona directory does not exist: {persona_dir}")
    paths = sorted(persona_dir.glob(f"*{PERSONA_FILE_EXTENSION}"))
    personas: list[Persona] = []
    for path in paths:
        personas.append(_load_one(path))
    return tuple(personas)


def sync_personas_into_termbase(tb: Termbase, persona_dir: Path | None = None) -> int:
    """Load ``persona_dir`` and write each persona into ``tb``.

    Returns the number of personas synced. Idempotent on repeat calls
    — :meth:`Termbase.add_persona` upserts on ``persona_id``.
    """
    personas = load_personas(persona_dir)
    for persona in personas:
        tb.add_persona(persona)
    return len(personas)


# --- Internals ---


def _load_one(path: Path) -> Persona:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover — yaml lib error path
        raise PersonaLoadError(f"YAML parse error in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PersonaLoadError(f"Persona file {path} must contain a YAML mapping at the top level")
    try:
        schema = _PersonaSchema.model_validate(raw)
    except ValidationError as exc:
        raise PersonaLoadError(f"Schema error in {path}: {exc}") from exc
    expected_id = path.stem
    if schema.persona_id != expected_id:
        raise PersonaLoadError(
            f"Persona file {path} has persona_id={schema.persona_id!r} "
            f"but the filename stem is {expected_id!r}; the two must match "
            f"so a directory listing is the same as the persona-id listing"
        )
    return schema.to_persona()


def _default_persona_dir() -> Path:
    # Resolve relative to the package install root so the loader
    # works regardless of the caller's working directory. The
    # `DEFAULT_PERSONA_DIR` constant is a project-relative path
    # (``"src/ainemo/personas"``) used in test setups; production
    # code passes an absolute path explicitly.
    return Path(__file__).parent.parent.parent / "personas"


__all__ = [
    "PersonaLoadError",
    "load_personas",
    "sync_personas_into_termbase",
    "DEFAULT_PERSONA_DIR",
]
