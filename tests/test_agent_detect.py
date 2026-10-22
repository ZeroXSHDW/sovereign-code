"""Tests for coding-agent detection."""

from __future__ import annotations

from unittest.mock import patch

from sovereign_code.agent_detect import (
    AgentReport,
    detect_agent,
    detect_all,
    gateway_targets,
    installed_agents,
    summarize,
)


def test_detect_agent_known_key():
    report = detect_agent("claude")
    assert isinstance(report, AgentReport)
    assert report.key == "claude"
    assert report.name == "Claude"


def test_detect_all_returns_list():
    reports = detect_all()
    assert isinstance(reports, list)
    assert len(reports) == 14
    keys = {r.key for r in reports}
    expected = {
        "opencode",
        "codex",
        "claude",
        "qwen",
        "cursor",
        "windsurf",
        "zed",
        "aider",
        "continue",
        "copilot",
        "junie",
        "amp",
        "cline",
        "roo",
    }
    assert keys == expected


def test_detect_all_installed_first():
    reports = detect_all()
    installed_flags = [r.installed for r in reports]
    # once a False appears, no True should follow
    seen_false = False
    for flag in installed_flags:
        if flag is False:
            seen_false = True
        elif seen_false and flag is True:
            raise AssertionError("installed agent appeared after a missing one")


def test_installed_agents_only_installed():
    for r in installed_agents():
        assert r.installed is True


def test_gateway_targets():
    targets = gateway_targets()
    assert targets["opencode"] == "http://127.0.0.1:4010/v1"
    assert targets["codex"] == "http://127.0.0.1:4010/v1"
    assert targets["claude"] == "http://127.0.0.1:4001"
    assert targets["qwen"] == "http://127.0.0.1:4010/v1"


def test_summarize_returns_text():
    text = summarize()
    assert isinstance(text, str)
    assert "coding agent" in text.lower() or "No coding agents" in text


@patch("sovereign_code.agent_detect.shutil.which", return_value=None)
def test_detect_agent_not_installed(mock_which):
    report = detect_agent("cursor")
    assert report.installed is False
    assert report.command is None
