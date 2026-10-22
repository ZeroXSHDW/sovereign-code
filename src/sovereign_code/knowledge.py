""".md knowledge base: index every Markdown file (skills, prompts, notes) and
search it semantically with local embeddings.

Engineers keep their context in .md files: skills, prompts, ADRs, runbooks,
specs. This module builds a SQLite + embedding index under DATA_DIR/knowledge.db
so any local model can retrieve the right file by meaning, not by keyword.

It reuses the search indexer (:mod:`search`) for file walking and Ollama for
embeddings, so there is no new backend to run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .search import DEFAULT_EMBED, build_index, index_path_for, search_query

DEFAULT_DB = DATA_DIR / "knowledge.db"


@dataclass
class KnowledgeHit:
    path: str
    name: str
    snippet: str
    score: float
    lines: int


class KnowledgeBase:
    """Semantic index over a directory tree of .md files.

    Each indexed root gets its own embedding database (built by :mod:`search`),
    and this layer records the root, file count, and last index time so the CLI
    can show what is searchable.
    """

    _SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS roots (
            root          TEXT PRIMARY KEY,
            file_count    INTEGER NOT NULL DEFAULT 0,
            chunk_count   INTEGER NOT NULL DEFAULT 0,
            indexed_at    TEXT NOT NULL,
            embed_model   TEXT NOT NULL DEFAULT ''
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS roots_indexed_idx ON roots(indexed_at)
        """,
    )

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        for statement in self._SCHEMA:
            self._conn.execute(statement)
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> KnowledgeBase:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- index

    def index_root(
        self,
        root: str | Path,
        *,
        embed_model: str = DEFAULT_EMBED,
        limit: int | None = None,
    ) -> dict[str, int]:
        """Embed every .md under ``root`` and record it as searchable."""
        from datetime import datetime

        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ValueError(f"not a directory: {root}")
        files, chunks, store = build_index(
            root_path, "http://127.0.0.1:11434", model=embed_model, limit=limit
        )
        store.close()
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO roots (root, file_count, chunk_count, indexed_at, embed_model)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(root) DO UPDATE SET
                file_count = excluded.file_count,
                chunk_count = excluded.chunk_count,
                indexed_at = excluded.indexed_at,
                embed_model = excluded.embed_model
            """,
            (str(root_path), int(files), int(chunks), now, embed_model),
        )
        self._conn.commit()
        return {"files": int(files), "chunks": int(chunks)}

    # ---------------------------------------------------------------- search

    def search(
        self,
        query: str,
        *,
        root: str | Path | None = None,
        embed_model: str = DEFAULT_EMBED,
        top: int = 10,
    ) -> list[KnowledgeHit]:
        """Semantic search across indexed roots (or one root)."""

        roots = self._roots()
        if root is not None:
            root_path = str(Path(root).expanduser().resolve())
            if root_path not in roots:
                return []
            roots = [root_path]
        hits: list[KnowledgeHit] = []
        seen: set[str] = set()
        for root_path in roots:
            db = index_path_for(Path(root_path))
            if not db.is_file():
                continue
            try:
                results = search_query(
                    "http://127.0.0.1:11434", db, query, model=embed_model, top=top
                )
            except Exception:
                continue
            for result in results:
                if result.path in seen:
                    continue
                seen.add(result.path)
                path = Path(result.path)
                hits.append(
                    KnowledgeHit(
                        path=result.path,
                        name=path.name,
                        snippet=" ".join(result.text.split())[:300],
                        score=result.score,
                        lines=result.line,
                    )
                )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top]

    # ---------------------------------------------------------------- roots

    def _roots(self) -> list[str]:
        rows = self._conn.execute("SELECT root FROM roots ORDER BY indexed_at DESC").fetchall()
        return [row["root"] for row in rows]

    def list_roots(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT root, file_count, chunk_count, indexed_at, embed_model "
            "FROM roots ORDER BY indexed_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM roots").fetchone()
        return int(row[0]) if row else 0

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")
        self._conn.commit()


def default_knowledge() -> KnowledgeBase:
    return KnowledgeBase()
