"""Tests for project check detection and execution."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.checks import detect_checks, run_checks


def test_detects_makefile_test_target(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    assert detect_checks(tmp_path) == ["make test"]


def test_pytest_detection_prefers_the_project_venv(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("", encoding="utf-8")

    checks = detect_checks(tmp_path)
    assert checks == [f"{venv / 'python'} -m pytest -q"]


def test_unknown_project_has_no_checks(tmp_path: Path) -> None:
    assert detect_checks(tmp_path) == []


def test_run_checks_reports_failure(tmp_path: Path) -> None:
    result = run_checks(tmp_path, ["exit 3"], timeout=30)
    assert result.ok is False
    assert "exit 3" in result.log


def test_run_checks_passes(tmp_path: Path) -> None:
    result = run_checks(tmp_path, ["true"], timeout=30)
    assert result.ok is True
