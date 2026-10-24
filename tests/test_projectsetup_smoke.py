from __future__ import annotations

from pathlib import Path

from sovereign_code import projectsetup


def test_profile_current_project() -> None:
    profile = projectsetup.profile(Path("."))
    assert profile.files >= 0
    assert isinstance(profile.ecosystem, str)


def test_brief_text() -> None:
    profile = projectsetup.profile(Path("."))
    text = projectsetup.brief_text(profile)
    assert "agent brief" in text
    assert "Working rules" in text


def test_init_project_dry_run(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    actions = projectsetup.init_project(root, dry_run=True)
    assert actions is not None
