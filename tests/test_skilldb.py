"""Tests for the skill database."""

from __future__ import annotations

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
    rows = db.list()
    assert len(rows) == 2
    rows = db.list(category="code")
    assert len(rows) == 1
    assert rows[0].name == "code-review"
    found = db.list(search="Review")
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
