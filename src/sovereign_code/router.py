"""Hardware-aware model and context selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .mlx import online as mlx_online
from .models import CATALOG, ModelView, mlx_preferred_tags
from .models import preferred_tags as preferred_tags


class Task(StrEnum):
    """The kind of work a model is being picked for.

    A ``StrEnum`` so a task can be compared with, and formatted as, its
    plain name: ``str(Task.CODE)`` is ``"code"``, not ``"Task.CODE"``.
    """

    CODE = "code"
    CHAT = "chat"
    REASON = "reason"
    VISION = "vision"
    FAST = "fast"
    AGENT = "agent"


CONTEXT_CHOICES = (32768, 24576, 20480, 16384, 8192, 4096, 2048)


@dataclass(frozen=True)
class Selection:
    task: Task
    model: ModelView | None
    context: int
    reason: str
    needs_pull: str | None = None

    @property
    def tag(self) -> str | None:
        return self.model.tag if self.model else None


def estimated_kv_gb(view: ModelView, context: int) -> float:
    """Small, deliberately conservative KV-cache estimate for Apple unified memory."""
    base = max(view.size_gb, view.spec.size_gb, 1.0)
    return max(0.35, base * (context / 32768.0) * 0.22)


def estimated_total_gb(view: ModelView, context: int) -> float:
    return round(max(view.size_gb, view.spec.size_gb) + estimated_kv_gb(view, context), 2)


# A model whose weights alone exceed the free-RAM budget still runs: macOS
# reclaims file cache and Ollama spills to shared memory. Returning 2048 in that
# case made coding models useless (measured: qwen3-coder:30b, 19 GB, runs fine at
# 16k and 32k on this 24 GB Mac). Keep a working floor instead of collapsing.
TIGHT_CONTEXT = 16384


def context_for(view: ModelView, free_gb: float | None, max_context: int = 32768) -> int:
    ceiling = min(view.spec.max_context or max_context, max_context)
    choices = [c for c in CONTEXT_CHOICES if c <= ceiling] or [2048]
    # A resident model already owns its KV allocation; do not shrink it just
    # because the free-RAM figure now excludes that allocation.
    if view.loaded and view.context:
        return min(int(view.context), ceiling)
    if free_gb is None:
        return min(choices[0], 16384)
    budget = max(1.0, free_gb) * 0.85
    weights = max(view.size_gb, view.spec.size_gb, 1.0)
    for context in choices:
        if estimated_total_gb(view, context) <= budget:
            return context
    if weights >= budget:
        # Slightly over budget: allow a usable window. macOS reclaims several GB
        # of cache and compressible memory under load, so a model up to ~1.5x the
        # "potential free" figure still runs (verified with a 19 GB model at 16k
        # and 32k). Beyond that it cannot fit and we fall back to the minimum.
        return min(TIGHT_CONTEXT, ceiling) if weights <= max(1.0, free_gb) * 1.5 else choices[-1]
    return choices[-1]


def _fallback(views: dict[str, ModelView]) -> ModelView | None:
    """The best installed model when the curated list has nothing for the task.

    Picking the *smallest* installed model chose `phi` (1.6 GB, a smoke-test
    model) over anything usable, which is exactly what the curated preference
    list exists to prevent. Prefer a real model, then the largest one, then
    one that is already resident because a warm model answers sooner.
    """
    installed: list[ModelView] = []
    seen: set[int] = set()
    for view in views.values():
        # A cloud tag is "installed" in Ollama's model list, but selecting it
        # would send the prompt off-device and break the local-first promise.
        if view.installed and not view.spec.cloud and id(view) not in seen:
            seen.add(id(view))
            installed.append(view)
    if not installed:
        return None

    def key(view: ModelView) -> tuple[int, float, int, str]:
        return (
            0 if _is_usable(view) else 1,
            -view.size_gb,
            0 if view.loaded else 1,
            view.tag,
        )

    return sorted(installed, key=key)[0]


def _is_usable(view: ModelView) -> bool:
    """False for the tiny smoke-test models that cannot do real work."""
    return not (view.spec.max_context <= 2048 and view.size_gb <= 2.0)


def choose(
    task: Task,
    views: dict[str, ModelView],
    free_gb: float | None = None,
    preferred: str | None = None,
    max_context: int = 32768,
) -> Selection:
    if preferred:
        view = views.get(preferred)
        if view and view.installed:
            context = context_for(view, free_gb, max_context)
            return Selection(task, view, context, f"selected {view.tag}", None)

    # MLX models run on Apple Metal and answer far faster than Ollama for the
    # same size, so when the mlx-lm server is online they take performance
    # priority for code, reason, agent, chat and general work. `fast` stays
    # Ollama-only: a warm tiny Ollama model answers sooner than loading MLX.
    if task != Task.FAST and mlx_online():
        for tag in mlx_preferred_tags(task.value):
            view = views.get(tag)
            if view and view.installed:
                context = context_for(view, free_gb, max_context)
                return Selection(task, view, context, f"mlx {view.tag}", None)

    for tag in preferred_tags(task.value):
        view = views.get(tag)
        if view and view.installed:
            context = context_for(view, free_gb, max_context)
            reason = f"best installed model for {task.value} on this Mac"
            return Selection(task, view, context, reason, None)

    fallback = _fallback(views)
    if fallback:
        context = context_for(fallback, free_gb, max_context)
        return Selection(task, fallback, context, "fallback to an installed model", None)

    # Nothing is installed: still tell the user which model to pull.
    wanted = recommend_pull(task)
    spec = CATALOG.get(wanted)
    reason = "no local models are installed"
    return Selection(task, None, 4096, reason, wanted if spec else None)


def recommend_pull(task: Task = Task.CODE) -> str:
    return preferred_tags(task.value)[0]


def system_prompt(task: Task) -> str:
    base = (
        "You are Sovereign Code, a local-first engineering assistant running entirely "
        "on this Mac through Ollama. You have no cloud access; never claim to browse "
        "the web or call external APIs. Be precise, concise, and practical."
    )
    if task in (Task.CODE, Task.AGENT):
        return (
            f"{base}\n\n"
            "You are in coding mode. When proposing changes: state the file, give a "
            "minimal diff or complete replacement, preserve existing style, and call "
            "out anything you could not verify. Prefer standard-library solutions. "
            "Never invent file contents you have not been shown."
        )
    if task is Task.REASON:
        return (
            f"{base}\n\n"
            "Reason step by step, separate assumptions from facts, and finish with a "
            "short recommendation. Do not expose hidden chain-of-thought; summarize "
            "the reasoning that matters."
        )
    if task is Task.VISION:
        return (
            f"{base}\n\n"
            "You may receive images. Describe only what is visible, distinguish "
            "observation from inference, and mention uncertainty."
        )
    if task is Task.FAST:
        return f"{base}\n\nAnswer with the smallest useful response."
    return (
        f"{base}\n\n"
        "You are a helpful pair-programmer and technical tutor. Use Markdown and "
        "fenced code blocks. Ask a brief clarifying question only when necessary."
    )


# Domain-flavoured names ChatGPT and other clients use when asking for the
# best model for a kind of work. They are normalised to the router's task
# enum so `best_model("legal")` picks a reasoner instead of crashing or
# falling back to chat.
_TASK_SYNONYMS: dict[str, Task] = {
    "coder": Task.CODE,
    "coding": Task.CODE,
    "programming": Task.CODE,
    "developer": Task.CODE,
    "dev": Task.CODE,
    "legal": Task.REASON,
    "law": Task.REASON,
    "compliance": Task.REASON,
    "contract": Task.REASON,
    "finance": Task.REASON,
    "financial": Task.REASON,
    "forensics": Task.REASON,
    "dfir": Task.REASON,
    "incident": Task.REASON,
    "image": Task.VISION,
    "images": Task.VISION,
    "visual": Task.VISION,
    "photo": Task.VISION,
    "agentic": Task.AGENT,
    "tools": Task.AGENT,
    "speed": Task.FAST,
    "quick": Task.FAST,
}


def task_from_name(name: str | None) -> Task:
    cleaned = (name or "chat").lower().strip()
    try:
        return Task(cleaned)
    except ValueError:
        return _TASK_SYNONYMS.get(cleaned, Task.CHAT)


def mode_label(task: Task) -> str:
    return {
        Task.CODE: "code",
        Task.CHAT: "chat",
        Task.REASON: "reason",
        Task.VISION: "vision",
        Task.FAST: "fast",
        Task.AGENT: "agent",
    }[task]
