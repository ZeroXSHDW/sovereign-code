"""Tests for tier classification and the OpenAI/Ollama translation."""

from __future__ import annotations

import json
from typing import ClassVar

import httpx

from sovereign_code import tier_gateway as tg


def test_short_simple_prompt_is_fast() -> None:
    tier, reason = tg.classify([{"role": "user", "content": "hello"}])
    assert tier == tg.FAST
    assert "short" in reason


def test_code_prompt_is_deep() -> None:
    tier, _ = tg.classify(
        [
            {
                "role": "user",
                "content": "```python\ndef add(a, b):\n    return a + b\n```\nFix this.",
            }
        ]
    )
    assert tier == tg.DEEP


def test_tools_use_balanced_not_deep() -> None:
    tier, reason = tg.classify(
        [{"role": "user", "content": "Say OK"}],
        tools=[{"type": "function", "function": {"name": "write_file"}}],
    )
    assert tier == tg.BALANCED
    assert "tool" in reason


def test_system_prompt_code_words_do_not_force_deep() -> None:
    tier, _ = tg.classify(
        [
            {"role": "system", "content": "You implement code and use ``` fences."},
            {"role": "user", "content": "Say OK"},
        ]
    )
    assert tier == tg.FAST


def test_large_tool_task_is_deep() -> None:
    messages = [{"role": "user", "content": "x " * 70000}]
    tier, _ = tg.classify(messages, tools=[{"type": "function"}])
    assert tier == tg.DEEP


def test_domain_keys_route_to_a_local_specialist() -> None:
    installed = {"qwen3.8:27b"}
    for key in ("legal", "forensics", "security", "vision"):
        route = tg.resolve_route({"model": key, "messages": []}, installed=installed)
        assert route.kind == "local", key
    legal = tg.resolve_route({"model": "legal", "messages": []}, installed=installed)
    assert legal.model == "qwen3.8:27b"


def test_catalog_lists_the_domain_routes() -> None:
    ids = {entry["id"] for entry in tg.catalog_models(set())}
    assert {"legal", "forensics", "security"} <= ids


def test_resolve_route_aliases() -> None:
    auto = tg.resolve_route({"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
    assert auto.kind == "local"
    assert auto.tier == tg.FAST
    balanced = tg.resolve_route(
        {"model": "auto", "messages": [{"role": "user", "content": "hi"}], "tools": [{}]}
    )
    assert balanced.tier == tg.BALANCED
    claude = tg.resolve_route({"model": "local-claude", "messages": []})
    assert claude.model in {"qwen3.5:9b", "qwen3-coder:30b", "glm-4.7-flash"}
    assert 8192 <= claude.context <= 65536
    cloud = tg.resolve_route({"model": "cloud-kimi-k3", "messages": []})
    assert cloud.kind == "proxy"


def test_tool_history_is_converted_for_ollama() -> None:
    messages = [
        {"role": "user", "content": "write a file"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "Write", "arguments": '{"file_path": "a.py"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]
    converted = tg._convert_tool_history(messages)
    arguments = converted[1]["tool_calls"][0]["function"]["arguments"]
    assert arguments == {"file_path": "a.py"}
    assert converted[2]["tool_name"] == "Write"


def test_openai_tool_calls_stringify_arguments() -> None:
    calls = tg._openai_tool_calls(
        [
            {
                "id": "call_1",
                "function": {"index": 0, "name": "Write", "arguments": {"a": 1}},
            }
        ]
    )
    assert calls[0]["function"]["name"] == "Write"
    assert json.loads(calls[0]["function"]["arguments"]) == {"a": 1}


def test_stream_chunk_has_tool_calls_and_stable_id() -> None:
    chunk = tg._chunk(
        "qwen3.5:4b",
        {"tool_calls": [{"index": 0, "id": "call_1"}]},
        cid="chatcmpl-test",
    ).decode()
    assert "chatcmpl-test" in chunk
    assert "tool_calls" in chunk


class _FakeWfile:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.chunks.append(data)
        return len(data)

    def flush(self) -> None:
        pass


def test_replay_cached_stream_emits_sse_without_a_model_call() -> None:
    """A cached streaming hit replays the completion as SSE, no Ollama call."""
    cached = tg._completion(
        "qwen3.5:4b", "hello from cache", "", [], {"prompt_tokens": 1, "completion_tokens": 3}
    )
    handler = tg._Handler.__new__(tg._Handler)
    handler.wfile = _FakeWfile()  # type: ignore[attr-defined]
    handler.close_connection = False

    def send_response(code: int) -> None:
        handler._code = code  # type: ignore[attr-defined]

    def send_header(key: str, value: str) -> None:
        pass

    def end_headers() -> None:
        pass

    def cors() -> None:
        pass

    handler.send_response = send_response  # type: ignore[assignment]
    handler.send_header = send_header  # type: ignore[assignment]
    handler.end_headers = end_headers  # type: ignore[assignment]
    handler._cors = cors  # type: ignore[assignment]

    route = tg.Route("local", "qwen3.5:4b", tg.FAST, 4096, False, "cached test")
    handler._replay_cached_stream(cached, route)  # type: ignore[attr-defined]

    stream = b"".join(handler.wfile.chunks).decode()  # type: ignore[union-attr]
    assert "hello from cache" in stream
    assert "data: [DONE]" in stream


def test_response_cache_expires(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tg.time, "monotonic", lambda: 0.0)
    cache = tg.ResponseCache(max_entries=2, ttl=10)
    cache.put("k", {"value": 1})
    assert cache.get("k") == {"value": 1}
    # A returned value is a copy, not shared state.
    value = cache.get("k")
    value["value"] = 2
    assert cache.get("k") == {"value": 1}
    monkeypatch.setattr(tg.time, "monotonic", lambda: 20.0)
    assert cache.get("k") is None


def test_metrics_summary(tmp_path, monkeypatch) -> None:
    path = tmp_path / "tiers.jsonl"
    path.write_text(
        "\n".join(json.dumps({"tier": "fast", "ms": 10}) for _ in range(2))
        + "\n"
        + json.dumps({"tier": "deep", "ms": 100})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tg, "metrics_path", lambda: path)
    summary = tg.metrics_summary()
    assert summary["requests"] == 3
    assert summary["by_tier"]["fast"]["avg_ms"] == 10
    assert summary["by_tier"]["deep"]["avg_ms"] == 100


def test_tier_headers_are_carried_to_the_responses_reply() -> None:
    class FakeResponse:
        headers: ClassVar[dict[str, str]] = {
            "x-sovereign-tier": "fast",
            "x-sovereign-model": "qwen3.5:4b",
            "x-sovereign-reason": "simple short prompt",
        }

    headers = tg._tier_headers(FakeResponse())
    assert headers["x-sovereign-tier"] == "fast"
    assert headers["x-sovereign-model"] == "qwen3.5:4b"
    assert "x-sovereign-fallback" not in headers


def test_responses_request_translates_to_chat() -> None:
    payload = {
        "model": "auto",
        "instructions": "You are Codex.",
        "max_output_tokens": 512,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "make a file"}],
            },
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "exec_command",
                "arguments": '{"cmd":"ls"}',
            },
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        ],
        "tools": [
            {
                "type": "function",
                "name": "exec_command",
                "description": "Run a command",
                "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            }
        ],
    }
    chat = tg.responses_to_chat(payload)
    assert chat["model"] == "auto"
    assert chat["messages"][0] == {"role": "system", "content": "You are Codex."}
    assert chat["messages"][1]["role"] == "user"
    assert chat["messages"][2]["tool_calls"][0]["function"]["name"] == "exec_command"
    assert chat["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "ok"}
    assert chat["tools"][0]["function"]["parameters"]["type"] == "object"


def test_chat_completion_becomes_responses_object() -> None:
    completion = {
        "model": "qwen3.5:9b",
        "choices": [
            {
                "message": {
                    "content": "working",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "exec_command", "arguments": '{"cmd":"ls"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    response = tg.chat_to_responses(completion)
    assert response["object"] == "response"
    assert response["output"][0]["type"] == "message"
    assert response["output"][1]["type"] == "function_call"
    assert response["output"][1]["call_id"] == "call_1"
    assert response["usage"]["total_tokens"] == 15


def test_responses_sse_emits_codex_events_and_monotonic_sequence() -> None:
    response = tg.chat_to_responses(
        {
            "model": "qwen3.5:9b",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "exec_command", "arguments": '{"cmd":"ls"}'},
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
    )
    stream = b"".join(tg.responses_sse(response)).decode()
    assert "event: response.created" in stream
    assert "event: response.output_item.added" in stream
    assert "response.function_call_arguments.delta" in stream
    assert "event: response.completed" in stream
    sequences = [
        json.loads(line[len("data: ") :])["sequence_number"]
        for line in stream.splitlines()
        if line.startswith("data: ")
    ]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


def test_deep_code_uses_the_faster_moe() -> None:
    installed = {"qwen3-coder:30b", "glm-4.7-flash", "qwen3.8:27b", "qwen3.5:9b"}
    model, _context, _think = tg.choose_model(tg.DEEP, installed, "code")
    assert model == "qwen3-coder:30b"


def test_deep_reasoning_uses_glm_before_the_dense_27b() -> None:
    installed = {"qwen3-coder:30b", "glm-4.7-flash", "qwen3.8:27b"}
    model, _context, _think = tg.choose_model(tg.DEEP, installed, "reason")
    assert model == "glm-4.7-flash"


def test_ultra_tier_keeps_the_27b() -> None:
    installed = {"qwen3-coder:30b", "glm-4.7-flash", "qwen3.8:27b"}
    model, _context, _think = tg.choose_model(tg.ULTRA, installed, "code")
    assert model == "qwen3.8:27b"


def test_intent_detection_prefers_code_and_reasoning() -> None:
    assert tg.detect_intent([{"role": "user", "content": "fix this Python bug"}]) == "code"
    assert tg.detect_intent([{"role": "user", "content": "analyze the tradeoffs"}]) == "reason"
    assert tg.detect_intent([{"role": "user", "content": "hello"}]) == "general"


def test_best_code_uses_the_30b_coder() -> None:
    route = tg.resolve_route(
        {
            "model": "best",
            "messages": [{"role": "user", "content": "fix this Python bug"}],
        },
        installed={"qwen3-coder:30b", "glm-4.7-flash", "qwen3.8:27b"},
    )
    assert route.model == "qwen3-coder:30b"
    assert route.tier == tg.DEEP


def test_best_reasoning_uses_ultra() -> None:
    route = tg.resolve_route(
        {
            "model": "best",
            "messages": [{"role": "user", "content": "analyze the tradeoffs"}],
        },
        installed={"qwen3-coder:30b", "glm-4.7-flash", "qwen3.8:27b"},
    )
    assert route.model == "qwen3.8:27b"
    assert route.tier == tg.ULTRA


def test_local_only_is_the_default(monkeypatch) -> None:
    monkeypatch.delenv("SOVEREIGN_LOCAL_ONLY", raising=False)
    assert tg.local_only() is True
    monkeypatch.setenv("SOVEREIGN_LOCAL_ONLY", "0")
    assert tg.local_only() is False


def test_claude_skill_turn_does_not_hide_the_real_prompt() -> None:
    messages = [
        {
            "role": "user",
            "content": "<system-reminder>context</system-reminder>\n\nSay exactly: OK",
        },
        {"role": "user", "content": "skill list " * 1200},
    ]
    assert tg.task_user_message(messages) is messages[0]
    assert tg.is_simple_request(messages) is True


def test_best_simple_request_stays_on_the_balanced_tier() -> None:
    route = tg.resolve_route(
        {
            "model": "best",
            "messages": [{"role": "user", "content": "Say OK"}],
        },
        installed={"qwen3-coder:30b", "qwen3.5:9b"},
    )
    assert route.tier == tg.BALANCED


def test_repeated_tool_call_is_detected() -> None:
    call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c", "function": {"name": "exec_command", "arguments": '{"cmd":"ls"}'}}
        ],
    }
    assert tg.repeated_tool_call([call, call, call]) is True


def test_long_tool_outputs_are_truncated() -> None:
    messages = tg.truncate_tool_outputs(
        [{"role": "tool", "tool_call_id": "c", "content": "x" * 5000}], limit=100
    )
    assert len(messages[0]["content"]) < 200
    assert "truncated" in messages[0]["content"]


def test_long_sessions_keep_the_task_anchor() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "TASK ANCHOR"},
    ]
    for index in range(40):
        messages.append({"role": "assistant", "content": f"step {index} " * 200})
        messages.append({"role": "user", "content": f"feedback {index} " * 50})
    compacted = tg.compact_messages(messages, 4096)
    assert compacted[0]["content"].startswith("Earlier conversation")
    assert any(m.get("content") == "TASK ANCHOR" for m in compacted)
    assert len(compacted) < len(messages)


def test_compaction_drops_orphan_tool_results() -> None:
    messages = [
        {"role": "user", "content": "TASK"},
        {"role": "tool", "tool_call_id": "missing", "content": "orphan"},
        {"role": "assistant", "content": "x" * 5000},
        {"role": "user", "content": "recent"},
    ]
    compacted = tg.compact_messages(messages, 1024)
    assert all(m.get("role") != "tool" for m in compacted)


def test_catalog_lists_every_name_a_client_can_use() -> None:
    installed = {"qwen3.5:9b", "qwen3-coder:30b", "nomic-embed-text:latest"}
    ids = {entry["id"] for entry in tg.catalog_models(installed)}
    # The tiers, the quality route and the auto route.
    assert {"fast", "balanced", "deep", "ultra", "auto", "best"} <= ids
    # The aliases that name a model directly.
    assert "local-claude" in ids
    # The installed models themselves.
    assert "qwen3-coder:30b" in ids
    # An embedding model cannot answer a chat turn.
    assert "nomic-embed-text:latest" not in ids


def test_every_catalog_name_is_routable() -> None:
    installed = {"qwen3.5:9b", "qwen3-coder:30b", "glm-4.7-flash"}
    for entry in tg.catalog_models(installed):
        route = tg.resolve_route(
            {"model": entry["id"], "messages": [{"role": "user", "content": "hi"}]},
            None,
            installed,
        )
        assert route.kind == "local", entry["id"]


def test_catalog_reports_the_model_behind_a_name() -> None:
    entries = {entry["id"]: entry for entry in tg.catalog_models({"qwen3.5:9b"})}
    assert entries["deep"]["model"] == "qwen3-coder:30b"
    assert entries["fast"]["model"] == "qwen3.5:4b"
    assert entries["local-claude"]["model"] == "qwen3.5:9b"
    assert entries["auto"]["tier"] == "auto"


def test_a_request_too_big_for_the_model_uses_the_long_context_one() -> None:
    installed = {"qwen3.5:9b", "qwen3-coder:30b", "qwen3.8:27b"}
    # 40k tokens do not fit the 30B coder at 32k.
    messages = [{"role": "user", "content": "x " * 80000}]
    route = tg.resolve_route({"model": "deep", "messages": messages}, None, installed)
    assert route.model == "qwen3.5:9b"
    assert route.context >= 40000


def test_a_request_that_fits_keeps_the_tier_model() -> None:
    installed = {"qwen3.5:9b", "qwen3-coder:30b"}
    route = tg.resolve_route(
        {"model": "deep", "messages": [{"role": "user", "content": "hi"}]}, None, installed
    )
    assert route.model == "qwen3-coder:30b"


def test_an_installed_model_name_is_served_directly() -> None:
    installed = {"qwen3.5:9b", "qwen3-coder:30b"}
    route = tg.resolve_route(
        {"model": "qwen3.5:9b", "messages": [{"role": "user", "content": "hi"}]},
        None,
        installed,
    )
    assert route.kind == "local"
    assert route.model == "qwen3.5:9b"


def test_a_cloud_tag_is_not_served_locally() -> None:
    installed = {"kimi-k3:cloud"}
    route = tg.resolve_route(
        {"model": "kimi-k3:cloud", "messages": [{"role": "user", "content": "hi"}]},
        None,
        installed,
    )
    assert route.kind == "proxy"


def test_the_catalog_holds_no_cloud_or_embedding_model() -> None:
    installed = {"kimi-k3:cloud", "nomic-embed-text:latest", "glm-4.7-flash:latest"}
    ids = {entry["id"] for entry in tg.catalog_models(installed)}
    assert "kimi-k3:cloud" not in ids
    assert "nomic-embed-text" not in ids
    # A ":latest" tag is listed under the name the configs use.
    assert "glm-4.7-flash" in ids


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


def test_responses_stream_forwards_text_then_tool_use() -> None:
    chunks = [
        {"model": "qwen3-coder:30b", "choices": [{"delta": {"role": "assistant"}}]},
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
                                "function": {"name": "Write", "arguments": '{"file_path":'},
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
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
    ]
    events = _events(b"".join(tg.responses_stream(chunks, "resp_1", "auto")))
    names = [name for name, _ in events]
    assert names[:2] == ["response.created", "response.in_progress"]
    assert names[-1] == "response.completed"
    sequences = [payload["sequence_number"] for _, payload in events]
    assert sequences == list(range(len(events)))

    deltas = [payload["delta"] for name, payload in events if name == "response.output_text.delta"]
    assert deltas == ["Hel", "lo"]
    text_done = next(payload for name, payload in events if name == "response.output_text.done")
    assert text_done["text"] == "Hello"

    arguments_done = next(
        payload for name, payload in events if name == "response.function_call_arguments.done"
    )
    assert json.loads(arguments_done["arguments"]) == {"file_path": "a.py"}
    completed = events[-1][1]["response"]
    assert completed["status"] == "completed"
    assert completed["model"] == "qwen3-coder:30b"
    assert [item["type"] for item in completed["output"]] == ["message", "function_call"]
    assert completed["usage"] == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}


def test_responses_stream_without_output_still_completes() -> None:
    events = _events(b"".join(tg.responses_stream([], "resp_1", "fast")))
    completed = events[-1][1]["response"]
    assert completed["output"][0]["type"] == "message"
    assert completed["output"][0]["content"][0]["text"] == ""


def test_iter_chat_stream_parses_chunks_and_surfaces_errors() -> None:
    response = httpx.Response(
        200,
        content=(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'),
    )
    chunks = list(tg.iter_chat_stream(response))
    assert chunks[0]["choices"][0]["delta"]["content"] == "hi"

    failed = httpx.Response(200, content=b'data: {"error":{"message":"model failed"}}\n\n')
    try:
        list(tg.iter_chat_stream(failed))
    except RuntimeError as exc:
        assert "model failed" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("a stream error must not look like a reply")


def test_gateway_starts_without_loading_a_model(tmp_path, monkeypatch) -> None:
    order: list[str] = []
    loaded: list[str] = []

    class FakeServer:
        def serve_forever(self) -> None:
            order.append("serving")

        def server_close(self) -> None:
            return

    def fake_make_server(*args, **kwargs) -> FakeServer:
        order.append("bound")
        return FakeServer()

    monkeypatch.setattr(tg, "pid_path", lambda: tmp_path / "tier.pid")
    monkeypatch.setattr(tg, "make_server", fake_make_server)
    monkeypatch.setattr(tg._SCHEDULER, "enter", loaded.append)
    tg.serve("127.0.0.1", 0, "http://127.0.0.1:11434", "http://127.0.0.1:4000")
    # Starting the gateway must not occupy RAM: only a real request loads a model.
    assert order == ["bound", "serving"]
    assert loaded == []


def test_model_timeouts_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv("SOVEREIGN_REQUEST_TIMEOUT", "12.5")
    monkeypatch.setenv("SOVEREIGN_STREAM_IDLE_TIMEOUT", "7")
    assert tg.request_timeout() == 12.5
    assert tg.stream_idle_timeout() == 7.0

    # A bad or zero value falls back to the reviewed default instead of
    # disabling the guard entirely.
    monkeypatch.setenv("SOVEREIGN_REQUEST_TIMEOUT", "not-a-number")
    monkeypatch.setenv("SOVEREIGN_STREAM_IDLE_TIMEOUT", "0")
    assert tg.request_timeout() == tg.DEFAULT_REQUEST_TIMEOUT
    assert tg.stream_idle_timeout() == tg.DEFAULT_STREAM_IDLE_TIMEOUT
