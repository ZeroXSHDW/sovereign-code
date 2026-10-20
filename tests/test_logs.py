"""Log path and tailing tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code.logs import WATCHDOG_LOG, log_path, tail_lines


def test_log_paths() -> None:
    assert log_path("gateway").name == "gateway.log"
    assert log_path("watchdog") == WATCHDOG_LOG
    assert log_path("dashboard").parts[-2:] == ("logs", "login.err.log")
    with pytest.raises(ValueError):
        log_path("nope")


def test_tail_lines_returns_last_lines(tmp_path: Path) -> None:
    path = tmp_path / "test.log"
    path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    assert tail_lines(path, 2) == ["three", "four"]
    assert tail_lines(path, 0) == []
    assert tail_lines(tmp_path / "missing.log", 5) == []
