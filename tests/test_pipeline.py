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
