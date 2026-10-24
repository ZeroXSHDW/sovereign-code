"""Log path and tailing tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code.logs import WATCHDOG_LOG, log_path, tail_lines


def test_log_paths() -> None:
    assert log_path("gateway").name == "gateway.log"
    assert log_path("watchdog") == WATCHDOG_LOG
    assert log_path("dashboard").parts[-2:] == ("logs", "login.err.log")
    assert log_path("loop").name == "service-loop.log"
    assert log_path("bridge").name == "bridge.log"
    assert log_path("tier").name == "tier-gateway.log"
    with pytest.raises(ValueError):
        log_path("nope")


def test_resolve_log_path_falls_back_to_legacy(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code.logs import resolve_log_path

    legacy = tmp_path / "watchdog.log"
    legacy.write_text("old", encoding="utf-8")
    monkeypatch.setattr("sovereign_code.logs.LEGACY_WATCHDOG_LOG", legacy)
    monkeypatch.setattr("sovereign_code.logs.WATCHDOG_LOG", tmp_path / "missing.log")
    assert resolve_log_path("watchdog") == legacy


def test_resolve_log_path_returns_current_when_present(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code.logs import resolve_log_path

    current = tmp_path / "watchdog.log"
    current.write_text("now", encoding="utf-8")
    monkeypatch.setattr("sovereign_code.logs.WATCHDOG_LOG", current)
    assert resolve_log_path("watchdog") == current


def test_resolve_log_path_non_watchdog(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code.logs import resolve_log_path

    monkeypatch.setattr("sovereign_code.logs.LOG_DIR", tmp_path)
    assert resolve_log_path("loop").name == "service-loop.log"


def test_tail_lines_returns_last_lines(tmp_path: Path) -> None:
    path = tmp_path / "test.log"
    path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    assert tail_lines(path, 2) == ["three", "four"]
    assert tail_lines(path, 0) == []
    assert tail_lines(tmp_path / "missing.log", 5) == []
