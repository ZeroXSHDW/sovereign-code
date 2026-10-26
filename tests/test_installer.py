"""Tests for the project installer scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["install.sh", "bootstrap.sh", "agent-connect.sh"])
def test_installer_script_is_executable(name: str) -> None:
    path = ROOT / "scripts" / name
    assert path.exists(), f"{path} should exist"
    assert path.stat().st_mode & 0o111, f"{path} should be executable"


@pytest.mark.parametrize("name", ["install.sh", "bootstrap.sh", "agent-connect.sh"])
def test_installer_script_parses(name: str) -> None:
    path = ROOT / "scripts" / name
    result = subprocess.run(
        ["bash", "-n", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_installer_includes_required_steps() -> None:
    text = (ROOT / "scripts" / "install.sh").read_text()
    required = [
        "uv sync",
        "pre-commit install",
        "install-clients",
        "install-login",
        "ollama",
        "playwright install chromium",
    ]
    for fragment in required:
        assert fragment in text, f"install.sh should mention {fragment!r}"


def test_bootstrap_delegates_to_installer() -> None:
    text = (ROOT / "scripts" / "bootstrap.sh").read_text()
    assert "scripts/install.sh" in text


def test_agent_connect_uses_the_same_maintained_installer() -> None:
    text = (ROOT / "scripts" / "agent-connect.sh").read_text()
    assert 'exec "$ROOT/scripts/install.sh" --skip-extras "$@"' in text
    assert 'cat > "$cfg"' not in text
