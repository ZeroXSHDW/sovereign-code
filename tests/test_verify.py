"""Tests for the end-to-end gateway check."""

from __future__ import annotations

import json

import httpx

from sovereign_code.verify import (
    CORE_ALIASES,
    configured_aliases,
    probe_alias,
    probe_aliases,
)


def _reply(content: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 8
        assert payload["messages"][0]["content"]
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


def test_probe_alias_passes_with_non_empty_reply() -> None:
    result = probe_alias("http://gw", "local-chat", transport=_reply("OK"))
    assert result.ok is True
    assert result.alias == "local-chat"
    assert result.detail == "OK"


def test_probe_alias_rejects_empty_reply() -> None:
    result = probe_alias("http://gw", "local-chat", transport=_reply("   "))
    assert result.ok is False
    assert result.detail == "empty reply"


def test_probe_alias_reports_http_status() -> None:
    result = probe_alias("http://gw", "local-code", transport=_reply("", status=503))
    assert result.ok is False
    assert result.detail == "HTTP 503"


def test_probe_alias_reports_malformed_body() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="not-json"))
    result = probe_alias("http://gw", "local-chat", transport=transport)
    assert result.ok is False
    assert result.detail == "malformed response"


def test_thinking_alias_gets_room_for_reasoning() -> None:
    seen: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["max_tokens"] = json.loads(request.content)["max_tokens"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    result = probe_alias("http://gw", "local-thinking", transport=httpx.MockTransport(handler))
    assert result.ok is True
    assert seen["max_tokens"] == 512


def test_probe_aliases_keeps_order_and_covers_core_set() -> None:
    results = probe_aliases("http://gw", ("local-agent", "local-claude"), transport=_reply("OK"))
    assert [result.alias for result in results] == ["local-agent", "local-claude"]
    assert all(result.ok for result in results)
    assert CORE_ALIASES == ("local-chat", "local-code", "local-agent", "local-claude")


def test_check_embedding_ok() -> None:
    from sovereign_code.verify import check_embedding

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"embeddings": [[0.1] * 768]})
    )
    ok, detail = check_embedding("http://gw", transport=transport)
    assert ok is True
    assert "768" in detail


def test_check_embedding_http_error() -> None:
    from sovereign_code.verify import check_embedding

    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="down"))
    ok, detail = check_embedding("http://gw", transport=transport)
    assert ok is False
    assert "500" in detail


def _config(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_configured_aliases_skips_the_openai_passthrough(tmp_path) -> None:
    path = _config(
        tmp_path,
        "model_list:\n"
        "  - model_name: local-code\n"
        "    litellm_params:\n"
        "      model: ollama/qwen3-coder:30b\n"
        '  - model_name: "openai/*"\n'
        "    litellm_params:\n"
        '      model: "openai/*"\n'
        "  - model_name: local-chat\n",
    )
    # Order preserved, quoting tolerated, cloud passthrough excluded.
    assert configured_aliases(path) == ("local-code", "local-chat")


def test_configured_aliases_missing_file_is_empty(tmp_path) -> None:
    assert configured_aliases(tmp_path / "nope.yaml") == ()
