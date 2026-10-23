"""Skill database: structured index of skills, prompts and .md knowledge.

Builds on the existing ``skills/`` Markdown skills plus a SQLite index
(``DATA_DIR/skills.db``) with FTS5 search, metadata (category, rating, usage,
installed state), install/uninstall and a sync from the repo ``skills/`` tree.
This is the single source of truth for "which skill does what" that the tier
gateway, the browser agent and every code agent can query.

The index is deliberately boring: one row per skill version, the markdown
stored once in ``skills.content``, and a full-text index that points back at
those rows instead of keeping a second copy of the text.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .skills import USER_SKILLS_DIR, _skill_dirs

DEFAULT_DB = DATA_DIR / "skills.db"

# The full-text index is an *external content* index over ``skills``: FTS5
# keeps only the token index and reads the column values back from ``skills``
# when it needs them.  The previous declaration made FTS5 store its own copy
# of every column, so the 167 MB of markdown was held twice (471 MB database
# for 167 MB of content).
_FTS_CREATE = """
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    name, tags, category, description, content,
    content='skills', content_rowid='rowid', tokenize='unicode61'
)
"""
# The same table without the IF NOT EXISTS guard, used when the old table has
# to be dropped and recreated.
_FTS_RECREATE = """
CREATE VIRTUAL TABLE skills_fts USING fts5(
    name, tags, category, description, content,
    content='skills', content_rowid='rowid', tokenize='unicode61'
)
"""

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS skills (
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
    """,
    """
    CREATE INDEX IF NOT EXISTS skills_category_idx ON skills(category)
    """,
    """
    CREATE INDEX IF NOT EXISTS skills_updated_idx ON skills(updated_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS skills_name_idx ON skills(name)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS skills_name_version_uidx ON skills(name, version)
    """,
    # Covering index for the dashboard's bank query: it answers "the installed
    # skills ordered by rating and usage" without touching the table, which
    # holds the markdown inline and costs a full scan per refresh.
    """
    CREATE INDEX IF NOT EXISTS skills_bank_idx
    ON skills(installed, rating DESC, usage_count DESC, name, category)
    """,
    _FTS_CREATE,
)

_INSERT_SKILL = """
INSERT INTO skills
(id, name, category, tags, description, content, rating,
 usage_count, last_used_at, installed, source, version, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPDATE_SKILL = """
UPDATE skills SET content = ?, description = ?, tags = ?, category = ?,
    source = ?, installed = 1, updated_at = ? WHERE rowid = ?
"""

# Index one row of ``skills``.  Reading the values back from the table keeps
# the index and the content in step by construction.
_INDEX_BY_ID = (
    "INSERT INTO skills_fts(rowid, name, tags, category, description, content) "
    "SELECT rowid, name, tags, category, description, content FROM skills WHERE id = ?"
)
_INDEX_BY_ROWID = (
    "INSERT INTO skills_fts(rowid, name, tags, category, description, content) "
    "SELECT rowid, name, tags, category, description, content FROM skills WHERE rowid = ?"
)
# The FTS5 'delete' command is the only safe way to drop a row from an
# external-content index: the values have to match the ones that were
# indexed, otherwise the tokens stay behind and the index drifts.
_UNINDEX_BY_ROWID = (
    "INSERT INTO skills_fts(skills_fts, rowid, name, tags, category, description, content) "
    "SELECT 'delete', rowid, name, tags, category, description, content FROM skills WHERE rowid = ?"
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


def _digest(text: str) -> str:
    """Fingerprint of a skill body, so unchanged files can be skipped."""
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _last_rowid(cursor: sqlite3.Cursor) -> int:
    """Rowid of the row just inserted; the full-text index keys on it."""
    rowid = cursor.lastrowid
    if rowid is None:
        raise sqlite3.OperationalError("insert did not return a rowid")
    return rowid


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a block inside one explicit transaction.

    The connection runs in autocommit mode, so the block owns its
    transaction: DDL and DML inside it commit together, and a failure rolls
    the whole thing back.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    conn.execute("COMMIT")


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


@dataclass
class _SyncRow:
    """The fields the sync compares and writes for one skill.

    The body is kept as a digest: ``skills.content`` holds 167 MB of
    markdown, and the sync only has to know whether it changed.
    """

    digest: str
    description: str
    tags: str
    category: str
    source: str
    installed: int = 1
    content: str = ""
    rowid: int = 0
    version: int = 0


def _same_row(row: _SyncRow, state: _SyncRow) -> bool:
    """True when the stored row already holds everything the file has."""
    return (
        row.digest == state.digest
        and row.description == state.description
        and row.tags == state.tags
        and row.category == state.category
        and row.source == state.source
        and row.installed == 1
    )


def _same_indexed(row: _SyncRow, state: _SyncRow) -> bool:
    """True when the indexed columns are unchanged, so the FTS entry can stay."""
    return (
        row.digest == state.digest
        and row.description == state.description
        and row.tags == state.tags
        and row.category == state.category
    )


class SkillDB:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        # Autocommit mode: every write path opens its own explicit
        # transaction, so the DDL around a rebuild is atomic as well and
        # nothing is ever left half-open on the connection.
        self._conn.isolation_level = None
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        for statement in _SCHEMA:
            self._conn.execute(statement)
        self._migrate()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> SkillDB:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -------------------------------------------------------------- migration

    def _migrate(self) -> None:
        """Bring an older database up to the current layout.

        The one structural change that matters is the full-text table: a
        database built before the external-content switch keeps a private copy
        of every column, which doubled the size of the file.  The old layout
        is detected from ``sqlite_master`` and rebuilt in a single
        transaction, so a failed migration leaves the old index untouched.
        """
        if self._fts_is_external():
            return
        self.rebuild_fts()

    def _fts_is_external(self) -> bool:
        """True when ``skills_fts`` indexes ``skills`` instead of copying it."""
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'skills_fts'"
        ).fetchone()
        if row is None or not row["sql"]:
            return False
        sql = row["sql"].lower()
        return "content=" in sql and "content_rowid=" in sql

    def rebuild_fts(self) -> None:
        """Rebuild the full-text index from the ``skills`` table.

        Drops the FTS table (which takes its shadow tables with it), recreates
        it as an external-content index and re-tokenizes every row in one
        pass.  Everything happens inside a single transaction, so an
        interrupted rebuild leaves the previous index in place.
        """
        with _transaction(self._conn):
            self._conn.execute("DROP TABLE IF EXISTS skills_fts")
            self._conn.execute(_FTS_RECREATE)
            self._conn.execute("INSERT INTO skills_fts(skills_fts) VALUES('rebuild')")
        self._reclaim_space()

    def _reclaim_space(self) -> None:
        """Give the pages freed by the rebuild back to the filesystem.

        Dropping the old FTS table leaves ~170 MB of dead pages behind; only
        a VACUUM returns them to the disk.  A VACUUM needs room for a second
        copy of the file, so a failure here is not fatal - the rebuild itself
        has already been committed.
        """
        try:
            free = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0])
            pages = int(self._conn.execute("PRAGMA page_count").fetchone()[0])
        except sqlite3.Error:
            return
        if pages <= 0 or free * 10 < pages:
            return
        try:
            self._conn.execute("VACUUM")
        except sqlite3.Error:
            pass

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
        if not replace:
            exists = self._conn.execute(
                "SELECT 1 FROM skills WHERE name = ? AND version = ?",
                (name, int(version)),
            ).fetchone()
            if exists is not None:
                raise ValueError(f"skill already exists: {name}") from None
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
            with _transaction(self._conn):
                cursor = self._conn.execute(_INSERT_SKILL, row)
                self._fts_write(_last_rowid(cursor), name, tags_csv, category, description, content)
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
        skill = self._row_to_skill(
            self._conn.execute("SELECT * FROM skills WHERE id = ?", (pid,)).fetchone()
        )
        if skill is None:
            raise RuntimeError(f"skill {name} was not found after insert")
        return skill

    def _fts_write(
        self,
        rowid: int,
        name: str,
        tags: str,
        category: str,
        description: str,
        content: str,
    ) -> None:
        """Index one row; the rowid has to be the ``skills`` rowid."""
        self._conn.execute(
            "INSERT INTO skills_fts(rowid, name, tags, category, description, content) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rowid, name, tags, category, description, content),
        )

    def _fts_delete(
        self,
        rowid: int,
        name: str,
        tags: str,
        category: str,
        description: str,
        content: str,
    ) -> None:
        """Drop one row from the full-text index."""
        self._conn.execute(
            "INSERT INTO skills_fts(skills_fts, rowid, name, tags, category, description, content) "
            "VALUES ('delete', ?, ?, ?, ?, ?, ?)",
            (rowid, name, tags, category, description, content),
        )

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
        with _transaction(self._conn):
            cursor = self._conn.execute(
                _INSERT_SKILL,
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
                _last_rowid(cursor),
                name,
                tags_csv,
                row["category"] if category is None else category,
                desc,
                content,
            )
        skill = self._row_to_skill(
            self._conn.execute("SELECT * FROM skills WHERE id = ?", (pid,)).fetchone()
        )
        if skill is None:
            raise RuntimeError(f"skill {name} was not found after replace")
        return skill

    # ---------------------------------------------------------------- read

    def get(self, name: str) -> Skill | None:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        return self._row_to_skill(row)

    def get_version(self, name: str, version: int) -> Skill | None:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE name = ? AND version = ? LIMIT 1",
            (name, int(version)),
        ).fetchone()
        return self._row_to_skill(row)

    def list_all(
        self,
        *,
        category: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        installed_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Skill]:
        if search:
            return self._search(
                search,
                category=category,
                tag=tag,
                installed_only=installed_only,
                limit=limit,
                offset=offset,
            )
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
        sql = "SELECT * FROM skills"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rating DESC, usage_count DESC, updated_at DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
        rows = self._conn.execute(sql, params)
        return [s for s in (self._row_to_skill(r) for r in rows) if s is not None]

    def _search(
        self,
        query: str,
        *,
        category: str | None = None,
        tag: str | None = None,
        installed_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Skill]:
        """Full-text search, best match first.

        The order comes from FTS5's bm25() relevance score; rating, usage and
        update time only break ties.  Ordering by those columns alone made a
        search for "testing" return whichever rows happened to be synced last
        instead of the rows that actually talk about testing.
        """
        clauses: list[str] = []
        params: list[Any] = [query]
        if category:
            clauses.append("s.category = ?")
            params.append(category)
        if tag:
            clauses.append("s.tags LIKE ?")
            params.append(f"%,{tag},%")
        if installed_only:
            clauses.append("s.installed = 1")
        sql = (
            "WITH hits AS ("
            " SELECT rowid AS rid, bm25(skills_fts) AS score FROM skills_fts"
            " WHERE skills_fts MATCH ?"
            ") SELECT s.* FROM skills s JOIN hits h ON h.rid = s.rowid"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += (
            " ORDER BY h.score, s.rating DESC, s.usage_count DESC, s.updated_at DESC"
            " LIMIT ? OFFSET ?"
        )
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
        with _transaction(self._conn):
            self._conn.execute(
                "UPDATE skills SET usage_count = usage_count + 1, "
                "last_used_at = ?, updated_at = ? WHERE id = ?",
                (_now(), _now(), row["id"]),
            )

    def rate(self, name: str, rating: float) -> bool:
        row = self._conn.execute(
            "SELECT id FROM skills WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return False
        with _transaction(self._conn):
            self._conn.execute(
                "UPDATE skills SET rating = ?, updated_at = ? WHERE id = ?",
                (max(0.0, min(5.0, float(rating))), _now(), row["id"]),
            )
        return True

    # ---------------------------------------------------------------- delete

    def delete(self, name: str) -> bool:
        rows = self._conn.execute(
            "SELECT rowid, name, tags, category, description, content FROM skills WHERE name = ?",
            (name,),
        ).fetchall()
        if not rows:
            return False
        with _transaction(self._conn):
            for row in rows:
                self._fts_delete(
                    row["rowid"],
                    row["name"],
                    row["tags"],
                    row["category"],
                    row["description"],
                    row["content"],
                )
            self._conn.execute("DELETE FROM skills WHERE name = ?", (name,))
        return True

    # ---------------------------------------------------------------- sync

    def sync_repo(self, *, dry_run: bool = False) -> dict[str, int]:
        """Index every markdown skill under skills/ and user skills dir.

        Returns counts of {added, updated, unchanged, disabled}. Marks everything found
        on disk as installed=1; skills only in the DB but no longer on disk are
        marked installed=0 (not deleted, so history is kept).

        The tree is read once, compared in memory and written back with
        ``executemany`` inside a single transaction.  The old code opened a
        transaction per file - about 23k commits for a 23k file tree - and it
        rewrote ``skills.content`` without touching the full-text index, so
        search results slowly drifted away from the content they indexed.
        """
        stats = {"added": 0, "updated": 0, "unchanged": 0, "disabled": 0}
        snapshot, row_names = self._index_snapshot()
        known: dict[str, str] = {}
        pending: dict[str, _SyncRow] = {}
        now = _now()

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
                state = _SyncRow(
                    digest=_digest(text),
                    description=_first_heading(text),
                    tags=_csv(self._tags_from_text(text)),
                    category=self._category_from_name(name),
                    source=source,
                    content=text,
                )
                # A name can show up twice: a local override and the shipped
                # file share one.  The first occurrence creates the row, the
                # next one updates it, the way the per-file loop used to.
                previous = pending.get(name)
                if previous is None:
                    previous = snapshot.get(name)
                if previous is None:
                    stats["added"] += 1
                elif previous.digest != state.digest or previous.description != state.description:
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
                pending[name] = state
                known[name] = source

        if dry_run:
            # A dry run reports what it saw on disk and writes nothing; the
            # disabled count stays at zero, as it always has.
            return stats

        inserts: list[tuple[Any, ...]] = []
        updates: list[tuple[Any, ...]] = []
        reindex: list[int] = []
        for name, state in pending.items():
            row = snapshot.get(name)
            if row is None:
                inserts.append(
                    (
                        str(uuid.uuid4()),
                        name,
                        state.category,
                        state.tags,
                        state.description or name,
                        state.content,
                        0.0,
                        0,
                        None,
                        1,
                        state.source,
                        1,
                        now,
                        now,
                    )
                )
                continue
            if _same_row(row, state):
                continue
            updates.append(
                (
                    state.content,
                    state.description,
                    state.tags,
                    state.category,
                    state.source,
                    now,
                    row.rowid,
                )
            )
            if not _same_indexed(row, state):
                reindex.append(row.rowid)

        missing = [name for name in row_names if name not in known]
        stats["disabled"] = len(missing)

        with _transaction(self._conn):
            if inserts:
                self._conn.executemany(_INSERT_SKILL, inserts)
                self._conn.executemany(_INDEX_BY_ID, [(row[0],) for row in inserts])
            if reindex:
                # Drop the stale index entries before the rows change: the
                # 'delete' command needs the values that are indexed now.
                self._conn.executemany(_UNINDEX_BY_ROWID, [(rid,) for rid in reindex])
            if updates:
                self._conn.executemany(_UPDATE_SKILL, updates)
            if reindex:
                self._conn.executemany(_INDEX_BY_ROWID, [(rid,) for rid in reindex])
            if missing:
                self._conn.executemany(
                    "UPDATE skills SET installed = 0 WHERE name = ?",
                    [(name,) for name in dict.fromkeys(missing)],
                )
        return stats

    def _index_snapshot(self) -> tuple[dict[str, _SyncRow], list[str]]:
        """Read the whole table once, keeping only what the sync compares.

        ``skills.content`` holds 167 MB of markdown, so each body is reduced
        to a digest while the rows stream past; the full-text re-index reads
        the bodies it needs straight from the table.
        """
        snapshot: dict[str, _SyncRow] = {}
        names: list[str] = []
        cursor = self._conn.execute(
            "SELECT rowid, name, version, content, description, tags, category, source, installed "
            "FROM skills"
        )
        for row in cursor:
            name = row["name"]
            names.append(name)
            current = snapshot.get(name)
            if current is not None and int(row["version"]) <= current.version:
                continue
            snapshot[name] = _SyncRow(
                digest=_digest(row["content"] or ""),
                description=row["description"] or "",
                tags=row["tags"] or "",
                category=row["category"] or "",
                source=row["source"] or "",
                installed=int(row["installed"]),
                rowid=int(row["rowid"]),
                version=int(row["version"]),
            )
        return snapshot, names

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
