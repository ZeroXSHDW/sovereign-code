"""Tests for the per-client configuration writers."""

from __future__ import annotations

import json
import tomllib

from sovereign_code import client_setup

ROUTER = "http://127.0.0.1:4010"

CLOUD_CONFIG = """\
model = "gpt-5-codex"
model_provider = "openai"
notify = ["/tmp/notify"]

[desktop]
followUpQueueMode = "steer"

[analytics]
enabled = true

[mcp_servers.sovereign]
command = "/usr/bin/python"
args = ["-m", "sovereign_code", "mcp"]
"""


def test_opencode_config_has_working_provider_and_mcp() -> None:
    config = client_setup.opencode_config()
    assert config["model"] == "sovereign/best"
    local = config["provider"]["local"]
    assert local["options"]["baseURL"] == "http://127.0.0.1:11434/v1"
    assert local["models"]["qwen3-coder:30b"]["tool_call"] is True
    assert "moonshotai/kimi-k3" in config["provider"]["openrouter"]["models"]
    assert config["mcp"]["sovereign"]["type"] == "local"
    assert config["mcp"]["sovereign"]["command"][-2:] == ["sovereign_code", "mcp"]


def test_codex_mcp_block_is_idempotent(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "x"\n', encoding="utf-8")
    client_setup.install_codex_mcp(path)
    first = path.read_text()
    assert "[mcp_servers.sovereign]" in first
    assert first.count("[mcp_servers.sovereign]") == 1
    client_setup.install_codex_mcp(path)
    assert path.read_text().count("[mcp_servers.sovereign]") == 1
    assert 'model = "x"' in path.read_text()


def test_claude_desktop_config_preserves_existing_keys(tmp_path) -> None:
    path = tmp_path / "claude_desktop_config.json"
    path.write_text(json.dumps({"deploymentMode": "1p", "mcpServers": {"other": {}}}))
    client_setup.install_claude_desktop_mcp(path)
    data = json.loads(path.read_text())
    assert data["deploymentMode"] == "1p"
    assert "other" in data["mcpServers"]
    assert data["mcpServers"]["sovereign"]["args"][-1] == "mcp"
    assert data["mcpServers"]["sovereign"]["command"].endswith("python")


def test_opencode_merge_updates_stale_mcp_command(tmp_path) -> None:
    path = tmp_path / "opencode.json"
    path.write_text(
        json.dumps(
            {
                "model": "local/qwen3-coder:30b",
                "provider": {"local": {"models": {"qwen3-coder:30b": {"name": "old"}}}},
                "mcp": {"sovereign": {"type": "local", "command": ["/usr/bin/python", "-m"]}},
            }
        )
    )
    client_setup.install_opencode_mcp(path)
    data = json.loads(path.read_text())
    command = data["mcp"]["sovereign"]["command"]
    assert "sovereign_code" in command
    assert data["provider"]["local"]["models"]["qwen3-coder:30b"]["tool_call"] is True


def test_forced_local_pins_the_app_to_the_local_gateway(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "best"
    assert data["model_provider"] == "sovereign-tier"
    assert data["openai_base_url"] == "http://127.0.0.1:4010/v1"
    provider = data["model_providers"]["sovereign-tier"]
    assert provider["base_url"] == "http://127.0.0.1:4010/v1"
    assert provider["wire_api"] == "responses"
    # The token comes from a command, so no environment variable is needed and
    # the app never asks for an OpenAI sign-in.
    assert provider["auth"]["command"]
    assert "requires_openai_auth" not in provider
    assert "env_key" not in provider
    assert data["analytics"]["enabled"] is False
    # The app's own settings survive the rewrite.
    assert data["desktop"]["followUpQueueMode"] == "steer"
    assert data["mcp_servers"]["sovereign"]["args"] == ["-m", "sovereign_code", "mcp"]
    assert data["notify"] == ["/tmp/notify"]
    assert client_setup.codex_forced_local(path, router_url=ROUTER) is True


def test_forced_local_is_idempotent(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    first = path.read_text(encoding="utf-8")
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    assert path.read_text(encoding="utf-8") == first
    assert first.count("[model_providers.sovereign-tier]") == 1
    assert first.count("[model_providers.sovereign-tier.auth]") == 1


def test_forced_local_keeps_the_cloud_config_once(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    backup = client_setup.codex_cloud_backup_path(path)
    assert backup.read_text(encoding="utf-8") == CLOUD_CONFIG
    # A later run must not overwrite the backup with the already-rewritten file.
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    assert backup.read_text(encoding="utf-8") == CLOUD_CONFIG


def test_forced_local_drops_a_leftover_env_key(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        CLOUD_CONFIG
        + "\n[model_providers.sovereign-tier]\n"
        + 'name = "Sovereign tier gateway"\n'
        + 'base_url = "http://127.0.0.1:4010/v1"\n'
        + 'env_key = "SOVEREIGN_API_KEY"\n'
        + "requires_openai_auth = true\n"
        + 'wire_api = "responses"\n',
        encoding="utf-8",
    )
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    provider = data["model_providers"]["sovereign-tier"]
    # An env_key would make Codex ask for the variable and put the sign-in gate back.
    assert "env_key" not in provider
    assert "requires_openai_auth" not in provider
    assert provider["auth"]["command"]


def test_forced_local_does_not_save_a_local_config_as_the_cloud_copy(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    # The user drops the saved cloud copy; a new run must not pretend the
    # already-local config is the cloud one.
    client_setup.codex_cloud_backup_path(path).unlink()
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    assert not client_setup.codex_cloud_backup_path(path).exists()


def test_restore_codex_cloud_puts_the_original_back(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    assert client_setup.restore_codex_cloud(path) == path
    assert path.read_text(encoding="utf-8") == CLOUD_CONFIG
    assert not client_setup.codex_cloud_backup_path(path).exists()
    assert client_setup.codex_forced_local(path, router_url=ROUTER) is False


def test_restore_codex_cloud_without_a_backup_is_a_no_op(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    assert client_setup.restore_codex_cloud(path) is None
    assert path.read_text(encoding="utf-8") == CLOUD_CONFIG


def test_codex_needs_openai_signin_is_false_when_pinned_local(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    assert client_setup.codex_needs_openai_signin(path) is True
    client_setup.install_codex_forced_local(path, router_url=ROUTER)
    assert client_setup.codex_needs_openai_signin(path) is False


def test_codex_needs_openai_signin_is_true_for_an_openai_provider(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "gpt-5-codex"\nmodel_provider = "openai"\n', encoding="utf-8")
    assert client_setup.codex_needs_openai_signin(path) is True


def test_codex_probe_local_reports_an_unusable_config(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CLOUD_CONFIG, encoding="utf-8")
    ok, detail = client_setup.codex_probe_local(path)
    assert ok is False
    assert "openai" in detail or "base_url" in detail


def test_claude_local_and_cloud_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
    assert client_setup.claude_forced_local(path) is False
    client_setup.install_claude_settings(path)
    assert client_setup.claude_forced_local(path) is True
    settings = json.loads(path.read_text())
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4001"
    backup = client_setup.claude_cloud_backup_path(path)
    assert json.loads(backup.read_text())["env"] == {"FOO": "bar"}
    assert client_setup.restore_claude_cloud(path) == path
    assert json.loads(path.read_text())["env"] == {"FOO": "bar"}
    assert not backup.exists()
    assert client_setup.claude_forced_local(path) is False


def test_restore_claude_cloud_strips_the_local_keys_without_a_backup(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
    client_setup.install_claude_settings(path)
    client_setup.claude_cloud_backup_path(path).unlink()
    assert client_setup.restore_claude_cloud(path) == path
    settings = json.loads(path.read_text())
    assert settings["env"] == {"FOO": "bar"}
    assert client_setup.claude_forced_local(path) is False


def test_claude_local_settings_do_not_save_a_local_copy_as_cloud(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
    client_setup.install_claude_settings(path)
    client_setup.claude_cloud_backup_path(path).unlink()
    client_setup.install_claude_settings(path)
    assert not client_setup.claude_cloud_backup_path(path).exists()


def test_claude_settings_map_every_slot_to_a_local_route(tmp_path) -> None:
    path = tmp_path / "settings.json"
    client_setup.install_claude_settings(path)
    env = json.loads(path.read_text(encoding="utf-8"))["env"]
    # The default turn follows the quality route.
    assert env["ANTHROPIC_MODEL"] == "best"
    # The picker slots carry the model id Claude Code knows, so it never
    # complains about a name it does not recognise.
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-5"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-1"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "claude-haiku-4-5"
    # Every slot lands on a route the local catalog can serve.
    from sovereign_code.tier_gateway import catalog_ids

    known = catalog_ids()
    routes = client_setup.claude_slot_routes(path)
    assert routes["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deep"
    assert routes["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "ultra"
    assert routes["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "fast"
    for route in routes.values():
        assert route in known


def test_the_claude_ids_and_the_bridge_map_agree() -> None:
    from sovereign_code import bridge
    from sovereign_code.tier_gateway import CLAUDE_MODEL_ROUTES, CLAUDE_SLOT_MODELS

    for _slot, (model_id, route) in CLAUDE_SLOT_MODELS.items():
        assert bridge.MODEL_MAP[model_id] == route
    assert CLAUDE_MODEL_ROUTES["claude-sonnet-4-5"] == "deep"


def test_configured_models_are_read_back_from_the_client_files(tmp_path) -> None:
    codex = tmp_path / "config.toml"
    codex.write_text('model = "best"\n', encoding="utf-8")
    assert client_setup.codex_configured_model(codex) == "best"
    claude = tmp_path / "settings.json"
    client_setup.install_claude_settings(claude)
    slots = client_setup.claude_configured_models(claude)
    assert slots["ANTHROPIC_MODEL"] == "best"
    assert slots["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-5"
    assert client_setup.claude_slot_routes(claude)["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deep"
