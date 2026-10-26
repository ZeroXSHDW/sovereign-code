"""Semantic search tests (pure parts) plus an optional embedding check."""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code.search import (
    IndexStore,
    chunk_text,
    cosine,
    embed,
    index_path_for,
    iter_source_files,
    pack,
    unpack,
)


def test_chunk_text_short_and_blank() -> None:
    assert chunk_text("hello") == [(1, "hello")]
    assert chunk_text("   ") == []


def test_chunk_text_large_tracks_lines() -> None:
    chunks = chunk_text("a\n" * 5000, max_chars=1200, overlap=160)
    assert len(chunks) > 1
    assert chunks[0][0] == 1
    lines = [line for line, _ in chunks]
    assert lines == sorted(lines)
    assert all(chunk for _, chunk in chunks)


def test_pack_unpack_roundtrip() -> None:
    vector = [0.1, -0.2, 0.3]
    assert unpack(pack(vector)) == pytest.approx(vector)


def test_cosine_extremes() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0


def test_iter_source_files_prunes_ignored_and_binary(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".git" / "config").write_text("y", encoding="utf-8")
    (tmp_path / "node_modules" / "x.js").write_text("z", encoding="utf-8")
    (tmp_path / ".hidden.py").write_text("x", encoding="utf-8")
    (tmp_path / "main.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")

    names = {path.name for path in iter_source_files(tmp_path)}
    assert "main.py" in names
    assert "config" not in names
    assert "x.js" not in names
    assert ".hidden.py" not in names
    assert "img.png" not in names
    assert "bin.dat" not in names


def test_index_store_ranks_by_similarity(tmp_path: Path) -> None:
    store = IndexStore(tmp_path / "idx.sqlite")
    store.clear()
    store.add("a.py", 1, "alpha", [1.0, 0.0])
    store.add("b.py", 1, "beta", [0.0, 1.0])
    store.commit()
    results = store.search([0.9, 0.1], top=2)
    assert results[0].path == "a.py"
    assert results[0].score > results[1].score
    assert store.count() == 2
    store.close()


def test_index_path_is_stable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sovereign_code.search.DATA_DIR", tmp_path)
    assert index_path_for(Path("/tmp/foo")) == index_path_for(Path("/tmp/foo"))


def test_search_query_uses_store_and_embedding(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code.search import IndexStore, search_query

    store = IndexStore(tmp_path / "idx.sqlite")
    store.clear()
    store.add("a.py", 1, "gateway restart", [1.0, 0.0])
    store.add("b.py", 1, "unrelated", [0.0, 1.0])
    store.commit()
    store.close()
    monkeypatch.setattr("sovereign_code.search.embed", lambda *a, **k: [[0.9, 0.1]])
    results = search_query("http://gw", tmp_path / "idx.sqlite", "restart", top=2)
    assert results[0].path == "a.py"


def test_embed_integration_optional() -> None:
    try:
        vectors = embed("http://127.0.0.1:11434", "nomic-embed-text", ["hello"], timeout=30.0)
    except Exception as exc:
        pytest.skip(f"Ollama embedding unavailable: {exc}")
    assert len(vectors) == 1
    assert len(vectors[0]) == 768


def test_cosine_returns_zero_on_dimension_mismatch() -> None:
    assert cosine([1.0, 0.0], [1.0]) == 0.0


def test_chunk_text_honours_overlap_when_it_is_zero() -> None:
    # max_chars == overlap + 1 forces the guard path: start = end.
    chunks = chunk_text("x" * 20, max_chars=11, overlap=10)
    assert len(chunks) > 1


def test_embed_raises_on_http_error(monkeypatch) -> None:
    import httpx

    def boom(*_a, **_k):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(
        "sovereign_code.search.shared_client", lambda: type("C", (), {"post": boom})()
    )
    with pytest.raises(Exception, match="Ollama unreachable"):
        embed("http://x", "m", ["hi"])


def test_embed_raises_on_bad_status(monkeypatch) -> None:
    class Resp:
        status_code = 500

    monkeypatch.setattr(
        "sovereign_code.search.shared_client",
        lambda: type("C", (), {"post": lambda *a, **k: Resp()})(),
    )
    with pytest.raises(Exception, match="embed HTTP 500"):
        embed("http://x", "m", ["hi"])


def test_build_index_embeds_and_swaps(tmp_path: Path, monkeypatch) -> None:
    from sovereign_code.search import build_index

    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr(
        "sovereign_code.search.embed", lambda _url, _model, texts: [[1.0, 0.0]] * len(texts)
    )
    files, chunks, store = build_index(root, "http://x", model="nomic-embed-text")
    assert files == 1
    assert chunks == 1
    assert store.count() == 1
    store.close()
