"""Tests for the Anthropic bridge used by Claude Code."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from sovereign_code.bridge import (
    anthropic_stream_events,
    iter_completion,
    make_server,
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


def _events(stream: bytes) -> list[tuple[str, dict]]:
    events = []
    for block in stream.decode().split("\n\n"):
        name = ""
        payload = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if name:
            events.append((name, payload))
    return events


def test_streaming_request_asks_the_gateway_to_stream() -> None:
    request = to_openai_request(
        {"model": "claude-sonnet-4-5", "messages": []},
        default_model="deep",
        stream=True,
    )
    assert request["stream"] is True
    assert request["model"] == "deep"


def test_streaming_text_arrives_before_the_tool_block() -> None:
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "Write",
                                    "arguments": '{"file_path":',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "a.py"}'}}]}}
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}},
    ]
    events = _events(b"".join(anthropic_stream_events(chunks, "msg_1", "deep")))
    names = [name for name, _ in events]
    assert "message_start" not in names
    assert names[0] == "content_block_start"
    assert names[-2:] == ["message_delta", "message_stop"]

    starts = [payload for name, payload in events if name == "content_block_start"]
    assert starts[0]["content_block"] == {"type": "text", "text": ""}
    assert starts[1]["content_block"]["type"] == "tool_use"
    assert starts[1]["content_block"]["name"] == "Write"
    assert starts[1]["index"] == 1

    texts = [
        payload["delta"]["text"]
        for name, payload in events
        if name == "content_block_delta" and payload["delta"]["type"] == "text_delta"
    ]
    assert texts == ["Hel", "lo"]
    # The text block closes before the tool block opens, so Claude renders the
    # sentence first and then runs the tool.
    text_stop = next(
        index
        for index, (name, payload) in enumerate(events)
        if name == "content_block_stop" and payload["index"] == 0
    )
    tool_start = next(
        index
        for index, (name, payload) in enumerate(events)
        if name == "content_block_start" and payload["content_block"]["type"] == "tool_use"
    )
    assert text_stop < tool_start

    partial = next(
        payload["delta"]["partial_json"]
        for name, payload in events
        if name == "content_block_delta" and payload["delta"]["type"] == "input_json_delta"
    )
    assert json.loads(partial) == {"file_path": "a.py"}
    delta = next(payload for name, payload in events if name == "message_delta")
    assert delta["delta"]["stop_reason"] == "tool_use"
    assert delta["usage"] == {"output_tokens": 4}


def test_streaming_without_text_or_tools_still_closes_a_block() -> None:
    events = _events(b"".join(anthropic_stream_events([], "msg_1", "fast")))
    names = [name for name, _ in events]
    assert names == ["content_block_start", "content_block_stop", "message_delta", "message_stop"]
    assert events[2][1]["delta"]["stop_reason"] == "end_turn"


def test_iter_completion_parses_gateway_sse() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        body = (
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body)

    chunks = list(
        iter_completion(
            "http://127.0.0.1:4010",
            {"model": "deep", "messages": [{"role": "user", "content": "hi"}]},
            transport=httpx.MockTransport(handler),
        )
    )
    assert seen["stream"] is True
    assert seen["model"] == "deep"
    assert [chunk["choices"][0]["delta"].get("content") for chunk in chunks] == ["hi", None]


def test_iter_completion_reports_a_stream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = b'data: {"error":{"message":"model failed"}}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, content=body)

    chunks = iter_completion(
        "http://127.0.0.1:4010",
        {"messages": []},
        transport=httpx.MockTransport(handler),
    )
    try:
        list(chunks)
    except RuntimeError as exc:
        assert "model failed" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("an upstream error chunk must not look like a reply")


def test_iter_completion_reports_a_gateway_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="model failed")

    iterator = iter_completion(
        "http://127.0.0.1:4010",
        {"messages": []},
        transport=httpx.MockTransport(handler),
    )
    try:
        list(iterator)
    except RuntimeError as exc:
        assert "502" in str(exc)
        assert "model failed" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("a gateway error must not look like a reply")


def test_bridge_streams_an_end_to_end_reply() -> None:
    class FakeGateway(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            return

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            chunks = [
                {"choices": [{"delta": {"content": "Hello"}}]},
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {
                                            "name": "Write",
                                            "arguments": '{"file_path":"a.py"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
                {"choices": [], "usage": {"completion_tokens": 3}},
            ]
            body = (
                b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
                + b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
    bridge = make_server(
        host="127.0.0.1",
        port=0,
        gateway_url=f"http://127.0.0.1:{gateway.server_address[1]}",
        default_model="deep",
    )
    for server in (gateway, bridge):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{bridge.server_address[1]}/v1/messages",
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 128,
                "stream": True,
                "messages": [{"role": "user", "content": "make a file"}],
            },
            timeout=10.0,
        ) as response:
            assert response.status_code == 200
            stream = b"".join(response.iter_bytes()).decode()
    finally:
        bridge.shutdown()
        gateway.shutdown()
        bridge.server_close()
        gateway.server_close()

    events = _events(stream.encode())
    names = [name for name, _ in events]
    assert names[0] == "message_start"
    assert "Hello" in stream
    assert "tool_use" in stream
    assert "input_json_delta" in stream
    assert names[-1] == "message_stop"
    text_delta = next(payload for name, payload in events if name == "content_block_delta")
    assert text_delta["delta"] == {"type": "text_delta", "text": "Hello"}
