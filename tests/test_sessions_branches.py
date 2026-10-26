"""Supplementary branch coverage for session persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sovereign_code.sessions import (
    SessionInfo,
    SessionWriter,
    export_sessions,
    prune_sessions,
    read_session,
    recent_sessions,
    scan_sessions,
)


def test_session_create_exhausts_attempts(monkeypatch, tmp_path: Path) -> None:
    import sovereign_code.sessions as sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(
        sessions.os, "open", lambda *a, **k: (_ for _ in ()).throw(FileExistsError("taken"))
    )
    try:
        SessionWriter.create("m:1")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError after 1000 collisions")


def test_append_chmod_failure_is_tolerated(monkeypatch, tmp_path: Path) -> None:
    import sovereign_code.sessions as sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    writer = SessionWriter.create("m:1")

    def boom(self, _mode):
        raise OSError("nope")

    monkeypatch.setattr(Path, "chmod", boom)
    writer.append("user", "hello")  # must not raise
    assert writer.messages == 1


def test_recent_sessions_returns_limited(monkeypatch, tmp_path: Path) -> None:
    import sovereign_code.sessions as sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    for i in range(3):
        (tmp_path / f"{i}.jsonl").write_text("{}\n", encoding="utf-8")
    result = recent_sessions(2)
    assert len(result) == 2


def test_mtime_tolerates_disappearing_file(monkeypatch, tmp_path: Path) -> None:
    import sovereign_code.sessions as sessions

    path = tmp_path / "gone.jsonl"
    real_stat = Path.stat

    def flaky(self, *a, **k):
        if self.name == "gone.jsonl":
            raise OSError("gone")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", flaky)
    assert sessions._mtime(path) == 0.0


def test_export_sessions_chmod_failure_tolerated(monkeypatch, tmp_path: Path) -> None:
    host = tmp_path / "sessions"
    host.mkdir()
    (host / "a.jsonl").write_text(
        json.dumps({"type": "message", "content": "hi"}) + "\n", encoding="utf-8"
    )
    dest = tmp_path / "export.jsonl"

    def boom(self, _mode):
        raise OSError("nope")

    monkeypatch.setattr(Path, "chmod", boom)
    count = export_sessions(dest, directory=host)
    assert count == 1
    assert dest.is_file()


def test_read_session_skips_blank_and_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    path.write_text(
        "\n" + json.dumps({"type": "message", "content": "ok"}) + "\nnot json\n\n",
        encoding="utf-8",
    )
    records = read_session(path)
    assert len(records) == 1
    assert records[0]["content"] == "ok"


def test_read_session_missing_file(tmp_path: Path) -> None:
    assert read_session(tmp_path / "missing.jsonl") == []


def test_scan_sessions_tolerates_glob_and_stat_failure(monkeypatch, tmp_path: Path) -> None:
    # glob failure path
    class BoomPath(type(Path())):
        pass

    # stat failure: one file vanishes between glob and stat
    host = tmp_path / "sessions"
    host.mkdir()
    (host / "a.jsonl").write_text("{}\n", encoding="utf-8")
    real_stat = Path.stat

    def flaky_stat(self, *a, **k):
        if self.name == "a.jsonl":
            raise OSError("gone")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    infos = scan_sessions(host)
    assert infos == []


def test_scan_sessions_empty_with_missing_dir(monkeypatch, tmp_path: Path) -> None:

    assert scan_sessions(tmp_path / "missing") == []


def test_scan_sessions_tolerates_glob_failure(monkeypatch, tmp_path: Path) -> None:

    def boom(self, _pattern):
        raise OSError("unreadable dir")

    monkeypatch.setattr(Path, "glob", boom)
    assert scan_sessions(tmp_path) == []


def test_prune_sessions_tolerates_unlink_failure(monkeypatch, tmp_path: Path) -> None:
    info = SessionInfo(tmp_path / "a.jsonl", "m", 0, 0.0, 0.0)
    (tmp_path / "a.jsonl").write_text("{}\n", encoding="utf-8")

    def boom(self):
        raise OSError("nope")

    monkeypatch.setattr(Path, "unlink", boom)
    assert prune_sessions([info]) == 0


def test_read_session_skips_non_dict_json(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    assert read_session(path) == []


def test_export_sessions_tolerates_temp_unlink_failure(monkeypatch, tmp_path: Path) -> None:
    import os

    host = tmp_path / "sessions"
    host.mkdir()
    (host / "a.jsonl").write_text(
        json.dumps({"type": "message", "content": "hi"}) + "\n", encoding="utf-8"
    )
    dest = tmp_path / "export.jsonl"

    def raising_fdopen(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(os, "fdopen", raising_fdopen)

    def raising_unlink(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(os, "unlink", raising_unlink)

    with pytest.raises(OSError):
        export_sessions(dest, directory=host)
