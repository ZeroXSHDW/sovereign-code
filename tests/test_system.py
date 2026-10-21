"""Tests for system probes and GPU capacity helpers."""

from sovereign_code.system import models_to_evict


def test_small_model_needs_no_eviction():
    assert models_to_evict(7.0, [("other:9b", 3.0)], 18.0) == []


def test_big_model_evicts_every_resident():
    residents = [("qwen3.5:9b", 7.1), ("nomic-embed-text:latest", 0.3)]
    assert models_to_evict(19.0, residents, 18.0) == ["qwen3.5:9b", "nomic-embed-text:latest"]


def test_borderline_model_reserves_headroom():
    # 16.5 GB leaves less than the 2 GB reserve, so free the machine first.
    assert models_to_evict(16.5, [("qwen3.5:9b", 7.0)], 18.0) == ["qwen3.5:9b"]


def test_nothing_to_evict_when_idle():
    assert models_to_evict(19.0, [], 18.0) == []
