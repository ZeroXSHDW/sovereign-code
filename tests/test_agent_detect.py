"""Tests for coding-agent detection."""

from __future__ import annotations

from pathlib import Path
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


@patch("sovereign_code.agent_detect.system_binary", return_value=None)
def test_detect_agent_not_installed(mock_system_binary):
    report = detect_agent("cursor")
    assert report.installed is False
    assert report.command is None


def test_agent_report_to_dict_roundtrip() -> None:
    report = detect_agent("cursor")
    d = report.to_dict()
    assert d["key"] == "cursor"
    assert d["installed"] == report.installed
    assert "config_dir" in d


def test_version_helpers_handle_failure(monkeypatch) -> None:
    import subprocess

    from sovereign_code.agent_detect import _version

    assert _version(None) is None
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
    )
    assert _version("/bin/false") is None


def test_detect_agent_omits_empty_version(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "fake-agent"
    binary.write_text("#!/bin/sh\necho ''\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setattr("sovereign_code.agent_detect.system_binary", lambda _name: str(binary))
    report = detect_agent("cursor")
    assert "version" not in report.details


def test_installed_and_missing_helpers() -> None:
    from sovereign_code.agent_detect import (
        agent_keys_installed,
        any_installed,
        installed_agents,
        missing_agents,
    )

    any_installed()  # does not raise
    assert isinstance(installed_agents(), list)
    assert isinstance(missing_agents(), list)
    assert isinstance(agent_keys_installed(), list)


def test_summarize_with_and_without_agents(monkeypatch) -> None:
    from sovereign_code.agent_detect import summarize

    monkeypatch.setattr(
        "sovereign_code.agent_detect.installed_agents",
        list,
    )
    assert "No coding agents" in summarize()

    class FakeReport:
        name = "Test"
        command = None
        config_dir = None
        app_bundle = None

    monkeypatch.setattr(
        "sovereign_code.agent_detect.installed_agents",
        lambda: [FakeReport()],
    )
    assert "Test" in summarize()
