"""Tests for the response cache."""

from __future__ import annotations

import pytest

from sovereign_code import cache as cache_module
from sovereign_code.cache import (
    DiskCache,
    MemoryCache,
    cache_key_chat,
    cache_key_generate,
    cached_chat,
    store_chat,
)


@pytest.fixture
def memory():
    return MemoryCache(max_entries=8, ttl=60.0)


def test_memory_put_get(memory):
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    value = {"choices": [{"message": {"content": "hello"}}]}
    memory.put(key, value)
    assert memory.get(key) == value


def test_memory_lru_eviction(memory):
    for i in range(10):
        key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": f"msg {i}"}])
        memory.put(key, {"content": f"resp {i}"})
    # The first entries should have been evicted
    first = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "msg 0"}])
    last = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "msg 9"}])
    assert memory.get(first) is None
    assert memory.get(last) is not None


def test_memory_ttl_expiry(memory):
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    memory.put(key, {"content": "x"})
    # Force expiry by manipulating internal data
    with memory._lock:
        memory._data[key] = (0.0, {"content": "expired"})
    assert memory.get(key) is None


def test_disk_cache(tmp_path):
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    value = {"choices": [{"message": {"content": "hello"}}], "model": "qwen3.5:4b", "tier": "fast"}
    disk.put(key, value, model="qwen3.5:4b", tier="fast")
    assert disk.get(key) == value
    disk.close()

    # Re-open and confirm persistence
    disk2 = DiskCache(db, ttl=60.0)
    assert disk2.get(key) == value
    disk2.close()


def test_disk_cache_stats_labels_one_layer(tmp_path) -> None:
    """DiskCache.stats() reports this layer's hits/misses, not 'memory' keys.

    The tier gateway exposes memory and disk as separate objects; the disk
    layer must not name its own counters `memory_*`, or a consumer (cli.py
    cache --stats) reads a field that is always absent.
    """
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)
    assert "memory_hits" not in disk.stats()
    assert "memory_misses" not in disk.stats()
    assert "hits" in disk.stats() and "misses" in disk.stats()
    disk.close()


def test_disk_cache_ttl_expiry(tmp_path, monkeypatch):
    """A row whose deadline has passed is dropped, not served.

    The clock is injected rather than slept on so the test is deterministic.
    """
    db = tmp_path / "cache.db"
    now = 1_000_000.0
    monkeypatch.setattr(cache_module.time, "time", lambda: now)
    disk = DiskCache(db, ttl=60.0)
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    disk.put(key, {"content": "x"})
    assert disk.get(key) == {"content": "x"}

    # Move past the TTL.
    monkeypatch.setattr(cache_module.time, "time", lambda: now + 61.0)
    assert disk.get(key) is None
    disk.close()


def test_disk_cache_expiry_uses_wall_clock_not_monotonic(tmp_path, monkeypatch):
    """Persisted deadlines must survive a reboot.

    A monotonic clock resets on reboot, so a row written before the restart
    would look like it expires in the future and never be collected.
    """
    db = tmp_path / "cache.db"
    monkeypatch.setattr(cache_module.time, "time", lambda: 1_000_000.0)
    disk = DiskCache(db, ttl=60.0)
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    disk.put(key, {"content": "x"})
    disk.close()

    # "Reboot": the wall clock moved on, the monotonic clock went backwards.
    monkeypatch.setattr(cache_module.time, "time", lambda: 1_000_100.0)
    disk2 = DiskCache(db, ttl=60.0)
    assert disk2.get(key) is None
    disk2.close()


def test_disk_cache_clear_older_than_uses_age(tmp_path, monkeypatch):
    """``older_than`` is an age in seconds, measured from when it was written."""
    db = tmp_path / "cache.db"
    now = 1_000_000.0
    monkeypatch.setattr(cache_module.time, "time", lambda: now)
    disk = DiskCache(db, ttl=600.0)
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    disk.put(key, {"content": "x"})

    # Nothing is old enough yet.
    assert disk.clear(older_than=3600.0) == 0
    assert disk.get(key) == {"content": "x"}

    # 601 seconds later the entry is older than the 600 second threshold.
    monkeypatch.setattr(cache_module.time, "time", lambda: now + 601.0)
    assert disk.clear(older_than=600.0) == 1
    assert disk.get(key) is None
    disk.close()


def test_disk_cache_clear_older_than_is_independent_of_ttl(tmp_path, monkeypatch):
    """A long-lived entry is still "old" once its age passes the threshold."""
    db = tmp_path / "cache.db"
    now = 1_000_000.0
    monkeypatch.setattr(cache_module.time, "time", lambda: now)
    disk = DiskCache(db, ttl=86_400.0)
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    disk.put(key, {"content": "x"})

    monkeypatch.setattr(cache_module.time, "time", lambda: now + 3601.0)
    assert disk.clear(older_than=3600.0) == 1
    disk.close()


def test_cached_chat_roundtrip(tmp_path):
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"content": f"answer {calls['n']}"}

    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    # First call: miss -> run fetch, store
    hit = cached_chat(key, fetch, memory=MemoryCache(), disk=disk)
    assert hit == {"content": "answer 1"}
    # Second call: hit -> no fetch
    hit = cached_chat(key, fetch, memory=MemoryCache(), disk=disk)
    assert hit == {"content": "answer 1"}
    assert calls["n"] == 1
    disk.close()


def test_cached_chat_does_not_store_empty_answers(tmp_path):
    """An empty answer must not poison the cache."""
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return None

    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    assert cached_chat(key, fetch, memory=MemoryCache(), disk=disk) is None
    assert cached_chat(key, fetch, memory=MemoryCache(), disk=disk) is None
    assert calls["n"] == 2
    disk.close()


def test_store_chat(memory):
    key = cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "hi"}])
    value = {"content": "hello"}
    store_chat(key, value, model="qwen3.5:4b", tier="fast", memory=memory)
    assert memory.get(key) == value


def test_cache_keys_are_stable_and_distinct():
    messages = [{"role": "user", "content": "hi"}]
    a = cache_key_chat("qwen3.5:4b", "fast", messages)
    b = cache_key_chat("qwen3.5:4b", "fast", list(messages))
    assert a == b
    assert a != cache_key_chat("qwen3.5:4b", "deep", messages)
    assert a != cache_key_chat("qwen3.5:9b", "fast", messages)
    assert a != cache_key_chat("qwen3.5:4b", "fast", [{"role": "user", "content": "bye"}])
    assert cache_key_generate("m", "p") != cache_key_generate("m", "q")
    assert cache_key_generate("m", "p") == cache_key_generate("m", "p")


def test_disk_cache_is_not_created_at_import_time(tmp_path):
    """Importing the module must not touch the filesystem.

    Checked in a fresh interpreter, because by the time this test runs the
    shared cache may legitimately have been created by another test.
    """
    import subprocess
    import sys
    import textwrap

    home = tmp_path / "home"
    code = textwrap.dedent(
        """
        import sys
        import sovereign_code.cache as c
        created = c.__dict__.get("_DISK")
        print("EAGER" if created is not None else "LAZY")
        """
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SOVEREIGN_HOME": str(home),
        "PYTHONPATH": str(cache_module.Path(__file__).resolve().parents[1] / "src"),
    }
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    assert "LAZY" in out.stdout
    assert not (home / "data" / "response_cache.db").exists()


def test_memory_cache_clear(memory):
    key = cache_key_chat("m", "t", [{"role": "user", "content": "hi"}])
    memory.put(key, {"content": "x"})
    memory.clear()
    assert memory.get(key) is None
    assert memory.stats()["entries"] == 0.0


def test_disk_cache_context_manager_closes(tmp_path):
    db = tmp_path / "cache.db"
    with DiskCache(db, ttl=60.0) as disk:
        disk.put(cache_key_chat("m", "t", [{"role": "user", "content": "hi"}]), {"content": "x"})
    # after exit, closed


def test_disk_cache_close_clears_connections(tmp_path):
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)
    disk.get("missing")
    disk.close()
    disk.close()  # idempotent


def test_disk_cache_del_handles_error(tmp_path):
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)

    class FakeConn:
        def close(self) -> None:
            raise RuntimeError("boom")

    disk._connections = [FakeConn()]  # type: ignore[list-item]
    disk.__del__()


def test_close_disk_cache_idempotent(monkeypatch):
    closed: list[bool] = []

    class FakeDisk:
        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(cache_module, "_DISK", FakeDisk())
    cache_module._close_disk_cache()
    assert len(closed) == 1
    cache_module._close_disk_cache()
    assert len(closed) == 1
    monkeypatch.setattr(cache_module, "_DISK", None)


def test_disk_cache_clear_all(tmp_path):
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)
    key = cache_key_chat("m", "t", [{"role": "user", "content": "hi"}])
    disk.put(key, {"content": "x"})
    assert disk.clear() == 1
    assert disk.get(key) is None
    disk.close()


def test_disk_cache_close_handles_sqlite_error(tmp_path):
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)

    class FakeConn:
        def close(self) -> None:
            import sqlite3

            raise sqlite3.Error("boom")

    disk._connections = [FakeConn()]  # type: ignore[list-item]
    disk.close()


def test_disk_attr_caches_instance(monkeypatch, tmp_path):
    monkeypatch.setattr(cache_module, "_DISK", None)
    # Accessing DISK twice returns the same object
    first = cache_module.__getattr__("DISK")
    second = cache_module.__getattr__("DISK")
    assert first is second
    first.close()


def test_cached_chat_returns_memory_hit_without_disk(tmp_path):
    db = tmp_path / "cache.db"
    disk = DiskCache(db, ttl=60.0)
    memory = MemoryCache()
    key = cache_key_chat("m", "t", [{"role": "user", "content": "hi"}])
    value = {"content": "from-memory"}
    memory.put(key, value)
    calls = []

    def fetch():
        calls.append(1)
        return {"content": "fetched"}

    result = cached_chat(key, fetch, memory=memory, disk=disk)
    assert result == value
    assert calls == []
    disk.close()
