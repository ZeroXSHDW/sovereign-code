"""Tests for the per-client configuration writers."""

from __future__ import annotations

import json
import subprocess
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
    assert config["model"] == "sovereign/auto"
    local = config["providers"]["local"]
    assert local["package"] == "@opencode/ai/providers/openai-compatible"
    assert local["settings"]["baseURL"] == "http://127.0.0.1:11434/v1"
    assert local["models"]["qwen3-coder:30b"]["capabilities"]["tools"] is True
    assert config["mcp"]["servers"]["sovereign"]["type"] == "local"
    assert config["mcp"]["servers"]["sovereign"]["command"][-2:] == ["sovereign_code", "mcp"]


def test_opencode_config_is_native_v2_and_adds_coding_helpers() -> None:
    config = client_setup.opencode_config()
    # V2 maps and ordered rules, not the deprecated V1 shapes.
    assert "provider" not in config
    assert "permission" not in config
    assert "providers" in config and "permissions" in config
    assert isinstance(config["permissions"], list)
    assert any(rule["action"] == "shell" for rule in config["permissions"])
    assert config["agents"]["reviewer"]["mode"] == "subagent"
    assert config["agents"]["reviewer"]["permissions"] == [
        {"action": "edit", "resource": "*", "effect": "deny"}
    ]
    assert {"check", "review", "plan"} <= set(config["commands"])
    assert config["experimental"]["todo"] is True
    assert config["experimental"]["background_compaction"] is True
    assert config["formatter"] is True
    assert ".venv/**" in config["watcher"]["ignore"]
    # The ponytail ruleset is pinned so an install keeps the lazy-senior-dev
    # guard even before the user opens a fresh clone.
    assert "@dietrichgebert/ponytail" in config["plugins"]


def test_ponytail_installers_are_graceful_without_clis(monkeypatch) -> None:
    """A missing CLI yields a message, never a crash or a hanging subprocess."""
    monkeypatch.setattr(client_setup.shutil, "which", lambda _name: None)
    assert client_setup.install_ponytail() == "codex not installed"
    assert client_setup.install_ponytail_claude() == "claude not installed"
    assert client_setup.install_ponytail_qwen() == "qwen not installed"


def test_codex_mcp_block_carries_the_computer_env(tmp_path) -> None:
    """Full computer control is pinned, not left to the server's default."""
    path = tmp_path / "config.toml"
    client_setup.install_codex_mcp(path)
    text = path.read_text(encoding="utf-8")
    assert 'env = ["SOVEREIGN_MCP_COMPUTER=1"]' in text


def test_claude_desktop_sovereign_entry_carries_computer_env(tmp_path) -> None:
    path = tmp_path / "claude_desktop_config.json"
    client_setup.install_claude_desktop_mcp(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["sovereign"]["env"]["SOVEREIGN_MCP_COMPUTER"] == "1"


def test_claude_code_mcp_registers_complementary_servers(monkeypatch) -> None:
    """Claude Code gets the reference servers and the computer-control env."""
    calls: list[list[str]] = []
    results = iter(
        [
            subprocess.CompletedProcess([], 0, "", ""),  # remove
            subprocess.CompletedProcess([], 0, "", ""),  # add sovereign
        ]
    )
    monkeypatch.setattr(client_setup.shutil, "which", lambda _name: "/usr/bin/claude")

    def fake_run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        cmd = list(args[0]) if args and isinstance(args[0], list) else []
        calls.append(cmd)
        if "-e" in cmd:  # the sovereign add with env
            return next(results)
        if "sovereign" in cmd and "--" in cmd:  # the sovereign add
            return next(results)
        return subprocess.CompletedProcess([], 0, "", "")  # complementary adds

    monkeypatch.setattr(client_setup.subprocess, "run", fake_run)
    assert (
        client_setup.install_claude_code_mcp()
        == "added (filesystem:added, memory:added, playwright:added, git:added, fetch:added)"
    )
    # The sovereign entry carries the explicit computer-control env.
    sovereign_add = next(c for c in calls if "sovereign" in c and "-e" in c)
    assert "SOVEREIGN_MCP_COMPUTER=1" in sovereign_add


def test_unsupported_clients_reports_unknown_majors(monkeypatch) -> None:
    monkeypatch.setattr(client_setup.shutil, "which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr(
        client_setup,
        "client_cli_version",
        lambda name: "0.999.0" if name == "codex" else "3.0.0",
    )
    unsupported = client_setup.unsupported_clients()
    assert unsupported["codex"] == "0.999.0"
    assert unsupported["claude"] == "3.0.0"


def test_supported_client_versions_are_not_reported(monkeypatch) -> None:
    monkeypatch.setattr(client_setup.shutil, "which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr(
        client_setup,
        "client_cli_version",
        lambda name: "0.163.0" if name == "codex" else "2.1.0",
    )
    assert client_setup.unsupported_clients() == {}


def test_opencode_cloud_provider_is_opt_in() -> None:
    """A local-first install must not put a remote provider in the config.

    Writing the OpenRouter block unconditionally meant a prompt typed in
    OpenCode could leave the machine without the user asking for it.
    """
    local_only = client_setup.opencode_config()
    assert "openrouter" not in local_only["providers"]

    with_cloud = client_setup.opencode_config(include_cloud=True)
    assert "moonshotai/kimi-k3" in with_cloud["providers"]["openrouter"]["models"]


def test_install_opencode_mcp_does_not_add_a_cloud_provider(tmp_path) -> None:
    path = tmp_path / "opencode.json"
    client_setup.install_opencode_mcp(path)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert "openrouter" not in written["providers"]
    assert "sovereign" in written["providers"]

    client_setup.install_opencode_mcp(path, include_cloud=True)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert "openrouter" in written["providers"]


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
                "permission": {"bash": "deny"},
                "mcp": {"sovereign": {"type": "local", "command": ["/usr/bin/python", "-m"]}},
            }
        )
    )
    client_setup.install_opencode_mcp(path)
    data = json.loads(path.read_text())
    command = data["mcp"]["servers"]["sovereign"]["command"]
    assert "sovereign_code" in command
    capabilities = data["providers"]["local"]["models"]["qwen3-coder:30b"]["capabilities"]
    assert capabilities["tools"] is True
    assert {"action": "shell", "resource": "*", "effect": "deny"} in data["permissions"]
    # The V1 input was translated, not copied through.
    assert "provider" not in data
    assert "permission" not in data


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
    # Claude Code 2.1 added the Fable tier; unset, the picker falls through to
    # the bridge's default alias instead of a chosen route.
    assert env["ANTHROPIC_DEFAULT_FABLE_MODEL"] == "claude-fable-5"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "claude-haiku-4-5"
    # Removed from Claude Code 2.1: a dead knob is drift, not a setting.
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in env
    # Every slot lands on a route the local catalog can serve.
    from sovereign_code.tier_gateway import catalog_ids

    known = catalog_ids()
    routes = client_setup.claude_slot_routes(path)
    assert routes["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deep"
    assert routes["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "ultra"
    assert routes["ANTHROPIC_DEFAULT_FABLE_MODEL"] == "ultra"
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


def test_opencode_config_matches_the_2x_schema() -> None:
    """The keys OpenCode 2.x accepts — checked against opencode.ai/config.json.

    `enabled` on a server and a custom `small_model` both fail the current
    schema, and the server map may only live under `mcp.servers`.
    """
    config = client_setup.opencode_config()
    assert "small_model" not in config
    assert set(config["mcp"]) <= {"servers", "timeout"}
    allowed = {
        "type",
        "command",
        "cwd",
        "environment",
        "disabled",
        "codemode",
        "timeout",
        "protocol",
        "url",
        "headers",
        "oauth",
    }
    for name, server in config["mcp"]["servers"].items():
        assert "enabled" not in server, name
        assert set(server) <= allowed, name


def test_install_opencode_mcp_moves_the_v1_server_map(tmp_path) -> None:
    """A V1 top-level map is migrated, not copied next to `servers`."""
    path = tmp_path / "opencode.json"
    path.write_text(
        json.dumps(
            {
                "mcp": {
                    "docs": {"type": "local", "command": ["docs"], "enabled": True},
                    "off": {"type": "remote", "url": "http://127.0.0.1:1", "enabled": False},
                }
            }
        ),
        encoding="utf-8",
    )
    client_setup.install_opencode_mcp(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data["mcp"]["servers"]
    assert "docs" not in data["mcp"]
    assert servers["docs"]["command"] == ["docs"]
    assert "enabled" not in servers["docs"]
    assert servers["off"]["disabled"] is True


def test_backups_keep_only_the_newest_five(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"live": 1}', encoding="utf-8")
    for minute in range(10):
        (tmp_path / f"settings.json.bak-20260101-0000{minute:02d}").write_text(
            f'{{"old": {minute}}}', encoding="utf-8"
        )
    client_setup._backup(path)
    assert len(list(tmp_path.glob("settings.json.bak-*"))) == client_setup.BACKUP_KEEP


def test_backup_skips_an_identical_copy(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    client_setup._backup(path)
    before = set(tmp_path.glob("settings.json.bak-*"))
    client_setup._backup(path)
    assert set(tmp_path.glob("settings.json.bak-*")) == before
