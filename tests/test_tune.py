"""Tests for Ollama runtime tuning helpers."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

from sovereign_code import tune
from sovereign_code.tune import (
    desired_env,
    env_drift,
    parse_server_env,
    read_context_length,
    supported,
    write_context_length,
)


def test_desired_env_targets_the_requested_context() -> None:
    env = desired_env(16384)
    assert env["OLLAMA_CONTEXT_LENGTH"] == "16384"
    assert env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
    assert env["OLLAMA_FLASH_ATTENTION"] == "1"


def test_parse_server_env_reads_ps_output() -> None:
    line = (
        "  PID  COMMAND\n"
        " 1234 ollama serve OLLAMA_CONTEXT_LENGTH=32768 OLLAMA_NO_CLOUD=1 "
        "PATH=/usr/bin"
    )
    env = parse_server_env(line)
    assert env["OLLAMA_CONTEXT_LENGTH"] == "32768"
    assert env["OLLAMA_NO_CLOUD"] == "1"
    assert "PATH" not in env


def test_env_drift_reports_missing_and_wrong() -> None:
    drift = env_drift({"OLLAMA_CONTEXT_LENGTH": "65536"}, desired_env(32768))
    keys = [key for key, _now, _want in drift]
    assert "OLLAMA_CONTEXT_LENGTH" in keys
    assert "OLLAMA_KV_CACHE_TYPE" in keys  # missing entirely
    assert env_drift(desired_env(32768), desired_env(32768)) == []


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "db.sqlite"
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, context_length INTEGER)")
        con.execute("INSERT INTO settings (id, context_length) VALUES (1, 65536)")
        con.commit()
    finally:
        con.close()
    return path


def test_context_length_roundtrip(tmp_path: Path) -> None:
    path = _db(tmp_path)
    assert read_context_length(path) == 65536
    assert write_context_length(32768, path) is True
    assert read_context_length(path) == 32768


def test_context_length_handles_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.sqlite"
    assert read_context_length(missing) is None
    assert write_context_length(1, missing) is False


def test_context_length_handles_corrupt_db(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.sqlite"
    path.write_text("not a sqlite database", encoding="utf-8")
    assert read_context_length(path) is None
    assert write_context_length(1, path) is False


def test_read_context_length_returns_none_when_no_row(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite"
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, context_length INTEGER)")
        con.commit()
    finally:
        con.close()
    assert read_context_length(path) is None


def test_supported_returns_bool() -> None:
    assert isinstance(supported(), bool)


def test_current_server_pid_none_when_pgrep_empty(monkeypatch) -> None:
    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    assert tune._current_server_pid() is None


def test_current_server_env_empty_when_no_pid(monkeypatch) -> None:
    monkeypatch.setattr(tune, "_current_server_pid", lambda: None)
    assert tune.current_server_env() == {}


def test_set_session_env_calls_launchctl(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **_k):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    tune.set_session_env({"OLLAMA_FLASH_ATTENTION": "1"})
    assert any("launchctl" in c[0] for c in calls)


def test_any_process_false_when_pgrep_fails(monkeypatch) -> None:
    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess([], 1, "", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    assert tune._any_process(("nope",)) is False


def test_restart_ollama_does_not_raise(monkeypatch) -> None:
    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    monkeypatch.setattr(tune, "_any_process", lambda _p: False)
    tune.restart_ollama(timeout=0.01)


def test_restart_ollama_applies_env(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **_k):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    monkeypatch.setattr(tune, "_any_process", lambda _p: False)
    tune.restart_ollama(timeout=0.01, env={"OLLAMA_FLASH_ATTENTION": "1"})
    assert any("open" in c[0] for c in calls)


def test_restart_ollama_kills_when_timeout(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **_k):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    monkeypatch.setattr(tune, "_any_process", lambda _p: True)
    tune.restart_ollama(timeout=0.01)
    assert any("-9" in c for c in calls)


def test_current_server_env_handles_ps_failure(monkeypatch) -> None:
    monkeypatch.setattr(tune, "_current_server_pid", lambda: "1234")

    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(tune.subprocess, "run", boom)
    assert tune.current_server_env() == {}


def test_any_process_false_when_all_pgrep_return_empty(monkeypatch) -> None:
    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    assert tune._any_process(("a", "b")) is False


def test_any_process_true_when_pgrep_finds_output(monkeypatch) -> None:
    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess([], 0, "1234\n", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    assert tune._any_process(("a",)) is True


def test_any_process_tolerates_pgrep_failure(monkeypatch) -> None:
    def fake_run(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    assert tune._any_process(("a",)) is False


def test_read_context_length_tolerates_db_error(tmp_path: Path) -> None:
    path = tmp_path / "locked.sqlite"
    # Write a file with the sqlite header so is_file passes, but make sqlite fail.
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    assert tune.read_context_length(path) is None


def test_read_context_length_connect_fails_before_assignment(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "db.sqlite"
    path.write_text("not a db", encoding="utf-8")

    def boom(*_a, **_k):
        raise sqlite3.Error("boom")

    monkeypatch.setattr("sovereign_code.tune.sqlite3.connect", boom)
    assert tune.read_context_length(path) is None


def test_read_context_length_uses_default_path(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, context_length INTEGER)")
        con.execute("INSERT INTO settings (id, context_length) VALUES (1, 8192)")
        con.commit()
    finally:
        con.close()
    monkeypatch.setattr(tune, "ollama_db_path", lambda: db)
    assert tune.read_context_length() == 8192


def test_current_server_pid_handles_pgrep_failure(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(tune.subprocess, "run", boom)
    assert tune._current_server_pid() is None


def test_current_server_env_parses_ps_output(monkeypatch) -> None:
    monkeypatch.setattr(tune, "_current_server_pid", lambda: "1234")

    def fake_run(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 0, "OLLAMA_CONTEXT_LENGTH=4096\n", "")

    monkeypatch.setattr(tune.subprocess, "run", fake_run)
    assert tune.current_server_env() == {"OLLAMA_CONTEXT_LENGTH": "4096"}
