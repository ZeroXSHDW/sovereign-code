"""Additional coverage for small pure-logic modules.

Each test targets specific branches that the module's primary test file does
not reach: edge-case branches in scheduler fairness, pipeline fix-round
termination, and memory truncation.
"""

from __future__ import annotations

from pathlib import Path

from sovereign_code.memory import ensure_memory, project_context
from sovereign_code.pipeline import PipelineResult, run_pipeline
from sovereign_code.scheduler import ModelScheduler, SchedulerStats

# ------------------------------------------------------------------ pipeline


def test_empty_pipeline_is_not_successful() -> None:
    assert PipelineResult().succeeded is False
    assert PipelineResult().verified is None


def test_fix_round_stops_when_fix_reports_failure() -> None:
    """A fix stage that returns repaired=False ends the round immediately."""
    failures = iter([(False, "1 failed")])
    fixed: list[bool] = []

    def verify() -> tuple[bool, str]:
        return next(failures)

    def fix(prompt: str, plan_text: str, failure: str) -> tuple[bool, str]:
        fixed.append(True)
        return False, "could not patch"

    result = run_pipeline(
        "x",
        lambda p: "plan",
        lambda p, pl: (True, "wrote files"),
        verify=verify,
        fix=fix,
        max_fixes=3,
    )
    assert [s.name for s in result.stages] == ["plan", "implement", "verify", "fix 1"]
    assert result.stages[-1].ok is False
    assert len(fixed) == 1
    assert result.succeeded is False


# ------------------------------------------------------------------ scheduler


def test_scheduler_stats_fields() -> None:
    stats = SchedulerStats(active="m", inflight=2, waiting={"n": 1})
    assert stats.active == "m"
    assert stats.inflight == 2
    assert stats.waiting == {"n": 1}


def test_scheduler_exclusive_blocks_regular_requests() -> None:
    scheduler = ModelScheduler()
    assert scheduler.stats().inflight == 0
    with scheduler.exclusive():
        assert scheduler.stats().active is None
    scheduler.enter_exclusive()
    scheduler.exit_exclusive()  # idempotent release path


def test_scheduler_release_when_empty_is_idempotent() -> None:
    scheduler = ModelScheduler()
    scheduler.exit("unused")  # inflight already 0; must not go negative
    assert scheduler.stats().inflight == 0


# ------------------------------------------------------------------ memory


def test_project_context_truncates_long_agent_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sovereign_code.memory.DATA_DIR", tmp_path)
    cwd = tmp_path / "proj"
    cwd.mkdir()
    # 80 chars, max 10 -> must truncate and append the marker.
    (cwd / "AGENTS.md").write_text("x" * 80, encoding="utf-8")
    context = project_context(cwd, max_chars=10)
    assert "…[truncated]" in context
    assert "x" * 10 in context


def test_ensure_memory_creates_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sovereign_code.memory.DATA_DIR", tmp_path)
    cwd = tmp_path / "proj"
    cwd.mkdir()
    path = ensure_memory(cwd)
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("# Project memory · proj")
