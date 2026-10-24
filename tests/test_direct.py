"""Tests for single-shot file editing."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from sovereign_code.direct import (
    FileWrite,
    apply_writes,
    build_messages,
    parse_blocks,
    relevant_files,
    resolve_target,
    undo_writes,
)


def test_parses_strict_blocks() -> None:
    text = "<<<FILE: a.py>>>\nprint(1)\n<<<END>>>\n<<<FILE: b/c.py>>>\nx = 2\n<<<END>>>"
    assert parse_blocks(text) == [
        FileWrite("a.py", "print(1)\n"),
        FileWrite("b/c.py", "x = 2\n"),
    ]


def test_parses_block_without_closing_marker() -> None:
    text = "<<<FILE: a.py>>>\nprint(1)\n"
    assert parse_blocks(text) == [FileWrite("a.py", "print(1)\n")]


def test_no_blocks_returns_empty() -> None:
    assert parse_blocks("I could not do that.") == []


def test_paths_cannot_escape_the_project(tmp_path: Path) -> None:
    assert resolve_target(tmp_path, "../etc/passwd") is None
    assert resolve_target(tmp_path, "/etc/passwd") is None
    assert resolve_target(tmp_path, "a/../../b") is None
    assert resolve_target(tmp_path, "./ok.py") == (tmp_path / "ok.py").resolve()


def test_apply_writes_writes_and_rejects(tmp_path: Path) -> None:
    written, rejected = apply_writes(
        tmp_path,
        [FileWrite("pkg/mod.py", "value = 1\n"), FileWrite("../evil.py", "boom\n")],
    )
    assert written == ["pkg/mod.py"]
    assert rejected == ["../evil.py"]
    assert (tmp_path / "pkg" / "mod.py").read_text() == "value = 1\n"
    assert not (tmp_path.parent / "evil.py").exists()


def test_relevant_files_prefers_mentioned_names(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "junk.py").write_text("z", encoding="utf-8")

    picked = relevant_files(tmp_path, "change target.py please")
    assert "target.py" in picked
    assert ".git/junk.py" not in picked


def test_messages_include_the_format_and_the_failure() -> None:
    messages = build_messages("do it", "plan", {"a.py": "x = 1\n"}, "1 failed")
    blob = "\n".join(message["content"] for message in messages)
    assert "<<<FILE:" in blob
    assert "1 failed" in blob
    assert "a.py" in blob


def test_messages_without_files_or_failure() -> None:
    messages = build_messages("do it", "plan", {})
    blob = "\n".join(message["content"] for message in messages)
    assert "Current files:" not in blob
    assert "failed" not in blob
    assert "<<<FILE:" in blob  # the format contract is still stated


def test_apply_writes_restores_on_a_partial_failure(tmp_path: Path, monkeypatch) -> None:
    """A write that fails mid-batch must roll back the files already written."""
    # First target writes fine; the second fails, so the first is restored.
    (tmp_path / "keep.py").write_text("original\n", encoding="utf-8")
    real_write = Path.write_text

    def failing_write(self, content, *args, **kwargs):
        if self.name == "boom.py":
            raise OSError("disk full")
        return real_write(self, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write)
    with pytest.raises(OSError, match="disk full"):
        apply_writes(
            tmp_path,
            [FileWrite("keep.py", "changed\n"), FileWrite("boom.py", "x\n")],
        )
    # The already-written file was rolled back to its original content.
    assert (tmp_path / "keep.py").read_text(encoding="utf-8") == "original\n"


def test_undo_writes_restores_the_journal(tmp_path: Path) -> None:
    apply_writes(tmp_path, [FileWrite("a.py", "new\n")])
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "new\n"

    restored = undo_writes(tmp_path)
    assert restored == ["a.py"]
    # The original file did not exist, so undo removes it again.
    assert not (tmp_path / "a.py").exists()


def test_undo_writes_restores_an_overwritten_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("before\n", encoding="utf-8")
    apply_writes(tmp_path, [FileWrite("a.py", "after\n")])
    assert undo_writes(tmp_path) == ["a.py"]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "before\n"


def test_undo_with_no_journal_is_a_noop(tmp_path: Path) -> None:
    assert undo_writes(tmp_path) == []


def test_undo_restores_a_binary_file_as_bytes(tmp_path: Path) -> None:
    """A non-UTF-8 file is backed up as bytes, so undo does not delete it."""
    before = b"\x00\x01\x02\xffbinary"
    (tmp_path / "bin.dat").write_bytes(before)
    # apply_writes only writes text targets, so poison the journal directly.
    journal = {
        "written": ["bin.dat"],
        "backups": {"bin.dat": {"binary": base64.b64encode(before).decode("ascii")}},
    }
    (tmp_path / ".sovereign-undo.json").write_text(json.dumps(journal), encoding="utf-8")

    assert undo_writes(tmp_path) == ["bin.dat"]
    assert (tmp_path / "bin.dat").read_bytes() == before
