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


def _ndjson(lines: list[dict]) -> httpx.Response:
    body = "\n".join(json.dumps(line) for line in lines).encode()
    return httpx.Response(200, content=body)


async def test_chat_stream_yields_chunks_with_thinking_and_counts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ndjson(
            [
                {"message": {"content": "let me ", "thinking": "plan"}, "done": False},
                {"message": {"content": "think", "thinking": "about it"}, "done": False},
                {
                    "message": {"content": "", "thinking": ""},
                    "done": True,
                    "model": "qwen3.5:4b",
                    "eval_count": 12,
                    "prompt_eval_count": 34,
                    "total_duration": 9000,
                },
            ]
        )

    client = OllamaClient()
    chunks = [
        chunk async for chunk in client.chat_stream("qwen3.5:4b", [], transport=_mock(handler))
    ]
    assert [c.content for c in chunks] == ["let me ", "think", ""]
    assert chunks[1].thinking == "about it"
    assert chunks[2].done is True
    assert chunks[2].model == "qwen3.5:4b"
    assert chunks[2].eval_count == 12
    assert chunks[2].prompt_eval_count == 34
    assert chunks[2].total_duration_ns == 9000


async def test_chat_stream_skips_blank_and_malformed_lines() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = b'\nnot json\n\n{"message": {"content": "ok"}, "done": false}\n\n'
        return httpx.Response(200, content=body)

    client = OllamaClient()
    chunks = [chunk async for chunk in client.chat_stream("m", [], transport=_mock(handler))]
    # The blank and non-JSON lines are skipped; only the real event yields.
    assert [c.content for c in chunks] == ["ok"]


async def test_chat_stream_reports_an_error_event() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ndjson([{"error": "model not found"}])

    client = OllamaClient()
    with pytest.raises(OllamaError, match="model not found"):
        async for _chunk in client.chat_stream("nope", [], transport=_mock(handler)):
            pass


async def test_unload_sends_keep_alive_zero(monkeypatch) -> None:
    seen: dict[str, dict] = {}

    async def fake_request(self, method, path, payload=None, timeout=None, transport=None):
        seen["payload"] = payload or {}
        return {}

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    client = OllamaClient()
    await client.unload("qwen3.5:4b")
    assert seen["payload"]["keep_alive"] == 0
    assert seen["payload"]["model"] == "qwen3.5:4b"


async def test_version_returns_unknown_when_missing(monkeypatch) -> None:
    seen: dict[str, str] = {}

    async def fake_request(self, method, path, payload=None, timeout=None, transport=None):
        seen["path"] = path
        return {}

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    client = OllamaClient()
    assert await client.version() == "unknown"
    assert seen["path"] == "/api/version"


def test_chat_chunk_defaults() -> None:
    from sovereign_code.ollama import ChatChunk

    chunk = ChatChunk()
    assert chunk.content == ""
    assert chunk.done is False
