"""Create a local tarball of configs and chat data (no models, no caches)."""

from __future__ import annotations

import os
import tarfile
from datetime import datetime
from pathlib import Path

from .safefile import ensure_private_dir, harden, open_private


def _entries(
    include_dirs: list[Path],
    exclude: dict[Path, tuple[str, ...]],
    root: Path | None,
):
    for directory in include_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(directory)
            if relative.parts and relative.parts[0] in exclude.get(directory, ()):
                continue
            arcname = path.relative_to(root) if root else path.relative_to(directory.parent)
            yield path, arcname


def prune_backups(dest_dir: Path, keep: int) -> int:
    """Delete the oldest backups, keeping the newest `keep`."""
    if keep <= 0:
        return 0
    backups = sorted(
        dest_dir.glob("sovereign-backup-*.tar.gz"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for path in backups[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def create_backup(
    include_dirs: list[Path],
    dest_dir: Path,
    exclude: dict[Path, tuple[str, ...]] | None = None,
    extra_files: dict[Path, str] | None = None,
    root: Path | None = None,
) -> Path:
    """Archive the given directories and extra files into a timestamped .tar.gz.

    The archive holds the sessions, the cached completions and the project
    notes, so it is created 0600: an unreadable-to-others backup is not much
    of a backup if the machine is shared.
    """
    ensure_private_dir(dest_dir)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}"
    path = dest_dir / f"sovereign-backup-{stamp}.tar.gz"
    # Write to a private partial file first: an interrupted run must never
    # leave a truncated archive that prune_backups then treats as the newest
    # good backup, and two backups in the same instant must not overwrite each
    # other.
    partial = path.with_name(path.name + ".partial")
    try:
        with open_private(partial, "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz") as archive:
                for file_path, arcname in _entries(include_dirs, exclude or {}, root):
                    archive.add(file_path, arcname=str(arcname))
                for file_path, arcname in (extra_files or {}).items():
                    if file_path.is_file():
                        archive.add(file_path, arcname=arcname)
        os.replace(partial, path)
    except BaseException:
        # An interrupted or failed archive must not leave a truncated
        # ``.partial`` file behind for prune_backups to mistake for a backup.
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    harden(path)
    return path
