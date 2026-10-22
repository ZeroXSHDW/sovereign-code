"""Tests for the guardian: the stack stays up, the clients stay local."""

from __future__ import annotations

import json

from sovereign_code import client_setup, guardian


def _local_claude_settings(tmp_path) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4001",
                    "ANTHROPIC_MODEL": "best",
                }
            }
        ),
        encoding="utf-8",
    )


def _local_codex_config(tmp_path) -> None:
    (tmp_path / "config.toml").write_text(
        'model = "best"\nmodel_provider = "sovereign-tier"\n'
        'openai_base_url = "http://127.0.0.1:4010/v1"\n'
        "\n[model_providers.sovereign-tier]\n"
        'name = "Sovereign tier gateway"\n'
        'base_url = "http://127.0.0.1:4010/v1"\n'
        "\n[model_providers.sovereign-tier.auth]\n"
        'command = "/bin/echo"\n'
        'args = ["local"]\n',
        encoding="utf-8",
    )


def _patch_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(client_setup, "codex_config_path", lambda *a, **k: tmp_path / "config.toml")
    monkeypatch.setattr(
        client_setup, "claude_settings_path", lambda *a, **k: tmp_path / "settings.json"
    )


def test_a_drifted_config_is_put_back(tmp_path, monkeypatch) -> None:
    _patch_home(monkeypatch, tmp_path)
    (tmp_path / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    # The saved cloud copy is what says the local mode is the current one.
    (tmp_path / "config.toml.sovereign-cloud").write_text('model = "gpt-5-codex"\n', "utf-8")
    repaired = guardian.repair_clients()
    assert "ChatGPT config" in repaired
    assert client_setup.codex_forced_local() is True


def test_a_config_in_cloud_mode_is_left_alone(tmp_path, monkeypatch) -> None:
    _patch_home(monkeypatch, tmp_path)
    # No saved cloud copy: the user asked for the cloud, so nothing is forced.
    (tmp_path / "config.toml").write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    assert guardian.repair_clients() == []
    assert 'model = "gpt-5-codex"' in (tmp_path / "config.toml").read_text(encoding="utf-8")


def test_the_claude_settings_are_put_back(tmp_path, monkeypatch) -> None:
    _patch_home(monkeypatch, tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"env": {}}), encoding="utf-8")
    (tmp_path / "settings.json.sovereign-cloud").write_text("{}\n", encoding="utf-8")
    repaired = guardian.repair_clients()
    assert "Claude settings" in repaired
    assert client_setup.claude_forced_local() is True


def test_a_local_stack_is_left_alone(tmp_path, monkeypatch) -> None:
    _patch_home(monkeypatch, tmp_path)
    _local_codex_config(tmp_path)
    _local_claude_settings(tmp_path)
    (tmp_path / "config.toml.sovereign-cloud").write_text("x\n", encoding="utf-8")
    (tmp_path / "settings.json.sovereign-cloud").write_text("{}\n", encoding="utf-8")
    assert guardian.repair_clients() == []
