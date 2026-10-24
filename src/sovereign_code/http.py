"""Shared HTTP clients and retry policy.

Every module in this project talks to a service on the same machine: Ollama
on 11434, the tier gateway on 4010, the Anthropic bridge on 4001, the LiteLLM
gateway on 4000. Almost none of them are the public internet.

Two things were wrong with how those calls were made:

* A new ``httpx`` client per request. Each one opened a fresh connection
  pool and a fresh TCP handshake, so a dashboard that refreshes every 2.5
  seconds paid thousands of handshakes an hour to ask the same loopback
  service three questions.
* No retries. A service that is restarting, or a provider that answers 429,
  failed the whole operation on a single transient error.

The clients here are pooled and reused, and :func:`retry` gives the calls
that deserve it a bounded backoff.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

import httpx

T = TypeVar("T")

# A loopback service needs very few connections, but the tier gateway serves
# several clients at once, so the pool is generous enough not to serialise.
DEFAULT_LIMITS = httpx.Limits(
    max_connections=64,
    max_keepalive_connections=32,
    keepalive_expiry=30.0,
)

# Status codes worth trying again: the service is busy, or restarting.
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _timeout(timeout: float, connect: float, read: float | None) -> httpx.Timeout:
    if read is None:
        return httpx.Timeout(timeout, connect=connect)
    # Long total budget, short per-read budget: a stream that stops producing
    # bytes fails fast even though a healthy stream may run for an hour.
    return httpx.Timeout(timeout, connect=connect, read=read)


def local_client(
    timeout: float = 30.0,
    connect: float = 3.0,
    follow_redirects: bool = False,
    transport: httpx.BaseTransport | None = None,
    read: float | None = None,
) -> httpx.Client:
    """A pooled synchronous client for a loopback service."""
    return httpx.Client(
        timeout=_timeout(timeout, connect, read),
        limits=DEFAULT_LIMITS,
        follow_redirects=follow_redirects,
        transport=transport,
    )


def shared_client(
    timeout: float = 30.0,
    connect: float = 3.0,
    follow_redirects: bool = False,
    transport: httpx.BaseTransport | None = None,
    read: float | None = None,
) -> httpx.Client:
    """The process-wide synchronous client for a given configuration.

    A synchronous client is not bound to an event loop, so one is enough for
    the whole process and it can be reused from any thread. The configuration
    is part of the key: a health probe wants three seconds, a model call
    wants five minutes, and both should get a warm pool.
    """
    if transport is not None:
        # A caller-supplied transport (a mock in a test) must not be shared.
        return local_client(
            timeout=timeout,
            connect=connect,
            follow_redirects=follow_redirects,
            transport=transport,
            read=read,
        )
    key = (timeout, connect, follow_redirects, read, id(transport) if transport else None)
    client = _shared.get(key)
    if client is None or client.is_closed:
        client = local_client(
            timeout=timeout,
            connect=connect,
            follow_redirects=follow_redirects,
            read=read,
            transport=transport,
        )
        _shared[key] = client
    return client


@contextmanager
def leased_client(
    timeout: float = 30.0,
    connect: float = 3.0,
    follow_redirects: bool = False,
    read: float | None = None,
) -> Iterator[httpx.Client]:
    """Yield the shared client without closing it on exit.

    ``httpx.Client`` is itself a context manager, but leaving its ``with``
    block closes the connection pool — which would throw away the very thing
    this module exists to reuse.
    """
    yield shared_client(
        timeout=timeout, connect=connect, follow_redirects=follow_redirects, read=read
    )


@contextmanager
def client_for(
    timeout: float = 30.0,
    connect: float = 3.0,
    follow_redirects: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[httpx.Client]:
    """A pooled client, or a throwaway one when the caller supplies a transport.

    This is the drop-in replacement for the ``with httpx.Client(...) as
    client:`` blocks that used to open a fresh connection pool on every
    call.
    """
    if transport is not None:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=connect),
            follow_redirects=follow_redirects,
            transport=transport,
        ) as client:
            yield client
        return
    with leased_client(
        timeout=timeout, connect=connect, follow_redirects=follow_redirects
    ) as client:
        yield client


_shared: dict[tuple[float, float, bool, float | None, int | None], httpx.Client] = {}


# An async client is bound to the event loop that first used it, so the cache
# is keyed by loop as well as by name. The loop is kept alive by the stored
# reference, which also stops its id from being reused.
_async_clients: dict[tuple[int, str, float, float], tuple[Any, httpx.AsyncClient]] = {}


def async_client(
    key: str,
    timeout: float = 30.0,
    connect: float = 3.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """A pooled async client, reused for the lifetime of the current loop.

    ``key`` names the service, so two clients for the same host do not
    fight over the same pool.
    """
    if transport is not None:
        # A caller-supplied transport (a mock in a test) must not be shared.
        return httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=connect),
            transport=transport,
        )
    try:
        loop: Any = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    # Callers such as the MCP tools run each collection with a fresh
    # ``asyncio.run``. Without this sweep, every call left behind a closed
    # loop, its client, and its connection pool for the life of the process.
    for stale_key, (held_loop, stale_client) in list(_async_clients.items()):
        if held_loop is loop:
            continue
        if held_loop is None or held_loop.is_closed():
            _async_clients.pop(stale_key, None)
            if loop is not None:
                try:
                    task = loop.create_task(stale_client.aclose())
                except Exception:
                    pass
                else:
                    # Closing an anyio pool created on another loop can raise
                    # inside the task; consume it so Python does not emit
                    # "Task exception was never retrieved" on every call.
                    task.add_done_callback(lambda done: done.cancelled() or done.exception())
    cache_key = (id(loop), key, float(timeout), float(connect))
    entry = _async_clients.get(cache_key)
    if entry is not None:
        held_loop, client = entry
        if held_loop is loop and not client.is_closed:
            return client
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=connect),
        limits=DEFAULT_LIMITS,
    )
    _async_clients[cache_key] = (loop, client)
    return client


async def close_async_clients() -> None:
    """Close every pooled async client. Used by tests and at shutdown."""
    for _key, (_loop, client) in list(_async_clients.items()):
        try:
            await client.aclose()
        except Exception:  # shutdown must not raise
            pass
    _async_clients.clear()


def close_shared_client() -> None:
    """Close the process-wide synchronous clients."""
    for client in list(_shared.values()):
        try:
            client.close()
        except Exception:  # shutdown must not raise
            pass
    _shared.clear()


def retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    backoff: float = 0.4,
    retry_on: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``operation``, retrying transient failures with a backoff.

    The default predicate retries connection and timeout errors and HTTP
    statuses in :data:`RETRY_STATUS`. Anything else is raised at once: a
    400 is not going to become a 200 on the second try.
    """
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return operation()
        except Exception as exc:  # the predicate decides what is transient
            last = exc
            if attempt + 1 >= attempts or not _is_transient(exc, retry_on):
                raise
            # A little jitter so several clients do not retry in lockstep.
            sleep(backoff * (2**attempt) * (0.5 + random.random()))  # noqa: S311 - jitter, not security
    raise last or RuntimeError("retry made no attempt")


async def retry_async(
    operation: Callable[[], Any],
    *,
    attempts: int = 3,
    backoff: float = 0.4,
    retry_on: Callable[[Exception], bool] | None = None,
) -> Any:
    """The awaitable twin of :func:`retry`."""
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            result = operation()
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as exc:  # the predicate decides what is transient
            last = exc
            if attempt + 1 >= attempts or not _is_transient(exc, retry_on):
                raise
            await asyncio.sleep(
                backoff * (2**attempt) * (0.5 + random.random())  # noqa: S311 - jitter
            )
    raise last or RuntimeError("retry made no attempt")


def _is_transient(exc: Exception, predicate: Callable[[Exception], bool] | None) -> bool:
    if predicate is not None:
        return predicate(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout))


__all__ = [
    "DEFAULT_LIMITS",
    "RETRY_STATUS",
    "async_client",
    "client_for",
    "close_async_clients",
    "close_shared_client",
    "leased_client",
    "local_client",
    "retry",
    "retry_async",
    "shared_client",
]
