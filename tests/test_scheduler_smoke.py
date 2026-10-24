from __future__ import annotations

from sovereign_code import scheduler


def test_scheduler_basic() -> None:
    s = scheduler.ModelScheduler()
    with s.request("m"):
        if hasattr(s, "stats"):
            s.stats()
    assert True


def test_scheduler_stats_dataclass() -> None:
    stats = scheduler.SchedulerStats(active=None, inflight=0, waiting={})
    assert stats.active is None
