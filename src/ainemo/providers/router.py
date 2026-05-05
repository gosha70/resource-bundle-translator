"""Cost/latency-tracked router that fronts every concrete provider.

Per AGENTS.md § Provider Rules: "All LLM provider calls wrapped with
cost + latency tracking. Every call records (provider, model,
input_tokens, output_tokens, latency_ms, cost). No bare provider
invocations." :class:`ProviderRouter` is the single
implementation; the pipeline calls the router, the router calls the
right concrete :class:`~ainemo.providers.base.Provider`, records the
result to :class:`~ainemo.providers._usage_log.UsageLog`, and applies
exponential-backoff retry via
:func:`~ainemo.providers._retry.with_retry`.

The router itself implements the :class:`Provider` Protocol — drop-in
for the cycle-1 pipeline contract — so existing callers don't need to
know there's routing happening underneath.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from dataclasses import replace as _replace
from typing import Callable, ClassVar, Mapping

from ainemo.core.segment import Segment
from ainemo.providers._retry import with_retry
from ainemo.providers._usage_log import UsageLog
from ainemo.providers.base import Provider, ProviderResult

# --- Routing config -------------------------------------------------------


@dataclass(frozen=True)
class RoutingRule:
    """One rule in a :class:`RoutingConfig`. Fields default to ``None``
    meaning "any" — narrower-rule-first matching with a single
    ``default_provider`` fallback.
    """

    provider_id: str

    source_lang: str | None = None
    """BCP-47 source language; ``None`` matches any."""

    target_lang: str | None = None
    """BCP-47 target language; ``None`` matches any."""

    persona: str | None = None
    """Persona name (cycle 3+ termbase work); ``None`` matches any."""

    domain: str | None = None
    """Domain pack id (cycle 4+ work); ``None`` matches any."""

    def matches(
        self,
        *,
        source_lang: str,
        target_lang: str,
        persona: str | None,
        domain: str | None,
    ) -> bool:
        if self.source_lang is not None and self.source_lang != source_lang:
            return False
        if self.target_lang is not None and self.target_lang != target_lang:
            return False
        if self.persona is not None and self.persona != persona:
            return False
        if self.domain is not None and self.domain != domain:
            return False
        return True


@dataclass(frozen=True)
class RoutingConfig:
    """Routing rules + the fallback default provider id.

    Cycle-2 design choice: rules are tried in order; the first match
    wins. ``default_provider`` is used only when no rule matches —
    NOT as a silent fallback when the rule-selected provider has no
    credentials (per /bet open question 7: fail fast on no-creds).
    """

    default_provider: str
    rules: tuple[RoutingRule, ...] = field(default_factory=tuple)


# --- Router exceptions ----------------------------------------------------


class ProviderRouteNotFound(Exception):
    """No rule matched and the configured default is not registered."""


class ProviderUnsupportedPair(Exception):
    """The selected provider returned False from ``supports()`` for the
    given language pair. Per /bet open question 7: fail fast rather
    than silently fall back to a different provider class."""


# --- Router ---------------------------------------------------------------


class ProviderRouter:
    """Drop-in :class:`Provider`-shaped front for a registry of concrete
    providers."""

    # ProviderRouter doesn't have its own provider_id in the same sense
    # as a concrete backend — it's a façade. The pipeline still asks
    # for ``router.provider_id`` though (Provider Protocol requirement),
    # so we expose the *active* selection's id via the result's
    # ``provider`` field of TranslatedSegment after the call. For the
    # ClassVar, route boundaries record under "router".
    provider_id: ClassVar[str] = "router"

    def __init__(
        self,
        providers: Mapping[str, Provider],
        routing_config: RoutingConfig,
        usage_log: UsageLog,
        *,
        retry_exceptions: tuple[type[BaseException], ...] = (),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._providers = dict(providers)
        self._routing_config = routing_config
        self._usage_log = usage_log
        self._retry_exceptions = retry_exceptions
        # `sleep` is injectable so unit tests pass a no-op without
        # monkey-patching `time.sleep` globally. Defaults to the real
        # `time.sleep` for production. Forwarded into `with_retry`
        # below if any retry exceptions are configured.
        self._sleep = sleep

    def translate(
        self,
        segment: Segment,
        target_lang: str,
        *,
        persona: str | None = None,
        domain: str | None = None,
    ) -> ProviderResult:
        """Route ``segment`` to the right provider, time the call,
        record to UsageLog, return the ProviderResult.

        Wrapped with :func:`with_retry` on the configured rate-limit
        exception types. Non-retryable exceptions surface immediately."""
        provider = self._select_provider(
            source_lang=segment.source_lang,
            target_lang=target_lang,
            persona=persona,
            domain=domain,
        )
        if not provider.supports(segment.source_lang, target_lang):
            raise ProviderUnsupportedPair(
                f"Provider {provider.provider_id!r} does not support "
                f"({segment.source_lang!r} → {target_lang!r}). Per the "
                f"cycle-2 fail-fast routing policy, the router does not "
                f"silently fall back to a different provider — fix the "
                f"routing config or pass --provider explicitly."
            )

        def _do_call() -> ProviderResult:
            started = time.perf_counter()
            result = provider.translate(segment, target_lang)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            # PR #7 review #10: split the post-call patch into two
            # explicit defense-in-depth steps so a future bisect or
            # reader sees one concern per branch. Observable output is
            # identical to the pre-split single-conditional form
            # (``test_router.py`` covers both legs); only the number of
            # ProviderResult allocations changes (worst case 2 instead
            # of 1, on the cold path where both fields need patching).

            # Step 1: attribution. Providers MUST self-attribute via
            # ``result.provider``, but a buggy provider returning an
            # empty string would silently misroute TM rows. Fall back
            # to the concrete provider's ``provider_id`` ClassVar when
            # the result didn't set it.
            if not result.provider:
                result = _replace(result, provider=provider.provider_id)

            # Step 2: latency. Providers typically populate
            # ``latency_ms`` themselves; if they didn't (or set 0),
            # substitute the router's wall-clock measurement so cost
            # surveillance never under-reports.
            if result.latency_ms <= 0:
                result = _replace(result, latency_ms=elapsed_ms)

            return result

        if self._retry_exceptions:
            result = with_retry(
                _do_call,
                rate_limit_exceptions=self._retry_exceptions,
                sleep=self._sleep,
            )
        else:
            result = _do_call()

        self._usage_log.record(
            provider=provider.provider_id,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            cost_usd=result.cost_usd,
            source_lang=segment.source_lang,
            target_lang=target_lang,
            segment_fingerprint=segment.fingerprint,
        )
        return result

    def supports(self, source_lang: str, target_lang: str) -> bool:
        """The router supports the pair iff *some* registered provider
        supports it (so the pipeline can ask the router this question
        without knowing the routing rules)."""
        return any(p.supports(source_lang, target_lang) for p in self._providers.values())

    # --- Internals ---

    def _select_provider(
        self,
        *,
        source_lang: str,
        target_lang: str,
        persona: str | None,
        domain: str | None,
    ) -> Provider:
        for rule in self._routing_config.rules:
            if rule.matches(
                source_lang=source_lang,
                target_lang=target_lang,
                persona=persona,
                domain=domain,
            ):
                provider = self._providers.get(rule.provider_id)
                if provider is None:
                    raise ProviderRouteNotFound(
                        f"Routing rule selected provider {rule.provider_id!r} "
                        f"but no provider with that id is registered. "
                        f"Available: {sorted(self._providers)}."
                    )
                return provider
        # No rule matched — fall back to default.
        default = self._providers.get(self._routing_config.default_provider)
        if default is None:
            raise ProviderRouteNotFound(
                f"No routing rule matched ({source_lang!r} → {target_lang!r}) "
                f"and the default provider "
                f"{self._routing_config.default_provider!r} is not registered. "
                f"Available: {sorted(self._providers)}."
            )
        return default


__all__ = [
    "ProviderRouter",
    "ProviderRouteNotFound",
    "ProviderUnsupportedPair",
    "RoutingConfig",
    "RoutingRule",
]
