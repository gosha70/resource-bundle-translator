"""Unit tests for :mod:`ainemo.providers._retry`."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ainemo.providers._retry import (
    BACKOFF_BASE_SECONDS,
    MAX_RETRY_ATTEMPTS,
    with_retry,
)


class _RateLimitError(Exception):
    """Stand-in for an SDK's rate-limit exception."""


class _AuthError(Exception):
    """Stand-in for an SDK's auth-failure exception (NOT retryable)."""


@dataclass
class _CountingCallable:
    """Callable that raises ``_RateLimitError`` for the first
    ``failures`` calls, then returns ``"ok"``. ``calls`` exposes the
    running count for test assertions."""

    failures: int
    calls: int = field(default=0)

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise _RateLimitError("simulated rate limit")
        return "ok"


def _make_succeed_after(failures: int) -> _CountingCallable:
    return _CountingCallable(failures=failures)


def _no_sleep(seconds: float) -> None:
    pass


def test_succeeds_on_first_attempt_no_retry() -> None:
    fn = _make_succeed_after(0)
    result = with_retry(fn, rate_limit_exceptions=(_RateLimitError,), sleep=_no_sleep)
    assert result == "ok"
    assert fn.calls == 1


def test_retries_then_succeeds() -> None:
    fn = _make_succeed_after(2)
    result = with_retry(fn, rate_limit_exceptions=(_RateLimitError,), sleep=_no_sleep)
    assert result == "ok"
    assert fn.calls == 3  # initial + 2 retries


def test_exhausts_retries_and_raises() -> None:
    """When every attempt fails, the last exception propagates."""
    fn = _make_succeed_after(MAX_RETRY_ATTEMPTS + 1)
    with pytest.raises(_RateLimitError):
        with_retry(fn, rate_limit_exceptions=(_RateLimitError,), sleep=_no_sleep)
    assert fn.calls == MAX_RETRY_ATTEMPTS


def test_non_retryable_exception_raises_immediately() -> None:
    """A malformed-request / auth / corrupt-segment exception should
    surface on attempt 1, not be hidden behind 7 seconds of retries."""
    counter = {"calls": 0}

    def fn() -> str:
        counter["calls"] += 1
        raise _AuthError("invalid api key")

    with pytest.raises(_AuthError):
        with_retry(fn, rate_limit_exceptions=(_RateLimitError,), sleep=_no_sleep)
    assert counter["calls"] == 1


def test_uses_exponential_backoff() -> None:
    """Successive sleeps follow `base * 2^(attempt - 1)`."""
    sleeps: list[float] = []
    fn = _make_succeed_after(MAX_RETRY_ATTEMPTS)

    with pytest.raises(_RateLimitError):
        with_retry(
            fn,
            rate_limit_exceptions=(_RateLimitError,),
            sleep=sleeps.append,
        )
    # MAX_RETRY_ATTEMPTS = 3 → 2 sleeps between 3 attempts.
    assert sleeps == [
        BACKOFF_BASE_SECONDS,
        BACKOFF_BASE_SECONDS * 2,
    ]


def test_custom_max_attempts() -> None:
    """`max_attempts=5` overrides the default 3. With 5 simulated
    failures, all 5 attempts fail and the function gives up."""
    fn = _make_succeed_after(5)
    with pytest.raises(_RateLimitError):
        with_retry(
            fn,
            rate_limit_exceptions=(_RateLimitError,),
            max_attempts=5,
            sleep=_no_sleep,
        )
    assert fn.calls == 5


def test_custom_backoff_base() -> None:
    sleeps: list[float] = []
    fn = _make_succeed_after(2)
    with_retry(
        fn,
        rate_limit_exceptions=(_RateLimitError,),
        backoff_base_seconds=0.5,
        sleep=sleeps.append,
    )
    assert sleeps == [0.5, 1.0]


def test_zero_max_attempts_is_rejected() -> None:
    with pytest.raises(ValueError):
        with_retry(
            lambda: "x",
            rate_limit_exceptions=(_RateLimitError,),
            max_attempts=0,
        )


def test_multiple_exception_types_all_trigger_retry() -> None:
    """The allow-list takes a tuple; matching ANY type retries."""

    class _OtherTransient(Exception):
        pass

    counter = {"calls": 0}

    def fn() -> str:
        counter["calls"] += 1
        if counter["calls"] == 1:
            raise _RateLimitError("first")
        if counter["calls"] == 2:
            raise _OtherTransient("second")
        return "ok"

    result = with_retry(
        fn,
        rate_limit_exceptions=(_RateLimitError, _OtherTransient),
        sleep=_no_sleep,
    )
    assert result == "ok"
    assert counter["calls"] == 3
