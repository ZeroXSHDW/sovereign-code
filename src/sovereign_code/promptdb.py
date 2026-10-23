"""Prompt database: versioned, categorized, searchable prompt store.

Every prompt lives in SQLite (``DATA_DIR/prompts.db``) with FTS5 full-text
search, version history, usage counters and ``{{variable}}`` rendering. This is
the structured prompt layer that sits next to the markdown skills under
``skills/`` and feeds the tier gateway, the browser agent and every code agent
Sovereign Code launches.

The database is created lazily on first use and is safe to open from multiple
processes (WAL mode).
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR

DEFAULT_DB = DATA_DIR / "prompts.db"

_VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS prompts (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        category     TEXT NOT NULL DEFAULT 'general',
        tags         TEXT NOT NULL DEFAULT '',
        content      TEXT NOT NULL,
        variables    TEXT NOT NULL DEFAULT '[]',
        version      INTEGER NOT NULL DEFAULT 1,
        usage_count  INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        source       TEXT NOT NULL DEFAULT 'local',
        engine       TEXT NOT NULL DEFAULT 'sovereign'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS prompts_category_idx ON prompts(category)
    """,
    """
    CREATE INDEX IF NOT EXISTS prompts_updated_idx ON prompts(updated_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS prompts_name_idx ON prompts(name)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS prompts_name_version_uidx ON prompts(name, version)
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS prompts_fts USING fts5(
        name, tags, category, content, tokenize='unicode61'
    )
    """,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _tag_list(value: str | tuple[str, ...] | list[str]) -> str:
    raw = value if isinstance(value, str) else ",".join(value)
    return ",".join(part.strip() for part in raw.split(",") if part.strip())


def _tag_set(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _variables(content: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_VARIABLE.findall(content)))


def _render(content: str, variables: dict[str, str]) -> str:
    """Replace ``{{var}}`` placeholders; unknown variables are left as-is."""

    def repl(match: re.Match[str]) -> str:
        return variables.get(match.group(1), match.group(0))

    return _VARIABLE.sub(repl, content)


@dataclass
class Prompt:
    id: str
    name: str
    category: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    content: str = ""
    variables: tuple[str, ...] = field(default_factory=tuple)
    version: int = 1
    usage_count: int = 0
    last_used_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
    source: str = "local"
    engine: str = "sovereign"

    @property
    def variable_names(self) -> list[str]:
        return list(self.variables)


class PromptDB:
    """Thread-safe-ish SQLite prompt store. One instance per process is fine."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        for statement in _SCHEMA:
            self._conn.execute(statement)
        self._conn.commit()

    # ------------------------------------------------------------------ close

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> PromptDB:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- write

    def add(
        self,
        name: str,
        content: str,
        *,
        category: str = "general",
        tags: str | tuple[str, ...] | list[str] = (),
        version: int = 1,
        source: str = "local",
        engine: str = "sovereign",
        replace: bool = False,
    ) -> Prompt:
        """Insert a prompt, returning the stored :class:`Prompt`.

        Raises ``ValueError`` if a prompt with ``name`` already exists unless
        ``replace=True`` (which bumps the version and keeps history).
        """
        now = _now()
        tags_csv = _tag_list(tags)
        variables = _variables(content)
        if not replace:
            exists = self._conn.execute(
                "SELECT 1 FROM prompts WHERE name = ? AND version = ?",
                (name, int(version)),
            ).fetchone()
            if exists is not None:
                raise ValueError(f"prompt already exists: {name}") from None
        pid = str(uuid.uuid4())
        row = (
            pid,
            name,
            category,
            tags_csv,
            content,
            json.dumps(list(variables)),
            int(version),
            0,
            None,
            now,
            now,
            source,
            engine,
        )
        try:
            self._conn.execute(
                """
                INSERT INTO prompts
                (id, name, category, tags, content, variables, version,
                 usage_count, last_used_at, created_at, updated_at, source, engine)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            self._fts_write(name, tags_csv, category, content)
            self._conn.commit()
        except sqlite3.IntegrityError:
            if not replace:
                raise ValueError(f"prompt already exists: {name}") from None
            return self.replace(
                name,
                content,
                category=category,
                tags=tags,
                version=version + 1,
                source=source,
                engine=engine,
            )
        row = self._conn.execute("SELECT * FROM prompts WHERE id = ?", (pid,)).fetchone()
        prompt = self._row_to_prompt(row)
        if prompt is None:
            raise KeyError(f"prompt {pid!r} not found")
        return prompt

    def replace(
        self,
        name: str,
        content: str,
        *,
        category: str | None = None,
        tags: str | tuple[str, ...] | list[str] | None = None,
        version: int | None = None,
        source: str | None = None,
        engine: str | None = None,
    ) -> Prompt:
        """Create a new version of an existing prompt (old version stays)."""
        row = self._conn.execute(
            "SELECT * FROM prompts WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            raise ValueError(f"no such prompt: {name}")
        now = _now()
        tags_csv = _tag_list(tags if tags is not None else row["tags"])
        variables = _variables(content)
        new_version = int(version) if version is not None else int(row["version"]) + 1
        pid = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO prompts
            (id, name, category, tags, content, variables, version,
             usage_count, last_used_at, created_at, updated_at, source, engine)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                name,
                category if category is not None else row["category"],
                tags_csv,
                content,
                json.dumps(list(variables)),
                int(new_version),
                0,
                None,
                row["created_at"],
                now,
                source if source is not None else row["source"],
                engine if engine is not None else row["engine"],
            ),
        )
        category_value = row["category"] if category is None else category
        self._fts_write(name, tags_csv, category_value, content)
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM prompts WHERE id = ?", (pid,)).fetchone()
        prompt = self._row_to_prompt(row)
        if prompt is None:
            raise KeyError(f"prompt {pid!r} not found")
        return prompt

    def _fts_write(self, name: str, tags: str, category: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO prompts_fts(name, tags, category, content) VALUES (?, ?, ?, ?)",
            (name, tags, category, content),
        )

    def _fts_delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM prompts_fts WHERE name = ?", (name,))

    def _row_to_prompt(self, row: sqlite3.Row | None) -> Prompt | None:
        if row is None:
            return None
        return Prompt(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            tags=_tag_set(row["tags"] or ""),
            content=row["content"],
            variables=tuple(json.loads(row["variables"] or "[]")),
            version=int(row["version"]),
            usage_count=int(row["usage_count"]),
            last_used_at=row["last_used_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source=row["source"],
            engine=row["engine"],
        )

    # ---------------------------------------------------------------- read

    def get(self, name: str) -> Prompt | None:
        """Latest version of the named prompt."""
        row = self._conn.execute(
            "SELECT * FROM prompts WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        return self._row_to_prompt(row)

    def get_version(self, name: str, version: int) -> Prompt | None:
        row = self._conn.execute(
            "SELECT * FROM prompts WHERE name = ? AND version = ? ORDER BY version DESC LIMIT 1",
            (name, int(version)),
        ).fetchone()
        return self._row_to_prompt(row)

    def list_all(
        self,
        *,
        category: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Prompt]:
        """List prompts, newest first. Optional category/tag/full-text filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f"%,{tag},%")
        if search:
            clauses.append("rowid IN (SELECT rowid FROM prompts_fts WHERE prompts_fts MATCH ?)")
            params.append(search)
        sql = "SELECT * FROM prompts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
        rows = self._conn.execute(sql, params)
        return [p for p in (self._row_to_prompt(r) for r in rows) if p is not None]

    def names(self) -> list[str]:
        rows = self._conn.execute("SELECT name FROM prompts GROUP BY name ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(DISTINCT name) FROM prompts").fetchone()[0])

    # ---------------------------------------------------------------- usage

    def touch(self, name: str) -> None:
        """Bump usage_count and last_used_at for the latest version of a prompt."""
        row = self._conn.execute(
            "SELECT id FROM prompts WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return
        self._conn.execute(
            "UPDATE prompts SET usage_count = usage_count + 1, "
            "last_used_at = ?, updated_at = ? WHERE id = ?",
            (_now(), _now(), row["id"]),
        )
        self._conn.commit()

    def render(self, prompt_name: str, *, version: int | None = None, **variables: str) -> str:
        """Render a prompt with ``{{variable}}`` substitution.

        Records a usage hit so the hot prompts surface first in listings.
        """
        prompt = (
            self.get_version(prompt_name, version) if version is not None else self.get(prompt_name)
        )
        if prompt is None:
            raise KeyError(f"no such prompt: {prompt_name}")
        self.touch(prompt_name)
        return _render(prompt.content, variables)

    # ---------------------------------------------------------------- delete

    def delete(self, name: str, *, version: int | None = None) -> bool:
        """Delete a prompt version (or all versions). Returns True if removed."""
        if version is not None:
            row = self._conn.execute(
                "SELECT id FROM prompts WHERE name = ? AND version = ?",
                (name, int(version)),
            ).fetchone()
            if row is None:
                return False
            self._fts_delete(name)
            self._conn.execute("DELETE FROM prompts WHERE id = ?", (row["id"],))
        else:
            rows = self._conn.execute("SELECT id FROM prompts WHERE name = ?", (name,)).fetchall()
            if not rows:
                return False
            for _row in rows:
                self._fts_delete(name)
            self._conn.execute("DELETE FROM prompts WHERE name = ?", (name,))
        self._conn.commit()
        return True

    # ---------------------------------------------------------------- import/export

    def export_json(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM prompts ORDER BY name, version DESC").fetchall()
        return [dict(r) for r in rows]

    def import_json(self, rows: Iterable[dict[str, Any]]) -> int:

        written = 0
        for row in rows:
            self.add(
                str(row["name"]),
                str(row["content"]),
                category=str(row.get("category") or "general"),
                tags=str(row.get("tags") or ""),
                version=int(row.get("version") or 1),
                source=str(row.get("source") or "imported"),
                engine=str(row.get("engine") or "sovereign"),
                replace=True,
            )
            written += 1
        return written

    # ---------------------------------------------------------------- maintenance

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")
        self._conn.commit()
