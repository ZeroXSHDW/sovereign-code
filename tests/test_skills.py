"""Skill template tests."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.skills import list_skills, read_skill, render_skill


def test_skills_list_read_and_render(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sovereign_code.skills.USER_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("sovereign_code.skills.REPO_SKILLS_DIR", tmp_path / "repo")
    (tmp_path / "code-review.md").write_text(
        "# Review code\nYou review:\n\n{{prompt}}\n", encoding="utf-8"
    )
    (tmp_path / "explain.md").write_text("# Explain\nExplain:\n\n{{prompt}}\n", encoding="utf-8")

    rows = list_skills()
    assert [name for name, _ in rows] == ["code-review", "explain"]
    assert rows[0][1] == "Review code"
    assert read_skill("code-review").startswith("# Review code")
    assert render_skill("code-review", "x = 1") == "# Review code\nYou review:\n\nx = 1\n"
    assert read_skill("missing") is None
