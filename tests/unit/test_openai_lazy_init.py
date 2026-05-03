"""Regression test: importing OpenAI provider must not require API key.

The pre-fix ``open_ai_model.py`` had ``client = OpenAI()`` at module
top level. The OpenAI SDK constructor raises when ``OPENAI_API_KEY`` is
unset, so *any* import chain that touched this module (notably:
``ainemo.cli.resource_bundle_generator`` -> ``ModelType`` ->
``open_ai_model``) failed at module-import time without credentials —
which broke pytest collection in CI.

The cycle-0 audit-bug fix moves SDK client construction into
``OpenAITranslatorModel.__init__``. Importing the module is free; the
client is built only when the user explicitly instantiates the OpenAI
provider, at which point the existing API-key check already gates the
construction.

These tests pin the contract:

1. The OpenAI provider module imports cleanly with no API key.
2. The full transitive import chain imports cleanly with no API key.
3. Instantiating ``OpenAITranslatorModel`` without a key still raises —
   the fix does not relax authentication; it only defers it.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

# Modules to cycle through `sys.modules` for a fresh import. Listed as a
# constant so the test names and the cleanup stay in lockstep.
_LAZY_INIT_MODULE: str = "ainemo.providers.openai.open_ai_model"
_MODEL_TYPES_MODULE: str = "ainemo.providers.model_types"
_CLI_GENERATOR_MODULE: str = "ainemo.cli.resource_bundle_generator"
_API_KEY_ENV_VAR: str = "OPENAI_API_KEY"


def _reimport_without_api_key(monkeypatch: pytest.MonkeyPatch, module_name: str) -> ModuleType:
    """Force-reimport ``module_name`` with the API key env var unset."""
    monkeypatch.delenv(_API_KEY_ENV_VAR, raising=False)
    # Drop the target module *and* its dependency on the OpenAI provider
    # so the reimport actually re-runs the module body.
    for cached in (_LAZY_INIT_MODULE, _MODEL_TYPES_MODULE, module_name):
        sys.modules.pop(cached, None)
    return importlib.import_module(module_name)


def test_openai_provider_module_imports_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("openai")  # CI installs it; locally optional.
    module = _reimport_without_api_key(monkeypatch, _LAZY_INIT_MODULE)
    assert hasattr(module, "OpenAITranslatorModel")
    assert hasattr(module, "MissingEnvironmentVariableError")


def test_model_types_imports_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The full provider-registry module — used by every CLI entry —
    must import without OpenAI credentials."""
    pytest.importorskip("openai")
    module = _reimport_without_api_key(monkeypatch, _MODEL_TYPES_MODULE)
    assert hasattr(module, "ModelType")


def test_cli_generator_imports_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI test collection path — what the reviewer reproduced —
    must succeed without an API key."""
    pytest.importorskip("openai")
    module = _reimport_without_api_key(monkeypatch, _CLI_GENERATOR_MODULE)
    assert hasattr(module, "load_resource_bundle")


def test_openai_translator_init_still_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lazy client init does not relax auth: instantiating the provider
    without the env var must still raise. Failing fast at construction
    time is a feature; the bug was only that *importing* the module did
    the same."""
    pytest.importorskip("openai")
    monkeypatch.delenv(_API_KEY_ENV_VAR, raising=False)

    from ainemo._legacy.languages import Language
    from ainemo.providers.openai.open_ai_model import (
        MissingEnvironmentVariableError,
        OpenAITranslatorModel,
    )

    with pytest.raises(MissingEnvironmentVariableError):
        OpenAITranslatorModel(
            source_lang=Language.EN_US,
            target_langs=[Language.DE],
        )
