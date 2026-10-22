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

import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .safefile import harden

DEFAULT_DB = DATA_DIR / "response_cache.db"
TTL_DEFAULT = 3600.0  # one hour

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

    def __init__(self, max_entries: int = 512, ttl: float = TTL_DEFAULT) -> None:
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

    def stats(self) -> dict[str, int]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._data),
                "hits": self.hits,
                "misses": self.misses,
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        for statement in self._SCHEMA:
            self._conn.execute(statement)
        self._conn.commit()
        # The cached values are whole completions, which contain the user's
        # prompt and the model's reply. They are not anybody else's business.
        harden(self.path)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> DiskCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                self.misses += 1
                return None
            if float(row["expires_at"]) < time.time():
                self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                self._conn.commit()
                self.misses += 1
                return None
            self._conn.execute("UPDATE cache SET hit_count = hit_count + 1 WHERE key = ?", (key,))
            self._conn.commit()
            self.hits += 1
            return json.loads(bytes(row["value"]))

    def put(self, key: str, value: dict[str, Any], model: str = "", tier: str = "") -> None:
        with self._lock:
            now = time.time()
            expires = now + self.ttl
            blob = json.dumps(value, default=str).encode()
            self._conn.execute(
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
            self._conn.commit()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n, SUM(hit_count) AS hits FROM cache"
            ).fetchone()
            total_requests = (self.hits + self.misses) or 1
            return {
                "entries": int(row["n"] or 0),
                "disk_hits": int(row["hits"] or 0),
                "memory_hits": self.hits,
                "memory_misses": self.misses,
                "hit_rate": round(100.0 * self.hits / total_requests, 1),
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
                result = self._conn.execute("DELETE FROM cache")
            else:
                deadline = time.time() - max(0.0, older_than)
                result = self._conn.execute("DELETE FROM cache WHERE created_at < ?", (deadline,))
            self._conn.commit()
            self._conn.execute("VACUUM")
            self._conn.commit()
            return result.rowcount or 0


# ------------------------------------------------------------------ defaults

MEMORY = MemoryCache()

# The disk cache is created on first use, not at import time. Importing this
# module must not create directories or a database as a side effect: the tier
# gateway, the MCP server and the test suite all import it, and the tests
# assert that a clean checkout stays clean.
_DISK: DiskCache | None = None


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
    return __getattr__("DISK")  # type: ignore[no-any-return]


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
    value = fetch()
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
