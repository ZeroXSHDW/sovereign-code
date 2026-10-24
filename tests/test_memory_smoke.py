from __future__ import annotations

from pathlib import Path

from sovereign_code import memory


def test_project_slug() -> None:
    assert isinstance(memory.project_slug(Path(".")), str)


def test_memory_path() -> None:
    assert memory.memory_path() is not None


def test_ensure_memory(tmp_path) -> None:
    p = memory.ensure_memory(tmp_path)
    assert p.exists()


def test_project_context(tmp_path) -> None:
    ctx = memory.project_context(tmp_path)
    assert isinstance(ctx, str)


def test_add_and_read_memory(tmp_path) -> None:
    memory.add_memory("hello", tmp_path)
    text = memory.read_memory(tmp_path)
    assert "hello" in text


def test_clear_memory(tmp_path) -> None:
    memory.add_memory("hello", tmp_path)
    memory.clear_memory(tmp_path)
    text = memory.read_memory(tmp_path)
    assert "hello" not in text
