"""Tests for Ollama runtime tuning helpers."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

from sovereign_code import tune
from sovereign_code.tune import (
    _any_process,
    _current_server_pid,
    current_server_env,
    desired_env,
    env_drift,
    parse_server_env,
    read_context_length,
    set_session_env,
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
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, context_length INTEGER)")
        con.commit()
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
