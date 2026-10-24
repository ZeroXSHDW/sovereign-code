"""Tests for installing one skill library into each client's layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code import skills_install
from sovereign_code.skills_install import (
    INDEX_END,
    INDEX_START,
    Skill,
    install,
    install_skill,
    load_skill,
    split_frontmatter,
)

SOURCE = """---
name: demo-skill
description: A demo skill for tests
---

# Demo

Do the thing.
"""


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    (root / "addy--demo.md").write_text(SOURCE, encoding="utf-8")
    (root / "other.md").write_text("# Ignored\n", encoding="utf-8")
    return root


def test_split_frontmatter_and_load(tmp_path) -> None:
    path = tmp_path / "addy--demo.md"
    path.write_text(SOURCE, encoding="utf-8")
    meta, body = split_frontmatter(SOURCE)
    assert meta["name"] == "demo-skill"
    assert body.startswith("# Demo")
    skill = load_skill(path)
    assert skill.name == "demo-skill"
    assert "demo skill" in skill.description


def test_install_writes_agent_skill_and_continue_prompt(tmp_path, monkeypatch) -> None:
    root = _source(tmp_path)
    targets = {
        "claude": lambda: tmp_path / "claude",
        "codex": lambda: tmp_path / "codex",
        "qwen": lambda: tmp_path / "qwen",
        "opencode": lambda: tmp_path / "opencode",
    }
    monkeypatch.setattr(skills_install, "TARGETS", targets)
    monkeypatch.setattr(skills_install, "CONTINUE_PROMPTS", lambda: tmp_path / "continue")
    # Point the curated loader at the fixture library.
    monkeypatch.setattr(skills_install, "LOCAL_AI_ROOT", tmp_path / "missing")

    written = install(targets="all", source=root)
    assert written["claude"] and written["codex"] and written["qwen"] and written["opencode"]
    assert written["continue"]
    skill_file = tmp_path / "claude" / "demo-skill" / "SKILL.md"
    assert skill_file.is_file()
    assert "name: demo-skill" in skill_file.read_text()
    prompt = tmp_path / "continue" / "demo-skill.prompt"
    assert prompt.is_file()

    # Re-running is idempotent (no duplicates, same paths).
    again = install(targets="all", source=root)
    assert written == again


def test_install_project_writes_index_and_keeps_existing_text(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    claude = project / "CLAUDE.md"
    claude.write_text("# Existing project rules\n", encoding="utf-8")
    skill = Skill("demo", "A demo", "Body\n", tmp_path / "demo.md")
    written = skills_install.install_project(project, [skill])
    assert written
    body = claude.read_text()
    assert "# Existing project rules" in body
    assert INDEX_START in body and INDEX_END in body
    assert "demo" in body
    # A second run replaces the block instead of appending another.
    skills_install.upsert_index(claude, [skill])
    assert body.count(INDEX_START) == 1


def test_install_skill_twice_does_not_duplicate(tmp_path) -> None:
    target = tmp_path / "skills"
    skill = Skill("demo", "A demo", "Body\n", tmp_path / "demo.md")
    first = install_skill(skill, target)
    second = install_skill(skill, target)
    assert first == second
    assert len(list(target.glob("*/SKILL.md"))) == 1


def test_get_skill_refuses_to_leave_the_library(tmp_path, monkeypatch) -> None:
    """The name is compared by slug but resolved as a path: it must be checked."""
    library = tmp_path / "skills"
    library.mkdir()
    (library / "demo.md").write_text(SOURCE, encoding="utf-8")
    secret = tmp_path / "secret.md"
    secret.write_text("# Secret\ns3cr3t\n", encoding="utf-8")

    monkeypatch.setattr(skills_install, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(skills_install, "LOCAL_AI_ROOT", tmp_path / "local")

    assert skills_install.get_skill("demo") is not None
    assert skills_install.get_skill("../secret") is None
    assert skills_install.get_skill("../../etc/passwd") is None
    assert skills_install.get_skill(str(secret)) is None
    assert skills_install.get_skill("sub/dir") is None


def test_install_ignores_a_traversing_name(tmp_path, monkeypatch) -> None:
    library = tmp_path / "skills"
    library.mkdir()
    (library / "demo.md").write_text(SOURCE, encoding="utf-8")
    monkeypatch.setattr(skills_install, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(skills_install, "LOCAL_AI_ROOT", tmp_path / "local")
    monkeypatch.setattr(skills_install, "TARGETS", {"claude": lambda: tmp_path / "claude"})
    monkeypatch.setattr(skills_install, "CONTINUE_PROMPTS", lambda: tmp_path / "continue")

    written = install(targets="claude", names=["../../evil"])
    assert written["claude"] == []
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path.parent / "evil").exists()


def test_install_skill_refuses_an_unsafe_name(tmp_path) -> None:
    skill = Skill("../../evil", "A demo", "Body\n", tmp_path / "demo.md")
    with pytest.raises(ValueError, match="unsafe skill name"):
        install_skill(skill, tmp_path / "skills")


def test_ponytail_skills_are_curated() -> None:
    """The vendored ponytail skills flow through the default curated profile."""
    names = {skill.name for skill in skills_install.load_curated()}
    assert {
        "ponytail",
        "ponytail-review",
        "ponytail-audit",
        "ponytail-debt",
        "ponytail-gain",
        "ponytail-help",
    } <= names
