# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Concept-oriented termbase.

Cycle-3 surface (per ``specs/pitches/0003-kuzu-termbase/pitch.md``).
The termbase is the fifth port of the same shape as cycle-1's
:class:`~ainemo.core.tm.base.TranslationMemory`,
:class:`~ainemo.core.adapters.base.BundleAdapter`,
:class:`~ainemo.core.validators.base.Validator`, and cycle-2's
:class:`~ainemo.providers.base.Provider`: ``core/`` declares the
Protocol + entity dataclasses; concrete backends import their drivers.

S1 ships:
- :class:`ainemo.core.termbase.base.Termbase` Protocol + frozen
  entity dataclasses (``Concept``, ``Term``, ``Domain``, ``Persona``,
  ``ConceptHit``, ``TermbaseStats``, ``GlossaryOverride``)
- :class:`ainemo.core.termbase.kuzu.store.KuzuTermbase` — the only
  concrete implementation, Kuzu-backed, schema-bootstrap idempotent.

S2 (TBX import), S4 (persona YAML loader), S5 (auto-promotion +
``nemo termbase`` CLI), and S6 (pipeline integration) consume this
surface; they do not reach into Kuzu directly.
"""
