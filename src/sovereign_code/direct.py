"""Single-shot file editing: ask once, write the files, let checks decide.

The agent loop is expensive — every turn re-sends a growing prompt through an
18 GB model, so one small edit costs minutes. This mode asks for the complete
contents of the files to change in one request, parses them, and writes them.
No tool calls, no loop, one round trip (plus repair rounds from the pipeline).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_FILES = 8
MAX_FILE_BYTES = 200_000

_STRICT = re.compile(
    r"<<<FILE:\s*(?P<path>[^\n>]+?)\s*>>>\r?\n(?P<body>.*?)\r?\n?<<<END>>>",
    re.DOTALL,
)
_LOOSE = re.compile(
    r"<<<FILE:\s*(?P<path>[^\n>]+?)\s*>>>\r?\n(?P<body>.*?)(?=<<<FILE:|\Z)",
    re.DOTALL,
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".ruff_cache",
}
CODE_SUFFIXES = {".py", ".toml", ".md", ".json", ".yaml", ".yml", ".txt", ".cfg", ".ini"}


@dataclass(frozen=True)
class FileWrite:
    path: str
    content: str


def parse_blocks(text: str) -> list[FileWrite]:
    """Extract file blocks, tolerating a missing closing marker."""
    matches = list(_STRICT.finditer(text))
    if not matches:
        matches = list(_LOOSE.finditer(text))
    writes: list[FileWrite] = []
    for match in matches[:MAX_FILES]:
        path = match.group("path").strip().strip("`'\"")
        body = match.group("body")
        if not path:
            continue
        writes.append(FileWrite(path=path, content=body.rstrip("\n") + "\n"))
    return writes


def resolve_target(root: Path, relative: str) -> Path | None:
    """Resolve a model-supplied path, refusing anything outside the project."""
    # NB: never use lstrip("./") here — it strips leading dots *and* slashes,
    # which would turn "../../etc/passwd" into a harmless-looking "etc/passwd".
    cleaned = relative.strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    candidate = Path(cleaned)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def apply_writes(root: Path, writes: list[FileWrite]) -> tuple[list[str], list[str]]:
    """Write the files. Returns (written, rejected)."""
    root = root.resolve()
    written: list[str] = []
    rejected: list[str] = []
    for item in writes:
        target = resolve_target(root, item.path)
        if target is None or len(item.content.encode("utf-8", "ignore")) > MAX_FILE_BYTES:
            rejected.append(item.path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8")
        written.append(str(target.relative_to(root)))
    return written, rejected


def relevant_files(root: Path, prompt: str, limit_bytes: int = 30_000) -> dict[str, str]:
    """Source files worth showing the model, biased towards the prompt."""
    root = root.resolve()
    mentioned = {token for token in re.findall(r"[\w.-]+\.\w{1,5}", prompt)}
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix not in CODE_SUFFIXES:
            continue
        candidates.append(path)

    def priority(path: Path) -> tuple[int, int]:
        favoured = 0 if path.name in mentioned else 1
        return (favoured, len(path.name))

    chosen: dict[str, str] = {}
    budget = limit_bytes
    for path in sorted(candidates, key=priority):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > budget:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        chosen[str(path.relative_to(root))] = text
        budget -= size
        if budget <= 0:
            break
    return chosen


def build_messages(
    prompt: str,
    plan: str,
    files: dict[str, str],
    failure: str = "",
) -> list[dict[str, str]]:
    system = (
        "You are a precise coding agent. Return ONLY complete file contents in this "
        "exact format, one block per file changed or created:\n\n"
        "<<<FILE: relative/path.py>>>\n"
        "<entire new file content>\n"
        "<<<END>>>\n\n"
        "Rules: rewrite whole files (never patches or diffs), use paths relative to the "
        "project root, do not add commentary outside the blocks, and keep the existing "
        "style. If nothing needs to change, return no blocks."
    )
    parts = []
    if files:
        listing = "\n\n".join(f"--- {path} ---\n{text}" for path, text in files.items())
        parts.append(f"Current files:\n{listing}")
    parts.append(f"Task:\n{prompt}")
    parts.append(f"Plan:\n{plan}")
    if failure:
        parts.append(
            "The project's checks failed after your previous attempt. Fix the code so "
            f"they pass.\n\nCheck output:\n{failure}"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
