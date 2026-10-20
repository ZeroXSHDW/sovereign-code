"""Session listing and retention tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sovereign_code.sessions import (
    SessionInfo,
    prune_sessions,
    scan_sessions,
    select_prunable,
)


def _info(name: str, modified: float) -> SessionInfo:
    return SessionInfo(Path(name), "model", 1, 1.0, modified)


def test_scan_sessions_summarises_records(tmp_path: Path) -> None:
    path = tmp_path / "20260101-120000-qwen.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "session", "model": "qwen3.5:4b"}),
                json.dumps({"type": "message", "role": "user", "content": "hi"}),
                json.dumps({"type": "message", "role": "assistant", "content": "ok"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    infos = scan_sessions(tmp_path)
    assert len(infos) == 1
    assert infos[0].model == "qwen3.5:4b"
    assert infos[0].messages == 2
    assert infos[0].size_kb > 0


def test_select_prunable_respects_keep_and_age() -> None:
    now = 1_000_000.0
    old = _info("old.jsonl", now - 40 * 86400)
    recent = _info("recent.jsonl", now - 2 * 86400)

    assert select_prunable([recent, old], days=30, keep=1, now=now) == [old]
    assert select_prunable([recent, old], days=30, keep=0, now=now) == [old]
    assert select_prunable([recent, old], days=30, keep=2, now=now) == []
    assert select_prunable([recent, old], days=0, keep=0, now=now) == []


def test_prune_sessions_unlinks_files(tmp_path: Path) -> None:
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    first.write_text("{}\n", encoding="utf-8")
    second.write_text("{}\n", encoding="utf-8")
    os.utime(first, (1, 1))
    infos = scan_sessions(tmp_path)
    removed = prune_sessions(infos)
    assert removed == 2
    assert not first.exists()
    assert not second.exists()


def test_search_sessions(tmp_path: Path) -> None:
    from sovereign_code.sessions import search_sessions

    path = tmp_path / "a.jsonl"
    path.write_text(
        json.dumps({"type": "session", "model": "m"})
        + "\n"
        + json.dumps({"type": "message", "role": "user", "content": "find the gateway restart"})
        + "\n",
        encoding="utf-8",
    )
    matches = search_sessions("gateway", directory=tmp_path)
    assert len(matches) == 1
    assert matches[0]["role"] == "user"
    assert "gateway restart" in matches[0]["snippet"]
    assert search_sessions("nothing", directory=tmp_path) == []


def test_export_sessions(tmp_path: Path) -> None:
    from sovereign_code.sessions import export_sessions

    path = tmp_path / "a.jsonl"
    path.write_text(
        json.dumps({"type": "session", "model": "m"})
        + "\n"
        + json.dumps({"type": "message", "role": "user", "content": "hi"})
        + "\n",
        encoding="utf-8",
    )
    dest = tmp_path / "out.jsonl"
    count = export_sessions(dest, directory=tmp_path)
    assert count == 2
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all("_session" in json.loads(line) for line in lines)
