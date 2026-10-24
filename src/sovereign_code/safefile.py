"""Write files that only the owner can read.

Several files in this project hold prompts, model replies, cached
completions, or API keys. A plain ``Path.write_text`` creates the file with
the process umask, which on a default macOS account is ``0644`` — readable by
every other user on the machine. Chmod-ing afterwards leaves a window in
which the file is already world-readable.

The helpers here create the file with the right mode in the first place, so
there is no window at all.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import IO, Any

# Owner read/write only.
PRIVATE_FILE = 0o600
# Owner read/write/execute only.
PRIVATE_DIR = 0o700


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` as a directory only the owner can enter."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(PRIVATE_DIR)
    except OSError:
        # A directory we do not own (a shared volume, for instance) is left
        # alone rather than failing the operation.
        pass
    return path


def open_private(path: Path, mode: str = "a") -> IO[Any]:
    """Open ``path`` for writing, creating it with mode 0600 if it is new.

    An existing file keeps its own mode; call :func:`harden` to fix a file
    that was created before this project tightened up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_APPEND", 0)
    if "w" in mode:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(path), flags, PRIVATE_FILE)
    return os.fdopen(fd, mode, encoding="utf-8" if "b" not in mode else None)


def write_private(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` atomically, with mode 0600.

    ``open_private(..., "w")`` truncates in place, so a crash halfway through
    leaves an empty or partial file — a real problem for files such as the
    Claude settings that this project rewrites. Stage the new contents in a
    private temp file in the same directory and rename it into place instead.
    """
    return write_private_bytes(path, text.encode("utf-8"))


def write_private_bytes(path: Path, data: bytes) -> Path:
    """Byte-oriented :func:`write_private` (downloads, images, binary state)."""
    ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, PRIVATE_FILE)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    harden(path)
    return path


def harden(path: Path) -> None:
    """Set mode 0600 on a file that already exists."""
    try:
        path.chmod(PRIVATE_FILE)
    except OSError:
        pass


__all__ = [
    "PRIVATE_DIR",
    "PRIVATE_FILE",
    "ensure_private_dir",
    "harden",
    "open_private",
    "write_private",
    "write_private_bytes",
]
