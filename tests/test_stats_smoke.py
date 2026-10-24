from __future__ import annotations

from sovereign_code import stats


def test_human_size() -> None:
    assert isinstance(stats.human_size(1024), str)


def test_dir_size(tmp_path) -> None:
    assert stats.dir_size(tmp_path) >= 0


def test_collect_stats() -> None:
    data = stats.collect_stats()
    assert isinstance(data, dict)
