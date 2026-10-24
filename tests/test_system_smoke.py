from __future__ import annotations

from sovereign_code import system


def test_total_memory_gb() -> None:
    assert system.total_memory_gb() >= 0


def test_read_memory() -> None:
    mem = system.read_memory()
    assert mem is not None


def test_disk_free_gb() -> None:
    assert system.disk_free_gb() >= 0


def test_wired_limit_gb() -> None:
    assert system.wired_limit_gb(24.0) >= 0
