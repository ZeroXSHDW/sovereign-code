from __future__ import annotations

from sovereign_code import terminal


def test_shell_path() -> None:
    path = terminal.shell_path()
    assert path


def test_session_command_dry() -> None:
    line = terminal.session_command(cwd="/tmp", command="echo hi", full_access=False)
    assert "echo hi" in line
    assert "cd " in line


def test_session_command_empty() -> None:
    line = terminal.session_command()
    assert "exec" in line


def test_spawn_terminal_dry_run(tmp_path) -> None:
    result = terminal.spawn_terminal(cwd=tmp_path, command="echo hi", dry_run=True)
    assert result["ok"] is True
    assert result["method"] == "dry-run"
    assert result["cwd"] == str(tmp_path)


def test_run_shell_echo() -> None:
    result = terminal.run_shell("echo hello", timeout=30)
    assert result["ok"] is True
    assert "hello" in result["stdout"]


def test_run_shell_empty_raises() -> None:
    try:
        terminal.run_shell("   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_run_shell_timeout_cap() -> None:
    # very large timeout is capped, command still runs
    result = terminal.run_shell("echo capped", timeout=100000)
    assert result["ok"] is True


def test_run_background(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(terminal, "DATA_DIR", tmp_path)
    result = terminal.run_background("echo bg-test")
    assert result["ok"] is True
    assert "pid" in result
    assert "log" in result


def test_tmux_available_returns_bool() -> None:
    assert isinstance(terminal.tmux_available(), bool)


def test_tmux_session_without_tmux() -> None:
    if terminal.tmux_available():
        return
    result = terminal.tmux_session("sovereign-test")
    assert result["ok"] is False
