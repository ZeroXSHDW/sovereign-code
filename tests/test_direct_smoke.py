from __future__ import annotations

from sovereign_code import direct


def test_parse_blocks() -> None:
    writes = direct.parse_blocks("```python\nprint('hi')\n```")
    assert isinstance(writes, list)


def test_resolve_target(tmp_path) -> None:
    (tmp_path / "a.py").write_text("x")
    resolved = direct.resolve_target(tmp_path, "a.py")
    assert resolved is not None


def test_relevant_files(tmp_path) -> None:
    (tmp_path / "a.py").write_text("hello")
    files = direct.relevant_files(tmp_path, "hello")
    assert isinstance(files, dict)
