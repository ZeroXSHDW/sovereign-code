"""Tests for the staged patch review screen."""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code.direct import FileWrite
from sovereign_code.tui import patch as patch_mod
from sovereign_code.tui.patch import PatchReview


def test_patch_review_refuses_paths_outside_the_project(tmp_path: Path) -> None:
    review = PatchReview(tmp_path, [FileWrite("../evil.txt", "x")])
    assert review.rejected == ["../evil.txt"]
    assert review.valid_writes == []


def test_patch_review_counts_lines_and_keeps_a_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(patch_mod, "DATA_DIR", tmp_path / "data")
    target = tmp_path / "note.txt"
    target.write_text("old\n", encoding="utf-8")

    review = PatchReview(tmp_path, [FileWrite("note.txt", "new\n")])

    assert review.rejected == []
    assert review._counts(0) == (1, 1)
    backup = review._backup()
    assert backup is not None
    assert (backup / "note.txt").read_text(encoding="utf-8") == "old\n"
