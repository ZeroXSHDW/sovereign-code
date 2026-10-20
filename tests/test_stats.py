"""Disk usage helper tests."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.stats import collect_stats, dir_size, human_size


def test_human_size() -> None:
    assert human_size(0) == "0 B"
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(1024 * 1024) == "1.0 MB"


def test_dir_size_counts_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x" * 10, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("y" * 5, encoding="utf-8")
    assert dir_size(tmp_path) == 15


def test_collect_stats_uses_components(monkeypatch, tmp_path: Path) -> None:
    import sovereign_code.stats as stats

    models = tmp_path / "models"
    data = tmp_path / "data"
    models.mkdir()
    data.mkdir()
    (models / "m.bin").write_text("z", encoding="utf-8")
    (data / "d.bin").write_text("zz", encoding="utf-8")
    monkeypatch.setattr(stats, "COMPONENTS", {"models": models, "data": data})
    result = stats.collect_stats()
    assert result["models"]["bytes"] == 1
    assert result["data"]["bytes"] == 2
