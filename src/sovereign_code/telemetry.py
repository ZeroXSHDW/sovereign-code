"""Incremental readers for the live telemetry the monitor shows.

The tier gateway appends one JSON record per request to ``tiers.jsonl``, and the
monitor refreshes every five seconds. Re-reading and re-parsing the tail on
every tick was duplicate work: between two ticks the file has almost always
only grown. :class:`MetricsTail` remembers the byte offset, the inode, and the
records it already parsed, and consumes only the new bytes. When the gateway
rotates the file (it renames it at 5 MB) the inode changes and the reader
restarts from the tail of the new file.

The other live fact that is cheap to read but expensive to guess is the
response cache: the gateway writes it to SQLite, so any process can report how
many completions are stored and how often they were reused without talking to
the gateway at all.

This module is deliberately below ``monitor``: it knows the on-disk formats,
not the dashboard's presentation models.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DATA_DIR

# Read at most this much of a fresh (or rotated) metrics file. The monitor only
# shows a recent window, and a 256 KB tail is thousands of requests.
TAIL_BYTES = 256 * 1024

# How many parsed records to retain for aggregations. The dashboard asks for
# 500; keeping more makes a later, larger request free until the tail rolls.
MAX_EVENTS = 4096


@dataclass(frozen=True)
class CacheSnapshot:
    """What the persistent response cache holds right now."""

    entries: int = 0
    hits: int = 0
    size_mb: float = 0.0
    path: str = ""
    available: bool = False


def _timestamp(record: dict[str, Any]) -> float:
    try:
        return float(record.get("ts") or 0.0)
    except (TypeError, ValueError):
        return 0.0


class MetricsTail:
    """A thread-safe, append-only reader for ``tiers.jsonl``.

    ``read`` returns ``(records, total)`` where records are newest first and
    ``total`` is the number of non-empty lines in the current tail window. The
    monitor uses the first for the feed and the second for its "N logged"
    counter, so one pass serves both.
    """

    def __init__(self, max_events: int = MAX_EVENTS, tail_bytes: int = TAIL_BYTES) -> None:
        self.max_events = max(1, int(max_events))
        self.tail_bytes = max(1, int(tail_bytes))
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=self.max_events)
        self._path = ""
        self._inode = -1
        self._mtime_ns = -1
        self._offset = 0
        self._total = 0

    def read(self, path: Path, limit: int = 500) -> tuple[list[dict[str, Any]], int]:
        """Return the newest records and the line count of the tail window."""
        with self._lock:
            try:
                stat = path.stat()
            except OSError:
                self._forget()
                return ([], 0)

            rotated = (
                str(path) != self._path or stat.st_ino != self._inode or stat.st_size < self._offset
            )
            if rotated:
                self._begin(path, stat.st_size, stat.st_ino)
            elif stat.st_size > self._offset:
                self._consume(path, stat.st_size)
            elif stat.st_mtime_ns != self._mtime_ns:
                # The file was replaced in place with the same size; the bytes
                # we remember no longer describe this file.
                self._begin(path, stat.st_size, stat.st_ino)
            self._mtime_ns = stat.st_mtime_ns

            if limit <= 0:
                return ([], self._total)
            newest = sorted(self._events, key=_timestamp, reverse=True)
            return newest[:limit], self._total

    def _forget(self) -> None:
        self._path = ""
        self._inode = -1
        self._mtime_ns = -1
        self._offset = 0
        self._total = 0
        self._events.clear()

    def _begin(self, path: Path, size: int, inode: int) -> None:
        self._path = str(path)
        self._inode = inode
        self._total = 0
        self._events.clear()
        start = max(0, size - self.tail_bytes)
        self._offset = start
        if start:
            try:
                with path.open("rb") as handle:
                    handle.seek(start)
                    # Drop the partial line the window starts in.
                    handle.readline()
                    self._offset = handle.tell()
            except OSError:
                self._offset = size
                return
        self._consume(path, size)

    def _consume(self, path: Path, size: int) -> None:
        try:
            with path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read(max(0, size - self._offset))
        except OSError:
            return
        if not chunk:
            return

        if chunk.endswith(b"\n"):
            lines = chunk.splitlines()
            consumed = len(chunk)
        else:
            # Keep the incomplete final line for the next refresh. The gateway
            # always terminates a record, so this only matters mid-write.
            cut = chunk.rfind(b"\n") + 1
            if cut == 0:
                return
            lines = chunk[:cut].splitlines()
            consumed = cut

        self._offset += consumed
        for raw in lines:
            if not raw.strip():
                continue
            self._total += 1
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if isinstance(record, dict):
                self._events.append(record)


def cache_snapshot(path: Path | None = None) -> CacheSnapshot:
    """Read the persistent response cache without contacting the gateway.

    The gateway keeps the authoritative in-process hit counters, but the stored
    completions and their reuse counts are in SQLite and are the useful
    cross-process signal: "the cache is doing work" rather than "the monitor
    process has seen no traffic".
    """
    database = Path(path) if path is not None else DATA_DIR / "response_cache.db"
    try:
        size_mb = round(database.stat().st_size / (1024 * 1024), 1)
    except OSError:
        return CacheSnapshot(path=str(database), available=False)
    try:
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.5)
    except sqlite3.Error:
        return CacheSnapshot(path=str(database), size_mb=size_mb, available=False)
    try:
        row = conn.execute("SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM cache").fetchone()
    except sqlite3.Error:
        return CacheSnapshot(path=str(database), size_mb=size_mb, available=False)
    finally:
        conn.close()
    entries, hits = (int(row[0] or 0), int(row[1] or 0)) if row else (0, 0)
    return CacheSnapshot(
        entries=entries,
        hits=hits,
        size_mb=size_mb,
        path=str(database),
        available=True,
    )


__all__ = ["MAX_EVENTS", "TAIL_BYTES", "CacheSnapshot", "MetricsTail", "cache_snapshot"]
