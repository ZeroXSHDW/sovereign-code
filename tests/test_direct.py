"""Tests for single-shot file editing."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.direct import (
    FileWrite,
    apply_writes,
    build_messages,
    parse_blocks,
    relevant_files,
    resolve_target,
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
