"""Tests for the client launch plans and the OpenCode model pinning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sovereign_code import clients
from sovereign_code.clients import (
    CLIENT_ROLE_ALIAS,
    _pin_opencode_model,
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


def test_pin_opencode_model_writes_the_config_content(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "sovereign_code.tools.read_text",
        lambda _path: json.dumps(
            {"provider": {"local": {"models": {"qwen3-coder:30b": {"name": "Qwen"}}}}}
        ),
    )
    env: dict[str, str] = {}
    assert _pin_opencode_model(env, "qwen3-coder:30b") is True
    payload = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert payload["model"] == "local/qwen3-coder:30b"


def test_pin_opencode_model_refuses_an_unlisted_model(monkeypatch, tmp_path):
    """Pinning a model OpenCode does not know makes it fail to start."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "sovereign_code.tools.read_text",
        lambda _path: json.dumps(
            {"provider": {"ollama": {"models": {"other:1b": {"name": "Other"}}}}}
        ),
    )
    env: dict[str, str] = {}
    assert _pin_opencode_model(env, "qwen3-coder:30b") is False
    assert "OPENCODE_CONFIG_CONTENT" not in env


def test_pin_opencode_model_works_without_a_user_config(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("sovereign_code.tools.read_text", lambda _path: "")
    env: dict[str, str] = {}
    assert _pin_opencode_model(env, "qwen3-coder:30b") is True
    assert "OPENCODE_CONFIG_CONTENT" in env


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
