"""Tests for local client detection, profiles, and launch plans."""

import pytest

from sovereign_code import clients
from sovereign_code.config import Settings
from sovereign_code.models import CATALOG, build_views

GIB = 1024**3


def _views(*names):
    tags = {
        "models": [
            {"name": name, "size": int(CATALOG[name].size_gb * GIB), "details": {}}
            for name in names
        ]
    }
    return build_views(tags, None)


def test_resolve_client_models_picks_best_installed():
    resolved = clients.resolve_client_models(_views("qwen2.5-coder:14b", "qwen3.5:4b"), free_gb=20)
    assert resolved["codex"] == ("local-code", "qwen2.5-coder:14b")
    assert resolved["chatgpt"] == ("local-chat", "qwen3.5:4b")
    assert resolved["claude"] == ("local-claude", "qwen3.5:4b")


def test_resolve_client_models_empty_machine():
    resolved = clients.resolve_client_models(build_views({"models": []}, None), free_gb=20)
    assert resolved["codex"] == ("local-code", "")
    assert resolved["qwen"] == ("local-agent", "")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(clients, "LOCAL_AI_ROOT", tmp_path / "local-ai")
    monkeypatch.setattr(clients.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_codex_profile_targets_loopback(home):
    path = clients.write_codex_profile()
    text = path.read_text(encoding="utf-8")

    assert path == home / "local-ai" / "config" / "codex" / "local.config.toml"
    assert 'model = "local-code"' in text
    assert 'base_url = "http://127.0.0.1:4000/v1"' in text
    assert "model_context_window = 32768" in text
    assert "api.openai.com" not in text


def test_codex_launch_requires_profile(home, tmp_path):
    with pytest.raises(ValueError, match="install-clients"):
        clients.plan_launch("codex", tmp_path, Settings())


def test_codex_launch_uses_documents_home(home, tmp_path):
    clients.write_codex_profile()
    plan = clients.plan_launch("codex", tmp_path, Settings())

    assert plan.env["CODEX_HOME"] == str(home / "local-ai" / "config" / "codex")
    assert plan.env["SOVEREIGN_API_KEY"] == "local"


def test_qwen_launch_uses_agent_model(home, tmp_path):
    plan = clients.plan_launch("qwen", tmp_path, Settings(), yolo=True)

    assert plan.argv[:2] == ["qwen", "--model"]
    assert plan.argv[2] == clients.AGENT_MODEL
    assert "yolo" in plan.argv
    assert plan.env["QWEN_HOME"] == str(home / "local-ai" / "qwen")
    assert plan.cwd == tmp_path.resolve()


def test_claude_launch_stays_local(home, tmp_path):
    plan = clients.plan_launch("claude", tmp_path, Settings())

    assert plan.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4000"
    assert plan.env["ANTHROPIC_MODEL"] == clients.CLAUDE_ALIAS
    assert plan.env["ANTHROPIC_API_KEY"] == "local"
    assert "api.anthropic.com" not in " ".join(plan.argv)
    assert plan.note


def test_launch_rejects_missing_directory(home, tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        clients.plan_launch("qwen", tmp_path / "nope", Settings())


def test_wrappers_live_in_documents_and_are_linked(home):
    written = clients.install_client_wrappers()

    assert {path.name for path in written} == {"qwen-local", "codex-local", "claude-local"}
    for path in written:
        assert path.parent == home / "local-ai" / "bin"
        assert path.stat().st_mode & 0o111
        assert "launch" in path.read_text(encoding="utf-8")
        link = home / ".local" / "bin" / path.name
        assert link.is_symlink() and link.readlink() == path


def test_agent_clients_are_marked_agent():
    by_key = {client.key: client for client in clients.local_clients()}

    assert by_key["qwen"].capability == "agent"
    assert by_key["codex"].capability == "chat"
    assert by_key["claude"].capability == "chat"
