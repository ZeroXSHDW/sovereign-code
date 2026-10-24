"""The JSON-RPC surface every client uses to reach this machine.

Dispatch mistakes here are invisible until a client cannot see a tool, so the
protocol methods and the local (no-model) tools are exercised directly.
"""

from __future__ import annotations

import json

import pytest

from sovereign_code import mcp


def _call(name: str, arguments: dict | None = None) -> dict:
    payload = mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    assert payload is not None
    return payload


def test_notifications_are_not_answered():
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_initialize_echoes_a_supported_protocol_version():
    supported = sorted(mcp.SUPPORTED_PROTOCOL_VERSIONS)[0]
    result = mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "initialize",
            "params": {"protocolVersion": supported},
        }
    )
    assert result is not None
    assert result["result"]["protocolVersion"] == supported
    assert result["result"]["capabilities"]["tools"] == {}
    assert "Sovereign Code" in result["result"]["instructions"]


def test_initialize_falls_back_to_our_version():
    result = mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        }
    )
    assert result is not None
    assert result["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION


def test_ping_answers_an_empty_result():
    result = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert result == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_tools_list_describes_every_tool():
    result = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert result is not None
    tools = result["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"ask", "repo_read", "repo_search", "list_packs", "run_checks"} <= names
    for tool in tools:
        assert tool["description"], tool["name"]
        assert isinstance(tool["inputSchema"], dict), tool["name"]


def test_tool_errors_are_results_not_protocol_errors(monkeypatch):
    """A refusing tool must not look like a broken server."""

    def boom(_name: str, _args: dict) -> str:
        raise ValueError("this tool said no")

    monkeypatch.setattr(mcp, "call_tool", boom)
    payload = _call("whatever")
    assert payload["result"]["isError"] is True
    assert "this tool said no" in payload["result"]["content"][0]["text"]


def test_tool_results_are_wrapped_as_text(monkeypatch):
    monkeypatch.setattr(mcp, "call_tool", lambda _name, _args: "done")
    payload = _call("whatever")
    assert payload["result"] == {"content": [{"type": "text", "text": "done"}], "isError": False}


def test_resources_and_prompts_are_listed(monkeypatch):
    monkeypatch.setattr(mcp, "resources", lambda: [{"uri": "sovereign://x", "name": "x"}])
    listed = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    assert listed is not None
    assert listed["result"]["resources"] == [{"uri": "sovereign://x", "name": "x"}]

    monkeypatch.setattr(mcp, "read_resource", lambda uri: f"body for {uri}")
    read = mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "resources/read",
            "params": {"uri": "sovereign://x"},
        }
    )
    assert read is not None
    assert read["result"]["contents"][0]["text"] == "body for sovereign://x"
    assert read["result"]["contents"][0]["mimeType"] == "text/markdown"

    monkeypatch.setattr(mcp, "prompts", lambda: [{"name": "p"}])
    prompts = mcp.handle({"jsonrpc": "2.0", "id": 6, "method": "prompts/list"})
    assert prompts is not None
    assert prompts["result"]["prompts"] == [{"name": "p"}]

    monkeypatch.setattr(mcp, "get_prompt", lambda name, args: {"messages": [name]})
    got = mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "prompts/get", "params": {"name": "p"}})
    assert got is not None
    assert got["result"] == {"messages": ["p"]}


def test_an_unknown_method_is_a_method_not_found_error():
    payload = mcp.handle({"jsonrpc": "2.0", "id": 8, "method": "nope/nope"})
    assert payload is not None
    assert payload["error"]["code"] == -32601
    assert "nope/nope" in payload["error"]["message"]


def test_a_dispatch_crash_is_reported_without_killing_the_server(monkeypatch):
    def boom() -> list[dict]:
        raise RuntimeError("bank unavailable")

    monkeypatch.setattr(mcp, "resources", boom)
    payload = mcp.handle({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
    assert payload is not None
    assert payload["error"]["code"] == -32000
    assert "bank unavailable" in payload["error"]["message"]


def test_bearer_check(monkeypatch):
    assert mcp._bearer_ok(None, "")
    assert mcp._bearer_ok("Bearer secret", "secret")
    assert not mcp._bearer_ok("Bearer wrong", "secret")
    assert not mcp._bearer_ok(None, "secret")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Point the workspace guard at the temp tree instead of the real repo."""
    monkeypatch.setenv("SOVEREIGN_WORKSPACE", str(tmp_path))
    return tmp_path


def test_repo_read_returns_numbered_lines(workspace):
    path = workspace / "sample.py"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    payload = _call("repo_read", {"path": str(path), "start": 2, "end": 3})
    text = payload["result"]["content"][0]["text"]
    assert "two" in text and "three" in text


def test_repo_write_edit_and_patch_round_trip(workspace):
    target = workspace / "module.py"
    written = _call("repo_write", {"path": str(target), "content": "value = 1\n"})
    assert "sha256" in written["result"]["content"][0]["text"].lower()
    assert target.read_text(encoding="utf-8") == "value = 1\n"

    edited = _call(
        "repo_edit",
        {"path": str(target), "old": "value = 1", "new": "value = 2"},
    )
    assert edited["result"]["isError"] is False
    assert target.read_text(encoding="utf-8") == "value = 2\n"

    patch = "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-value = 2\n+value = 3\n"
    patched = _call("repo_patch", {"path": str(workspace), "patch": patch})
    assert patched["result"]["isError"] is False
    assert target.read_text(encoding="utf-8") == "value = 3\n"


def test_repo_search_and_map_work_on_a_small_tree(workspace):
    (workspace / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (workspace / "b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")

    found = _call("repo_search", {"path": str(workspace), "query": "alpha", "limit": 5})
    assert "a.py" in found["result"]["content"][0]["text"]

    mapped = _call("repo_map", {"path": str(workspace), "max_files": 10})
    text = mapped["result"]["content"][0]["text"]
    assert "a.py" in text or "alpha" in text


def test_packs_are_listed_without_a_model():
    listed = _call("list_packs")
    payload = json.loads(listed["result"]["content"][0]["text"])
    keys = {pack["key"] for pack in payload}
    assert {"legal", "forensics"} <= keys


def test_an_unknown_pack_is_an_error_result():
    payload = _call("pack_profile", {"key": "does-not-exist"})
    assert payload["result"]["isError"] is True
