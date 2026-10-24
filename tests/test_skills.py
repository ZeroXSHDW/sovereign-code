"""Skill template tests."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.skills import list_skills, read_skill, render_skill, search_skills


def test_skills_list_read_and_render(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sovereign_code.skills.USER_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("sovereign_code.skills.REPO_SKILLS_DIR", tmp_path / "repo")
    # Isolate the curated-profile overlay: this test exercises the filesystem
    # read path, whose headings the real profile would otherwise replace.
    monkeypatch.setattr("sovereign_code.skills._profile_descriptions", dict)
    # The shared SQLite index may already know a real "code-review" skill;
    # force the filesystem path the test is actually checking.
    monkeypatch.setattr("sovereign_code.skills._index_usable", lambda _conn: False)
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


def test_read_skill_refuses_to_leave_the_skills_directory(monkeypatch, tmp_path: Path) -> None:
    """A name is a file stem, never a path that walks out of the library."""
    library = tmp_path / "skills"
    library.mkdir()
    (library / "real.md").write_text("# Real\nbody\n", encoding="utf-8")
    secret = tmp_path / "secret.md"
    secret.write_text("# Secret\ns3cr3t\n", encoding="utf-8")

    monkeypatch.setattr("sovereign_code.skills.USER_SKILLS_DIR", library)
    monkeypatch.setattr("sovereign_code.skills.REPO_SKILLS_DIR", library)

    assert read_skill("real") == "# Real\nbody\n"
    assert read_skill("../secret") is None
    assert read_skill("../../secret") is None
    assert read_skill("sub/dir") is None
    assert read_skill(str(secret)) is None
    assert read_skill("..") is None
    assert read_skill("") is None
    assert read_skill("real\x00.md") is None


def _indexed_library(tmp_path: Path, monkeypatch) -> Path:
    """A two-skill library with a matching SQLite index."""
    from sovereign_code import skilldb

    db_path = tmp_path / "skills.db"
    with skilldb.SkillDB(db_path) as db:
        db.add("alpha", "# Index version\nAlpha body\n", source="repo")
        db.add("beta", "# Beta version\nBeta body\n", source="repo")
    monkeypatch.setattr(skilldb, "DEFAULT_DB", db_path)

    library = tmp_path / "skills"
    library.mkdir()
    (library / "alpha.md").write_text("# File version\nFile body\n", encoding="utf-8")
    (library / "beta.md").write_text("# File version\nFile body\n", encoding="utf-8")
    monkeypatch.setattr("sovereign_code.skills.USER_SKILLS_DIR", tmp_path / "user")
    monkeypatch.setattr("sovereign_code.skills.REPO_SKILLS_DIR", library)
    return library


def test_list_skills_reads_the_index_when_it_covers_the_tree(tmp_path: Path, monkeypatch) -> None:
    """The 22k-file library is answered from SQLite, not by reading the files."""
    _indexed_library(tmp_path, monkeypatch)
    rows = dict(list_skills())
    assert rows["alpha"] == "Index version"
    assert rows["beta"] == "Beta version"


def test_list_skills_falls_back_to_the_filesystem(tmp_path: Path, monkeypatch) -> None:
    """Without an index the files are read, as they always were."""
    from sovereign_code import skilldb

    monkeypatch.setattr(skilldb, "DEFAULT_DB", tmp_path / "missing.db")
    library = tmp_path / "skills"
    library.mkdir()
    (library / "alpha.md").write_text("# File version\nFile body\n", encoding="utf-8")
    monkeypatch.setattr("sovereign_code.skills.USER_SKILLS_DIR", tmp_path / "user")
    monkeypatch.setattr("sovereign_code.skills.REPO_SKILLS_DIR", library)
    assert dict(list_skills()) == {"alpha": "File version"}


def test_the_index_does_not_answer_for_another_tree(tmp_path: Path, monkeypatch) -> None:
    """A database that describes a different library must not be used."""
    from sovereign_code import skilldb

    db_path = tmp_path / "skills.db"
    with skilldb.SkillDB(db_path) as db:
        for number in range(5):
            db.add(f"other-{number}", "# Other\nbody\n", source="repo")
    monkeypatch.setattr(skilldb, "DEFAULT_DB", db_path)

    library = tmp_path / "skills"
    library.mkdir()
    (library / "alpha.md").write_text("# File version\nFile body\n", encoding="utf-8")
    monkeypatch.setattr("sovereign_code.skills.USER_SKILLS_DIR", tmp_path / "user")
    monkeypatch.setattr("sovereign_code.skills.REPO_SKILLS_DIR", library)

    assert dict(list_skills()) == {"alpha": "File version"}
    assert search_skills("alpha", limit=5) == [("alpha", "File version")]


def test_search_skills_reads_the_index(tmp_path: Path, monkeypatch) -> None:
    _indexed_library(tmp_path, monkeypatch)
    rows = search_skills("alpha", limit=5)
    assert [name for name, _ in rows] == ["alpha"]
    # The body comes from the index, not from the file on disk.
    assert rows[0][1] == "Index version"


def test_search_skills_falls_back_to_the_filesystem(tmp_path: Path, monkeypatch) -> None:
    from sovereign_code import skilldb

    monkeypatch.setattr(skilldb, "DEFAULT_DB", tmp_path / "missing.db")
    library = tmp_path / "skills"
    library.mkdir()
    (library / "alpha.md").write_text("# File version\nFile body\n", encoding="utf-8")
    monkeypatch.setattr("sovereign_code.skills.USER_SKILLS_DIR", tmp_path / "user")
    monkeypatch.setattr("sovereign_code.skills.REPO_SKILLS_DIR", library)
    rows = search_skills("alpha", limit=5)
    assert [name for name, _ in rows] == ["alpha"]
    assert rows[0][1] == "File version"
