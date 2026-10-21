"""Tests for the headless agent command builders."""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code.agents import MODES, build_headless, make_agent_runner, run_headless
from sovereign_code.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def target(tmp_path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def _plan(client: str, mode: str = "local", target: Path | None = None, **kwargs):
    if target is None:
        raise RuntimeError("target fixture is required")
    return build_headless(
        client,
        mode,
        target,
        "make it faster",
        Settings(),
        kwargs.pop("agent_model", "qwen3.5:4b"),
        **kwargs,
    )


def test_qwen_prompt_is_positional(target):
    """`-p` makes qwen wait for stdin, so an inherited terminal hangs forever."""
    plan = _plan("qwen", target=target)
    assert plan.argv[0] == "qwen"
    assert plan.argv[-1] == "make it faster"
    assert "-p" not in plan.argv
    assert "--approval-mode" in plan.argv
    assert plan.argv[plan.argv.index("--approval-mode") + 1] == "auto-edit"


def test_qwen_unattended_approves_everything(target):
    plan = _plan("qwen", target=target, unattended=True)
    assert plan.argv[plan.argv.index("--approval-mode") + 1] == "yolo"


def test_codex_uses_the_local_profile(target):
    plan = _plan("codex", target=target)
    assert plan.argv[:2] == ["codex", "exec"]
    assert "--profile" in plan.argv
    assert plan.argv[plan.argv.index("--profile") + 1] == "local"
    assert "--skip-git-repo-check" in plan.argv


def test_codex_cloud_mode_has_no_local_profile(target):
    plan = _plan("codex", mode="cloud", target=target)
    assert "--profile" not in plan.argv
    assert "--sandbox" in plan.argv


def test_claude_cloud_mode_leaves_the_model_alone(target):
    """A cloud run must not pin the local gateway model."""
    plan = _plan("claude", mode="cloud", target=target)
    assert "--model" not in plan.argv
    assert plan.argv[:2] == ["claude", "-p"]


def test_claude_local_mode_pins_the_model(target):
    plan = _plan("claude", target=target)
    assert "--model" in plan.argv
    assert plan.argv[plan.argv.index("--model") + 1]


def test_opencode_local_mode_uses_the_ollama_provider(target):
    plan = _plan("opencode", target=target)
    assert plan.argv[0] == "opencode"
    assert plan.argv[1] == "run"
    assert plan.argv[plan.argv.index("-m") + 1] == "ollama/qwen3.5:4b"


def test_opencode_cloud_mode_does_not_pin_a_model(target):
    plan = _plan("opencode", mode="cloud", target=target)
    assert "-m" not in plan.argv


def test_cloud_mode_keeps_the_user_environment(target):
    plan = _plan("codex", mode="cloud", target=target)
    assert "PATH" in plan.env


def test_unknown_client_is_rejected(target):
    with pytest.raises(ValueError, match="unknown client"):
        _plan("emacs", target=target)


def test_unknown_mode_is_rejected(target):
    with pytest.raises(ValueError, match="unknown mode"):
        _plan("codex", mode="offline", target=target)


def test_qwen_refuses_cloud_mode(target):
    with pytest.raises(ValueError, match="only runs locally"):
        _plan("qwen", mode="cloud", target=target)


def test_every_client_supports_both_modes():
    assert set(MODES) == {"local", "cloud"}


def test_run_headless_reports_a_missing_binary(target):
    from dataclasses import replace

    plan = _plan("codex", target=target)
    broken = replace(plan, argv=["definitely-not-installed-xyz", *plan.argv[1:]])
    ok, output = run_headless(broken, timeout=5)
    assert not ok
    assert "not installed" in output


def test_runner_swallows_a_bad_client(target):
    runner = make_agent_runner("emacs", "local", target, Settings(), "m", False)
    ok, output = runner("hello")
    assert not ok
    assert "unknown client" in output
