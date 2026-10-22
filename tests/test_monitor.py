"""Tests for the read-only live monitor."""

from __future__ import annotations

import json
import time

from sovereign_code import monitor


def _reset_caches() -> None:
    monitor._BANK_CACHE = {}
    monitor._BANK_CACHE_AT = 0.0
    monitor._PROJECT_CACHE = []
    monitor._PROJECT_CACHE_AT = 0.0


def test_skill_bank_counts_files_when_no_index(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "skills"
    user = tmp_path / "user-skills"
    repo.mkdir()
    user.mkdir()
    (repo / "legal--contract.md").write_text("# Contract\n", encoding="utf-8")
    (repo / "security--audit.md").write_text("# Audit\n", encoding="utf-8")
    (user / "legal--contract.md").write_text("# Override\n", encoding="utf-8")
    monkeypatch.setattr(monitor, "REPO_SKILLS_DIR", repo)
    monkeypatch.setattr(monitor, "USER_SKILLS_DIR", user)
    monkeypatch.setattr(monitor, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(monitor, "PROJECT_ROOT", tmp_path)
    _reset_caches()

    bank = monitor.skill_bank()
    assert bank.total == 2
    assert bank.source == "filesystem"
    assert dict(bank.categories)["legal"] == 1


def test_prompt_bank_reads_templates_when_db_is_absent(tmp_path, monkeypatch) -> None:
    local = tmp_path / "local-ai"
    templates = local / "config" / "skills"
    templates.mkdir(parents=True)
    (templates / "code-review.md").write_text("# Code review\n", encoding="utf-8")
    (templates / "write-tests.md").write_text("# Tests\n", encoding="utf-8")
    monkeypatch.setattr(monitor, "LOCAL_AI_ROOT", local)
    monkeypatch.setattr(monitor, "DATA_DIR", tmp_path / "data")
    _reset_caches()

    bank = monitor.prompt_bank()
    assert bank.total == 2
    assert bank.source == "filesystem"


def test_live_projects_merge_sessions_by_folder(tmp_path, monkeypatch) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    session = sessions / "20261022-120000-qwen.jsonl"
    session.write_text(
        json.dumps(
            {
                "type": "session",
                "started_at": time.time(),
                "model": "qwen3.5:4b",
                "cwd": str(tmp_path / "project"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(monitor, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(monitor, "_running_agents", lambda limit=8: [])
    _reset_caches()

    projects = monitor.live_projects()
    assert len(projects) == 1
    assert projects[0].name == "project"
    assert projects[0].model == "qwen3.5:4b"
    assert projects[0].active is True


def test_recent_activity_is_newest_first(tmp_path, monkeypatch) -> None:
    path = tmp_path / "tiers.jsonl"
    now = time.time()
    path.write_text(
        "\n".join(
            [
                json.dumps({"ts": now - 20, "tier": "fast", "model": "a"}),
                json.dumps({"ts": now, "tier": "deep", "model": "b", "tools": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(monitor, "metrics_path", lambda: path)

    events = monitor.recent_activity()
    assert [event.model for event in events] == ["b", "a"]
    assert events[0].tools is True


def test_demo_report_has_every_panel() -> None:
    report = monitor.demo_report()
    assert report.skills.total > 0
    assert report.prompts.total > 0
    assert report.projects
    assert report.activity
    assert any(service.up for service in report.services)
