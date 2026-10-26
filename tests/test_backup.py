"""Backup archive tests."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from sovereign_code.backup import create_backup


def test_backup_includes_config_and_data_but_not_browser(tmp_path: Path) -> None:
    root = tmp_path / "local-ai"
    sovereign = root / "config" / "sovereign"
    codex = root / "config" / "codex"
    data = root / "data"
    sovereign.mkdir(parents=True)
    codex.mkdir(parents=True)
    (data / "sessions").mkdir(parents=True)
    (data / "browser" / "profile").mkdir(parents=True)
    (sovereign / "config.toml").write_text("x", encoding="utf-8")
    (codex / "local.config.toml").write_text("p", encoding="utf-8")
    (codex / ".tmp" / "plugins").mkdir(parents=True)
    (codex / ".tmp" / "plugins" / "big.bin").write_text("z", encoding="utf-8")
    (data / "sessions" / "s.jsonl").write_text("y", encoding="utf-8")
    (data / "browser" / "profile" / "Cookies").write_text("secret", encoding="utf-8")

    path = create_backup(
        [sovereign, data],
        tmp_path / "backups",
        exclude={data: ("browser",)},
        extra_files={codex / "local.config.toml": "config/codex/local.config.toml"},
        root=root,
    )

    assert path.name.startswith("sovereign-backup-")
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
    assert "config/sovereign/config.toml" in names
    assert "config/codex/local.config.toml" in names
    assert "data/sessions/s.jsonl" in names
    assert not any("browser" in name for name in names)
    assert not any(".tmp" in name for name in names)


def test_prune_backups_keeps_newest(tmp_path: Path) -> None:
    import os

    from sovereign_code.backup import prune_backups

    for index in range(5):
        path = tmp_path / f"sovereign-backup-{index}.tar.gz"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (index + 1, index + 1))

    removed = prune_backups(tmp_path, 2)
    assert removed == 3
    remaining = sorted(path.name for path in tmp_path.glob("sovereign-backup-*.tar.gz"))
    assert len(remaining) == 2
    assert remaining == ["sovereign-backup-3.tar.gz", "sovereign-backup-4.tar.gz"]


def test_prune_backups_zero_keep_removes_nothing(tmp_path: Path) -> None:
    from sovereign_code.backup import prune_backups

    (tmp_path / "sovereign-backup-0.tar.gz").write_text("x", encoding="utf-8")
    assert prune_backups(tmp_path, 0) == 0
    assert (tmp_path / "sovereign-backup-0.tar.gz").exists()


def test_prune_backups_tolerates_unlink_failure(tmp_path: Path, monkeypatch) -> None:
    from sovereign_code.backup import prune_backups

    (tmp_path / "sovereign-backup-0.tar.gz").write_text("x", encoding="utf-8")
    (tmp_path / "sovereign-backup-1.tar.gz").write_text("x", encoding="utf-8")

    def boom(self):
        raise OSError("nope")

    monkeypatch.setattr(Path, "unlink", boom)
    assert prune_backups(tmp_path, 1) == 0


def test_backup_skips_missing_extra_file(tmp_path: Path) -> None:
    root = tmp_path / "local-ai"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "sessions").mkdir()
    (data / "sessions" / "s.jsonl").write_text("y", encoding="utf-8")

    path = create_backup(
        [data],
        tmp_path / "backups",
        extra_files={tmp_path / "does-not-exist.txt": "config/missing.txt"},
        root=root,
    )
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
    assert not any("missing.txt" in name for name in names)


def test_entries_skips_non_directory(tmp_path: Path) -> None:
    from sovereign_code.backup import _entries

    not_dir = tmp_path / "not-a-dir"
    not_dir.write_text("x", encoding="utf-8")
    assert list(_entries([not_dir], {}, None)) == []


def test_create_backup_cleans_up_partial_despite_unlink_failure(
    tmp_path: Path, monkeypatch
) -> None:
    import tarfile

    data = tmp_path / "data"
    data.mkdir()
    (data / "f.txt").write_text("x", encoding="utf-8")

    def raising_unlink(self, *a, **k):
        raise OSError("nope")

    monkeypatch.setattr(Path, "unlink", raising_unlink)

    def raising_open(*a, **k):
        raise RuntimeError("archive failed")

    monkeypatch.setattr(tarfile, "open", raising_open)

    with pytest.raises(RuntimeError):
        create_backup([data], tmp_path / "backups")
