"""Tests for the MCP server's protocol handling."""

from __future__ import annotations

import json

from sovereign_code.mcp import handle


def _result(method: str, params: dict | None = None):
    response = handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert response is not None
    return response


def test_initialize_and_tools_list() -> None:
    init = _result("initialize")["result"]
    assert init["serverInfo"]["name"] == "sovereign-code"
    assert "tools" in init["capabilities"]
    tools = {tool["name"] for tool in _result("tools/list")["result"]["tools"]}
    assert {
        "list_models",
        "best_model",
        "list_skills",
        "get_skill",
        "hf_status",
        "search_hf_models",
        "hf_model_info",
        "ask",
        "delegate",
        "browser_open",
        "browser_observe",
        "browser_act",
        "browser_screenshot",
        "browser_close",
        "local_status",
    } <= tools


def test_skills_tool_returns_curated_matches() -> None:
    response = _result(
        "tools/call",
        {"name": "list_skills", "arguments": {"query": "review"}},
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload
    assert any("review" in item["name"] for item in payload)


def test_get_skill_body_and_unknown_skill() -> None:
    listed = json.loads(
        _result("tools/call", {"name": "list_skills", "arguments": {}})["result"]["content"][0][
            "text"
        ]
    )
    name = listed[0]["name"]
    body = _result("tools/call", {"name": "get_skill", "arguments": {"name": name}})["result"][
        "content"
    ][0]["text"]
    assert body.strip()
    error = handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_skill", "arguments": {"name": "does-not-exist"}},
        }
    )
    assert "error" in error


def test_resources_and_prompts() -> None:
    resources = _result("resources/list")["result"]["resources"]
    assert any(item["uri"] == "sovereign://models" for item in resources)
    prompts = _result("prompts/list")["result"]["prompts"]
    assert prompts
    prompt = _result(
        "prompts/get",
        {"name": prompts[0]["name"], "arguments": {"context": "print(1)"}},
    )["result"]
    assert "print(1)" in prompt["messages"][0]["content"]["text"]


def test_unknown_method_is_an_error() -> None:
    response = _result("does/not/exist")
    assert response["error"]["code"] == -32601


def test_local_status_reports_the_stack_and_the_apps() -> None:
    body = _result("tools/call", {"name": "local_status", "arguments": {}})["result"]["content"][0][
        "text"
    ]
    payload = json.loads(body)
    assert set(payload["apps"]) == {"chatgpt", "claude"}
    assert "local_only" in payload
    assert "tiers" in payload["gateway"]
    assert "signin_required" in payload["apps"]["chatgpt"]
