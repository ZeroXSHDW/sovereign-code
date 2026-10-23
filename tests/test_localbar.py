"""Tests for the Sovereign Local macOS menu bar app builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from sovereign_code import localbar
from sovereign_code.config import PROJECT_ROOT


def test_app_path_in_applications() -> None:
    p = localbar.app_path()
    assert p == Path.home() / "Applications" / localbar.APP_NAME


def test_source_path_uses_project_root() -> None:
    p = localbar.source_path()
    assert p == PROJECT_ROOT / "tools" / "LocalBar.swift"


def test_info_contains_bundle_placeholder() -> None:
    assert "{bundle}" in localbar.INFO
    assert "Sovereign Local" in localbar.INFO


def test_install_writes_plist_and_compiles(monkeypatch, tmp_path) -> None:
    source = tmp_path / "LocalBar.swift"
    source.write_text("import Cocoa", encoding="utf-8")
    monkeypatch.setattr(localbar, "source_path", lambda: source)
    monkeypatch.setattr(localbar, "app_path", lambda: tmp_path / "Sovereign Local.app")

    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(localbar.subprocess, "run", fake_run)

    result = localbar.install()
    assert result == tmp_path / "Sovereign Local.app"
    plist = tmp_path / "Sovereign Local.app" / "Contents" / "Info.plist"
    assert plist.is_file()
    assert "com.sovereign.localbar" in plist.read_text(encoding="utf-8")
    # swiftc + codesign
    assert len(runs) == 2
    assert runs[0][0] == "swiftc"
    assert runs[1][0] == "codesign"


def test_install_raises_when_source_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(localbar, "source_path", lambda: tmp_path / "missing.swift")
    try:
        localbar.install()
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_open_app_runs_open(monkeypatch, tmp_path) -> None:
    app = tmp_path / "Sovereign Local.app"
    app.mkdir()
    monkeypatch.setattr(localbar, "app_path", lambda: app)

    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(localbar.subprocess, "run", fake_run)
    localbar.open_app()
    assert runs == [["open", str(app)]]


def test_open_app_installs_when_missing(monkeypatch, tmp_path) -> None:
    app = tmp_path / "Sovereign Local.app"
    monkeypatch.setattr(localbar, "app_path", lambda: app)

    installed = []

    def fake_install():
        installed.append(True)
        app.mkdir()
        return app

    monkeypatch.setattr(localbar, "install", fake_install)

    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(localbar.subprocess, "run", fake_run)
    localbar.open_app()
    assert installed == [True]
    assert runs == [["open", str(app)]]


def test_running_true_when_pgrep_finds(monkeypatch) -> None:
    monkeypatch.setattr(
        localbar.subprocess,
        "run",
        lambda *a, **k: MagicMock(stdout="12345\n", stderr="", returncode=0),
    )
    assert localbar.running() is True


def test_running_false_when_pgrep_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        localbar.subprocess,
        "run",
        lambda *a, **k: MagicMock(stdout="", stderr="", returncode=1),
    )
    assert localbar.running() is False


def test_running_false_on_oserror(monkeypatch) -> None:
    def boom(*a, **k):
        raise OSError("pgrep not found")

    monkeypatch.setattr(localbar.subprocess, "run", boom)
    try:
        localbar.running()
    except OSError:
        return
    raise AssertionError("expected OSError to propagate")
