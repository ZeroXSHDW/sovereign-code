"""Persistent + in-memory response cache for the fastest repeat answers.

A chat completion is keyed by a hash of the request (messages, model, tier,
temperature, max_tokens, stop). On a cache hit the stored completion is
returned instantly — no model load, no prefill, no generation. This is the
single biggest speedup for repeat coding questions, reviews, and skill runs.

Two layers:
* :class:`MemoryCache` — thread-safe LRU, sub-millisecond hits, no disk.
* :class:`DiskCache` — SQLite-backed, survives restarts, shared by the tier
  gateway and any client that imports it.

Both share the same key function so a hit in either layer returns identical
output. Nothing here touches the network; it is pure local computation.

Clocks
------
The memory layer is process-local, so it uses :func:`time.monotonic` — immune
to wall-clock jumps. The disk layer is *persisted*, so it uses
:func:`time.time`: a monotonic timestamp is uptime-relative and resets on
reboot, which would make every row written before a restart look like it was
created in the future and therefore never expire.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from .config import DATA_DIR
from .safefile import ensure_private_dir, harden

DEFAULT_DB = DATA_DIR / "response_cache.db"
TTL_DEFAULT = 7200.0  # two hours

__all__ = [
    "DEFAULT_DB",
    "DISK",  # noqa: F822 - provided lazily by __getattr__ (PEP 562)
    "MEMORY",
    "TTL_DEFAULT",
    "DiskCache",
    "MemoryCache",
    "cache_key_chat",
    "cache_key_generate",
    "cached_chat",
    "store_chat",
]


def _request_key(
    model: str,
    tier: str,
    messages: list[dict[str, Any]],
    temperature: float | None,
    max_tokens: int | None,
    stop: Any = None,
    tools: Any = None,
) -> str:
    payload = {
        "model": model,
        "tier": tier,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stop": stop,
        "tools": tools,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _completion_key(model: str, prompt: str, **options: Any) -> str:
    payload = {"model": model, "prompt": prompt, "options": options}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class MemoryCache:
    """Thread-safe in-memory LRU cache."""

    def __init__(self, max_entries: int = 2048, ttl: float = TTL_DEFAULT) -> None:
        self.max_entries = max_entries
        self.ttl = ttl
        self._data: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            expires, value = item
            if expires < time.monotonic():
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return deepcopy(value)

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, deepcopy(value))
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def stats(self) -> dict[str, float]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": float(len(self._data)),
                "hits": float(self.hits),
                "misses": float(self.misses),
                "hit_rate": round(100.0 * self.hits / total, 1) if total else 0.0,
            }

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class DiskCache:
    """SQLite-backed persistent cache.

    One row per cached completion. WAL mode, NORMAL synchronous — safe for
    concurrent readers and a single writer (the tier gateway process).

    Expiry is measured against the wall clock (:func:`time.time`) because the
    timestamps outlive the process that wrote them.
    """

    _SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS cache (
            key         TEXT PRIMARY KEY,
            value       BLOB NOT NULL,
            expires_at  REAL NOT NULL,
            created_at  REAL NOT NULL,
            hit_count   INTEGER NOT NULL DEFAULT 0,
            model       TEXT NOT NULL DEFAULT '',
            tier        TEXT NOT NULL DEFAULT ''
        )
        """,
        "CREATE INDEX IF NOT EXISTS cache_expires_idx ON cache(expires_at)",
        "CREATE INDEX IF NOT EXISTS cache_model_idx ON cache(model)",
        "CREATE INDEX IF NOT EXISTS cache_tier_idx ON cache(tier)",
    )

    def __init__(self, path: str | Path | None = None, ttl: float = TTL_DEFAULT) -> None:
        self.path = Path(path) if path else DEFAULT_DB
        ensure_private_dir(self.path.parent)
        self.ttl = ttl
        # Each thread gets its own connection: sqlite3 connections are not
        # safe to share across threads even with check_same_thread=False, and
        # the tier gateway serves every request on a fresh thread. All access
        # is still serialised by ``self._lock`` below.
        self._local = threading.local()
        self._lock = threading.Lock()
        # Keep every per-thread connection we hand out so close() can shut them
        # all down, not just the one on the calling thread.
        self._connections: list[sqlite3.Connection] = []
        # Bootstrap the schema on the creating thread so the first reader does
        # not race the writer.
        conn = self._connection()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for statement in self._SCHEMA:
            conn.execute(statement)
        conn.commit()
        # The cached values are whole completions, which contain the user's
        # prompt and the model's reply. They are not anybody else's business.
        self._harden_sidecars()
        self.hits = 0
        self.misses = 0

    def _connection(self) -> sqlite3.Connection:
        """A per-thread SQLite connection (created lazily on first use)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
            # Called either from __init__ (single-threaded) or from the
            # public methods that already hold self._lock, so no extra lock.
            self._connections.append(conn)
        return conn

    def _harden_sidecars(self) -> None:
        """Lock down the database and the WAL/SHM files SQLite creates.

        ``harden(self.path)`` alone is not enough: in WAL mode the most recent
        prompts and replies live in ``-wal``, which SQLite creates with the
        process umask and which is therefore world-readable on a default
        macOS account.
        """
        for suffix in ("", "-wal", "-shm"):
            harden(Path(f"{self.path}{suffix}"))

    def close(self) -> None:
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._local = threading.local()

    def __enter__(self) -> DiskCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = (
                self._connection()
                .execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,))
                .fetchone()
            )
            if row is None:
                self.misses += 1
                return None
            if float(row["expires_at"]) < time.time():
                self._connection().execute("DELETE FROM cache WHERE key = ?", (key,))
                self._connection().commit()
                self.misses += 1
                return None
            self._connection().execute(
                "UPDATE cache SET hit_count = hit_count + 1 WHERE key = ?", (key,)
            )
            self._connection().commit()
            self.hits += 1
            return cast(dict[str, Any], json.loads(bytes(row["value"])))

    def put(self, key: str, value: dict[str, Any], model: str = "", tier: str = "") -> None:
        with self._lock:
            now = time.time()
            expires = now + self.ttl
            blob = json.dumps(value, default=str).encode()
            self._connection().execute(
                """
                INSERT INTO cache (key, value, expires_at, created_at, model, tier)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at,
                    model = excluded.model,
                    tier = excluded.tier,
                    hit_count = 0
                """,
                (key, blob, expires, now, model, tier),
            )
            self._connection().commit()
            # The sidecars are created on the first write, after __init__.
            self._harden_sidecars()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = (
                self._connection()
                .execute("SELECT COUNT(*) AS n, SUM(hit_count) AS hits FROM cache")
                .fetchone()
            )
            total = (self.hits + self.misses) or 1
            return {
                "entries": int(row["n"] or 0),
                # `self.hits`/`self.misses` are this layer's own counters; the
                # SUM above counts persisted hits that predate this process.
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(100.0 * self.hits / total, 1),
            }

    def clear(self, older_than: float | None = None) -> int:
        """Delete every entry, or only the ones older than ``older_than`` seconds.

        ``older_than`` is an *age*, so it is turned into an absolute deadline
        against the wall clock before the comparison. Age is measured from
        ``created_at``, which is independent of the entry's TTL: an entry is
        "older than an hour" when it was written more than an hour ago, even
        if its TTL has not run out yet.
        """
        with self._lock:
            if older_than is None:
                result = self._connection().execute("DELETE FROM cache")
            else:
                deadline = time.time() - max(0.0, older_than)
                result = self._connection().execute(
                    "DELETE FROM cache WHERE created_at < ?", (deadline,)
                )
            self._connection().commit()
            # No VACUUM here: it rewrites the whole database under the single
            # request lock, stalling every cached answer while it runs. WAL
            # reclaims the space lazily, so the delete alone is enough.
            return result.rowcount or 0


# ------------------------------------------------------------------ defaults

MEMORY = MemoryCache()

# The disk cache is created on first use, not at import time. Importing this
# module must not create directories or a database as a side effect: the tier
# gateway, the MCP server and the test suite all import it, and the tests
# assert that a clean checkout stays clean.
_DISK: DiskCache | None = None


def _close_disk_cache() -> None:
    global _DISK
    if _DISK is not None:
        _DISK.close()
        _DISK = None


atexit.register(_close_disk_cache)


def __getattr__(name: str) -> Any:
    """Provide the lazily-created shared :class:`DiskCache` as ``DISK``."""
    if name == "DISK":
        global _DISK
        if _DISK is None:
            _DISK = DiskCache()
        return _DISK
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def disk_cache() -> DiskCache:
    """Return the shared disk cache, creating it on first use."""
    return cast(DiskCache, __getattr__("DISK"))


def cache_key_chat(
    model: str,
    tier: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    stop: Any = None,
    tools: Any = None,
) -> str:
    """Stable cache key for a chat-completion request."""
    return _request_key(model, tier, messages, temperature, max_tokens, stop, tools)


def cache_key_generate(model: str, prompt: str, **options: Any) -> str:
    """Stable cache key for an Ollama /api/generate request."""
    return _completion_key(model, prompt, **options)


def cached_chat(
    key: str,
    fetch: Any,
    memory: MemoryCache | None = None,
    disk: DiskCache | None = None,
) -> dict[str, Any] | None:
    """Return a cached completion, or run ``fetch()`` and store the result.

    ``fetch`` is a zero-argument callable that returns the completion dict.
    On a miss it runs exactly once and the result is written to both cache
    layers, so the next identical request is served without touching a model.

    A ``fetch`` that returns ``None`` is treated as a miss and is not stored —
    an empty answer must not poison the cache.
    """
    memory = memory if memory is not None else MEMORY
    disk = disk if disk is not None else disk_cache()
    hit = memory.get(key)
    if hit is not None:
        return hit
    hit = disk.get(key)
    if hit is not None:
        memory.put(key, hit)
        return hit
    value: dict[str, Any] | None = fetch()
    if value is not None:
        store_chat(key, value, memory=memory, disk=disk)
    return value


def store_chat(
    key: str,
    value: dict[str, Any],
    model: str = "",
    tier: str = "",
    memory: MemoryCache | None = None,
    disk: DiskCache | None = None,
) -> None:
    """Store a completed response in both cache layers."""
    memory = memory if memory is not None else MEMORY
    disk = disk if disk is not None else disk_cache()
    memory.put(key, value)
    disk.put(key, value, model=model, tier=tier)
