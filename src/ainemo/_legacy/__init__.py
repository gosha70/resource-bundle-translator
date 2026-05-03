"""DEPRECATED — pre-cycle-1 data modules.

These modules (`languages`, `translation`, `translation_request`,
`translation_service`) carry the original prototype's data model and
orchestration forward into the AI-NEMO layout *unchanged in behavior*.
Cycle 1 replaces them with `ainemo.core.segment`, `ainemo.core.pipeline`,
and friends; this `_legacy` subpackage and its top-level deprecation
shims (at the repo root) **delete at the end of cycle 1**.

Do not import from here in new code.
"""
