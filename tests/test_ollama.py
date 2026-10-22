"""Tests for the Ollama client: timeouts, error surfacing, pull streaming."""

from __future__ import annotations

import json

import httpx
import pytest

from sovereign_code.ollama import PRELOAD_TIMEOUT, OllamaClient, OllamaError


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_request_uses_the_client_timeout(monkeypatch) -> None:
    """A cold model load must not be cut off by a short read timeout.

    The client used to hard-code an 8 second budget for every non-streaming
    call, so `sovereign warm` failed while the model was still loading.
    """
    seen: dict[str, float | None] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            seen["constructor_timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, json=None, timeout=None):
            seen["timeout"] = timeout
            return httpx.Response(200, json={"version": "0.1"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = OllamaClient(timeout=45.0)
    assert await client.version() == "0.1"
    assert seen["timeout"] is not None
    # httpx.Timeout keeps the read budget; connect stays short.
    assert seen["timeout"].read == 45.0
    assert seen["timeout"].connect == client.connect_timeout


async def test_preload_gets_its_own_generous_budget(monkeypatch) -> None:
    seen: dict[str, float | None] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            seen["constructor_timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, json=None, timeout=None):
            seen["timeout"] = timeout
            return httpx.Response(200, json={})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = OllamaClient(timeout=60.0)
    await client.preload("qwen3.5:4b", context=8192)
    assert seen["timeout"].read == max(60.0, PRELOAD_TIMEOUT)


async def test_request_raises_on_http_error() -> None:
    transport = _mock(lambda request: httpx.Response(404, text="nope"))
    client = OllamaClient()
    with pytest.raises(OllamaError, match="404"):
        await client._request("GET", "/api/tags", transport=transport)


async def test_pull_reports_an_in_stream_error() -> None:
    """Ollama answers a failed pull with HTTP 200 and an error object.

    Treating that as a finished download reported broken pulls as successes.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps({"error": "model not found"}).encode()
        return httpx.Response(200, content=body)

    client = OllamaClient()
    with pytest.raises(OllamaError, match="model not found"):
        async for _event in client.pull("nope:1b", transport=_mock(handler)):
            pass


async def test_pull_yields_progress_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps({"status": "pulling manifest"}).encode()
        return httpx.Response(200, content=body)

    client = OllamaClient()
    events = [event async for event in client.pull("qwen3.5:4b", transport=_mock(handler))]
    assert events == [{"status": "pulling manifest"}]
