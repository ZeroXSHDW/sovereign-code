"""Tests for the skill database."""

from __future__ import annotations

import sqlite3

import pytest

from sovereign_code.skilldb import DEFAULT_DB, SkillDB


@pytest.fixture
def db(tmp_path, monkeypatch):
    import sovereign_code.skilldb as module

    path = tmp_path / "skills.db"
    monkeypatch.setattr(module, "DEFAULT_DB", path)
    instance = SkillDB(path)
    yield instance
    instance.close()


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A small skills tree that ``sync_repo`` reads."""
    import sovereign_code.skilldb as module

    repo = tmp_path / "skills"
    repo.mkdir()
    user = tmp_path / "user-skills"
    user.mkdir()
    monkeypatch.setattr(module, "USER_SKILLS_DIR", user)
    monkeypatch.setattr(module, "_skill_dirs", lambda: [user, repo])
    return repo


def _write(directory, name: str, body: str) -> None:
    (directory / f"{name}.md").write_text(body, encoding="utf-8")


def _old_style_db(path) -> None:
    """Build a database the way skilldb used to build them.

    The full-text table keeps its own copy of every column, which is what
    doubled the size of the file.
    """
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE skills (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            category      TEXT NOT NULL DEFAULT 'general',
            tags          TEXT NOT NULL DEFAULT '',
            description   TEXT NOT NULL DEFAULT '',
            content       TEXT NOT NULL DEFAULT '',
            rating        REAL NOT NULL DEFAULT 0,
            usage_count   INTEGER NOT NULL DEFAULT 0,
            last_used_at  TEXT,
            installed     INTEGER NOT NULL DEFAULT 1,
            source        TEXT NOT NULL DEFAULT 'repo',
            version       INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE skills_fts USING fts5("
        "name, tags, category, description, content, tokenize='unicode61')"
    )
    conn.execute(
        "INSERT INTO skills (id, name, category, tags, description, content, rating, "
        "usage_count, last_used_at, installed, source, version, created_at, updated_at) "
        "VALUES ('id-1', 'alpha', 'testing', 'tag', 'Alpha skill', 'testing body', "
        "1.0, 0, NULL, 1, 'repo', 1, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO skills_fts(name, tags, category, description, content) "
        "VALUES ('alpha', 'tag', 'testing', 'Alpha skill', 'testing body')"
    )
    conn.commit()
    conn.close()


def test_add_and_get(db):
    s = db.add(
        "code-review",
        "Review this: {{prompt}}",
        category="review",
        tags="coding",
        description="Code review skill",
        rating=4.5,
    )
    assert s.name == "code-review"
    assert s.category == "review"
    assert s.tags == ("coding",)
    assert s.description == "Code review skill"
    assert s.rating == 4.5
    assert s.version == 1

    got = db.get("code-review")
    assert got is not None
    assert got.content == "Review this: {{prompt}}"


def test_add_duplicate_raises(db):
    db.add("review", "v1")
    with pytest.raises(ValueError, match="already exists"):
        db.add("review", "v2")


def test_replace_bumps_version(db):
    db.add("review", "v1")
    p = db.replace("review", "v2", version=2)
    assert p.version == 2
    assert db.get("review").version == 2
    assert db.get_version("review", 1).content == "v1"


def test_rating_and_touch(db):
    db.add("greet", "Hi")
    db.rate("greet", 4.0)
    assert db.get("greet").rating == 4.0
    db.touch("greet")
    assert db.get("greet").usage_count == 1
    db.rate("greet", 9.0)
    assert db.get("greet").rating == 5.0


def test_list_and_search(db):
    db.add("code-review", "Review code", category="code", tags="coding")
    db.add("chat-help", "Help chat", category="chat", tags="chat")
    rows = db.list_all()
    assert len(rows) == 2
    rows = db.list_all(category="code")
    assert len(rows) == 1
    assert rows[0].name == "code-review"
    found = db.list_all(search="Review")
    assert len(found) == 1
    assert found[0].name == "code-review"


def test_count(db):
    assert db.count() == 0
    db.add("a", "x")
    db.add("b", "y")
    assert db.count() == 2


def test_delete(db):
    db.add("review", "v1")
    assert db.delete("review") is True
    assert db.get("review") is None
    assert db.delete("missing") is False


def test_export_import_json(db):
    db.add("review", "Review: {{prompt}}", category="review", tags="coding")
    data = db.export_json()
    assert len(data) == 1

    db2 = SkillDB(db.path)
    db2.delete("review")
    written = db2.import_json(data)
    assert written == 1
    assert db2.get("review").content == "Review: {{prompt}}"
    db2.close()


def test_default_db_path_is_under_data_dir():
    assert DEFAULT_DB.parent.name == "data"
    assert DEFAULT_DB.name == "skills.db"


# ------------------------------------------------------------------ index


def test_bank_query_uses_the_covering_index(db):
    """The dashboard's bank query must not scan the 167 MB content table."""
    db.add("alpha", "body", rating=3.0)
    plan = [
        row["detail"]
        for row in db._conn.execute(
            "EXPLAIN QUERY PLAN SELECT name, category, usage_count, rating FROM skills "
            "WHERE installed = 1 ORDER BY rating DESC, usage_count DESC LIMIT 400"
        )
    ]
    assert any("skills_bank_idx" in detail for detail in plan)
    assert not any(detail.startswith("SCAN skills") for detail in plan)


def test_bank_index_covers_the_installed_count(db):
    db.add("alpha", "body")
    plan = [
        row["detail"]
        for row in db._conn.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(DISTINCT name) FROM skills WHERE installed = 1"
        )
    ]
    assert any("skills_bank_idx" in detail for detail in plan)


# -------------------------------------------------------------- migration


def test_migration_rebuilds_an_old_style_fts(tmp_path):
    """An old database keeps its rows searchable after the migration."""
    path = tmp_path / "skills.db"
    _old_style_db(path)

    db = SkillDB(path)
    try:
        assert db._fts_is_external()
        assert [s.name for s in db.list_all(search="testing")] == ["alpha"]
        tables = {
            row[0]
            for row in db._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "skills_fts" in tables
        # The content is stored once now, not once per table.
        assert "skills_fts_content" not in tables
    finally:
        db.close()


def test_migration_keeps_the_fts_index_consistent(tmp_path):
    path = tmp_path / "skills.db"
    _old_style_db(path)

    db = SkillDB(path)
    try:
        db._conn.execute("INSERT INTO skills_fts(skills_fts) VALUES('integrity-check')")
    finally:
        db.close()


def test_migration_is_not_repeated(tmp_path):
    """A migrated database is left alone the next time it is opened."""
    path = tmp_path / "skills.db"
    _old_style_db(path)

    db = SkillDB(path)
    db.close()
    again = SkillDB(path)
    try:
        sql = again._conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'skills_fts'"
        ).fetchone()["sql"]
        assert "content='skills'" in sql
        assert again._fts_is_external()
    finally:
        again.close()


# ------------------------------------------------------------------- sync


def test_sync_writes_in_one_transaction(db, tree):
    """A sync of many files is one transaction, not one per file."""
    for index in range(25):
        _write(tree, f"skill-{index}", f"# Skill {index}\n\nbody {index}\n")

    statements: list[str] = []
    db._conn.set_trace_callback(statements.append)
    stats = db.sync_repo()
    db._conn.set_trace_callback(None)

    assert stats["added"] == 25
    assert len([s for s in statements if s.strip().upper().startswith("BEGIN")]) == 1
    assert len([s for s in statements if s.strip().upper().startswith("COMMIT")]) == 1
    # The table is read once, not once per file.
    assert len([s for s in statements if s.strip().upper().startswith("SELECT")]) <= 2


def test_sync_of_an_unchanged_tree_writes_nothing(db, tree):
    _write(tree, "alpha", "# Alpha\n\nbody\n")
    db.sync_repo()

    statements: list[str] = []
    db._conn.set_trace_callback(statements.append)
    stats = db.sync_repo()
    db._conn.set_trace_callback(None)

    assert stats == {"added": 0, "updated": 0, "unchanged": 1, "disabled": 0}
    assert not [s for s in statements if s.strip().upper().startswith("UPDATE")]


def test_sync_reindexes_changed_skills(db, tree):
    """The full-text index has to follow the content it indexes."""
    _write(tree, "alpha", "# Alpha\n\nthe body talks about kangaroos\n")
    db.sync_repo()
    assert [s.name for s in db.list_all(search="kangaroos")] == ["alpha"]

    _write(tree, "alpha", "# Alpha\n\nthe body talks about badgers now\n")
    stats = db.sync_repo()

    assert stats["updated"] == 1
    assert db.list_all(search="kangaroos") == []
    assert [s.name for s in db.list_all(search="badgers")] == ["alpha"]
    db._conn.execute("INSERT INTO skills_fts(skills_fts) VALUES('integrity-check')")


def test_sync_marks_missing_skills_disabled(db, tree):
    _write(tree, "alpha", "# Alpha\n\nbody\n")
    _write(tree, "beta", "# Beta\n\nbody\n")
    db.sync_repo()
    assert db.get("beta").installed is True

    (tree / "beta.md").unlink()
    stats = db.sync_repo()

    assert stats["disabled"] == 1
    assert db.get("beta").installed is False


def test_sync_dry_run_changes_nothing(db, tree):
    _write(tree, "alpha", "# Alpha\n\nbody\n")
    before = db._conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    stats = db.sync_repo(dry_run=True)
    after = db._conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]

    assert stats["added"] == 1
    assert before == after


def test_sync_handles_a_name_in_both_directories(db, tree, tmp_path, monkeypatch):
    """A local override and the shipped file can share a name."""
    import sovereign_code.skilldb as module

    user = tmp_path / "user-skills"
    monkeypatch.setattr(module, "USER_SKILLS_DIR", user)
    monkeypatch.setattr(module, "_skill_dirs", lambda: [user, tree])
    _write(tree, "alpha", "# Alpha\n\nshipped body\n")
    _write(user, "alpha", "# Alpha\n\nlocal body\n")

    stats = db.sync_repo()

    assert stats["added"] == 1
    assert stats["updated"] == 1
    assert db.count() == 1
    # The last file read wins the row, the way the per-file loop did.
    assert db.get("alpha").content == "# Alpha\n\nshipped body\n"
    db._conn.execute("INSERT INTO skills_fts(skills_fts) VALUES('integrity-check')")


# ----------------------------------------------------------------- search


def test_search_orders_by_relevance(db):
    """A full-text search is ordered by relevance, not by rating."""
    db.add("best-match", "testing", rating=0.0)
    db.add("high-rated", "testing happens", rating=5.0)
    db.add("unrelated", "nothing to see here", rating=4.0)

    hits = db.list_all(search="testing")
    assert [s.name for s in hits] == ["best-match", "high-rated"]
    # Without a search the old ordering is still the one that applies.
    assert [s.name for s in db.list_all()] == ["high-rated", "unrelated", "best-match"]


def test_search_still_filters_by_category(db):
    db.add("alpha", "testing body", category="code")
    db.add("beta", "testing body", category="chat")
    assert [s.name for s in db.list_all(search="testing", category="code")] == ["alpha"]


def test_delete_removes_the_skill_from_the_index(db):
    db.add("alpha", "testing body")
    assert db.delete("alpha") is True
    assert db.list_all(search="testing") == []
    db._conn.execute("INSERT INTO skills_fts(skills_fts) VALUES('integrity-check')")
