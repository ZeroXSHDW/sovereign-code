"""Tests for the runtime harness: role plans and the live event logs."""

from __future__ import annotations

import time

from sovereign_code import harness
from sovereign_code.harness import (
    RunRecorder,
    active_downloads,
    active_run,
    log_download,
    plan_roles,
    recent_downloads,
    recent_runs,
)
from sovereign_code.models import build_views


def _views():
    return build_views(
        {
            "models": [
                {"name": "qwen3.5:4b", "size": 4 * 1024**3, "details": {}},
                {"name": "qwen3.8:27b", "size": 18 * 1024**3, "details": {}},
                {"name": "gemma4:12b", "size": 8 * 1024**3, "details": {}},
            ]
        },
        None,
    )


def test_small_model_takes_quick_fixes_and_large_model_takes_the_work():
    roles = {role.key: role for role in plan_roles(_views(), free_gb=20.0)}
    assert roles["fix"].model == "qwen3.5:4b"
    assert roles["edit"].model == "qwen3.8:27b"
    assert roles["plan"].model == "qwen3.8:27b"
    # Review prefers a different family when one is installed.
    assert roles["review"].model == "gemma4:12b"
    assert roles["fix"].size_gb < roles["edit"].size_gb


def test_review_falls_back_when_only_one_model_exists():
    views = build_views(
        {"models": [{"name": "qwen3.5:4b", "size": 4 * 1024**3, "details": {}}]},
        None,
    )
    roles = {role.key: role for role in plan_roles(views, free_gb=20.0)}
    assert roles["review"].model == "qwen3.5:4b"
    assert "separate reviewer" in roles["review"].reason


def test_empty_catalog_reports_what_to_pull():
    roles = {role.key: role for role in plan_roles({}, free_gb=None)}
    assert roles["fix"].model is None
    assert "sovereign setup" in roles["fix"].detail


def test_run_log_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "DATA_DIR", tmp_path)
    recorder = RunRecorder("fix the parser", directory="/tmp/project")
    run = recorder.start()
    recorder.stage_start("plan", role="plan", model="qwen3.8:27b")
    recorder.stage_end(
        "plan", role="plan", model="qwen3.8:27b", ok=True, ms=1200, output="1. inspect\n2. fix"
    )
    recorder.stage_end("verify", ok=True, ms=300, output="3 passed")

    active = active_run()
    assert active is not None
    assert active.run == run
    assert active.active
    assert active.prompt == "fix the parser"
    assert active.stage == "verify"
    assert active.stages == ("plan", "verify")

    recorder.finish(True, verified=True, output="done")
    runs = recent_runs()
    assert runs[0].status == "complete"
    assert runs[0].verified is True
    assert not runs[0].active
    assert active_run() is None


def test_old_unfinished_run_is_not_active():
    summary = harness.RunSummary(
        run="old",
        started=time.time() - harness.ACTIVE_RUN_SECONDS - 60,
        prompt="old run",
    )
    assert not summary.active


def test_download_progress_and_activity(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "DATA_DIR", tmp_path)
    log_download("qwen3.5:4b", status="pulling", completed=1_000_000_000, total=4_000_000_000)
    rows = recent_downloads()
    assert rows[0].percent == 25
    assert rows[0].active
    assert active_downloads()

    log_download(
        "qwen3.5:4b", status="done", completed=4_000_000_000, total=4_000_000_000, done=True
    )
    assert not active_downloads()
    assert recent_downloads()[0].state == "done"


def test_failed_download_is_reported_once(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "DATA_DIR", tmp_path)
    log_download("x", error="no space left")
    row = recent_downloads()[0]
    assert row.error == "no space left"
    assert not row.active
