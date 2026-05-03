"""Exponential-backoff retry wrapper for provider calls.

Per AGENTS.md § Provider Rules: "Retry policy: exponential backoff on
rate limits, max 3 attempts. Failures surface to the caller — never
silently swallow." This module is the single implementation; every
provider's translate path goes through :func:`with_retry`, parameterized
with the provider-SDK's specific rate-limit exception types.

Sleep is injectable so unit tests don't actually wait. The default is
``time.sleep``; tests pass a no-op or a mock recorder.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Final, TypeVar

logger = logging.getLogger(__name__)

# --- Module constants (no magic strings; AGENTS.md § Prohibited Patterns) ---

# Default max attempts (initial + retries). Per AGENTS.md § Provider
# Rules. Three is enough to ride out the typical rate-limit blip
# (1s + 2s + 4s = 7s) without delaying a failing call too long.
MAX_RETRY_ATTEMPTS: Final = 3

# Backoff base in seconds. Each attempt waits
# ``base * 2 ** (attempt - 1)`` seconds, so attempt 1 waits 1s,
# attempt 2 waits 2s, attempt 3 waits 4s.
BACKOFF_BASE_SECONDS: Final = 1.0

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    *,
    rate_limit_exceptions: tuple[type[BaseException], ...],
    max_attempts: int = MAX_RETRY_ATTEMPTS,
    backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``fn`` with exponential-backoff retry on the listed
    exception types.

    Returns ``fn``'s result on success. Raises the underlying exception
    if all attempts fail; raises *immediately* (no retry) if ``fn``
    raises any exception NOT in ``rate_limit_exceptions``. The
    fail-fast-on-other-exceptions behavior is intentional: a malformed
    request, an authentication error, or a corrupt-segment bug should
    surface on attempt 1, not be hidden behind 7 seconds of retries.

    ``sleep`` is injectable so unit tests can pass a no-op without
    monkey-patching ``time.sleep`` globally.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1; got {max_attempts}")
    last_exception: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except rate_limit_exceptions as exc:
            last_exception = exc
            if attempt == max_attempts:
                logger.warning(
                    "Provider call exhausted retry budget (%d attempts); raising %s.",
                    max_attempts,
                    type(exc).__name__,
                )
                raise
            wait_seconds = backoff_base_seconds * (2 ** (attempt - 1))
            logger.info(
                "Provider call hit rate limit on attempt %d/%d (%s); backing off %.1fs.",
                attempt,
                max_attempts,
                type(exc).__name__,
                wait_seconds,
            )
            sleep(wait_seconds)
    # Unreachable in practice (the loop either returns or raises),
    # but mypy strict needs the explicit raise.
    assert last_exception is not None
    raise last_exception


__all__ = [
    "MAX_RETRY_ATTEMPTS",
    "BACKOFF_BASE_SECONDS",
    "with_retry",
]
