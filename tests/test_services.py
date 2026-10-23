"""Tests for the launchd services behind the local stack."""

from __future__ import annotations

import plistlib

from sovereign_code import services


def test_the_stack_is_a_known_set_of_services() -> None:
    labels = [service.label for service in services.service_definitions()]
    assert labels == [
        "com.user.sovereign.gateway",
        "com.user.sovereign.tier",
        "com.user.sovereign.bridge",
        "com.user.sovereign.mcp",
    ]
    # The always-on chat web UI and guardian were removed to stop paying RAM
    # and CPU for a 24/7 chat/restart loop.
    assert "com.user.sovereign.webchat" not in labels
    assert "com.user.sovereign.guardian" not in labels


def test_old_chat_and_guardian_jobs_are_retired(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(services, "AGENT_DIR", tmp_path)
    stale = tmp_path / "com.user.sovereign.webchat.plist"
    stale.write_text("old", encoding="utf-8")
    monkeypatch.setattr(services, "is_loaded", lambda label: False)
    rows = services.retire_services()
    assert not stale.exists()
    assert any("webchat" in label for label, _result in rows)


def test_the_plist_starts_the_service_and_brings_it_back() -> None:
    service = services.service_definitions()[1]
    payload = plistlib.loads(services.plist_text(service).encode("utf-8"))
    assert payload["Label"] == service.label
    assert payload["RunAtLoad"] is True
    # It comes back after a crash, but not after a clean exit: a clean exit
    # means another instance already owns the port.
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["LimitLoadToSessionType"] == "Aqua"
    assert payload["ProgramArguments"] == list(service.argv)


def test_the_gateway_service_never_execs_a_script_in_documents() -> None:
    # A launchd job may read files in ~/Documents but may not execute a
    # script there: the gateway has to go through its interpreter.
    service = services.service_definitions()[0]
    assert service.argv[0] == "/bin/bash"
    joined = " ".join(service.argv)
    assert "venv/bin/python3" in joined
    assert "venv/bin/litellm" in joined
    assert "run_gateway.sh" not in joined


def test_the_gateway_service_leaves_a_running_gateway_alone() -> None:
    joined = " ".join(services.gateway_argv(4000))
    assert "/dev/tcp/127.0.0.1/4000" in joined
    assert "exit 0" in joined


def test_the_services_use_log_files_of_their_own() -> None:
    # A log file another app created cannot be opened by launchd, so the
    # services must not share the logs the old detached processes wrote.
    names = {service.log_name for service in services.service_definitions()}
    assert len(names) == len(services.service_definitions())
    assert "bridge.log" not in names
    assert "gateway.log" not in names


def test_a_log_file_launchd_cannot_open_is_moved_aside(tmp_path, monkeypatch) -> None:
    log = tmp_path / "service-tier.log"
    log.write_text("old output", encoding="utf-8")
    monkeypatch.setattr(services, "_has_provenance", lambda path: True)
    monkeypatch.setattr(services, "LOG_DIR", tmp_path)
    services._usable_log(log)
    assert not log.exists()
    assert list(tmp_path.glob("service-tier.log.*.old"))


def test_a_log_file_launchd_can_open_is_kept(tmp_path, monkeypatch) -> None:
    log = tmp_path / "service-tier.log"
    log.write_text("old output", encoding="utf-8")
    monkeypatch.setattr(services, "_has_provenance", lambda path: False)
    monkeypatch.setattr(services, "LOG_DIR", tmp_path)
    services._usable_log(log)
    assert log.read_text(encoding="utf-8") == "old output"


def test_the_session_environment_points_at_the_tier_gateway() -> None:
    values = services.session_env()
    assert values["CODEX_APP_SERVER_OPENAI_BASE_URL"].endswith("/v1")
    assert values["SOVEREIGN_API_KEY"] == "local"


def test_the_cloud_keys_are_read_not_sourced(tmp_path, monkeypatch) -> None:
    root = tmp_path / "gateway"
    root.mkdir()
    (root / "cloud.env").write_text(
        "# a comment\nOPENAI_API_KEY='sk-test'\nexport OTHER=1\n\nbroken line\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(services, "gateway_root", lambda: root)
    values = services.cloud_env()
    assert values == {"OPENAI_API_KEY": "sk-test", "OTHER": "1"}


def test_a_service_with_keys_is_written_private(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(services, "AGENT_DIR", tmp_path)
    monkeypatch.setattr(services, "LOG_DIR", tmp_path / "logs")
    service = services.service_definitions()[0]
    service.env = {"OPENAI_API_KEY": "sk-test"}
    path = services.write_plist(service)
    assert path.stat().st_mode & 0o777 == 0o600
