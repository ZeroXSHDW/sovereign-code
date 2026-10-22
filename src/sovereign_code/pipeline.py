"""Multi-model coding pipeline: plan -> implement -> verify -> review.

Verification is the part that makes the result trustworthy: the implementation
is judged by the project's own tests, and a failed check is fed back to the
implementer for a bounded number of repair rounds before review.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageResult:
    name: str
    ok: bool
    output: str


@dataclass
class PipelineResult:
    stages: list[StageResult] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """Overall outcome, not "no stage ever failed".

        A check that fails and is then repaired still counts as success — that
        is the point of the fix round. What matters is that the implementation
        ran and the *final* verification passed.
        """
        if not self.stages:
            return False
        if any(stage.name == "implement" and not stage.ok for stage in self.stages):
            return False
        return self.verified is not False

    @property
    def verified(self) -> bool | None:
        """True/False when checks ran, None when no verification stage existed."""
        checks = [stage.ok for stage in self.stages if stage.name.startswith("verify")]
        return checks[-1] if checks else None


def run_pipeline(
    prompt: str,
    plan: Callable[[str], str],
    implement: Callable[[str, str], tuple[bool, str]],
    review: Callable[[str, str], str] | None = None,
    verify: Callable[[], tuple[bool, str]] | None = None,
    fix: Callable[[str, str, str], tuple[bool, str]] | None = None,
    max_fixes: int = 1,
    on_stage: Callable[[StageResult], None] | None = None,
) -> PipelineResult:
    """Orchestrate the stages, returning each stage's output in order.

    `verify` runs the project's checks; when it fails and `fix` is supplied, the
    failure log is handed back to the implementer and checks run again, up to
    `max_fixes` times.

    `on_stage` is called as soon as each stage finishes, so a terminal or the
    live monitor can show a result without waiting for the whole run.
    """
    result = PipelineResult()

    def emit(stage: StageResult) -> None:
        result.stages.append(stage)
        if on_stage is not None:
            try:
                on_stage(stage)
            except Exception:
                # Observability must never abort the work it observes.
                pass

    plan_text = plan(prompt)
    emit(StageResult("plan", True, plan_text))

    ok, implementation = implement(prompt, plan_text)
    emit(StageResult("implement", ok, implementation))

    if verify is not None and ok:
        attempt = 0
        while True:
            passed, verify_output = verify()
            name = "verify" if attempt == 0 else f"verify {attempt}"
            emit(StageResult(name, passed, verify_output))
            if passed or fix is None or attempt >= max_fixes:
                break
            attempt += 1
            repaired, fix_output = fix(prompt, plan_text, verify_output)
            emit(StageResult(f"fix {attempt}", repaired, fix_output))
            if not repaired:
                break

    if review is not None:
        emit(StageResult("review", True, review(plan_text, implementation)))

    return result
