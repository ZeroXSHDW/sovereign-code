"""Multi-model coding pipeline: plan -> implement -> review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


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
        return all(stage.ok for stage in self.stages)


def run_pipeline(
    prompt: str,
    plan: Callable[[str], str],
    implement: Callable[[str, str], tuple[bool, str]],
    review: Callable[[str, str], str] | None = None,
) -> PipelineResult:
    """Orchestrate the stages, returning each stage's output in order."""
    plan_text = plan(prompt)
    stages = [StageResult("plan", True, plan_text)]

    ok, implementation = implement(prompt, plan_text)
    stages.append(StageResult("implement", ok, implementation))

    if review is not None:
        review_text = review(plan_text, implementation)
        stages.append(StageResult("review", True, review_text))

    return PipelineResult(stages)
