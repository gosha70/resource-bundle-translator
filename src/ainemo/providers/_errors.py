# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""Provider-layer exception types.

These live in a dedicated module so callers can import only the
exception class without pulling in the full router or usage-log
machinery.  All provider errors are subclasses of standard built-in
exception types so they work in ``except`` clauses without importing
this module — but explicit imports are preferred per the no-wildcard
rule.
"""

from __future__ import annotations


class UnknownProviderError(ValueError):
    """Raised by :meth:`~ainemo.providers.router.ProviderRouter.translate_with`
    when ``provider_id`` is not registered in the router.

    Subclasses :exc:`ValueError` (plain Python; no dependency on Flask
    or any other framework) so callers can catch it as a
    ``ValueError`` without importing this module.
    """


__all__ = ["UnknownProviderError"]
