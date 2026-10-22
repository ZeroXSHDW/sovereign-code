"""Saved prompt templates ("skills") stored as Markdown files.

Skills ship with the repo under ``skills/`` and can be overridden or
extended per-machine under ``~/Documents/local-ai/config/skills``.

The shipped library is large (22k files). Reading every file costs seconds
and hundreds of megabytes of IO, so the listing and the search read the
SQLite index (``sovereign skill-db sync``) when it describes the tree, and
walk the filesystem only when it does not.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import DATA_DIR, LOCAL_AI_ROOT, PROJECT_ROOT

REPO_SKILLS_DIR = PROJECT_ROOT / "skills"
USER_SKILLS_DIR = LOCAL_AI_ROOT / "config" / "skills"

# The filesystem walk read the first screen of every skill file; the index
# stores whole bodies, so the same slice is taken from there.
BODY_CHARS = 4000

# How many extra name matches the index may fetch for one search. The cap
# keeps a very broad query from reading the body of every skill.
MAX_EXTRA_NAMES = 1000

# How much of the tree the index has to know before it may answer for it,
# and how much bigger than the tree its own library may be. A few rows for
# skills that are gone from disk must not switch the library back to reading
# every file.
INDEX_COVERAGE = 0.5
INDEX_SIZE_FACTOR = 1.1

# The index labels the rows it synced from the shipped library and the ones it
# synced from the per-user directory.
SOURCE_USER = "user"
SOURCE_REPO = "repo"


def _skill_dirs() -> list[Path]:
    # User dir first so local edits win over the shipped defaults.
    return [USER_SKILLS_DIR, REPO_SKILLS_DIR]


def ensure_skills_dir() -> Path:
    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return USER_SKILLS_DIR


# ------------------------------------------------------------------ paths


def resolve_skill_path(root: Path, name: str) -> Path | None:
    """Resolve a skill name to a file inside `root`, or None when it escapes.

    Mirrors ``direct.resolve_target``: a name is a plain file stem, and the
    resolved path must still sit inside the skills directory. A name like
    ``../../../../tmp/secret`` must never read a file outside the library.
    """
    if not name or "\x00" in name:
        return None
    # A separator would reach a subdirectory, on any platform.
    if "/" in name or "\\" in name:
        return None
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    base = root.resolve()
    resolved = (base / f"{name}.md").resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


def _dir_source(directory: Path) -> str:
    """Which half of the library a directory belongs to."""
    return SOURCE_USER if directory == USER_SKILLS_DIR else SOURCE_REPO


def _dir_stems(directory: Path) -> set[str]:
    """The skill file stems of one directory (one listing, no file reads)."""
    try:
        with os.scandir(directory) as entries:
            return {entry.name[:-3] for entry in entries if entry.name.endswith(".md")}
    except OSError:
        return set()


def _chunks(items: list[str], size: int) -> list[list[str]]:
    """Split a list into chunks of at most `size` items."""
    return [items[index : index + size] for index in range(0, len(items), size)]


# ------------------------------------------------------------------ index


def _index_path() -> Path:
    """Where the SQLite skill index lives."""
    try:
        from .skilldb import DEFAULT_DB
    except ImportError:  # pragma: no cover - skilldb ships with the package
        return DATA_DIR / "skills.db"
    return DEFAULT_DB


def _connect_index() -> sqlite3.Connection | None:
    """Open the index read-only, or return None when it cannot be used."""
    path = _index_path()
    if not path.is_file():
        return None
    # Read-only first: the index belongs to the skill database, this module
    # only ever asks it questions. A plain handle is the fallback for a
    # database whose write-ahead log cannot be opened read-only.
    for target, uri in ((f"{path.resolve().as_uri()}?mode=ro", True), (str(path), False)):
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(target, uri=uri)
            conn.execute("SELECT 1 FROM skills LIMIT 1").fetchone()
            return conn
        except sqlite3.Error:
            if conn is not None:
                conn.close()
    return None


@contextmanager
def _index() -> Iterator[sqlite3.Connection | None]:
    """A read-only connection to the skill index, or None when it is unusable."""
    conn = _connect_index()
    try:
        yield conn
    finally:
        if conn is not None:
            conn.close()


def _index_usable(conn: sqlite3.Connection | None) -> bool:
    """Whether the index may answer for the skills tree on disk.

    The index has to describe *this* tree: it must know most of the files and
    it must not be a library of its own, or it would answer with skills the
    caller never had. Both checks are cheap - the name list comes from a
    covering index - and they keep the index from making a small tree slower
    than reading it.
    """
    if conn is None:
        return False
    stems: set[str] = set()
    for directory in _skill_dirs():
        stems |= _dir_stems(directory)
    if not stems:
        return False
    try:
        names = {str(row[0]) for row in conn.execute("SELECT name FROM skills").fetchall()}
    except sqlite3.Error:
        return False
    if not names:
        return False
    known = len(stems & names)
    return known >= len(stems) * INDEX_COVERAGE and len(names) <= len(stems) * INDEX_SIZE_FACTOR


def _fts_query(terms: list[str]) -> str | None:
    """An FTS5 MATCH expression for the search terms, or None when unusable."""
    parts: list[str] = []
    for term in terms:
        for token in re.findall(r"\w+", term):
            # The prefix match keeps the query close to the substring search
            # the filesystem walk did ("review" also finds "reviewing").
            parts.append(f'"{token}"*')
    if not parts:
        return None
    return " AND ".join(parts)


# ------------------------------------------------------------------ files


def _fs_description(path: Path) -> str:
    """The first Markdown heading of a skill file."""
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return ""


def _fs_entries(directory: Path) -> list[tuple[str, str]]:
    """(name, description) pairs read from the filesystem."""
    entries: list[tuple[str, str]] = []
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.md")):
        entries.append((path.stem, _fs_description(path)))
    return entries


def _fs_bodies(directory: Path) -> list[tuple[str, str]]:
    """(name, first screen of the body) pairs read from the filesystem."""
    bodies: list[tuple[str, str]] = []
    if not directory.is_dir():
        return bodies
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:BODY_CHARS]
        except OSError:
            continue
        bodies.append((path.stem, text))
    return bodies


def _search_description(body: str) -> str:
    """The one-line description the search reads from the head of a skill."""
    for line in body.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# ------------------------------------------------------------------ public


def list_skills() -> list[tuple[str, str]]:
    """Return (name, one-line description) pairs, alphabetical."""
    seen: dict[str, str] = {}
    with _index() as conn:
        snapshot = None
        if conn is not None and _index_usable(conn):
            snapshot = _index_snapshot(conn)
        for directory in _skill_dirs():
            for name, description in _dir_entries(directory, snapshot):
                # User dir first, so a local edit wins over the shipped one.
                seen.setdefault(name, description)
    return sorted(seen.items())


def _index_snapshot(
    conn: sqlite3.Connection,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """({source: {name: description}}, {name: description}) from the index.

    The second group holds the rows the index does not label with a known
    directory; they are still usable, the file check keeps them in place.
    """
    rows = conn.execute(
        "SELECT name, description, source FROM skills WHERE installed = 1"
    ).fetchall()
    labelled: dict[str, dict[str, str]] = {}
    unlabelled: dict[str, str] = {}
    for row in rows:
        name = str(row[0])
        description = str(row[1] or "")
        source = str(row[2])
        if source in (SOURCE_REPO, SOURCE_USER):
            labelled.setdefault(source, {})[name] = description
        else:
            unlabelled[name] = description
    return labelled, unlabelled


def _index_rows_for(
    snapshot: tuple[dict[str, dict[str, str]], dict[str, str]], source: str
) -> dict[str, str]:
    """The index rows that describe one directory."""
    labelled, unlabelled = snapshot
    rows = labelled.get(source)
    return rows if rows else unlabelled


def _dir_entries(
    directory: Path,
    snapshot: tuple[dict[str, dict[str, str]], dict[str, str]] | None,
) -> list[tuple[str, str]]:
    """(name, description) pairs for one directory, from the index when it fits."""
    if not directory.is_dir():
        return []
    if snapshot is not None:
        rows = _index_rows_for(snapshot, _dir_source(directory))
        if rows:
            stems = _dir_stems(directory)
            entries = [(name, rows[name]) for name in stems if name in rows]
            # Skills the index does not know yet are read from disk.
            for name in stems - rows.keys():
                entries.append((name, _fs_description(directory / f"{name}.md")))
            return entries
    return _fs_entries(directory)


def read_skill(name: str) -> str | None:
    """The body of one skill, or None when there is no such skill."""
    for directory in _skill_dirs():
        path = resolve_skill_path(directory, name)
        if path is None or not path.is_file():
            continue
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def render_skill(name: str, user_input: str) -> str:
    template = read_skill(name)
    if template is None:
        raise KeyError(name)
    return template.replace("{{prompt}}", user_input)


def search_skills(query: str, limit: int = 30) -> list[tuple[str, str]]:
    """Search names and the first screen of every skill in both directories."""
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return []
    matches: list[tuple[int, str, str]] = []
    with _index() as conn:
        usable = conn is not None and _index_usable(conn)
        for directory in _skill_dirs():
            bodies = _index_bodies(conn, directory, terms) if usable else None
            if bodies is None:
                bodies = _fs_bodies(directory)
            for name, body in bodies:
                description = _search_description(body)
                haystack = f"{name}\n{description}\n{body}".lower()
                if not all(term in haystack for term in terms):
                    continue
                score = 0
                if all(term in name.lower() for term in terms):
                    score += 10
                if all(term in description.lower() for term in terms):
                    score += 5
                matches.append((-score, name, description))
    matches.sort()
    return [(name, description) for _score, name, description in matches[: max(1, limit)]]


def _name_matches(conn: sqlite3.Connection, terms: list[str], exclude: set[str]) -> list[str]:
    """Skill names that contain every term, even when the text index misses them.

    The full-text index knows whole words, so "cybersecurity" holds no
    "security" token. The index still lists every name in one cheap scan, and
    a name that contains the terms is a match the filesystem walk would have
    found.
    """
    try:
        names = conn.execute("SELECT name FROM skills").fetchall()
    except sqlite3.Error:
        return []
    found: list[str] = []
    for row in names:
        name = str(row[0])
        if name in exclude:
            continue
        lowered = name.lower()
        if all(term in lowered for term in terms):
            found.append(name)
            if len(found) >= MAX_EXTRA_NAMES:
                break
    return found


def _index_bodies(
    conn: sqlite3.Connection | None, directory: Path, terms: list[str]
) -> list[tuple[str, str]] | None:
    """(name, body) candidates for one directory, or None when the index cannot serve it."""
    if conn is None:
        return None
    if directory != REPO_SKILLS_DIR:
        # The per-user directory holds a handful of prompt templates and
        # overrides the shipped ones, so it is always read directly.
        return None
    match = _fts_query(terms)
    if match is None:
        return None
    stems = _dir_stems(directory)
    if not stems:
        return []
    try:
        rows = list(
            conn.execute(
                "SELECT name, substr(content, 1, ?) FROM skills "
                "WHERE installed = 1 "
                "AND name IN (SELECT name FROM skills_fts WHERE skills_fts MATCH ?)",
                (BODY_CHARS, match),
            ).fetchall()
        )
        extra = _name_matches(conn, terms, {str(row[0]) for row in rows})
        for chunk in _chunks(extra, 500):
            rows.extend(
                conn.execute(
                    "SELECT name, substr(content, 1, ?) FROM skills "
                    "WHERE installed = 1 "
                    "AND name IN (SELECT value FROM json_each(?))",
                    (BODY_CHARS, json.dumps(chunk)),
                ).fetchall()
            )
    except sqlite3.Error:
        return None
    return [(str(row[0]), str(row[1] or "")) for row in rows if str(row[0]) in stems]
