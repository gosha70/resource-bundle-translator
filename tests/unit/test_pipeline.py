"""Unit tests for :mod:`ainemo.core.pipeline`."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ainemo.core.adapters.java_properties import JavaPropertiesAdapter
from ainemo.core.pipeline import TranslationPipeline
from ainemo.core.segment import (
    Segment,
)
from ainemo.core.tm.sqlite import SqliteTranslationMemory
from ainemo.core.validators.placeholder import PlaceholderParityValidator
from ainemo.providers.base import Provider, ProviderResult

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"
_LANG_FR = "fr-FR"

# Test-stub model id. Concrete providers use real ids from
# `ainemo.providers._ids`; stubs use this so tests don't accidentally
# pass through cycle-2 router logic that branches on provider_id.
_FAKE_MODEL = "test-fake-1.0"


class _FakeProvider:
    """Stub provider that prefixes the source text with the target lang."""

    provider_id: ClassVar[str] = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        self.calls.append((segment.source_text, target_lang))
        return ProviderResult(
            target_text=f"[{target_lang}] {segment.source_text}",
            provider=self.provider_id,
            model=_FAKE_MODEL,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


class _DroppingProvider:
    """Provider that drops placeholders — used to test that validators
    block writes."""

    provider_id: ClassVar[str] = "dropping"

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        out: list[str] = []
        in_placeholder = False
        for ch in segment.source_text:
            if ch == "{":
                in_placeholder = True
                continue
            if ch == "}":
                in_placeholder = False
                continue
            if not in_placeholder:
                out.append(ch)
        return ProviderResult(
            target_text="".join(out).strip(),
            provider=self.provider_id,
            model=_FAKE_MODEL,
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


def _write_props(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


# --- Provider Protocol conformance ----------------------------------------


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(_FakeProvider(), Provider)


# --- End-to-end translation -----------------------------------------------


def test_translates_simple_bundle(tmp_path: Path) -> None:
    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "greeting=Hello\nfarewell=Goodbye\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    provider = _FakeProvider()
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=provider,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )

    result = pipeline.translate_file(src, tmp_path / "out")

    assert result.tm_hit_count == 0
    assert result.provider_call_count == 2
    assert result.error_count == 0
    de_path = result.target_lang_paths[_LANG_DE]
    written = de_path.read_text(encoding="utf-8")
    assert "[de-DE] Hello" in written
    assert "[de-DE] Goodbye" in written
    tm.close()


def test_second_run_hits_tm_for_unchanged_segments(tmp_path: Path) -> None:
    """Re-running on the same input must not call the provider again
    for segments already in the TM."""
    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "greeting=Hello\n")

    tm_path = tmp_path / "tm.sqlite"
    tm = SqliteTranslationMemory(tm_path)
    provider = _FakeProvider()
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=provider,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )

    pipeline.translate_file(src, tmp_path / "out")
    assert provider.calls == [("Hello", _LANG_DE)]
    tm.close()

    # Re-open with a fresh provider
    tm2 = SqliteTranslationMemory(tm_path)
    provider2 = _FakeProvider()
    pipeline2 = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm2,
        provider=provider2,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )
    result2 = pipeline2.translate_file(src, tmp_path / "out")

    assert provider2.calls == []
    assert result2.tm_hit_count == 1
    assert result2.provider_call_count == 0
    tm2.close()


def test_multi_target_lang(tmp_path: Path) -> None:
    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "greeting=Hello\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=_FakeProvider(),
        validators=(),
        target_langs=(_LANG_DE, _LANG_FR),
        source_lang=_LANG_EN_US,
    )

    result = pipeline.translate_file(src, tmp_path / "out")
    assert set(result.target_lang_paths.keys()) == {_LANG_DE, _LANG_FR}
    de_path = result.target_lang_paths[_LANG_DE]
    fr_path = result.target_lang_paths[_LANG_FR]
    assert "[de-DE]" in de_path.read_text(encoding="utf-8")
    assert "[fr-FR]" in fr_path.read_text(encoding="utf-8")
    tm.close()


def test_validator_error_blocks_write(tmp_path: Path) -> None:
    """When a validator returns an error-severity violation, the
    translation is not stored in the TM and not written to the output
    file. The outcome captures the violations for review."""
    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "welcome=Hello {name}!\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=_DroppingProvider(),  # drops {name}!
        validators=(PlaceholderParityValidator(),),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )

    result = pipeline.translate_file(src, tmp_path / "out")

    assert result.error_count == 1
    assert result.outcomes[0].translated is None
    assert any(v.validator == "placeholder-parity" for v in result.outcomes[0].violations)
    # TM was not populated with the broken translation
    assert tm.stats().translation_count == 0
    tm.close()


def test_strict_mode_escalates_warnings(tmp_path: Path) -> None:
    """In strict mode, warning-severity violations also block the
    write. Useful for CI runs that want zero-warning builds."""
    from ainemo.core.validators.length import (
        METADATA_KEY_MAX_LENGTH,
        LengthBudgetValidator,
    )

    src = tmp_path / "messages_en_US.properties"
    # The Java properties adapter doesn't read max_length yet, so we
    # set it via a custom Segment by going around the adapter for this
    # one test. Cycle-1 length-budget testing happens at the adapter
    # boundary; this test exercises the pipeline's strict-mode logic.
    _write_props(src, "k=Hi\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")

    class _MetadataInjectingAdapter:
        format_id: ClassVar[str] = "test-adapter"
        file_extensions: ClassVar[tuple[str, ...]] = (".properties",)

        def parse(self, path: Path, source_lang: str) -> tuple[Segment, ...]:
            return (
                Segment(
                    key="k",
                    source_text="Hi",
                    source_lang=source_lang,
                    metadata={METADATA_KEY_MAX_LENGTH: "5"},
                ),
            )

        def serialize(
            self,
            path: Path,
            translated: tuple,  # type: ignore[type-arg]
            target_lang: str,
        ) -> None:
            path.write_text("ok\n", encoding="utf-8")

    pipeline = TranslationPipeline(
        adapter=_MetadataInjectingAdapter(),
        tm=tm,
        provider=_FakeProvider(),  # produces "[de-DE] Hi" — 9 chars > 5
        validators=(LengthBudgetValidator(),),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
        strict=True,
    )

    result = pipeline.translate_file(src, tmp_path / "out")

    # The length-budget violation is normally a warning; strict mode
    # escalates it to blocking.
    assert result.error_count == 0
    assert result.warning_count == 1
    assert result.outcomes[0].translated is None  # blocked under strict
    tm.close()


def test_output_path_strips_locale_token(tmp_path: Path) -> None:
    """`messages_en_US.properties` + target `de` should produce
    `messages_de.properties`, not `messages_en_US_de.properties`."""
    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "k=v\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=_FakeProvider(),
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )

    result = pipeline.translate_file(src, tmp_path / "out")
    de_path = result.target_lang_paths[_LANG_DE]
    assert de_path.name == "messages_de_DE.properties"
    tm.close()


def test_pipeline_with_router_attributes_tm_to_concrete_backend(tmp_path: Path) -> None:
    """Cycle-2 contract pin: when the pipeline's `provider` is a
    ProviderRouter (the cycle-2 normal case), TM rows must be keyed
    under the *concrete* backend's id (e.g. ``"openai"``), NOT under
    the router's façade id (``"router"``). Otherwise a later
    ``lookup(provider="openai", model=...)`` would miss the row the
    router just wrote."""
    from ainemo.providers._usage_log import UsageLog
    from ainemo.providers.router import ProviderRouter, RoutingConfig

    src = tmp_path / "messages_en_US.properties"
    src.write_text("greeting=Hello\n", encoding="utf-8")

    backend = _FakeProvider()  # provider_id = "fake"
    router = ProviderRouter(
        providers={"fake": backend},
        routing_config=RoutingConfig(default_provider="fake"),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )
    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=router,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )
    pipeline.translate_file(src, tmp_path / "out")

    # The TM row was stored under "fake" (the backend), not "router"
    # (the façade) — verified by looking up with a provider filter.
    parsed = JavaPropertiesAdapter().parse(src, _LANG_EN_US)
    seg = parsed[0]
    hit = tm.lookup(seg, _LANG_DE, provider="fake")
    assert hit is not None
    assert hit.translated.provider == "fake"
    assert hit.translated.model == "test-fake-1.0"

    # And looking up under "router" would miss — that's the bug this
    # test pins.
    miss = tm.lookup(seg, _LANG_DE, provider="router")
    assert miss is None
    tm.close()


def test_warnings_count_in_result(tmp_path: Path) -> None:
    """Warning-severity violations show up in result.warning_count
    but don't block writes."""
    from ainemo.core.validators.length import LengthBudgetValidator

    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "k=Hi\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=_FakeProvider(),
        validators=(LengthBudgetValidator(),),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )

    result = pipeline.translate_file(src, tmp_path / "out")
    # No max_length metadata, so length validator no-ops
    assert result.warning_count == 0
    assert result.error_count == 0
    tm.close()


# --- expected_provider TM scoping (P1 fix from PR #7 review) --------------


class _SecondProvider:
    """Second stub backend with a different provider_id, so we can pin
    the cross-provider TM scoping behavior."""

    provider_id: ClassVar[str] = "other"

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult:
        return ProviderResult(
            target_text=f"[OTHER:{target_lang}] {segment.source_text}",
            provider=self.provider_id,
            model="other-model-2.0",
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


def test_expected_provider_scopes_tm_lookup_to_its_rows(tmp_path: Path) -> None:
    """A second run with ``expected_provider="other"`` must not be
    served from rows the first run wrote under ``"fake"``. Without
    the scoping the second run would reuse the first row and never
    call the second provider — silently bypassing ``--provider``."""
    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "greeting=Hello\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")

    # Run 1: provider "fake", no expected_provider (cycle-1 default).
    fake = _FakeProvider()
    TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=fake,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    ).translate_file(src, tmp_path / "out1")
    assert len(fake.calls) == 1  # Provider called once.

    # Run 2: provider "other", expected_provider="other" — the cached
    # "fake" row must be ignored, and the "other" provider must be
    # called.
    other = _SecondProvider()
    result = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=other,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
        expected_provider="other",
    ).translate_file(src, tmp_path / "out2")
    assert result.tm_hit_count == 0
    assert result.provider_call_count == 1
    written = result.target_lang_paths[_LANG_DE].read_text(encoding="utf-8")
    assert "[OTHER:de-DE] Hello" in written
    assert "[de-DE] Hello" not in written

    # Run 3: provider "other" again with expected_provider="other".
    # Now there IS an "other" row from run 2, so this run should hit
    # TM and skip the provider.
    other2 = _SecondProvider()
    result3 = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=other2,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
        expected_provider="other",
    ).translate_file(src, tmp_path / "out3")
    assert result3.tm_hit_count == 1
    assert result3.provider_call_count == 0
    tm.close()


def test_expected_provider_none_preserves_cycle1_any_match_semantics(
    tmp_path: Path,
) -> None:
    """Callers that don't set expected_provider keep cycle-1 behavior:
    any cached row for the segment+target_lang satisfies the lookup,
    regardless of which backend produced it. Pinning this protects the
    cycle-1 e2e tests and the bare-provider (no router) callers."""
    src = tmp_path / "messages_en_US.properties"
    _write_props(src, "greeting=Hello\n")

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    fake = _FakeProvider()
    TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=fake,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    ).translate_file(src, tmp_path / "out1")

    other = _SecondProvider()
    result = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=other,
        validators=(),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
        # expected_provider not set — cycle-1 semantics.
    ).translate_file(src, tmp_path / "out2")
    # The cached "fake" row satisfies the lookup, so the second
    # provider is never called.
    assert result.tm_hit_count == 1
    assert result.provider_call_count == 0
    tm.close()
