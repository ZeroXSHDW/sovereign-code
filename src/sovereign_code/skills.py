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

# The FTS index already applies every term. Ranking the candidates in SQLite
# and reading only the best ones keeps a broad query ("the") from pulling tens
# of thousands of 4k-character bodies into Python just to return ten rows.
SEARCH_CANDIDATE_FLOOR = 200
SEARCH_CANDIDATE_PER_RESULT = 20
SEARCH_CANDIDATE_CEILING = 5000
NAME_MATCH_FLOOR = 50
NAME_MATCH_PER_RESULT = 10

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

# Query words that name a concept differently from most skill titles. Search
# groups each original word with its alternatives (OR), then ANDs the groups.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "a11y": ("accessibility",),
    "auth": ("authentication", "authorization"),
    "cd": ("deployment",),
    "ci": ("cicd", "github", "actions"),
    "click": ("cli",),
    "bug": ("debug", "debugging"),
    "bugs": ("debug", "debugging"),
    "db": ("database",),
    "deploy": ("deployment", "shipping"),
    "doc": ("documentation",),
    "docs": ("documentation",),
    "iac": ("terraform", "infrastructure"),
    "i18n": ("internationalization",),
    "k8s": ("kubernetes",),
    "llm": ("ai",),
    "optimi": ("performance",),
    "optimise": ("performance",),
    "optimize": ("performance",),
    "logging": ("observability",),
    "monitoring": ("observability",),
    "perf": ("performance",),
    "plan": ("planning",),
    "profile": ("performance", "profiling"),
    "rag": ("retrieval",),
    "refactor": ("simplification",),
    "ship": ("release", "shipping"),
    "slow": ("performance",),
    "spec": ("specification",),
    "speed": ("performance",),
    "sql": ("database",),
    "terminal": ("cli",),
    "tested": ("test", "testing"),
    "tests": ("test", "testing"),
    "ui": ("frontend", "interface"),
    "vuln": ("security", "vulnerability"),
}

# The listing, the index coverage check and the index snapshot are recomputed
# by every skill command, and each one otherwise scans 20k+ directory entries
# or rows. They are cached per directory/database signature; a change to the
# tree or the index changes the signature. Small limits keep a long-lived MCP
# process from accumulating entries for temporary directories.
STEM_CACHE_LIMIT = 32
NAMES_CACHE_LIMIT = 8
SNAPSHOT_CACHE_LIMIT = 8
USABLE_CACHE_LIMIT = 16
RESULT_CACHE_LIMIT = 64
FS_BODIES_CACHE_LIMIT = 4

_STEM_CACHE: dict[str, tuple[tuple[int, int], frozenset[str]]] = {}
_NAMES_CACHE: dict[tuple[str, int, int, int, int], frozenset[str]] = {}
_SNAPSHOT_CACHE: dict[
    tuple[str, int, int, int, int], tuple[dict[str, dict[str, str]], dict[str, str]]
] = {}
_USABLE_CACHE: dict[
    tuple[tuple[str, int, int, int, int], tuple[tuple[str, int, int], ...]], bool
] = {}
_LIST_CACHE: dict[tuple[object, ...], tuple[tuple[str, str], ...]] = {}
_SEARCH_CACHE: dict[tuple[object, ...], tuple[tuple[str, str], ...]] = {}
_FS_BODIES_CACHE: dict[
    str, tuple[tuple[tuple[str, int, int], ...], tuple[tuple[str, str, str], ...]]
] = {}


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


def _dir_stems(directory: Path) -> frozenset[str]:
    """The skill file stems of one directory (one listing, no file reads).

    Directory metadata changes when a skill is added, removed or renamed, so
    the listing is cached per directory signature. Editing a file's contents
    does not change its stem, which is all this function reports.
    """
    key = str(directory)
    try:
        stat = directory.stat()
    except OSError:
        return frozenset()
    signature = (stat.st_mtime_ns, stat.st_ino)
    cached = _STEM_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    try:
        with os.scandir(directory) as entries:
            stems = frozenset(entry.name[:-3] for entry in entries if entry.name.endswith(".md"))
    except OSError:
        stems = frozenset()
    if len(_STEM_CACHE) >= STEM_CACHE_LIMIT:
        _STEM_CACHE.clear()
    _STEM_CACHE[key] = (signature, stems)
    return stems


def _tree_signature() -> tuple[tuple[str, int, int], ...]:
    """A cheap identity for the skill directories as they are on disk."""
    parts: list[tuple[str, int, int]] = []
    for directory in _skill_dirs():
        try:
            stat = directory.stat()
        except OSError:
            parts.append((str(directory), -1, -1))
        else:
            parts.append((str(directory), stat.st_mtime_ns, stat.st_ino))
    return tuple(parts)


def _user_files_signature() -> tuple[tuple[str, int, int], ...]:
    """Names, mtimes and sizes of the small per-user skill directory."""
    parts: list[tuple[str, int, int]] = []
    try:
        with os.scandir(USER_SKILLS_DIR) as entries:
            for entry in entries:
                if not entry.name.endswith(".md"):
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                parts.append((entry.name, stat.st_mtime_ns, stat.st_size))
    except OSError:
        return ()
    parts.sort()
    return tuple(parts)


def _result_key() -> tuple[object, ...]:
    """Everything a cached listing or search depends on."""
    from .skills_install import profile_signature

    return (
        _db_signature(),
        _tree_signature(),
        _user_files_signature(),
        profile_signature("quality"),
    )


def _profile_descriptions() -> dict[str, str]:
    """Rich frontmatter descriptions for the installed quality profile.

    The SQLite index stores the first heading, which is fine for ranking but
    too terse to show an agent choosing a skill. The curated profile is cached
    and small, so overlay its descriptions on search and listing output.
    """
    from .skills_install import load_curated

    known: dict[str, str] = {}
    for skill in load_curated(profile="quality"):
        known[skill.name] = skill.description
        # Index rows are named after the file stem, which keeps the collection
        # prefix ("addy--security-and-hardening").
        known[skill.source.stem] = skill.description
    return known


def _prefer_profile(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    known = _profile_descriptions()
    return [(name, known.get(name, description)) for name, description in rows]


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


def _db_signature() -> tuple[str, int, int, int, int] | None:
    """Identity of the index file and its write-ahead log, for cache invalidation."""
    path = _index_path()
    try:
        stat = path.stat()
    except OSError:
        return None
    try:
        wal = path.with_name(path.name + "-wal").stat()
    except OSError:
        wal_mtime, wal_size = 0, 0
    else:
        wal_mtime, wal_size = wal.st_mtime_ns, wal.st_size
    return (str(path), stat.st_mtime_ns, stat.st_size, wal_mtime, wal_size)


def _index_names(conn: sqlite3.Connection) -> frozenset[str] | None:
    """Every name the index knows, cached until the index file changes."""
    signature = _db_signature()
    if signature is not None:
        cached = _NAMES_CACHE.get(signature)
        if cached is not None:
            return cached
    try:
        names = frozenset(str(row[0]) for row in conn.execute("SELECT name FROM skills"))
    except sqlite3.Error:
        return None
    if signature is not None:
        if len(_NAMES_CACHE) >= NAMES_CACHE_LIMIT:
            _NAMES_CACHE.clear()
        _NAMES_CACHE[signature] = names
    return names


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
    signature = _db_signature()
    tree = _tree_signature()
    if signature is not None:
        cached = _USABLE_CACHE.get((signature, tree))
        if cached is not None:
            return cached
    stems: set[str] = set()
    for directory in _skill_dirs():
        stems |= _dir_stems(directory)
    if not stems:
        return False
    names = _index_names(conn)
    if not names:
        return False
    known = len(stems & names)
    usable = known >= len(stems) * INDEX_COVERAGE and len(names) <= len(stems) * INDEX_SIZE_FACTOR
    if signature is not None:
        if len(_USABLE_CACHE) >= USABLE_CACHE_LIMIT:
            _USABLE_CACHE.clear()
        _USABLE_CACHE[(signature, tree)] = usable
    return usable


def _term_groups(terms: list[str]) -> list[tuple[str, ...]]:
    """Each query term plus its known alternatives, as one OR group."""
    groups: list[tuple[str, ...]] = []
    for term in terms:
        alternatives = tuple(
            dict.fromkeys(
                token
                for candidate in (term, *SYNONYMS.get(term, ()))
                for token in re.findall(r"\w+", candidate)
            )
        )
        if alternatives:
            groups.append(alternatives)
    return groups


def _groups_match(text: str, terms: list[str], groups: list[tuple[str, ...]]) -> bool:
    """Every term is present in ``text``; synonyms count for plain word terms.

    A punctuated term such as "C++" keeps its exact substring check, because
    FTS tokenises it to "c" and would otherwise match every C skill.
    """
    for term, group in zip(terms, groups, strict=True):
        if not (term.isascii() and term.isalnum()):
            if term not in text:
                return False
        elif not any(word in text for word in group):
            return False
    return True


def _fts_query(terms: list[str]) -> str | None:
    """An FTS5 MATCH expression for the search terms, or None when unusable."""
    groups = _term_groups(terms)
    if not groups:
        return None
    # One OR group per query term, ANDed together. The prefix match keeps the
    # query close to the substring search the filesystem walk did ("review"
    # also finds "reviewing").
    return " AND ".join(
        "(" + " OR ".join(f'"{token}"*' for token in group) + ")" for group in groups
    )


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


def _fs_bodies(directory: Path) -> list[tuple[str, str, str]]:
    """(name, body, description) read from the filesystem.

    Without a SQLite index every search has to read the corpus. The result is
    cached with a per-file mtime/size signature, so the first search pays the
    scan and later searches only stat the files. An edit changes the signature
    and rebuilds the cache.
    """
    try:
        with os.scandir(directory) as entries:
            files = []
            for entry in entries:
                if not entry.name.endswith(".md") or not entry.is_file():
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                files.append((entry.name, stat.st_mtime_ns, stat.st_size))
    except OSError:
        return []
    signature = tuple(sorted(files))
    key = str(directory)
    cached = _FS_BODIES_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return list(cached[1])
    bodies: list[tuple[str, str, str]] = []
    for name, _mtime, _size in signature:
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="ignore")[:BODY_CHARS]
        except OSError:
            continue
        bodies.append((name[:-3], text, _search_description(text)))
    if len(_FS_BODIES_CACHE) >= FS_BODIES_CACHE_LIMIT:
        _FS_BODIES_CACHE.clear()
    _FS_BODIES_CACHE[key] = (signature, tuple(bodies))
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
    key = _result_key()
    cached = _LIST_CACHE.get(key)
    if cached is not None:
        return list(cached)
    seen: dict[str, str] = {}
    indexed = False
    with _index() as conn:
        snapshot = None
        if conn is not None and _index_usable(conn):
            snapshot = _index_snapshot(conn)
            indexed = True
        for directory in _skill_dirs():
            for name, description in _dir_entries(directory, snapshot):
                # User dir first, so a local edit wins over the shipped one.
                seen.setdefault(name, description)
    rows = _prefer_profile(sorted(seen.items()))
    if indexed:
        if len(_LIST_CACHE) >= RESULT_CACHE_LIMIT:
            _LIST_CACHE.clear()
        _LIST_CACHE[key] = tuple(rows)
    return rows


def _index_snapshot(
    conn: sqlite3.Connection,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """({source: {name: description}}, {name: description}) from the index.

    The second group holds the rows the index does not label with a known
    directory; they are still usable, the file check keeps them in place.
    """
    signature = _db_signature()
    if signature is not None:
        cached = _SNAPSHOT_CACHE.get(signature)
        if cached is not None:
            return cached
    rows = conn.execute(
        "SELECT s.name, s.description, s.source FROM skills s "
        "WHERE s.installed = 1 AND s.version = ("
        "  SELECT MAX(v.version) FROM skills v WHERE v.name = s.name AND v.installed = 1"
        ")"
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
    snapshot = (labelled, unlabelled)
    if signature is not None:
        if len(_SNAPSHOT_CACHE) >= SNAPSHOT_CACHE_LIMIT:
            _SNAPSHOT_CACHE.clear()
        _SNAPSHOT_CACHE[signature] = snapshot
    return snapshot


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
    """Search names, descriptions and the full body of every skill.

    The SQLite index ranks candidates with bm25 and caps how many bodies are
    read, so a common word does not pull the whole 22k corpus into Python.
    """
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return []
    key = (query, limit, *_result_key())
    cached = _SEARCH_CACHE.get(key)
    if cached is not None:
        return list(cached)
    # A plain ASCII word query is already an AND match in FTS, so the whole
    # body does not have to travel from SQLite to Python just to be checked
    # again. Punctuated or non-Latin queries keep the substring check.
    groups = _term_groups(terms)
    simple = all(term.isascii() and term.isalnum() for term in terms)
    matches: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    with _index() as conn:
        usable = conn is not None and _index_usable(conn)
        for directory in _skill_dirs():
            bodies = (
                _index_bodies(conn, directory, terms, limit, include_body=not simple)
                if usable
                else None
            )
            indexed = bodies is not None
            if bodies is None:
                bodies = _fs_bodies(directory)
            for name, body, description in bodies:
                if not indexed or not simple:
                    haystack = f"{name}\n{description}\n{body}".lower()
                    if not _groups_match(haystack, terms, groups):
                        continue
                lowered_name = name.lower()
                lowered_description = description.lower()
                score = 0
                if all(any(word in lowered_name for word in group) for group in groups):
                    score += 10
                if all(any(word in lowered_description for word in group) for group in groups):
                    score += 5
                # The user directory is searched first and overrides the
                # shipped file with the same name, exactly like list_skills.
                if name in seen:
                    continue
                seen.add(name)
                matches.append((-score, name, description))
    matches.sort()
    rows = _prefer_profile(
        [(name, description) for _score, name, description in matches[: max(1, limit)]]
    )
    if usable:
        if len(_SEARCH_CACHE) >= RESULT_CACHE_LIMIT:
            _SEARCH_CACHE.clear()
        _SEARCH_CACHE[key] = tuple(rows)
    return rows


def _name_matches(
    conn: sqlite3.Connection, terms: list[str], exclude: set[str], limit: int
) -> list[str]:
    """Skill names that contain every term, even when the text index misses them.

    The full-text index knows whole words, so "cybersecurity" holds no
    "security" token. The index still lists every name in one cheap scan, and
    a name that contains the terms is a match the filesystem walk would have
    found.
    """
    names = _index_names(conn)
    if names is None:
        return []
    groups = _term_groups(terms)
    found: list[str] = []
    for name in names:
        if name in exclude:
            continue
        lowered = name.lower()
        if _groups_match(lowered, terms, groups):
            found.append(name)
            if len(found) >= MAX_EXTRA_NAMES:
                break
    # A short name that contains the terms is a more precise match than a long
    # path-like one ("security" beats "legal--information-security-policy").
    found.sort(key=lambda name: (len(name), name))
    return found[: max(1, limit)]


def _index_bodies(
    conn: sqlite3.Connection | None,
    directory: Path,
    terms: list[str],
    limit: int,
    *,
    include_body: bool = True,
) -> list[tuple[str, str, str]] | None:
    """(name, body, description) candidates for one directory, or None if unserved.

    ``include_body=False`` skips reading the markdown columns; the FTS match
    already proved every term is present, so only the ranked name and
    description are needed.
    """
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
    candidate_cap = max(
        SEARCH_CANDIDATE_FLOOR,
        min(limit * SEARCH_CANDIDATE_PER_RESULT, SEARCH_CANDIDATE_CEILING),
    )
    name_cap = max(NAME_MATCH_FLOOR, min(limit * NAME_MATCH_PER_RESULT, MAX_EXTRA_NAMES))
    if include_body:
        fts_sql = (
            "SELECT s.name, substr(s.content, 1, ?), s.description "
            "FROM skills s JOIN skills_fts ON skills_fts.rowid = s.rowid "
            "WHERE skills_fts MATCH ? AND s.installed = 1 "
            "AND s.version = ("
            "  SELECT MAX(v.version) FROM skills v "
            "  WHERE v.name = s.name AND v.installed = 1"
            ") "
            "ORDER BY bm25(skills_fts), s.name LIMIT ?"
        )
        name_sql = (
            "SELECT s.name, substr(s.content, 1, ?), s.description "
            "FROM skills s "
            "WHERE s.installed = 1 "
            "AND s.version = ("
            "  SELECT MAX(v.version) FROM skills v "
            "  WHERE v.name = s.name AND v.installed = 1"
            ") "
            "AND s.name IN (SELECT value FROM json_each(?))"
        )
        fts_params: tuple[object, ...] = (BODY_CHARS, match, candidate_cap)
        body_param: tuple[object, ...] = (BODY_CHARS,)
    else:
        fts_sql = (
            "SELECT s.name, '', s.description "
            "FROM skills s JOIN skills_fts ON skills_fts.rowid = s.rowid "
            "WHERE skills_fts MATCH ? AND s.installed = 1 "
            "AND s.version = ("
            "  SELECT MAX(v.version) FROM skills v "
            "  WHERE v.name = s.name AND v.installed = 1"
            ") "
            "ORDER BY bm25(skills_fts), s.name LIMIT ?"
        )
        name_sql = (
            "SELECT s.name, '', s.description "
            "FROM skills s "
            "WHERE s.installed = 1 "
            "AND s.version = ("
            "  SELECT MAX(v.version) FROM skills v "
            "  WHERE v.name = s.name AND v.installed = 1"
            ") "
            "AND s.name IN (SELECT value FROM json_each(?))"
        )
        fts_params = (match, candidate_cap)
        body_param = ()
    try:
        rows = list(conn.execute(fts_sql, fts_params).fetchall())
        extra = _name_matches(conn, terms, {str(row[0]) for row in rows}, name_cap)
        for chunk in _chunks(extra, 500):
            rows.extend(conn.execute(name_sql, (*body_param, json.dumps(chunk))).fetchall())
    except sqlite3.Error:
        return None
    return [
        (str(row[0]), str(row[1] or ""), str(row[2] or "")) for row in rows if str(row[0]) in stems
    ]
