"""End-to-end pipeline tests on representative bundle fixtures.

Cycle-1 acceptance criterion (per
``specs/pitches/0001-foundation/pitch.md`` § Test strategy):
**"Cache-hit rate on second run of identical input: must be ≥99%."**

The fixtures below are scaled-down approximations of real
software-bundle shapes (Spring Boot resource bundles, i18next
JSON files). For the cycle-1 acceptance bar a small representative
sample is sufficient; cycle-1's benchmark harness
(``tests/benchmarks/``) measures throughput on larger corpora.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from ainemo.core.adapters.i18next_json import I18NextJsonAdapter
from ainemo.core.adapters.java_properties import JavaPropertiesAdapter
from ainemo.core.pipeline import TranslationPipeline
from ainemo.core.segment import Segment
from ainemo.core.tm.sqlite import SqliteTranslationMemory
from ainemo.core.validators.icu import IcuSyntaxValidator
from ainemo.core.validators.placeholder import PlaceholderParityValidator
from ainemo.providers.base import ProviderResult

_LANG_EN_US = "en-US"
_LANG_DE = "de-DE"
_LANG_FR = "fr-FR"
_CACHE_HIT_RATE_TARGET = 0.99


class _PrefixingProvider:
    provider_id: ClassVar[str] = "prefixing"

    def translate(
        self, segment: Segment, target_lang: str, *, system_prompt_addendum: str | None = None
    ) -> ProviderResult:
        return ProviderResult(
            target_text=f"[{target_lang}] {segment.source_text}",
            provider=self.provider_id,
            model="test-prefixing-1.0",
        )

    def supports(self, source_lang: str, target_lang: str) -> bool:
        return True


def test_e2e_properties_bundle_cache_hit_rate(tmp_path: Path) -> None:
    """First run forwards every segment to the provider; second run
    must hit TM at ≥99% (the pitch's cycle-1 acceptance bar)."""
    src = tmp_path / "messages_en_US.properties"
    body = "\n".join(
        [
            "# Greetings",
            "greeting=Hello, {name}!",
            "farewell=Goodbye, {name}.",
            "items.zero=No items",
            "items.one=One item",
            "items.many=Many items: {count, plural, one {1 item} other {# items}}",
            "button.submit=Submit",
            "button.cancel=Cancel",
            "error.required=This field is required.",
            "error.email_format=Please enter a valid email address.",
            "welcome=Welcome to AI-NEMO!",
        ]
    )
    src.write_text(body + "\n", encoding="utf-8")
    tm_path = tmp_path / "tm.sqlite"

    def _build_pipeline() -> TranslationPipeline:
        return TranslationPipeline(
            adapter=JavaPropertiesAdapter(),
            tm=SqliteTranslationMemory(tm_path),
            provider=_PrefixingProvider(),
            validators=(PlaceholderParityValidator(), IcuSyntaxValidator()),
            target_langs=(_LANG_DE, _LANG_FR),
            source_lang=_LANG_EN_US,
        )

    # First run — every segment goes to the provider.
    first = _build_pipeline()
    first_result = first.translate_file(src, tmp_path / "out")
    total_segments = first_result.tm_hit_count + first_result.provider_call_count
    assert first_result.tm_hit_count == 0
    assert first_result.provider_call_count == total_segments
    assert first_result.error_count == 0

    # Second run — every segment should hit the TM.
    second = _build_pipeline()
    second_result = second.translate_file(src, tmp_path / "out")
    second_total = second_result.tm_hit_count + second_result.provider_call_count
    cache_hit_rate = second_result.tm_hit_count / second_total
    assert cache_hit_rate >= _CACHE_HIT_RATE_TARGET, (
        f"Cycle-1 acceptance bar: cache hit rate ≥{_CACHE_HIT_RATE_TARGET}; "
        f"got {cache_hit_rate:.4f}"
    )


def test_e2e_i18next_bundle_cache_hit_rate(tmp_path: Path) -> None:
    src = tmp_path / "en.json"
    payload = {
        "common": {
            "yes": "Yes",
            "no": "No",
            "cancel": "Cancel",
        },
        "login": {
            "title": "Sign in",
            "username": "Username",
            "password": "Password",
            "error": {
                "invalid": "Invalid credentials",
                "rate_limited": "Too many attempts; try again in {minutes} minutes.",
            },
        },
        "profile": {
            "greeting": "Hello, {name}!",
            "items": "{count, plural, one {1 unread message} other {# unread messages}}",
        },
    }
    src.write_text(json.dumps(payload), encoding="utf-8")
    tm_path = tmp_path / "tm.sqlite"

    def _build_pipeline() -> TranslationPipeline:
        return TranslationPipeline(
            adapter=I18NextJsonAdapter(),
            tm=SqliteTranslationMemory(tm_path),
            provider=_PrefixingProvider(),
            validators=(PlaceholderParityValidator(), IcuSyntaxValidator()),
            target_langs=(_LANG_DE,),
            source_lang=_LANG_EN_US,
        )

    first = _build_pipeline().translate_file(src, tmp_path / "out")
    assert first.error_count == 0
    second = _build_pipeline().translate_file(src, tmp_path / "out")
    second_total = second.tm_hit_count + second.provider_call_count
    cache_hit_rate = second.tm_hit_count / second_total
    assert cache_hit_rate >= _CACHE_HIT_RATE_TARGET


def test_e2e_validator_pass_rate(tmp_path: Path) -> None:
    """Validator pass rate on the cycle-1 fixture corpus: every
    placeholder is preserved by the prefixing provider, so all
    segments validate clean."""
    src = tmp_path / "messages_en_US.properties"
    src.write_text(
        "k1=Hello, {name}!\nk2={count, plural, one {1 thing} other {# things}}\nk3=Plain text\n",
        encoding="utf-8",
    )

    tm = SqliteTranslationMemory(tmp_path / "tm.sqlite")
    pipeline = TranslationPipeline(
        adapter=JavaPropertiesAdapter(),
        tm=tm,
        provider=_PrefixingProvider(),
        validators=(PlaceholderParityValidator(), IcuSyntaxValidator()),
        target_langs=(_LANG_DE,),
        source_lang=_LANG_EN_US,
    )
    result = pipeline.translate_file(src, tmp_path / "out")
    assert result.error_count == 0
    assert result.warning_count == 0
    tm.close()
