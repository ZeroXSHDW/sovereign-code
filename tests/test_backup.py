"""Backup archive tests."""

from __future__ import annotations

import tarfile
from pathlib import Path

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
