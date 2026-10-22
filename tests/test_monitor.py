"""Tests for the read-only live monitor."""

from __future__ import annotations

import json
import sqlite3
import time

from sovereign_code import monitor


def _reset_caches() -> None:
    monitor._BANK_CACHE = {}
    monitor._BANK_CACHE_AT = 0.0
    monitor._PROJECT_CACHE = []
    monitor._PROJECT_CACHE_AT = 0.0


def _write_skills_db(path) -> None:
    """Write a small skill index with the dashboard's covering index."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE skills (name TEXT, category TEXT, usage_count INTEGER, "
        "rating REAL, installed INTEGER)"
    )
    conn.executemany(
        "INSERT INTO skills (name, category, usage_count, rating, installed) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("alpha", "code", 3, 4.5, 1),
            ("beta", "chat", 1, 2.0, 1),
            ("gamma", "code", 0, 0.0, 0),
        ],
    )
    conn.execute(
        "CREATE INDEX skills_bank_idx ON skills(installed, rating DESC, usage_count DESC, "
        "name, category)"
    )
    conn.commit()
    conn.close()


def _bank_env(tmp_path, monkeypatch) -> None:
    """Point the monitor at an empty skills tree and a scratch data dir."""
    repo = tmp_path / "skills"
    repo.mkdir()
    monkeypatch.setattr(monitor, "REPO_SKILLS_DIR", repo)
    monkeypatch.setattr(monitor, "USER_SKILLS_DIR", tmp_path / "user-skills")
    monkeypatch.setattr(monitor, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(monitor, "PROJECT_ROOT", tmp_path)
    _reset_caches()


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
    monkeypatch.setattr(monitor, "_running_agents", lambda **_kwargs: [])
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
    assert report.models_installed > 0
    assert report.activity_stats.requests > 0
    assert report.health.level in {"ok", "warn", "critical"}


def test_sparkline_is_fixed_width_and_tracks_range() -> None:
    line = monitor.sparkline([0, 25, 50, 75, 100], width=8, minimum=0, maximum=100)
    assert len(line) == 8
    assert line.endswith("···▁▃▅▇█")
    assert monitor.sparkline([], width=6) == "······"


def test_activity_stats_summarise_latency_tokens_and_tiers() -> None:
    now = time.time()
    events = [
        monitor.Activity(now - 10, "fast", "a", 100, 10, tools=True, stream=True),
        monitor.Activity(now - 20, "deep", "b", 300, 20, stream=True),
        monitor.Activity(now - 90, "deep", "c", 200, 30),
    ]
    stats = monitor.activity_stats(events, now=now)
    assert stats.requests == 3
    assert stats.tokens == 60
    assert stats.tools == 1
    assert stats.streams == 2
    assert stats.p50_ms == 200
    assert stats.p95_ms == 300
    assert stats.per_minute == 2
    assert stats.top_tier == "deep"
    assert stats.top_tier_count == 2


def test_health_flags_low_memory_and_down_core_service() -> None:
    report = monitor.demo_report()
    report.memory = monitor.Memory(24.0, 0.5, 2.0)
    report.services[0] = monitor.ServiceLine("Ollama", 11434, False, "model server")
    report = monitor.LiveReport(
        services=report.services,
        memory=report.memory,
        disk_free_gb=report.disk_free_gb,
    )
    health = monitor.assess(report)
    assert health.level == "critical"
    assert "low RAM" in health.title
    assert any("Ollama" in reason for reason in health.reasons)


def test_health_is_green_when_everything_is_nominal() -> None:
    report = monitor.LiveReport(
        services=[monitor.ServiceLine("Ollama", 11434, True)],
        memory=monitor.Memory(24.0, 16.0, 67.0),
        disk_free_gb=220.0,
    )
    health = monitor.assess(report)
    assert health.level == "ok"
    assert health.reasons == ()


# ------------------------------------------------------------------- bank


def test_skill_bank_reads_the_index(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _write_skills_db(data / "skills.db")
    _bank_env(tmp_path, monkeypatch)

    bank = monitor.skill_bank()
    assert bank.total == 3
    assert bank.installed == 2
    assert dict(bank.categories) == {"code": 1, "chat": 1}
    assert bank.top == (("alpha", 3), ("beta", 1))
    assert bank.source.endswith("skills.db")


def test_skill_bank_query_uses_the_covering_index(tmp_path, monkeypatch) -> None:
    """The dashboard's hot query must not scan the content table."""
    data = tmp_path / "data"
    data.mkdir()
    _write_skills_db(data / "skills.db")
    _bank_env(tmp_path, monkeypatch)

    traced: list[str] = []
    real_open = monitor._open_readonly

    def traced_open(path):
        conn = real_open(path)
        if conn is not None:
            conn.set_trace_callback(traced.append)
        return conn

    monkeypatch.setattr(monitor, "_open_readonly", traced_open)
    monitor.skill_bank()

    statement = next(s for s in traced if "FROM skills" in s and "ORDER BY" in s)
    conn = sqlite3.connect(data / "skills.db")
    plan_sql = "EXPLAIN QUERY PLAN " + statement
    plan = [row[3] for row in conn.execute(plan_sql)]
    conn.close()

    assert any("skills_bank_idx" in detail for detail in plan)
    assert not any(detail.startswith("SCAN skills") for detail in plan)


def test_skill_bank_reads_an_index_without_the_installed_column(tmp_path, monkeypatch) -> None:
    """An index without the newer columns still has to be readable."""
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "skills.db")
    conn.execute("CREATE TABLE skills (name TEXT, category TEXT, usage_count INTEGER, rating REAL)")
    conn.executemany(
        "INSERT INTO skills (name, category, usage_count, rating) VALUES (?, ?, ?, ?)",
        [("alpha", "code", 3, 4.5), ("beta", "chat", 1, 2.0)],
    )
    conn.commit()
    conn.close()
    _bank_env(tmp_path, monkeypatch)

    bank = monitor.skill_bank()
    assert bank.total == 2
    assert bank.installed == 2
    assert dict(bank.categories) == {"code": 1, "chat": 1}
    assert bank.top == (("alpha", 3), ("beta", 1))


# --------------------------------------------------------------- metrics


def test_metrics_count_honours_the_limit(tmp_path, monkeypatch) -> None:
    path = tmp_path / "tiers.jsonl"
    path.write_text(
        "\n".join(json.dumps({"ts": index, "tier": "fast"}) for index in range(10)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(monitor, "metrics_path", lambda: path)

    assert monitor.metrics_count() == 10
    assert monitor.metrics_count(5) == 5
    assert monitor.metrics_count(1) == 1
    assert monitor.metrics_count(0) == 0
