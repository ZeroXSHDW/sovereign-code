"""Precise, atomic edits to files inside a workspace.

Reading a repository is not enough to change it. The MCP server could write a
whole file, but only with computer control on, and an agent that rewrites a
4,000-line file to change one line loses work when the model trims it.

``write_text`` creates or replaces a file atomically (temp file, then rename),
optionally refusing when the current content is not the version the caller
expects. ``edit_text`` replaces an exact string and refuses an ambiguous match,
so a one-line change cannot silently hit five places. ``apply_patch`` applies a
small unified diff when a client prefers that shape.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_WRITE_BYTES = 2 * 1024 * 1024
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Written:
    path: str
    bytes: int
    created: bool
    sha256: str


@dataclass(frozen=True)
class Edited:
    path: str
    replacements: int
    first_line: int
    sha256: str


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text_strict(target: Path) -> str:
    """Read a file as UTF-8, refusing instead of rewriting it lossily.

    ``errors="replace"`` looks harmless on the read, but the next write turns
    every non-UTF-8 byte into U+FFFD: one unrelated one-line edit corrupts a
    Latin-1 source file from top to bottom. Refusing is the only safe option
    until the caller asks for an explicit encoding.
    """
    try:
        # newline="" keeps CRLF intact. The default universal-newline mode
        # silently converts every line ending to LF on read, so the next write
        # rewrote whole CRLF files.
        with target.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{target} is not valid UTF-8; refusing to rewrite it") from exc


def _detect_newline(text: str) -> str:
    """Return the newline style used by the majority of ``text``."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o644
    if target.exists():
        try:
            mode = target.stat().st_mode & 0o777
        except OSError:
            pass
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            delete=False,
            prefix=".sovereign-",
        ) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise


def write_text(
    path: Path,
    content: str,
    *,
    expected_sha256: str | None = None,
    must_exist: bool = False,
    max_bytes: int = MAX_WRITE_BYTES,
) -> Written:
    """Create or replace ``path`` atomically, with optional version checking."""
    target = path.expanduser()
    data = content.encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError(f"content is {len(data)} bytes; the limit is {max_bytes}")
    exists = target.exists()
    if must_exist and not exists:
        raise ValueError(f"file does not exist: {target}")
    if exists and target.is_dir():
        raise ValueError(f"is a directory: {target}")
    if expected_sha256:
        current = _read_text_strict(target) if exists else ""
        if digest(current) != expected_sha256.strip().lower():
            raise ValueError("file changed since it was read (sha256 mismatch)")
    _atomic_write(target, content)
    return Written(str(target), len(data), not exists, digest(content))


def edit_text(
    path: Path,
    old: str,
    new: str,
    *,
    replace_all: bool = False,
) -> Edited:
    """Replace an exact string once, refusing when the match is ambiguous."""
    target = path.expanduser()
    if not target.is_file():
        raise ValueError(f"not a file: {target}")
    if not old:
        raise ValueError("old string is empty")
    text = _read_text_strict(target)
    occurrences = text.count(old)
    if occurrences == 0:
        raise ValueError("old string not found")
    if occurrences > 1 and not replace_all:
        raise ValueError(f"old string matches {occurrences} places; pass replace_all")
    updated = text.replace(old, new, -1 if replace_all else 1)
    first_line = text[: text.index(old)].count("\n") + 1
    _atomic_write(target, updated)
    return Edited(str(target), occurrences if replace_all else 1, first_line, digest(updated))


def preview(path: Path, old: str, new: str) -> str:
    """The unified diff an edit would produce, without touching the file."""
    text = _read_text_strict(path.expanduser())
    updated = text.replace(old, new, 1)
    return "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
            n=3,
        )
    )


def apply_patch(root: Path, patch: str, *, max_bytes: int = MAX_WRITE_BYTES) -> Edited:
    """Apply one unified diff to one existing file under ``root``.

    The parser is deliberately small: one file, ``@@`` hunks with context,
    additions and removals. Every hunk must match the current text or the whole
    patch is refused, so a stale patch cannot half-apply.
    """
    lines = patch.splitlines()
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        raise ValueError("patch must start with --- and +++ headers")
    relative = lines[1][4:].split("\t")[0].strip()
    if relative.startswith(("a/", "b/")):
        relative = relative[2:]
    target = (root / relative).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"patch path is outside the workspace: {relative}")
    if not target.is_file():
        raise ValueError(f"not a file: {target}")
    original = _read_text_strict(target)
    source = original.splitlines(keepends=True)
    newline = _detect_newline(original)

    out: list[str] = []
    index = 2
    cursor = 0
    changed = 0
    first_line = 0
    while index < len(lines):
        match = _HUNK.match(lines[index])
        if not match:
            index += 1
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2) or 1)
        new_count = int(match.group(4) or 1)
        old_seen = new_seen = 0
        if first_line == 0:
            first_line = old_start
        start = max(0, old_start - 1)
        if start < cursor:
            raise ValueError("patch hunks overlap")
        out.extend(source[cursor:start])
        cursor = start
        index += 1
        while index < len(lines) and not lines[index].startswith("@@"):
            line = lines[index]
            if line.startswith("\\"):
                index += 1
                continue
            tag, body = (line[:1], line[1:]) if line else (" ", "")
            if tag == " ":
                if not _matches(source, cursor, body):
                    raise ValueError(f"patch context does not match at line {cursor + 1}")
                out.append(source[cursor])
                cursor += 1
                old_seen += 1
                new_seen += 1
            elif tag == "-":
                if not _matches(source, cursor, body):
                    raise ValueError(f"patch removal does not match at line {cursor + 1}")
                cursor += 1
                changed += 1
                old_seen += 1
            elif tag == "+":
                out.append(body + newline)
                changed += 1
                new_seen += 1
            index += 1
        if (old_seen, new_seen) != (old_count, new_count):
            raise ValueError(
                f"hunk at line {old_start} declares {old_count}/{new_count} lines, "
                f"found {old_seen}/{new_seen}"
            )
    out.extend(source[cursor:])
    updated = "".join(out)
    if len(updated.encode("utf-8")) > max_bytes:
        raise ValueError(f"patched file exceeds {max_bytes} bytes")
    _atomic_write(target, updated)
    return Edited(str(target), changed, first_line or 1, digest(updated))


def _matches(source: list[str], cursor: int, body: str) -> bool:
    if cursor >= len(source):
        return False
    return source[cursor].rstrip("\r\n") == body.rstrip("\r\n")
