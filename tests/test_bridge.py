"""Tests for the Anthropic bridge used by Claude Code."""

from __future__ import annotations

import json

from sovereign_code.bridge import (
    resolve_model,
    sse_events,
    to_anthropic_response,
    to_openai_request,
)


def test_resolve_model_maps_claude_ids_and_keeps_aliases() -> None:
    # Claude's own model ids map onto the local routes, so the picker in
    # Claude Code offers real local models.
    assert resolve_model("claude-sonnet-4-5") == "deep"
    assert resolve_model("claude-opus-4-1") == "ultra"
    assert resolve_model("claude-3-5-haiku-latest") == "fast"
    assert resolve_model("claude-opus-9") == "local-agent"
    assert resolve_model("local-claude") == "local-claude"
    assert resolve_model("cloud-kimi-k3") == "cloud-kimi-k3"
    assert resolve_model(None) == "local-agent"


def test_anthropic_request_becomes_openai_with_tools_and_results() -> None:
    payload = {
        "model": "local-agent",
        "system": [{"type": "text", "text": "You are helpful."}],
        "max_tokens": 512,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "make a file"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "working"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Write",
                        "input": {"file_path": "a.py", "content": "x"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
                    {"type": "text", "text": "now finish"},
                ],
            },
        ],
        "tools": [
            {
                "name": "Write",
                "description": "Write a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                },
            }
        ],
        "tool_choice": {"type": "auto"},
    }
    request = to_openai_request(payload)
    assert request["model"] == "local-agent"
    assert request["stream"] is False
    assert request["messages"][0] == {"role": "system", "content": "You are helpful."}
    assistant = request["messages"][2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["function"]["name"] == "Write"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {
        "file_path": "a.py",
        "content": "x",
    }
    tool = request["messages"][3]
    assert tool == {"role": "tool", "tool_call_id": "toolu_1", "content": "ok"}
    assert request["messages"][4] == {"role": "user", "content": "now finish"}
    assert request["tools"][0]["function"]["parameters"]["type"] == "object"
    assert request["tool_choice"] == "auto"


def test_openai_response_becomes_anthropic_tool_use() -> None:
    data = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "Write",
                                "arguments": '{"file_path": "a.py", "content": "x"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    message = to_anthropic_response(data, "local-agent")
    assert message["stop_reason"] == "tool_use"
    assert message["content"][0]["type"] == "tool_use"
    assert message["content"][0]["input"]["file_path"] == "a.py"
    assert message["usage"] == {"input_tokens": 10, "output_tokens": 4}


def test_sse_stream_contains_start_tool_delta_and_stop() -> None:
    message = {
        "id": "msg_1",
        "model": "local-agent",
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "toolu_1", "name": "Write", "input": {"a": 1}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    stream = b"".join(sse_events(message))
    assert b"event: message_start" in stream
    assert b"text_delta" in stream
    assert b"tool_use" in stream
    assert b"input_json_delta" in stream
    assert b"event: message_stop" in stream
    # When the bridge already sent message_start, the body must not repeat it.
    body = b"".join(sse_events(message, include_start=False))
    assert b"message_start" not in body


def test_local_models_lists_the_whole_catalog(monkeypatch) -> None:
    from sovereign_code import tier_gateway
    from sovereign_code.bridge import local_models

    monkeypatch.setattr(tier_gateway, "installed_models", lambda *args, **kwargs: {"qwen3.5:9b"})
    models = local_models()
    ids = {entry["id"] for entry in models}
    # The same local models ChatGPT sees.
    assert {"fast", "balanced", "deep", "ultra", "auto", "best"} <= ids
    assert "local-claude" in ids
    assert all(entry["type"] == "model" for entry in models)
