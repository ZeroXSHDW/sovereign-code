"""Project memory tests."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.memory import (
    add_memory,
    clear_memory,
    memory_path,
    project_slug,
    read_memory,
)


def test_memory_roundtrip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sovereign_code.memory.DATA_DIR", tmp_path)
    cwd = tmp_path / "proj"
    cwd.mkdir()

    add_memory("use python 3.13", cwd)
    assert "use python 3.13" in read_memory(cwd)
    assert memory_path(cwd).is_file()
    assert len(project_slug(cwd)) == 12

    clear_memory(cwd)
    assert "use python 3.13" not in read_memory(cwd)
