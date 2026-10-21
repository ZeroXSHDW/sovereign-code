"""Multi-model pipeline orchestration tests."""

from __future__ import annotations

from sovereign_code.pipeline import run_pipeline


def test_run_pipeline_all_stages() -> None:
    def plan(prompt: str) -> str:
        return f"plan for {prompt}"

    def implement(prompt: str, plan_text: str) -> tuple[bool, str]:
        return True, "wrote files"

    def review(plan_text: str, implementation: str) -> str:
        return f"review of {implementation}"

    result = run_pipeline("build a cli", plan, implement, review)
    assert [stage.name for stage in result.stages] == ["plan", "implement", "review"]
    assert result.succeeded
    assert result.stages[0].output == "plan for build a cli"
    assert result.stages[2].output == "review of wrote files"


def test_run_pipeline_reports_failure_and_skips_review() -> None:
    def plan(prompt: str) -> str:
        return "plan"

    def implement(prompt: str, plan_text: str) -> tuple[bool, str]:
        return False, "failed"

    result = run_pipeline("x", plan, implement, None)
    assert [stage.name for stage in result.stages] == ["plan", "implement"]
    assert not result.succeeded


def _plan(prompt: str) -> str:
    return "plan"


def _implement(prompt: str, plan_text: str) -> tuple[bool, str]:
    return True, "wrote files"


def test_verify_runs_after_implementation() -> None:
    calls: list[int] = []

    def verify() -> tuple[bool, str]:
        calls.append(1)
        return True, "145 passed"

    result = run_pipeline("x", _plan, _implement, None, verify=verify)
    assert [s.name for s in result.stages] == ["plan", "implement", "verify"]
    assert result.verified is True
    assert len(calls) == 1


def test_failed_check_triggers_a_bounded_fix_round() -> None:
    verifications = iter([(False, "1 failed"), (True, "145 passed")])

    def verify() -> tuple[bool, str]:
        return next(verifications)

    def fix(prompt: str, plan_text: str, failure: str) -> tuple[bool, str]:
        assert "1 failed" in failure
        return True, "patched"

    result = run_pipeline("x", _plan, _implement, None, verify=verify, fix=fix, max_fixes=2)
    assert [s.name for s in result.stages] == [
        "plan",
        "implement",
        "verify",
        "fix 1",
        "verify 1",
    ]
    assert result.verified is True
    assert result.succeeded


def test_verification_stops_at_max_fixes() -> None:
    def verify() -> tuple[bool, str]:
        return False, "still broken"

    def fix(prompt: str, plan_text: str, failure: str) -> tuple[bool, str]:
        return True, "tried"

    result = run_pipeline("x", _plan, _implement, None, verify=verify, fix=fix, max_fixes=2)
    assert result.verified is False
    assert not result.succeeded
    assert [s.name for s in result.stages] == [
        "plan",
        "implement",
        "verify",
        "fix 1",
        "verify 1",
        "fix 2",
        "verify 2",
    ]


def test_verification_is_skipped_when_implementation_failed() -> None:
    def failing_implement(prompt: str, plan_text: str) -> tuple[bool, str]:
        return False, "boom"

    def verify() -> tuple[bool, str]:
        raise AssertionError("must not run")

    result = run_pipeline("x", _plan, failing_implement, None, verify=verify)
    assert [s.name for s in result.stages] == ["plan", "implement"]
