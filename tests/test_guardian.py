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


def test_port_parses_a_host_port_url_and_defaults_to_zero() -> None:
    # `_port` ingests the bare base URLs Settings holds (e.g. router_url), which
    # never carry a path or trailing slash.
    assert guardian._port("http://127.0.0.1:4010") == 4010
    assert guardian._port("http://127.0.0.1:4010/") == 4010
    assert guardian._port("http://127.0.0.1") == 0
    assert guardian._port("http://127.0.0.1:not-a-port") == 0


def test_port_open_reports_a_closed_port_and_an_open_socket(monkeypatch) -> None:
    # A closed port: connect raises OSError, so the guardian reports it down.
    assert guardian._port_open("127.0.0.1", 1) is False


def test_launchd_first_prefers_launchd_when_loaded(monkeypatch) -> None:
    import sovereign_code.services as services

    calls: list[str] = []
    monkeypatch.setattr(services, "is_loaded", lambda label: True)
    monkeypatch.setattr(services, "kickstart", lambda label: (calls.append("kickstart"), True)[1])

    def fallback() -> bool:
        calls.append("fallback")
        return True

    start = guardian._launchd_first("com.user.test", fallback)
    assert start() is True
    assert calls == ["kickstart"]


def test_launchd_first_falls_back_when_not_loaded(monkeypatch) -> None:
    import sovereign_code.services as services

    monkeypatch.setattr(services, "is_loaded", lambda label: False)

    def fallback() -> bool:
        return True

    start = guardian._launchd_first("com.user.test", fallback)
    assert start() is True


def test_check_restarts_a_down_service(monkeypatch) -> None:
    """A down service is restarted and re-probed until it is up."""
    from sovereign_code import guardian as g

    up = {"value": False}

    def running() -> bool:
        return up["value"]

    def start() -> bool:
        up["value"] = True
        return True

    service = g.Service("Test", 1, "http://127.0.0.1:1", running=running, start=start)
    monkeypatch.setattr(g, "services", lambda settings=None: [service])
    results = g.check(autostart=True)
    assert results[0].name == "Test"
    assert results[0].up is True
    assert results[0].restarted is True


def test_check_reports_a_failed_start(monkeypatch) -> None:
    from sovereign_code import guardian as g

    def running() -> bool:
        return False

    def start() -> bool:
        return False

    service = g.Service("Test", 1, "http://127.0.0.1:1", running=running, start=start)
    monkeypatch.setattr(g, "services", lambda settings=None: [service])
    results = g.check(autostart=True)
    assert results[0].up is False
    assert results[0].restarted is False
    assert results[0].detail == "start failed"


def test_check_does_not_restart_when_autostart_is_off(monkeypatch) -> None:
    from sovereign_code import guardian as g

    starts: list[object] = []

    def running() -> bool:
        return False

    def start() -> bool:
        starts.append(True)
        return True

    service = g.Service("Test", 1, "http://127.0.0.1:1", running=running, start=start)
    monkeypatch.setattr(g, "services", lambda settings=None: [service])
    results = g.check(autostart=False)
    assert results[0].restarted is False
    assert starts == []


def test_service_state_as_dict_is_complete() -> None:
    state = guardian.ServiceState(
        name="tier gateway",
        port=4010,
        url="u",
        up=True,
        restarted=False,
        detail="running",
        note="n",
    )
    d = state.as_dict()
    assert d == {
        "name": "tier gateway",
        "port": 4010,
        "url": "u",
        "up": True,
        "restarted": False,
        "detail": "running",
        "note": "n",
    }


def test_log_writes_only_restarted_services(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(guardian, "LOG_PATH", tmp_path / "guardian.jsonl")
    states = [
        guardian.ServiceState("a", 1, "u", True, restarted=False, detail="running"),
        guardian.ServiceState("b", 2, "u", False, restarted=True, detail="restarted"),
    ]
    guardian.log(states)
    lines = (tmp_path / "guardian.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["service"] == "b"
