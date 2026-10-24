"""Benchmark helper tests."""

from __future__ import annotations

import json

import httpx

from sovereign_code.bench import BenchResult, bench_alias


def test_tokens_per_second() -> None:
    result = BenchResult("local-chat", True, 12, 40, 4.0)
    assert result.tokens_per_second == 10.0
    assert BenchResult("x", True, 0, 0, 0.0).tokens_per_second == 0.0


def test_bench_alias_reports_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "local-chat"
        assert payload["max_tokens"] == 64
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 21},
            },
        )

    result = bench_alias("http://gw", "local-chat", "hi", transport=httpx.MockTransport(handler))
    assert result.ok is True
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 21
    assert result.seconds > 0


def test_bench_alias_reports_http_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="down"))
    result = bench_alias("http://gw", "local-code", "hi", transport=transport)
    assert result.ok is False
    assert result.detail == "HTTP 503"


def test_bench_alias_reports_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = bench_alias("http://gw", "local-agent", "hi", transport=httpx.MockTransport(handler))
    assert result.ok is False
    assert result.detail == "ConnectError"
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0
