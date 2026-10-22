"""The runtime harness: which model serves which job, and what just happened.

The router answers "what is the best model for this one request". The harness
answers the user's larger question: *which* installed models are the right ones
for planning, implementation, small repairs, review, chat, and vision, and what
are they doing right now?

Two append-only JSONL logs make the runtime observable without touching the
model server:

``data/logs/orchestrations.jsonl``
    stage-level events from ``sovereign orchestrate`` / ``sovereign pipeline``.
    The monitor tails them, so a run started in another terminal shows up live.

``data/logs/downloads.jsonl``
    progress from ``sovereign pull`` and ``sovereign hf download``. The monitor
    shows an active download with its percentage instead of an empty screen.

Everything here is read-only apart from the two logs, is safe to import from a
worker thread, and degrades to an empty list when a log is missing.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .models import ModelView
from .router import Task, choose

ORCHESTRATIONS_LOG = "orchestrations.jsonl"
DOWNLOADS_LOG = "downloads.jsonl"
LOG_LIMIT_BYTES = 5 * 1024 * 1024
ACTIVE_RUN_SECONDS = 30 * 60
ACTIVE_DOWNLOAD_SECONDS = 30 * 60

_LOCK = threading.Lock()


# --------------------------------------------------------------------- roles


@dataclass(frozen=True)
class RolePlan:
    """One job the orchestrator knows how to hand to a model."""

    key: str
    label: str
    tier: str
    task: Task
    model: str | None
    context: int = 0
    size_gb: float = 0.0
    installed: bool = False
    reason: str = ""

    @property
    def tag(self) -> str:
        return self.model or "not installed"

    @property
    def detail(self) -> str:
        if not self.model:
            return "pull a model with: sovereign setup"
        size = f"{self.size_gb:.1f}G · " if self.size_gb else ""
        return f"{size}{self.context or '?'} ctx"


def _installed(views: dict[str, ModelView], tag: str) -> ModelView | None:
    view = views.get(tag)
    if view is not None and view.installed:
        return view
    for candidate in views.values():
        if candidate.installed and candidate.tag.removesuffix(":latest") == tag.removesuffix(
            ":latest"
        ):
            return candidate
    return None


def _pick(
    views: dict[str, ModelView],
    task: Task,
    free_gb: float | None,
    max_context: int,
    preferred: str | None = None,
):
    return choose(task, views, free_gb, preferred=preferred, max_context=max_context)


def _role(
    key: str,
    label: str,
    tier: str,
    task: Task,
    selection,
) -> RolePlan:
    model = selection.model
    return RolePlan(
        key=key,
        label=label,
        tier=tier,
        task=task,
        model=model.tag if model else None,
        context=selection.context if model else 0,
        size_gb=max(model.size_gb, model.spec.size_gb) if model else 0.0,
        installed=bool(model and model.installed),
        reason=selection.reason,
    )


def plan_roles(
    views: dict[str, ModelView],
    free_gb: float | None = None,
    max_context: int = 32768,
) -> list[RolePlan]:
    """The strongest installed model for each job, small ones first.

    The split is the point: a one-line repair does not need an 18 GB model,
    while planning and review are exactly where a larger model earns its load.
    A named reviewer from another model family is preferred when it is
    installed, because a second opinion from the same weights is not a second
    opinion.
    """

    quick = _role(
        "fix",
        "bug fixes · quick edits",
        "fast",
        Task.FAST,
        _pick(views, Task.FAST, free_gb, max_context),
    )
    edit = _role(
        "edit",
        "implementation",
        "deep",
        Task.CODE,
        _pick(views, Task.CODE, free_gb, max_context),
    )
    plan = _role(
        "plan",
        "planning",
        "deep",
        Task.REASON,
        _pick(views, Task.REASON, free_gb, max_context),
    )

    reviewer = _installed(views, "gemma4:12b")
    if reviewer is not None and reviewer.tag != edit.model:
        review = RolePlan(
            "review",
            "independent review",
            "balanced",
            Task.REASON,
            reviewer.tag,
            context=reviewer.context or 0,
            size_gb=max(reviewer.size_gb, reviewer.spec.size_gb),
            installed=True,
            reason="a different model family from the implementer",
        )
    else:
        review = _role(
            "review",
            "review",
            "deep",
            Task.AGENT,
            _pick(views, Task.AGENT, free_gb, max_context),
        )
        review = RolePlan(
            review.key,
            review.label,
            review.tier,
            review.task,
            review.model,
            review.context,
            review.size_gb,
            review.installed,
            (review.reason + " · no separate reviewer installed").strip(" ·"),
        )

    chat = _role(
        "chat",
        "chat",
        "balanced",
        Task.CHAT,
        _pick(views, Task.CHAT, free_gb, max_context),
    )
    vision = _role(
        "vision",
        "vision / screenshots",
        "deep",
        Task.VISION,
        _pick(views, Task.VISION, free_gb, max_context),
    )
    return [quick, edit, plan, review, chat, vision]


def role_plan_lines(roles: list[RolePlan]) -> list[str]:
    """Compact lines shared by the CLI and the monitor."""
    return [f"{role.label:<24} {role.tag:<22} {role.detail}" for role in roles]


# ---------------------------------------------------------------------- logs


def logs_dir() -> Path:
    return Path(DATA_DIR) / "logs"


def _log_path(name: str) -> Path:
    return logs_dir() / name


def _append(name: str, payload: dict[str, Any]) -> None:
    """Append one JSON event, rotating only when the file gets large."""
    path = _log_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            if path.is_file() and path.stat().st_size > LOG_LIMIT_BYTES:
                path.replace(path.with_suffix(".jsonl.1"))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        # Observability must never break the work it is observing.
        pass


def _tail(name: str, max_lines: int = 800) -> list[dict[str, Any]]:
    path = _log_path(name)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-max_lines:]
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


# --------------------------------------------------------------------- runs


@dataclass(frozen=True)
class RunEvent:
    ts: float
    run: str
    event: str
    stage: str = ""
    role: str = ""
    model: str = ""
    ok: bool | None = None
    ms: int = 0
    preview: str = ""
    prompt: str = ""
    directory: str = ""
    verified: bool | None = None

    @property
    def age(self) -> str:
        seconds = max(0, int(time.time() - self.ts))
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        return f"{seconds // 3600}h ago"


@dataclass(frozen=True)
class RunSummary:
    run: str
    started: float
    ended: float = 0.0
    prompt: str = ""
    directory: str = ""
    status: str = "running"
    stage: str = ""
    model: str = ""
    ms: int = 0
    verified: bool | None = None
    preview: str = ""
    stages: tuple[str, ...] = ()

    @property
    def age(self) -> str:
        seconds = max(0, int(time.time() - (self.ended or self.started)))
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        return f"{seconds // 3600}h"

    @property
    def active(self) -> bool:
        return not self.ended and time.time() - self.started < ACTIVE_RUN_SECONDS

    @property
    def label(self) -> str:
        return (self.prompt or self.run).strip().splitlines()[0][:72]


def _event(raw: dict[str, Any]) -> RunEvent:
    return RunEvent(
        ts=float(raw.get("ts") or 0.0),
        run=str(raw.get("run") or "?"),
        event=str(raw.get("event") or "?"),
        stage=str(raw.get("stage") or ""),
        role=str(raw.get("role") or ""),
        model=str(raw.get("model") or ""),
        ok=raw.get("ok") if isinstance(raw.get("ok"), bool) else None,
        ms=int(float(raw.get("ms") or 0)),
        preview=str(raw.get("preview") or ""),
        prompt=str(raw.get("prompt") or ""),
        directory=str(raw.get("directory") or ""),
        verified=raw.get("verified") if isinstance(raw.get("verified"), bool) else None,
    )


def recent_run_events(limit: int = 120) -> list[RunEvent]:
    events = [_event(raw) for raw in _tail(ORCHESTRATIONS_LOG, limit * 4)]
    events.sort(key=lambda item: item.ts, reverse=True)
    return events[:limit]


def _summaries(events: list[RunEvent]) -> list[RunSummary]:
    grouped: dict[str, list[RunEvent]] = {}
    for event in events:
        grouped.setdefault(event.run, []).append(event)
    summaries: list[RunSummary] = []
    for run, items in grouped.items():
        items.sort(key=lambda item: item.ts)
        start = next((item for item in items if item.event == "run-start"), items[0])
        end = next((item for item in reversed(items) if item.event == "run-end"), None)
        last_stage = next(
            (item for item in reversed(items) if item.event == "stage-end"),
            next((item for item in reversed(items) if item.event == "stage-start"), None),
        )
        stages = tuple(item.stage for item in items if item.event == "stage-end" and item.stage)
        summaries.append(
            RunSummary(
                run=run,
                started=start.ts,
                ended=end.ts if end else 0.0,
                prompt=start.prompt,
                directory=start.directory,
                status="complete" if end and end.ok else ("failed" if end else "running"),
                stage=last_stage.stage if last_stage else "",
                model=last_stage.model if last_stage else "",
                ms=last_stage.ms if last_stage else 0,
                verified=end.verified if end else None,
                preview=(end.preview if end else (last_stage.preview if last_stage else "")),
                stages=stages,
            )
        )
    summaries.sort(key=lambda item: item.started, reverse=True)
    return summaries


def recent_runs(limit: int = 6) -> list[RunSummary]:
    return _summaries(recent_run_events(limit=400))[:limit]


def active_run() -> RunSummary | None:
    for summary in _summaries(recent_run_events(limit=400)):
        if summary.active:
            return summary
    return None


class RunRecorder:
    """Write the lifecycle of one orchestration to the shared log."""

    def __init__(
        self,
        prompt: str,
        directory: str = "",
        run_id: str | None = None,
        roles: list[RolePlan] | None = None,
    ):
        self.run_id = run_id or uuid.uuid4().hex[:10]
        self.prompt = prompt
        self.directory = directory
        self.roles = roles or []
        self._started = time.monotonic()

    def start(self) -> str:
        _append(
            ORCHESTRATIONS_LOG,
            {
                "ts": time.time(),
                "run": self.run_id,
                "event": "run-start",
                "prompt": self.prompt,
                "directory": self.directory,
                "roles": {role.key: role.tag for role in self.roles},
            },
        )
        return self.run_id

    def stage_start(self, stage: str, role: str = "", model: str = "") -> None:
        _append(
            ORCHESTRATIONS_LOG,
            {
                "ts": time.time(),
                "run": self.run_id,
                "event": "stage-start",
                "stage": stage,
                "role": role,
                "model": model,
            },
        )

    def stage_end(
        self,
        stage: str,
        *,
        role: str = "",
        model: str = "",
        ok: bool,
        ms: float | int = 0,
        output: str = "",
    ) -> None:
        _append(
            ORCHESTRATIONS_LOG,
            {
                "ts": time.time(),
                "run": self.run_id,
                "event": "stage-end",
                "stage": stage,
                "role": role,
                "model": model,
                "ok": bool(ok),
                "ms": int(ms),
                "preview": _preview(output),
            },
        )

    def finish(self, ok: bool, verified: bool | None = None, output: str = "") -> None:
        _append(
            ORCHESTRATIONS_LOG,
            {
                "ts": time.time(),
                "run": self.run_id,
                "event": "run-end",
                "ok": bool(ok),
                "verified": verified,
                "preview": _preview(output),
                "ms": int((time.monotonic() - self._started) * 1000),
            },
        )


def _preview(text: str, limit: int = 400) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned[:limit]


# ---------------------------------------------------------------- downloads


@dataclass(frozen=True)
class Download:
    tag: str
    source: str = "ollama"
    status: str = ""
    completed: int = 0
    total: int = 0
    done: bool = False
    error: str = ""
    ts: float = 0.0

    @property
    def percent(self) -> int:
        if self.done:
            return 100
        if not self.total:
            return 0
        return min(100, int(self.completed * 100 / self.total))

    @property
    def active(self) -> bool:
        return not self.done and not self.error and time.time() - self.ts < ACTIVE_DOWNLOAD_SECONDS

    @property
    def size(self) -> str:
        if not self.total:
            return ""
        return f"{self.completed / 1e9:.1f}/{self.total / 1e9:.1f} GB"

    @property
    def state(self) -> str:
        if self.error:
            return f"failed: {self.error[:60]}"
        if self.done:
            return "done"
        return f"{self.percent}% {self.size} · {self.status or 'downloading'}"


def log_download(
    tag: str,
    *,
    source: str = "ollama",
    status: str = "",
    completed: int | None = None,
    total: int | None = None,
    done: bool = False,
    error: str = "",
) -> None:
    _append(
        DOWNLOADS_LOG,
        {
            "ts": time.time(),
            "tag": tag,
            "source": source,
            "status": status,
            "completed": int(completed or 0),
            "total": int(total or 0),
            "done": bool(done),
            "error": error,
        },
    )


def recent_downloads(limit: int = 6) -> list[Download]:
    latest: dict[str, Download] = {}
    for raw in _tail(DOWNLOADS_LOG, 800):
        try:
            item = Download(
                tag=str(raw.get("tag") or "?"),
                source=str(raw.get("source") or "ollama"),
                status=str(raw.get("status") or ""),
                completed=int(raw.get("completed") or 0),
                total=int(raw.get("total") or 0),
                done=bool(raw.get("done")),
                error=str(raw.get("error") or ""),
                ts=float(raw.get("ts") or 0.0),
            )
        except (TypeError, ValueError):
            continue
        latest[item.tag] = item
    rows = sorted(latest.values(), key=lambda item: item.ts, reverse=True)
    # Keep an in-flight download above finished ones, then newest first.
    return sorted(rows, key=lambda item: (not item.active, -item.ts))[:limit]


def active_downloads() -> list[Download]:
    return [download for download in recent_downloads(20) if download.active]


__all__ = [
    "Download",
    "RolePlan",
    "RunEvent",
    "RunRecorder",
    "RunSummary",
    "active_downloads",
    "active_run",
    "log_download",
    "plan_roles",
    "recent_downloads",
    "recent_run_events",
    "recent_runs",
    "role_plan_lines",
]
