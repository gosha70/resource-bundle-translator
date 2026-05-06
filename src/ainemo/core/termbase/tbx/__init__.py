# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
"""TBX 3.0 (ISO 30042) interop.

Cycle-3 S2 ships the importer; S3 will add the exporter and the
Weblate round-trip benchmark. The importer reads the *documented
subset* — the elements Weblate's "Export glossary as TBX" flow
emits in practice. Anything outside that subset is recorded in
:class:`~ainemo.core.termbase.tbx.importer.TbxImportReport.skipped_unsupported`
so the cycle-3 retro can survey real-world exports and decide which
elements to promote to the supported set in cooldown.
"""

from ainemo.core.termbase.tbx.exporter import TbxExporter
from ainemo.core.termbase.tbx.importer import TbxImporter, TbxImportReport

__all__ = ["TbxExporter", "TbxImporter", "TbxImportReport"]
