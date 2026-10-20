"""Project memory tests."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.memory import (
    add_memory,
    clear_memory,
    memory_path,
    project_context,
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


def test_project_context_includes_agents_and_memory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sovereign_code.memory.DATA_DIR", tmp_path)
    cwd = tmp_path / "proj"
    cwd.mkdir()
    (cwd / "AGENTS.md").write_text("use ruff and mypy", encoding="utf-8")
    add_memory("prefer dataclasses", cwd)
    context = project_context(cwd)
    assert "AGENTS.md" in context
    assert "use ruff and mypy" in context
    assert "prefer dataclasses" in context
