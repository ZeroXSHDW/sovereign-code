from __future__ import annotations

from sovereign_code import monitor


def test_banks() -> None:
    skill, prompt = monitor.banks()
    assert skill is not None
    assert prompt is not None


def test_skill_bank() -> None:
    bank = monitor.skill_bank()
    assert bank is not None


def test_prompt_bank() -> None:
    bank = monitor.prompt_bank()
    assert bank is not None


def test_live_projects() -> None:
    projects = monitor.live_projects(limit=2)
    assert isinstance(projects, list)


def test_recent_activity() -> None:
    activity = monitor.recent_activity(limit=2)
    assert isinstance(activity, list)


def test_metrics_path() -> None:
    assert monitor.metrics_path() is not None


def test_demo_report() -> None:
    report = monitor.demo_report()
    assert report is not None
