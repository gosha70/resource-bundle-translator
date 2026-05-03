"""Translation memory.

The TM is the first stop in the translation pipeline (per AGENTS.md
§ Translation Memory Rules: "Translation memory is the first stop, not
the last"). Every Segment is looked up against the TM before any
provider call. Exact matches are cheap and zero-cost; fuzzy matches
return a similar segment plus a similarity score so callers can decide
whether to accept the cached translation or forward to a provider.

Cycle-1 ships:
- :class:`ainemo.core.tm.base.TranslationMemory` Protocol
- :class:`ainemo.core.tm.base.TmHit` / :class:`ainemo.core.tm.base.TmStats`
- :class:`ainemo.core.tm.sqlite.SqliteTranslationMemory` — the default
  backend with file-based SQLite + optional MiniLM embeddings for
  fuzzy lookup.
"""
