# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Kuzu-backed :class:`~ainemo.core.termbase.base.Termbase`.

The only concrete cycle-3 backend. Imports the ``kuzu`` driver here;
the Protocol in :mod:`ainemo.core.termbase.base` stays driver-free so
cycle-4 domain packs and the cycle-5 reviewer UI can consume the
Termbase surface without taking on a graph-DB dependency.

Mirrors the cycle-1 ``ainemo.core.tm.sqlite`` placement convention:
concrete backend in its own subpackage that imports its driver;
Protocol stays backend-free.
"""

from ainemo.core.termbase.kuzu.store import KuzuTermbase

__all__ = ["KuzuTermbase"]
