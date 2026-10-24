"""Tests for the shared HTTP clients and retry policy.

These cover the pure retry/backoff/timeout helpers with fakes; the pooled
client constructors are exercised elsewhere via live-loopback smoke tests.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from sovereign_code.http import RETRY_STATUS, _is_transient, _timeout, retry, retry_async


def _sleep(calls: list[float]) -> None:
    def sleep(seconds: float) -> None:
        calls.append(seconds)

    return sleep


def test_retry_succeeds_on_the_first_try() -> None:
    assert retry(lambda: "ok") == "ok"


def test_retry_recovers_from_a_transient_error() -> None:
    attempts = 0

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("resetting")
        return "ok"

    assert retry(flaky, attempts=3, sleep=_sleep([])) == "ok"
    assert attempts == 3


def test_retry_bounds_the_attempts_and_reraises() -> None:
    def always() -> str:
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        retry(always, attempts=2, sleep=_sleep([]))


def test_retry_backs_off_exponentially(monkeypatch) -> None:
    """Two failures -> two sleeps, each doubling the previous base.

    Jitter spans [0.5, 1.5), so consecutive sleeps overlap by design; pinning
    the jitter makes the schedule exact instead of accidentally flaky.
    """
    from sovereign_code import http

    monkeypatch.setattr(http.random, "random", lambda: 0.0)
    sleeps: list[float] = []

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("slow")
        return "ok"

    calls = 0
    assert retry(flaky, attempts=3, backoff=0.5, sleep=_sleep(sleeps)) == "ok"
    assert sleeps == [0.25, 0.5]


def test_retry_reraises_non_transient_immediately() -> None:
    def bad() -> str:
        raise ValueError("not transient")

    sleeps: list[float] = []
    with pytest.raises(ValueError):
        retry(bad, attempts=3, sleep=_sleep(sleeps))
    assert sleeps == []  # no backoff on a non-transient failure


def test_retry_honours_a_custom_predicate() -> None:
    def custom(exc: Exception) -> bool:
        return isinstance(exc, ValueError)

    attempts = 0

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise ValueError("retry me")
        return "ok"

    assert retry(flaky, attempts=2, retry_on=custom, sleep=_sleep([])) == "ok"


def test_retry_async_awaits_a_coroutine() -> None:
    async def ok() -> str:
        return "async-ok"

    assert asyncio.run(retry_async(ok)) == "async-ok"


def test_retry_async_recovers_from_a_transient_error() -> None:
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectTimeout("slow")
        return "ok"

    assert asyncio.run(retry_async(flaky, attempts=3)) == "ok"


def test_is_transient_classifies_http_statuses() -> None:
    for code in RETRY_STATUS:
        request = httpx.Request("GET", "http://x")
        resp = httpx.Response(code, request=request)
        assert _is_transient(httpx.HTTPStatusError("e", request=request, response=resp), None)
    # A 400 is not transient.
    request = httpx.Request("GET", "http://x")
    resp = httpx.Response(400, request=request)
    assert not _is_transient(httpx.HTTPStatusError("e", request=request, response=resp), None)


def test_is_transient_classifies_connection_errors() -> None:
    assert _is_transient(httpx.ConnectError("x"), None)
    assert _is_transient(httpx.ReadTimeout("x"), None)
    assert not _is_transient(ValueError("x"), None)


def test_timeout_uses_a_long_total_with_a_short_read_when_streaming() -> None:
    t = _timeout(3600.0, 3.0, 180.0)
    assert t.connect == 3.0
    assert t.read == 180.0
    assert t.write is not None  # default write budget is kept
    assert t.pool > 0


def test_timeout_omits_read_when_not_streaming() -> None:
    t = _timeout(30.0, 3.0, None)
    assert t.read == 30.0  # falls back to the total budget
