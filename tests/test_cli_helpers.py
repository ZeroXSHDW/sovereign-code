"""Tests for the pure helpers in cli.py.

cli.py is the thin dispatch layer around the real modules; most of it is
subprocess/network I/O. These pin the pure parser/format/coercion helpers that
carry real logic and were previously uncovered.
"""

from __future__ import annotations

from pathlib import Path

from sovereign_code import cli


def test_age_formats_seconds_minutes_hours_days() -> None:
    assert cli._age(30) == "0m"
    assert cli._age(120) == "2m"
    assert cli._age(7200) == "2h"
    assert cli._age(172800) == "2d"


def test_context_label_compacts_sizes() -> None:
    assert cli._context_label(None) == "?"
    assert cli._context_label(0) == "?"
    assert cli._context_label(512) == "512"
    assert cli._context_label(4096) == "4k"
    assert cli._context_label(1_048_576) == "1M"
    assert cli._context_label(2_000_000) == "2M"


def test_coerce_setting_preserves_types() -> None:
    assert cli._coerce_setting("", None) is None
    assert cli._coerce_setting("abc", None) == "abc"
    assert cli._coerce_setting("true", False) is True
    assert cli._coerce_setting("no", True) is False
    assert cli._coerce_setting("42", 0) == 42
    assert cli._coerce_setting("1.5", 0.0) == 1.5
    assert cli._coerce_setting("x", "default") == "x"


def test_parse_vars_splits_and_skips_malformed() -> None:
    assert cli._parse_vars(["A=1", "B = two", "malformed", " C = d "]) == {
        "A": "1",
        "B": "two",
        "C": "d",
    }


def test_is_git_repo_detects_the_marker(tmp_path: Path) -> None:
    assert cli._is_git_repo(tmp_path) is False
    (tmp_path / ".git").mkdir()
    assert cli._is_git_repo(tmp_path) is True


def test_project_changes_returns_empty_without_git(tmp_path: Path, monkeypatch) -> None:
    # `git` is present, but this dir is not a repo; both calls return empty.
    if not cli.command_exists("git"):
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: type("r", (), {"stdout": ""})())
    assert cli._project_changes(tmp_path) == ""


def test_build_parser_registers_every_documented_command() -> None:
    parser = cli.build_parser()
    # The commands the README documents must exist, so a doc string cannot
    # silently fall out of the CLI.
    for command in (
        "model-use",
        "pack",
        "domains",
        "mlx",
        "browse",
        "consult",
        "verify",
        "run",
        "pull",
    ):
        assert command in parser._subparsers._group_actions[0].choices, command
