"""Repo intelligence: map, search and read a project without flooding a model.

An agent working a real repository cannot read every file. Before this module
the MCP server offered a directory listing and a whole-file read, so a client
either guessed where the code was or spent its context on files that did not
matter. This layer answers the three questions an agent actually asks:

* ``repo_map``    - what is in this project, and where are its definitions?
* ``repo_search`` - which lines mention this term, across the whole tree?
* ``repo_read``   - the lines around a hit, without the rest of a 4,000-line file.

Walking is deterministic (sorted), skips vendored and generated trees, and
stops at a byte budget so one large file cannot stall a turn.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "bower_components",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".eggs",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        "vendor",
        "Pods",
        "DerivedData",
        "coverage",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".gradle",
        ".terraform",
        "site-packages",
    }
)
IGNORED_FILES = frozenset({".DS_Store", "package-lock.json", "yarn.lock", "poetry.lock"})
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".tar",
        ".whl",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".pyc",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".mp3",
        ".mp4",
        ".mov",
        ".gguf",
        ".safetensors",
        ".class",
        ".jar",
        ".o",
        ".a",
        ".dmg",
        ".iso",
    }
)
LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".md": "Markdown",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
}
# Languages whose files are code an agent may need to change. Markup and data
# files are still searchable, but they are ranked after code: this repo carries
# 22k skill Markdown files, and without ranking they filled every budget before
# the first Python file was reached.
CODE_LANGUAGES = frozenset(
    {
        "Python",
        "TypeScript",
        "JavaScript",
        "Go",
        "Rust",
        "Ruby",
        "Java",
        "Kotlin",
        "Swift",
        "C",
        "C++",
        "C#",
        "PHP",
        "Shell",
        "SQL",
        "HTML",
        "CSS",
    }
)
MAX_FILE_BYTES = 1_500_000
_WALK_CAP = 100_000
_SYMBOL_LIMIT = 40


@dataclass(frozen=True)
class SourceFile:
    path: Path
    rel: str
    size: int
    language: str


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    line: int


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str

    def as_line(self, max_chars: int = 240) -> str:
        text = self.text.strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return f"{self.path}:{self.line}: {text}"


def _parts_ignored(parts: tuple[str, ...]) -> bool:
    return any(part in IGNORED_DIRS for part in parts[:-1])


def is_code(language: str) -> bool:
    return language in CODE_LANGUAGES


def iter_files(
    root: Path,
    *,
    glob: str | None = None,
    max_files: int = 20_000,
    max_bytes: int = MAX_FILE_BYTES,
) -> list[SourceFile]:
    """Source files under ``root``, code first, with generated trees skipped."""
    files: list[SourceFile] = []
    stack = [root]
    while stack and len(files) < _WALK_CAP:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for entry in reversed(entries):
            if entry.name in IGNORED_FILES:
                continue
            rel = entry.relative_to(root).as_posix()
            if entry.is_dir():
                if entry.name in IGNORED_DIRS or _parts_ignored(tuple(rel.split("/"))):
                    continue
                stack.append(entry)
                continue
            if entry.suffix.lower() in BINARY_SUFFIXES:
                continue
            if glob and not fnmatch.fnmatch(rel, glob):
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            if size > max_bytes:
                continue
            files.append(
                SourceFile(
                    path=entry,
                    rel=rel,
                    size=size,
                    language=LANGUAGE_BY_SUFFIX.get(entry.suffix.lower(), ""),
                )
            )
    # Code first, then everything else, each alphabetical: a budget is spent on
    # the files an agent can change before it reaches documentation.
    return sorted(files, key=lambda item: (not is_code(item.language), item.rel))[:max_files]


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in data[:4096]:
        return ""
    return data.decode("utf-8", errors="replace")


def _python_symbols(text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    found: list[Symbol] = []

    def walk(nodes: list[ast.stmt], *, classes: bool) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                found.append(Symbol(node.name, kind, node.lineno))
            elif isinstance(node, ast.ClassDef):
                found.append(Symbol(node.name, "class", node.lineno))
                # Methods belong in the map; functions nested inside methods do not.
                walk(node.body, classes=True)
            elif classes and isinstance(node, (ast.If, ast.Try, ast.With)):
                walk(node.body, classes=True)

    walk(tree.body, classes=False)
    return found


_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "TypeScript": (
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M), "class"),
        (
            re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M),
            "function",
        ),
        (
            re.compile(
                r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", re.M
            ),
            "const",
        ),
        (re.compile(r"^\s*(?:export\s+)?(?:interface|type)\s+([A-Za-z_$][\w$]*)", re.M), "type"),
    ),
    "Go": (
        (re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", re.M), "func"),
        (re.compile(r"^type\s+([A-Za-z_]\w*)\s+", re.M), "type"),
    ),
    "Rust": (
        (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", re.M), "fn"),
        (re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", re.M), "type"),
    ),
    "Ruby": (
        (re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)", re.M), "def"),
        (re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*)", re.M), "class"),
    ),
    "Java": (
        (
            re.compile(r"^\s*(?:public|protected|private)?\s*(?:final\s+)?class\s+(\w+)", re.M),
            "class",
        ),
        (
            re.compile(r"^\s*(?:public|protected|private)\s+[\w<>\[\], ]+\s+(\w+)\s*\(", re.M),
            "method",
        ),
    ),
    "Swift": (
        (
            re.compile(
                r"^\s*(?:public\s+|private\s+|internal\s+)?(?:final\s+)?class\s+(\w+)", re.M
            ),
            "class",
        ),
        (re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?func\s+(\w+)", re.M), "func"),
    ),
}
_PATTERNS["JavaScript"] = _PATTERNS["TypeScript"]
_PATTERNS["C#"] = _PATTERNS["Java"]


def symbols(text: str, language: str) -> list[Symbol]:
    """Definitions in ``text``: accurate for Python, best effort for the rest."""
    if language == "Python":
        return _python_symbols(text)[:_SYMBOL_LIMIT]
    found: list[Symbol] = []
    for pattern, kind in _PATTERNS.get(language, ()):
        for match in pattern.finditer(text):
            found.append(Symbol(match.group(1), kind, text.count("\n", 0, match.start()) + 1))
    unique: dict[tuple[str, int], Symbol] = {}
    for symbol in found:
        unique.setdefault((symbol.name, symbol.line), symbol)
    return sorted(unique.values(), key=lambda item: item.line)[:_SYMBOL_LIMIT]


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def repo_map(
    root: Path,
    *,
    max_files: int = 400,
    max_tokens: int = 1800,
) -> str:
    """A token-bounded outline of the project: languages, files and definitions."""
    files = [item for item in iter_files(root, max_files=max_files) if is_code(item.language)]
    languages = Counter(item.language for item in files)
    header = [
        f"# Repo map: {root}",
        f"Files: {len(files)} · "
        + ", ".join(f"{name} {count}" for name, count in languages.most_common(6)),
        "",
    ]
    lines = list(header)
    used = estimate_tokens("\n".join(lines))
    listed = 0
    for item in files:
        definitions = symbols(_read_text(item.path), item.language)
        block = [f"## {item.rel} ({item.language})"]
        block += [f"- {symbol.kind} {symbol.name} @ {symbol.line}" for symbol in definitions[:12]]
        cost = estimate_tokens("\n".join(block))
        if used + cost > max_tokens:
            break
        lines += block
        used += cost
        listed += 1
    if listed < len(files):
        lines.append(
            f"… {len(files) - listed} more files omitted (raise max_files or narrow with search)"
        )
    return "\n".join(lines)


def search_repo(
    root: Path,
    query: str,
    *,
    regex: bool = False,
    ignore_case: bool = True,
    glob: str | None = None,
    limit: int = 50,
    max_files: int = 20_000,
    code_only: bool = False,
) -> list[Hit]:
    """Lines matching ``query`` across the project, code files first."""
    needle = query.strip()
    if not needle:
        raise ValueError("query is empty")
    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile(needle if regex else re.escape(needle), flags)
    hits: list[Hit] = []
    for item in iter_files(root, glob=glob, max_files=max_files):
        if code_only and not is_code(item.language):
            continue
        for number, line in enumerate(_read_text(item.path).splitlines(), start=1):
            if pattern.search(line):
                hits.append(Hit(item.rel, number, line))
                if len(hits) >= limit:
                    return hits
    return hits


def read_slice(
    path: Path,
    *,
    start: int = 1,
    end: int = 200,
    max_chars: int = 24_000,
) -> dict[str, object]:
    """Numbered lines ``start``..``end`` (1-based, inclusive), capped in size."""
    target = path.expanduser()
    if not target.is_file():
        raise ValueError(f"not a file: {target}")
    text = _read_text(target)
    if not text:
        return {"path": str(target), "binary": True, "content": ""}
    lines = text.splitlines()
    first = max(1, min(start, len(lines) or 1))
    last = max(first, min(end, len(lines) or first))
    body = "\n".join(f"{number}\t{lines[number - 1]}" for number in range(first, last + 1))
    truncated = len(body) > max_chars
    return {
        "path": str(target),
        "lines": len(lines),
        "start": first,
        "end": last,
        "truncated": truncated,
        "content": body[:max_chars],
    }
