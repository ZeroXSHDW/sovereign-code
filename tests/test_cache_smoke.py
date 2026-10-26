from __future__ import annotations

from sovereign_code import cache


def test_memory_cache() -> None:
    c = cache.MemoryCache()
    c.put("k", {"v": 1})
    assert c.get("k") == {"v": 1}


def test_disk_cache() -> None:
    c = cache.disk_cache()
    assert c is not None
    c.close()


def test_cache_key_chat() -> None:
    key = cache.cache_key_chat("m", "balanced", [{"role": "user", "content": "hi"}])
    assert isinstance(key, str)
