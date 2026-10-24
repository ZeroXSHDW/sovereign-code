"""Tests for the opt-in 24/7 coding loop.

The loop edits a real project unattended, so the tests concentrate on the
parts that decide *what* it does and *when it stops*: task discovery, the
skill/prompt budget, the clean-tree guard, and the pause-after-failures rule.
No test spawns OpenCode or runs a project's checks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sovereign_code import loop, services
from sovereign_code.loop import (
    CHECK_TASK_KEY,
    LoopConfig,
    LoopState,
    build_prompt,
    improvement_task,
    load_state,
    roadmap_tasks,
    run_forever,
    run_once,
    select_task,
    set_enabled,
    todo_tasks,
)


@pytest.fixture(autouse=True)
def isolated_loop_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "loop-state"
    monkeypatch.setattr(loop, "LOOP_DIR", root)
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "- [x] already done\n"
        "- [ ] add the first widget\n"
        "  and document it\n"
        "- [ ] remove the second widget\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Project\n\nRun make test.\n", encoding="utf-8")
    return root


def test_roadmap_tasks_reads_open_items_and_continuations(project: Path) -> None:
    tasks = roadmap_tasks(project)
    assert [task.title for task in tasks] == [
        "add the first widget and document it",
        "remove the second widget",
    ]
    assert tasks[0].source == "docs/ROADMAP.md:4"
    assert tasks[0].key == tasks[0].key


def test_todo_tasks_find_comments_and_skip_the_skill_bank(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "src" / "app.py").write_text("# TODO: handle the empty case\n", encoding="utf-8")
    (tmp_path / "skills" / "x.py").write_text("# TODO: never scan this\n", encoding="utf-8")
    tasks = todo_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0].source == "src/app.py:1"
    assert "empty case" in tasks[0].title


def test_select_task_prioritises_failing_checks(project: Path) -> None:
    state = LoopState(target=str(project))
    task = select_task(project, state, failure="E AssertionError")
    assert task is not None
    assert task.key == CHECK_TASK_KEY
    assert "checks are currently failing" in task.prompt

    state.attempts[CHECK_TASK_KEY] = 3
    assert select_task(project, state, failure="still red", max_attempts=3) is None


def test_select_task_skips_completed_and_exhausted_items(project: Path) -> None:
    tasks = roadmap_tasks(project)
    state = LoopState(target=str(project))
    state.completed[tasks[0].key] = "2026-10-24T00:00:00+00:00"
    selected = select_task(project, state)
    assert selected is not None and selected.key == tasks[1].key

    state.attempts[tasks[1].key] = 3
    selected = select_task(project, state, idle="wait", max_attempts=3)
    assert selected is None


def test_improvement_task_rotates_focus() -> None:
    first = improvement_task(LoopState())
    second = improvement_task(LoopState(focus_index=1))
    assert first.key != second.key
    assert first.source == "loop:improve"


def test_build_prompt_keeps_the_local_only_guardrails(project: Path) -> None:
    task = roadmap_tasks(project)[0]
    prompt = build_prompt(task, project, checks=["make test"], skills="## Skill\nbody")
    assert task.title in prompt
    assert "make test" in prompt
    assert "Use local models only" in prompt
    assert "Do not commit" in prompt
    assert "## Skill" in prompt
    assert "Run make test" in prompt


def test_state_roundtrip_is_owner_only(project: Path) -> None:
    set_enabled(project, True)
    state = load_state(project)
    assert state.enabled is True
    path = loop.state_path(project)
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["enabled"] is True

    set_enabled(project, False)
    assert load_state(project).enabled is False


def test_run_once_records_a_successful_task(project: Path) -> None:
    config = LoopConfig(directory=project, verify=False, skill_cards=0)
    run = run_once(config, runner=lambda _prompt: (True, "edited two files"))
    assert run.ok is True
    assert run.task is not None
    state = load_state(project)
    assert state.runs == 1 and state.successes == 1 and state.failures == 0
    assert state.completed[run.task.key]
    assert Path(run.run_dir).is_dir()
    assert (Path(run.run_dir) / "prompt.md").is_file()
    assert (Path(run.run_dir) / "result.json").is_file()
    assert "edited two files" in (Path(run.run_dir) / "agent.log").read_text(encoding="utf-8")


def test_run_once_pauses_after_repeated_failures(project: Path) -> None:
    config = LoopConfig(directory=project, verify=False, skill_cards=0, max_attempts=1)
    run = run_once(config, runner=lambda _prompt: (False, "agent gave up"))
    assert run.ok is False
    state = load_state(project)
    assert state.failures == 1
    assert state.attempts[run.task.key] == 1
    assert state.paused is True


def test_run_once_blocks_a_dirty_git_tree(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (project / ".git").mkdir()
    monkeypatch.setattr(loop, "_git_status", lambda _root: " M src/app.py")
    config = LoopConfig(directory=project, verify=False, skill_cards=0)
    run = run_once(config, runner=lambda _prompt: (True, "should not run"))
    assert run.ok is False
    assert "uncommitted changes" in run.output
    assert run.task is None


def test_run_once_preflights_failing_checks_before_new_work(project: Path) -> None:
    seen: list[str] = []
    results = [(False, "1 failed, 1 passed"), (True, "1 passed")]

    def verifier() -> tuple[bool, str]:
        return results.pop(0)

    config = LoopConfig(directory=project, checks=("pytest",), skill_cards=0)
    run = run_once(
        config,
        runner=lambda prompt: seen.append(prompt) or (True, "fixed it"),
        verifier=verifier,
    )
    assert run.task is not None and run.task.key == CHECK_TASK_KEY
    assert "1 failed, 1 passed" in seen[0]
    assert run.ok is True
    assert load_state(project).last_failure == ""


def test_run_forever_honours_the_run_budget(project: Path) -> None:
    set_enabled(project, True)
    config = LoopConfig(directory=project, verify=False, skill_cards=0, max_runs=2)
    assert (
        run_forever(
            config,
            runner=lambda _prompt: (True, "ok"),
            sleep=lambda _seconds: None,
        )
        == 0
    )
    state = load_state(project)
    assert state.runs == 2
    assert state.successes == 2


def test_run_forever_stops_when_disabled(project: Path) -> None:
    set_enabled(project, False)
    config = LoopConfig(directory=project, verify=False, skill_cards=0)
    assert run_forever(config, runner=lambda _prompt: (True, "ok")) == 0
    assert load_state(project).runs == 0


def test_run_forever_exits_cleanly_when_another_instance_holds_the_lock(
    project: Path,
) -> None:
    """A lock conflict is benign under launchd; exiting 1 would restart it forever."""
    set_enabled(project, True)
    lock = loop.lock_path(project)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    try:
        config = LoopConfig(directory=project, verify=False, skill_cards=0)
        assert run_forever(config) == 0
    finally:
        lock.unlink(missing_ok=True)


def test_loop_service_is_opt_in(project: Path) -> None:
    service = services.loop_service(project, interval=600)
    assert service.label == services.LOOP_LABEL
    assert service.argv[1:4] == ("-m", "sovereign_code", "loop")
    assert "run" in service.argv
    assert "--auto" not in service.argv
    assert services.LOOP_LABEL not in {item.label for item in services.service_definitions()}


def test_loop_cli_enable_foreground_writes_state(project: Path) -> None:
    from sovereign_code.cli import _loop, build_parser

    args = build_parser().parse_args(["loop", "enable", "--foreground", "--dir", str(project)])
    assert _loop(object(), args) == 0
    assert load_state(project).enabled is True
