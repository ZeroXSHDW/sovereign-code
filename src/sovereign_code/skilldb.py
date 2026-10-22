"""Skill database: structured index of skills, prompts and .md knowledge.

Builds on the existing ``skills/`` Markdown skills plus a SQLite index
(``DATA_DIR/skills.db``) with FTS5 search, metadata (category, rating, usage,
installed state), install/uninstall and a sync from the repo ``skills/`` tree.
This is the single source of truth for "which skill does what" that the tier
gateway, the browser agent and every code agent can query.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .skills import USER_SKILLS_DIR, _skill_dirs

DEFAULT_DB = DATA_DIR / "skills.db"

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS skills (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL UNIQUE,
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
    """,
    """
    CREATE INDEX IF NOT EXISTS skills_category_idx ON skills(category)
    """,
    """
    CREATE INDEX IF NOT EXISTS skills_updated_idx ON skills(updated_at)
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
        name, tags, category, description, content, tokenize='unicode61'
    )
    """,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _csv(value: str | tuple[str, ...] | list[str] | None) -> str:
    if value is None:
        return ""
    raw = value if isinstance(value, str) else ",".join(value)
    return ",".join(part.strip() for part in raw.split(",") if part.strip())


def _set(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


@dataclass
class Skill:
    id: str
    name: str
    category: str = "general"
    tags: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    content: str = ""
    rating: float = 0.0
    usage_count: int = 0
    last_used_at: str | None = None
    installed: bool = True
    source: str = "repo"
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    @property
    def tag_list(self) -> list[str]:
        return list(self.tags)


class SkillDB:
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

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> SkillDB:
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
        description: str = "",
        rating: float = 0.0,
        source: str = "local",
        version: int = 1,
        installed: bool = True,
        replace: bool = False,
    ) -> Skill:
        now = _now()
        tags_csv = _csv(tags)
        description = description or _first_heading(content) or name
        pid = str(uuid.uuid4())
        row = (
            pid,
            name,
            category,
            tags_csv,
            description,
            content,
            float(rating),
            0,
            None,
            1 if installed else 0,
            source,
            int(version),
            now,
            now,
        )
        try:
            self._conn.execute(
                """
                INSERT INTO skills
                (id, name, category, tags, description, content, rating,
                 usage_count, last_used_at, installed, source, version,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            self._fts_write(name, tags_csv, category, description, content)
            self._conn.commit()
        except sqlite3.IntegrityError:
            if not replace:
                raise ValueError(f"skill already exists: {name}") from None
            return self.replace(
                name,
                content,
                category=category,
                tags=tags,
                description=description,
                rating=rating,
                source=source,
                version=version + 1,
                installed=installed,
            )
        return self._row_to_skill(
            self._conn.execute("SELECT * FROM skills WHERE id = ?", (pid,)).fetchone()
        )

    def _fts_write(
        self, name: str, tags: str, category: str, description: str, content: str
    ) -> None:
        self._conn.execute(
            "INSERT INTO skills_fts(name, tags, category, description, content) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, tags, category, description, content),
        )

    def _fts_delete(self, name: str) -> None:
        self._conn.execute("DELETE FROM skills_fts WHERE name = ?", (name,))

    def _row_to_skill(self, row: sqlite3.Row | None) -> Skill | None:
        if row is None:
            return None
        return Skill(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            tags=_set(row["tags"]),
            description=row["description"],
            content=row["content"],
            rating=float(row["rating"]),
            usage_count=int(row["usage_count"]),
            last_used_at=row["last_used_at"],
            installed=bool(row["installed"]),
            source=row["source"],
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def replace(
        self,
        name: str,
        content: str,
        *,
        category: str | None = None,
        tags: str | tuple[str, ...] | list[str] | None = None,
        description: str | None = None,
        rating: float | None = None,
        source: str | None = None,
        version: int | None = None,
        installed: bool | None = None,
    ) -> Skill:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            raise ValueError(f"no such skill: {name}")
        now = _now()
        tags_csv = _csv(tags if tags is not None else row["tags"])
        desc = description if description is not None else row["description"]
        new_version = int(version) if version is not None else int(row["version"]) + 1
        pid = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO skills
            (id, name, category, tags, description, content, rating,
             usage_count, last_used_at, installed, source, version,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                name,
                category if category is not None else row["category"],
                tags_csv,
                desc,
                content,
                float(rating if rating is not None else row["rating"]),
                int(row["usage_count"]),
                row["last_used_at"],
                1 if (installed if installed is not None else row["installed"]) else 0,
                source if source is not None else row["source"],
                int(new_version),
                row["created_at"],
                now,
            ),
        )
        self._fts_write(
            name, tags_csv, row["category"] if category is None else category, desc, content
        )
        self._conn.commit()
        return self._row_to_skill(
            self._conn.execute("SELECT * FROM skills WHERE id = ?", (pid,)).fetchone()
        )

    # ---------------------------------------------------------------- read

    def get(self, name: str) -> Skill | None:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        return self._row_to_skill(row)

    def list(
        self,
        *,
        category: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        installed_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Skill]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f"%,{tag},%")
        if installed_only:
            clauses.append("installed = 1")
        if search:
            clauses.append("rowid IN (SELECT rowid FROM skills_fts WHERE skills_fts MATCH ?)")
            params.append(search)
        sql = "SELECT * FROM skills"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rating DESC, usage_count DESC, updated_at DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
        rows = self._conn.execute(sql, params)
        return [s for s in (self._row_to_skill(r) for r in rows) if s is not None]

    def names(self) -> list[str]:
        rows = self._conn.execute("SELECT name FROM skills GROUP BY name ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(DISTINCT name) FROM skills").fetchone()[0])

    # ---------------------------------------------------------------- usage

    def touch(self, name: str) -> None:
        row = self._conn.execute(
            "SELECT id FROM skills WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return
        self._conn.execute(
            "UPDATE skills SET usage_count = usage_count + 1, "
            "last_used_at = ?, updated_at = ? WHERE id = ?",
            (_now(), _now(), row["id"]),
        )
        self._conn.commit()

    def rate(self, name: str, rating: float) -> bool:
        row = self._conn.execute(
            "SELECT id FROM skills WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return False
        self._conn.execute(
            "UPDATE skills SET rating = ?, updated_at = ? WHERE id = ?",
            (max(0.0, min(5.0, float(rating))), _now(), row["id"]),
        )
        self._conn.commit()
        return True

    # ---------------------------------------------------------------- delete

    def delete(self, name: str) -> bool:
        rows = self._conn.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchall()
        if not rows:
            return False
        self._fts_delete(name)
        for row in rows:
            self._conn.execute("DELETE FROM skills WHERE id = ?", (row["id"],))
        self._conn.execute("DELETE FROM skills WHERE name = ?", (name,))
        self._conn.commit()
        return True

    # ---------------------------------------------------------------- sync

    def sync_repo(self, *, dry_run: bool = False) -> dict[str, int]:
        """Index every markdown skill under skills/ and user skills dir.

        Returns counts of {added, updated, unchanged}. Marks everything found
        on disk as installed=1; skills only in the DB but no longer on disk are
        marked installed=0 (not deleted, so history is kept).
        """
        stats = {"added": 0, "updated": 0, "unchanged": 0, "disabled": 0}
        known: dict[str, str] = {}
        for directory in _skill_dirs():
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                name = path.stem
                source = "user" if directory == USER_SKILLS_DIR else "repo"
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                description = _first_heading(text)
                tags = self._tags_from_text(text)
                category = self._category_from_name(name)
                existing = self.get(name)
                if existing is None:
                    if not dry_run:
                        self.add(
                            name,
                            text,
                            category=category,
                            tags=tags,
                            description=description,
                            source=source,
                        )
                    stats["added"] += 1
                else:
                    if not dry_run:
                        self._conn.execute(
                            "UPDATE skills SET content = ?, description = ?, tags = ?, "
                            "category = ?, source = ?, installed = 1, updated_at = ? "
                            "WHERE id = (SELECT id FROM skills WHERE name = ? "
                            "ORDER BY version DESC LIMIT 1)",
                            (text, description, tags, category, source, _now(), name),
                        )
                        self._conn.commit()
                    if (existing.content or "") == text and existing.description == description:
                        stats["unchanged"] += 1
                    else:
                        stats["updated"] += 1
                known[name] = source
        if not dry_run:
            for row in self._conn.execute("SELECT name FROM skills").fetchall():
                name = row["name"]
                if name not in known:
                    self._conn.execute("UPDATE skills SET installed = 0 WHERE name = ?", (name,))
                    stats["disabled"] += 1
            self._conn.commit()
        return stats

    @staticmethod
    def _tags_from_text(text: str) -> str:
        tags: set[str] = set()
        # Look for a `tags:` front-matter-ish line.
        for line in text.splitlines()[:40]:
            low = line.lower()
            if low.startswith("tags:") or low.startswith("tags :"):
                raw = line.split(":", 1)[1]
                for part in raw.replace("|", ",").split(","):
                    part = part.strip().strip('"').strip("'")
                    if part:
                        tags.add(part.lower())
                break
        # Derive category-ish tags from name prefixes handled elsewhere.
        return ",".join(sorted(tags))

    @staticmethod
    def _category_from_name(name: str) -> str:
        prefix = name.split("--", 1)[0].split("-", 1)[0]
        mapping = {
            "addy": "agent",
            "agent": "agent",
            "agent-teams": "team",
            "api-scaffolding": "api",
            "backend": "backend",
            "block": "security",
            "blockchain": "blockchain",
            "browser": "browser",
            "cicd": "ci-cd",
            "cloud": "cloud",
            "code-review": "review",
            "competitive": "research",
            "conductor": "workflow",
            "content": "content",
            "data-engineering": "data",
            "database": "database",
            "developer-essentials": "essentials",
            "dgx-spark": "ops",
            "documentation": "docs",
            "dotnet": "dotnet",
            "employment": "legal",
            "ethics": "governance",
            "explain": "utility",
            "file-conversion": "utility",
            "financial": "finance",
            "forensic": "forensics",
            "forensics": "forensics",
            "framework-migration": "migration",
            "frontend": "frontend",
            "game": "game",
            "gdpr": "compliance",
            "hermes": "social",
            "hr-legal": "legal",
            "incident-response": "incident",
            "javascript": "language",
            "jpeetz": "agent",
            "kubernetes": "kubernetes",
            "legal": "legal",
            "ml": "ml",
            "mobile": "mobile",
            "monorepo": "architecture",
            "network": "network",
            "observability": "observability",
            "orchestrate": "workflow",
            "payment": "payments",
            "performance": "performance",
            "php": "language",
            "playwright": "browser",
            "policy": "governance",
            "posix": "shell",
            "pptx": "utility",
            "prod-logs": "ops",
            "prompt": "prompt",
            "python": "language",
            "qa": "qa",
            "quant": "finance",
            "receipt": "utility",
            "reference": "utility",
            "review": "review",
            "risk": "risk",
            "ruby": "language",
            "rust": "language",
            "sales": "sales",
            "scala": "language",
            "search": "search",
            "security": "security",
            "seo": "seo",
            "service-mesh": "network",
            "session": "workflow",
            "social-publishing": "social",
            "sql": "database",
            "startup": "business",
            "tdd": "testing",
            "temporal": "workflow",
            "test-automator": "testing",
            "threat-modeling": "security",
            "tutorial": "tutorial",
            "typescript": "language",
            "ui": "ui",
            "unity": "game",
            "vector": "database",
            "wcag": "accessibility",
            "write-tests": "testing",
        }
        return mapping.get(prefix, "general")

    # ---------------------------------------------------------------- import/export

    def export_json(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM skills ORDER BY name, version DESC").fetchall()
        return [dict(r) for r in rows]

    def import_json(self, rows: Iterable[dict[str, Any]]) -> int:
        written = 0
        for row in rows:
            self.add(
                str(row["name"]),
                str(row.get("content") or ""),
                category=str(row.get("category") or "general"),
                tags=str(row.get("tags") or ""),
                description=str(row.get("description") or ""),
                rating=float(row.get("rating") or 0.0),
                source=str(row.get("source") or "imported"),
                version=int(row.get("version") or 1),
                installed=bool(row.get("installed", True)),
                replace=True,
            )
            written += 1
        return written

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")
        self._conn.commit()
