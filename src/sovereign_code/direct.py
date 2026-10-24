"""Single-shot file editing: ask once, write the files, let checks decide.

The agent loop is expensive — every turn re-sends a growing prompt through an
18 GB model, so one small edit costs minutes. This mode asks for the complete
contents of the files to change in one request, parses them, and writes them.
No tool calls, no loop, one round trip (plus repair rounds from the pipeline).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path

MAX_FILES = 8
MAX_FILE_BYTES = 400_000

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


UNDO_FILE = ".sovereign-undo.json"


def _capture_backup(target: Path) -> object:
    """Record the previous contents of ``target`` for a later undo.

    ``None`` means the file did not exist yet. A binary or unreadable file is
    recorded as a dict instead, because collapsing it to ``None`` would make
    :func:`undo_writes` delete a file it could not back up.
    """
    if not target.is_file():
        return None
    try:
        with target.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError:
        try:
            return {"binary": base64.b64encode(target.read_bytes()).decode("ascii")}
        except OSError:
            return {"unreadable": True}
    except OSError:
        return {"unreadable": True}


def _restore_backup(target: Path, previous: object) -> None:
    """Put one file back; raise rather than deleting an unknown backup."""
    if previous is None:
        target.unlink(missing_ok=True)
        return
    if isinstance(previous, str):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(previous)
        return
    if isinstance(previous, dict) and isinstance(previous.get("binary"), str):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(previous["binary"]))
        return
    raise OSError(f"no usable backup for {target}")


def apply_writes(root: Path, writes: list[FileWrite]) -> tuple[list[str], list[str]]:
    """Write the files. Returns (written, rejected).

    The write is *transactional*: every file is staged first, and only when
    all of them are valid does anything touch the working tree. The previous
    contents of every overwritten file (and the list of files that were
    created) are recorded in ``.sovereign-undo.json`` so a single
    :func:`undo_writes` can put the project back the way it was.
    """
    root = root.resolve()
    written: list[str] = []
    rejected: list[str] = []

    # Validate and stage every write before touching the working tree.
    staged: list[tuple[Path, str]] = []
    for item in writes:
        target = resolve_target(root, item.path)
        if target is None or len(item.content.encode("utf-8", "ignore")) > MAX_FILE_BYTES:
            rejected.append(item.path)
            continue
        staged.append((target, item.content))

    # Record the previous state so the whole batch can be undone.
    backups: dict[str, object] = {}
    for target, _content in staged:
        rel = str(target.relative_to(root))
        backups[rel] = _capture_backup(target)

    # Write everything. If one write fails, restore the ones already written.
    newly_written: list[str] = []
    try:
        for target, content in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            newly_written.append(str(target.relative_to(root)))
    except OSError:
        # Best-effort rollback of the files already written.
        for rel in newly_written:
            target = root / rel
            try:
                _restore_backup(target, backups.get(rel))
            except OSError:
                pass
        raise

    # Persist the journal for a later `undo_writes`.
    import json

    journal = {
        "written": newly_written,
        "backups": backups,
    }
    journal_path = root / UNDO_FILE
    try:
        journal_path.write_text(json.dumps(journal, ensure_ascii=False), encoding="utf-8")
        from .safefile import harden

        harden(journal_path)
    except OSError:
        pass

    written.extend(newly_written)
    return written, rejected


def undo_writes(root: Path) -> list[str]:
    """Restore the working tree to the state before the last ``apply_writes``.

    Returns the list of paths that were restored. An empty result means there
    was nothing to undo.
    """
    import json

    root = root.resolve()
    journal_path = root / UNDO_FILE
    if not journal_path.is_file():
        return []
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    backups = journal.get("backups") or {}
    if not isinstance(backups, dict):
        return []
    restored: list[str] = []
    for rel, previous in backups.items():
        target = resolve_target(root, str(rel))
        if target is None:
            # A journal is a file on disk and can be edited or shipped in a
            # clone; never let it name a path outside the project.
            continue
        try:
            _restore_backup(target, previous)
            restored.append(rel)
        except OSError:
            continue
    try:
        journal_path.unlink(missing_ok=True)
    except OSError:
        pass
    return restored


def relevant_files(root: Path, prompt: str, limit_bytes: int = 30_000) -> dict[str, str]:
    """Source files worth showing the model, biased towards the prompt."""
    root = root.resolve()
    mentioned = {token for token in re.findall(r"[\w.-]+\.\w{1,5}", prompt)}
    candidates: list[Path] = []
    for path in root.rglob("*"):
        # Only skip ignored directories *inside* the project. Checking the
        # absolute parts also skipped every project whose parent happened to
        # be named "build" or "dist", leaving the model with no context.
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in relative_parts):
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
