from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sovereign_code.knowledge import KnowledgeBase
from sovereign_code.search import SearchResult


def test_init_creates_db_and_schema(tmp_path: Path) -> None:
    db = tmp_path / "kb.db"
    kb = KnowledgeBase(db)
    assert db.is_file()
    rows = kb._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='roots'"
    ).fetchall()
    assert len(rows) == 1
    kb.close()


def test_init_falls_back_to_localhost_when_settings_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    """A broken Settings load must not prevent the knowledge base opening."""
    monkeypatch.setattr(
        "sovereign_code.config.Settings.load",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no config")),
    )
    kb = KnowledgeBase(tmp_path / "kb.db", ollama_url=None)
    assert kb.ollama_url == "http://127.0.0.1:11434"
    kb.close()


def test_context_manager(tmp_path: Path) -> None:
    db = tmp_path / "kb.db"
    with KnowledgeBase(db) as kb:
        assert kb is not None
    # closed; accessing conn should raise
    with pytest.raises(sqlite3.Error):
        kb._conn.execute("SELECT 1")


def test_index_root_inserts(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = MagicMock()
    monkeypatch.setattr(
        "sovereign_code.knowledge.build_index",
        lambda *a, **k: (3, 7, store),
    )
    db = tmp_path / "kb.db"
    kb = KnowledgeBase(db)
    result = kb.index_root(root, embed_model="m", limit=2)
    assert result == {"files": 3, "chunks": 7}
    rows = kb.list_roots()
    assert len(rows) == 1
    assert rows[0]["file_count"] == 3
    assert rows[0]["chunk_count"] == 7
    assert rows[0]["embed_model"] == "m"
    store.close.assert_called_once()
    kb.close()


def test_index_root_non_dir_raises(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")
    with pytest.raises(ValueError):
        kb.index_root(tmp_path / "nope")
    kb.close()


def test_search_constructs_hits_dedup_sort(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    kb = KnowledgeBase(tmp_path / "kb.db")
    # index root manually
    kb._conn.execute(
        "INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model) VALUES (?,?,?,?,?)",  # noqa: E501
        (str(root.resolve()), 1, 1, "now", "m"),
    )
    kb._conn.commit()

    sr1 = SearchResult(path="/a.md", line=5, text="  hello   world  ", score=0.5)
    sr2 = SearchResult(path="/a.md", line=5, text="dup", score=0.9)
    sr3 = SearchResult(path="/b.md", line=2, text="second", score=0.8)
    monkeypatch.setattr(
        "sovereign_code.knowledge.search_query",
        lambda *a, **k: [sr1, sr2, sr3],
    )
    # make db file exist for index_path_for check
    from sovereign_code.search import index_path_for

    dbfile = index_path_for(root)
    dbfile.parent.mkdir(parents=True, exist_ok=True)
    dbfile.write_bytes(b"")

    hits = kb.search("q", embed_model="m", top=10)
    # dedup by path -> /a.md once, /b.md once
    assert len(hits) == 2
    paths = {h.path for h in hits}
    assert paths == {"/a.md", "/b.md"}
    # sorted desc by score: /a.md 0.5? dedup keeps first occurrence sr1 score 0.5
    # Actually seen check on result.path before construction; first sr1 added with 0.5
    assert hits[0].score >= hits[1].score
    a = next(h for h in hits if h.path == "/a.md")
    assert a.snippet == "hello world"
    assert a.lines == 5
    assert a.name == "a.md"
    kb.close()


def test_search_root_filter(tmp_path: Path, monkeypatch) -> None:
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    r1.mkdir()
    r2.mkdir()
    kb = KnowledgeBase(tmp_path / "kb.db")
    for r in (r1, r2):
        kb._conn.execute(
            "INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model) VALUES (?,?,?,?,?)",  # noqa: E501
            (str(r.resolve()), 1, 1, "now", "m"),
        )
    kb._conn.commit()

    calls = []

    def fake_sq(*a, **k):
        calls.append(a[1] if len(a) > 1 else k.get("db"))
        return []

    monkeypatch.setattr("sovereign_code.knowledge.search_query", fake_sq)

    from sovereign_code.search import index_path_for

    for r in (r1, r2):
        f = index_path_for(r)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")

    kb.search("q", root=r1, top=5)
    # only r1 searched
    assert len(calls) == 1
    kb.close()


def test_search_nonexistent_root_returns_empty(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")
    assert kb.search("q", root=tmp_path / "nope") == []
    kb.close()


def test_search_query_raises_continues(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb._conn.execute(
        "INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model) VALUES (?,?,?,?,?)",  # noqa: E501
        (str(root.resolve()), 1, 1, "now", "m"),
    )
    kb._conn.commit()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("sovereign_code.knowledge.search_query", boom)

    from sovereign_code.search import index_path_for

    f = index_path_for(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"")

    assert kb.search("q") == []
    kb.close()


def test_roots_returns_paths(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb._conn.execute(
        "INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model) VALUES (?,?,?,?,?)",  # noqa: E501
        ("/a", 1, 1, "now", "m"),
    )
    kb._conn.commit()
    assert kb._roots() == ["/a"]
    kb.close()


def test_list_roots_returns_dicts(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb._conn.execute(
        "INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model) VALUES (?,?,?,?,?)",  # noqa: E501
        ("/a", 1, 2, "now", "m"),
    )
    kb._conn.commit()
    rows = kb.list_roots()
    assert isinstance(rows, list)
    assert isinstance(rows[0], dict)
    assert rows[0]["root"] == "/a"
    kb.close()


def test_count(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")
    assert kb.count() == 0
    kb._conn.execute(
        "INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model) VALUES (?,?,?,?,?)",  # noqa: E501
        ("/a", 1, 1, "now", "m"),
    )
    kb._conn.commit()
    assert kb.count() == 1
    kb.close()


def test_vacuum(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb.vacuum()  # should not raise
    kb.close()


def test_close_handles_error(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")

    class FakeConn:
        def close(self) -> None:
            import sqlite3

            raise sqlite3.Error("boom")

    kb._conn.close()  # close the real connection before replacing it
    kb._conn = FakeConn()  # type: ignore[assignment]
    kb.close()  # should not raise


def test_default_knowledge() -> None:
    from sovereign_code.knowledge import default_knowledge

    kb = default_knowledge()
    assert kb is not None
    kb.close()


def test_search_skips_missing_db(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb._conn.execute(
        "INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model) VALUES (?,?,?,?,?)",  # noqa: E501
        (str(root.resolve()), 1, 1, "now", "m"),
    )
    kb._conn.commit()

    monkeypatch.setattr(
        "sovereign_code.knowledge.search_query",
        lambda *a, **k: [
            __import__("sovereign_code.search", fromlist=["SearchResult"]).SearchResult(
                path="/x.md", line=1, text="t", score=0.1
            )
        ],
    )
    # ensure index db file does NOT exist -> continue branch
    hits = kb.search("q")
    assert hits == []
    kb.close()


def test_close_idempotent(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb.close()
    kb.close()  # second close should not raise
