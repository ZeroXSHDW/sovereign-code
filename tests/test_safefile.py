"""Tests for the safefile module.

Verifies that every write path creates files with mode 0600 and that the
harden helper fixes files that were created with a permissive umask.
"""

from __future__ import annotations

import stat
from pathlib import Path

from sovereign_code.safefile import (
    PRIVATE_DIR,
    PRIVATE_FILE,
    ensure_private_dir,
    harden,
    open_private,
    write_private,
)


def test_private_constants() -> None:
    assert PRIVATE_FILE == 0o600
    assert PRIVATE_DIR == 0o700


def test_ensure_private_dir_creates_with_mode(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "deep"
    result = ensure_private_dir(target)
    assert result == target
    assert target.is_dir()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_ensure_private_dir_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "dir"
    ensure_private_dir(target)
    ensure_private_dir(target)  # second call must not raise
    assert target.is_dir()


def test_open_private_creates_with_mode(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    with open_private(target, "w") as handle:
        handle.write("hello")
    assert target.read_text() == "hello"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_open_private_appends(tmp_path: Path) -> None:
    target = tmp_path / "log.txt"
    with open_private(target, "w") as handle:
        handle.write("first\n")
    with open_private(target, "a") as handle:
        handle.write("second\n")
    assert target.read_text() == "first\nsecond\n"


def test_write_private_sets_mode(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "file.txt"
    result = write_private(target, "content")
    assert result == target
    assert target.read_text() == "content"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_harden_fixes_permissive_file(tmp_path: Path) -> None:
    target = tmp_path / "world.txt"
    target.write_text("data")
    target.chmod(0o644)
    harden(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_harden_on_missing_file_is_noop(tmp_path: Path) -> None:
    target = tmp_path / "does-not-exist"
    harden(target)  # must not raise


def test_open_private_binary_mode(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    with open_private(target, "wb") as handle:
        handle.write(b"\x00\x01\x02")
    assert target.read_bytes() == b"\x00\x01\x02"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_ensure_private_dir_tolerates_chmod_failure(tmp_path: Path, monkeypatch) -> None:
    from sovereign_code import safefile

    def boom(self, _mode):
        raise OSError("read-only volume")

    monkeypatch.setattr(Path, "chmod", boom)
    target = tmp_path / "dir"
    assert safefile.ensure_private_dir(target) == target
    assert target.is_dir()


def test_write_private_bytes_cleans_up_on_failure(tmp_path: Path, monkeypatch) -> None:
    from sovereign_code import safefile

    target = tmp_path / "out.bin"
    monkeypatch.setattr(
        safefile.os, "replace", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(
        safefile.os, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError("gone"))
    )
    try:
        safefile.write_private_bytes(target, b"data")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the replace failure to propagate")
