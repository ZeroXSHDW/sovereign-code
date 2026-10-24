"""Tests for the client launch plans and the OpenCode model pinning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code import clients
from sovereign_code.clients import (
    CLIENT_ROLE_ALIAS,
    local_clients,
    plan_launch,
    resolve_client_models,
)
from sovereign_code.config import Settings
from sovereign_code.models import build_views


@pytest.fixture
def project(tmp_path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path


def _views(*tags: str) -> dict:
    payload = {"models": [{"name": tag, "size": (4 * 1024**3), "details": {}} for tag in tags]}
    return build_views(payload, None)


def test_resolve_client_models_returns_every_client():
    views = _views("qwen3-coder:30b", "qwen3.5:4b")
    resolved = resolve_client_models(views, free_gb=8.0)
    assert set(resolved) == set(CLIENT_ROLE_ALIAS)
    for client, (alias, tag) in resolved.items():
        assert alias
        assert tag, f"{client} has no resolved model"


def test_resolved_models_match_the_router_choice():
    """The displayed model has to be the model the client will actually run."""
    views = _views("qwen3-coder:30b")
    resolved = resolve_client_models(views, free_gb=8.0)
    for _client, (_alias, tag) in resolved.items():
        assert tag in views
        assert views[tag].installed


def test_resolve_client_models_survives_an_empty_machine():
    resolved = resolve_client_models(_views(), free_gb=8.0)
    assert set(resolved) == set(CLIENT_ROLE_ALIAS)
    assert all(alias for alias, _tag in resolved.values())


def test_local_clients_reports_the_resolved_models(project):
    """The displayed model has to be the model the client will actually run."""
    views = _views("qwen3-coder:30b")
    resolved = resolve_client_models(views, free_gb=8.0)
    clients = local_clients(resolved)
    assert clients
    for info in clients:
        if info.key == "claude":
            # Claude Code follows the quality route, and its picker maps onto
            # the local models.
            assert "best" in info.model
            assert "sonnet" in info.model
            continue
        if info.key == "codium":
            assert "Continue" in info.model
            continue
        tag = resolved.get(info.key, ("", ""))[1]
        if tag:
            assert tag in info.model, f"{info.key} shows {info.model!r}, not {tag!r}"


def test_local_clients_falls_back_to_the_defaults():
    clients = local_clients(None)
    assert clients
    assert all(info.model for info in clients)


def test_plan_launch_sets_the_local_environment(project, codex_home):
    # The local Codex profile points at the tier gateway's Responses API.
    plan = plan_launch("codex", project, Settings(), "auto")
    assert plan.argv[0] == "codex"
    assert "--oss" not in plan.argv
    assert "-m" not in plan.argv
    assert plan.env["CODEX_HOME"].endswith("config/codex")
    assert plan.env["SOVEREIGN_API_KEY"] == "local"


def test_plan_launch_rejects_a_missing_directory(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        plan_launch("codex", tmp_path / "nope", Settings(), "qwen3-coder:30b")


def test_plan_launch_qwen_sets_home_and_approval_mode(project):
    plan = plan_launch("qwen", project, Settings(), "qwen3.5:9b", yolo=True)
    assert plan.argv[0] == "qwen"
    assert plan.argv[1:3] == ["--model", "qwen3.5:9b"]
    assert plan.argv[-1] == "yolo"
    assert plan.env["QWEN_HOME"].endswith("qwen")


def test_plan_launch_qwen_defaults_to_normal_approval(project):
    plan = plan_launch("qwen", project, Settings(), "qwen3.5:9b")
    assert "--approval-mode" in plan.argv
    assert plan.argv[-1] == "default"


def test_plan_launch_codex_cloud_uses_the_account_login(project):
    plan = plan_launch("codex", project, Settings(), "auto", cloud=True)
    assert plan.argv == ["codex", "-C", str(project)]
    assert "CODEX_HOME" not in plan.env
    assert plan.model == "ChatGPT (cloud)"


def test_plan_launch_claude_cloud_has_no_local_overrides(project):
    plan = plan_launch("claude", project, Settings(), "auto", cloud=True)
    assert plan.argv == ["claude"]
    assert plan.model == "Claude (cloud)"


def test_plan_launch_codium_points_at_the_project(project):
    plan = plan_launch("codium", project, Settings(), "auto")
    assert plan.argv[0] == "codium"
    assert plan.argv[1] == str(project)


def test_plan_launch_rejects_an_unknown_client(project):
    with pytest.raises(ValueError, match="unsupported client"):
        plan_launch("not-a-client", project, Settings(), "auto")


def test_claude_launch_env_flows_from_the_same_base_as_install(project, monkeypatch) -> None:
    """The launch env and the installed settings share one base, so a slot added
    in one cannot silently drift out of the other."""
    from sovereign_code.client_setup import CLAUDE_LOCAL_ENV
    from sovereign_code.tier_gateway import CLAUDE_SLOT_MODELS

    plan = plan_launch("claude", project, Settings(), "auto")
    env = plan.env
    # Every key the install writes is present in the launch env (though the
    # launch sets a dynamic bridge URL on top).
    for key in CLAUDE_LOCAL_ENV:
        assert key in env, key
    # Every picker slot is populated with a model id.
    for slot in CLAUDE_SLOT_MODELS:
        assert env.get(slot), slot
    # Authentication and context budgets match the shared base.
    assert env["ANTHROPIC_AUTH_TOKEN"] == CLAUDE_LOCAL_ENV["ANTHROPIC_AUTH_TOKEN"]
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "65536"


def test_the_codex_catalog_describes_the_local_routes() -> None:
    catalog = clients.codex_model_catalog()
    slugs = {model["slug"] for model in catalog["models"]}
    assert {"best", "auto", "deep", "balanced", "ultra", "fast"} <= slugs
    for model in catalog["models"]:
        # Codex refuses an entry without instructions.
        assert model["model_messages"]["instructions_template"]
        # The context window has to be the one the model really has, or Codex
        # sends a prompt the local model cannot hold.
        assert model["context_window"] == model["max_context_window"]
        assert 8192 <= model["context_window"] <= 65536


def test_the_codex_profile_points_at_the_catalog(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(clients, "codex_home_path", lambda: tmp_path / "codex")
    path = clients.write_codex_profile()
    text = path.read_text(encoding="utf-8")
    assert "model_catalog_json" in text
    catalog = tmp_path / "codex" / "model-catalog.json"
    assert catalog.is_file()
    assert str(catalog) in text
    assert (tmp_path / "codex" / "config.toml").read_text(encoding="utf-8") == text
