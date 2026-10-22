"""Tests for the prompt database."""

from __future__ import annotations

import pytest

from sovereign_code.promptdb import DEFAULT_DB, PromptDB


@pytest.fixture
def db(tmp_path, monkeypatch):
    import sovereign_code.promptdb as module

    path = tmp_path / "prompts.db"
    monkeypatch.setattr(module, "DEFAULT_DB", path)
    instance = PromptDB(path)
    yield instance
    instance.close()


def test_add_and_get(db):
    p = db.add("review", "Review: {{prompt}}", category="review", tags="coding,review")
    assert p.name == "review"
    assert p.category == "review"
    assert p.tags == ("coding", "review")
    assert p.variables == ("prompt",)
    assert p.version == 1

    got = db.get("review")
    assert got is not None
    assert got.content == "Review: {{prompt}}"
    assert got.version == 1


def test_add_duplicate_raises(db):
    db.add("review", "v1")
    with pytest.raises(ValueError, match="already exists"):
        db.add("review", "v2")


def test_replace_bumps_version(db):
    db.add("review", "v1")
    p = db.replace("review", "v2", version=2)
    assert p.version == 2
    assert db.get("review").version == 2
    # old version is still retrievable
    assert db.get_version("review", 1).content == "v1"


def test_render(db):
    db.add("greet", "Hello {{name}}!")
    assert db.render("greet", name="Ada") == "Hello Ada!"
    # unknown variable left as-is
    assert db.render("greet", name="Ada") == "Hello Ada!"


def test_render_tracks_usage(db):
    db.add("greet", "Hello {{name}}!")
    assert db.get("greet").usage_count == 0
    db.render("greet", name="Ada")
    assert db.get("greet").usage_count == 1


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
    db.add("review", "v2", version=2)
    assert db.delete("review", version=1) is True
    assert db.get_version("review", 1) is None
    assert db.get("review").version == 2
    assert db.delete("review") is True
    assert db.get("review") is None
    assert db.delete("missing") is False


def test_touch(db):
    db.add("greet", "Hi")
    db.touch("greet")
    p = db.get("greet")
    assert p.usage_count == 1
    assert p.last_used_at is not None


def test_export_import_json(db):
    db.add("review", "Review: {{prompt}}", category="review", tags="coding")
    data = db.export_json()
    assert len(data) == 1

    db2 = PromptDB(db.path)
    db2.delete("review")
    written = db2.import_json(data)
    assert written == 1
    assert db2.get("review").content == "Review: {{prompt}}"
    db2.close()


def test_fts_search(db):
    db.add("code-review", "Review the python code for bugs", category="code")
    db.add("chat-help", "Help with chat UX", category="chat")
    results = db.list(search="python bugs")
    assert len(results) == 1
    assert results[0].name == "code-review"


def test_variables_extracted(db):
    p = db.add("t", "Use {{foo}} and {{bar}} but {{foo}} again")
    assert p.variables == ("foo", "bar")


def test_default_db_path_is_under_data_dir():
    assert DEFAULT_DB.parent.name == "data"
    assert DEFAULT_DB.name == "prompts.db"
