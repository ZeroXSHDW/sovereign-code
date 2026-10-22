"""Read-only live monitor data for the dashboard.

The monitor never loads a model, never starts a service, and never writes to
the skill or prompt databases. It reports what is already happening on the
machine: the size of the skill/prompt banks, which projects are using models,
which models are resident, and what the stack is doing right now.

This replaces the old always-on chat dashboard. A chat turn keeps a model
resident for its ``keep_alive`` window, which is exactly the RAM cost the
monitor is meant to avoid. Chat is still available explicitly with
``sovereign chat``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR, LOCAL_AI_ROOT, PROJECT_ROOT, SESSIONS_DIR
from .models import ModelView
from .skilldb import SkillDB
from .skills import REPO_SKILLS_DIR, USER_SKILLS_DIR
from .system import (
    Memory,
    disk_free_gb,
    port_open,
    read_memory,
    swap_usage_gb,
    wired_limit_gb,
)

# Dashboard refresh is cheap; the expensive lookups are cached separately.
BANK_CACHE_SECONDS = 30.0
PROJECT_CACHE_SECONDS = 10.0
ACTIVE_WINDOW_SECONDS = 15 * 60

_BANK_CACHE: dict[str, Any] = {}
_BANK_CACHE_AT = 0.0
_PROJECT_CACHE: list[LiveProject] = []
_PROJECT_CACHE_AT = 0.0


@dataclass(frozen=True)
class BankStats:
    """One searchable bank: skills, prompts, or prompt templates."""

    name: str
    total: int = 0
    installed: int = 0
    categories: tuple[tuple[str, int], ...] = ()
    top: tuple[tuple[str, int], ...] = ()
    size_mb: float = 0.0
    source: str = ""
    detail: str = ""

    @property
    def category_line(self) -> str:
        return " · ".join(f"{name} {count}" for name, count in self.categories) or "—"

    @property
    def top_line(self) -> str:
        return ", ".join(name for name, _count in self.top) or "—"


@dataclass(frozen=True)
class LiveProject:
    name: str
    path: str
    model: str = ""
    pid: int = 0
    last_seen: float = 0.0
    source: str = "session"
    active: bool = False

    @property
    def age(self) -> str:
        if not self.last_seen:
            return "now"
        seconds = max(0, int(time.time() - self.last_seen))
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        return f"{seconds // 3600}h"


@dataclass(frozen=True)
class Activity:
    at: float
    tier: str
    model: str
    ms: int = 0
    tokens: int = 0
    tools: bool = False
    reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stream: bool = False

    @property
    def age(self) -> str:
        seconds = max(0, int(time.time() - self.at))
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        return f"{seconds // 3600}h ago"

    @property
    def total_tokens(self) -> int:
        measured = self.prompt_tokens + self.completion_tokens
        return measured or self.tokens


@dataclass(frozen=True)
class ServiceLine:
    name: str
    port: int
    up: bool
    note: str = ""


@dataclass(frozen=True)
class Health:
    """A one-glance verdict plus the reasons behind it."""

    level: str = "ok"
    title: str = "healthy"
    reasons: tuple[str, ...] = ()

    @property
    def icon(self) -> str:
        return {"ok": "●", "warn": "▲", "critical": "■"}.get(self.level, "●")

    @property
    def style(self) -> str:
        return {"ok": "green", "warn": "yellow", "critical": "red"}.get(self.level, "green")


@dataclass(frozen=True)
class ActivityStats:
    """Aggregate of the recent gateway metrics window."""

    requests: int = 0
    tokens: int = 0
    tools: int = 0
    streams: int = 0
    p50_ms: int = 0
    p95_ms: int = 0
    per_minute: float = 0.0
    top_tier: str = ""
    top_tier_count: int = 0


@dataclass
class LiveReport:
    generated_at: float = field(default_factory=time.time)
    skills: BankStats = field(default_factory=lambda: BankStats("skill bank"))
    prompts: BankStats = field(default_factory=lambda: BankStats("prompt bank"))
    projects: list[LiveProject] = field(default_factory=list)
    activity: list[Activity] = field(default_factory=list)
    activity_stats: ActivityStats = field(default_factory=ActivityStats)
    services: list[ServiceLine] = field(default_factory=list)
    loaded: list[tuple[str, float, int | None, str]] = field(default_factory=list)
    memory: Memory = field(default_factory=lambda: Memory(0.0, 0.0, 0.0, known=False))
    swap_used_gb: float = 0.0
    swap_total_gb: float = 0.0
    disk_free_gb: float = 0.0
    load: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cpu_count: int = 0
    gateway_requests: int = 0
    models_installed: int = 0
    models_resident: int = 0
    resident_gb: float = 0.0
    potential_free_gb: float | None = None
    wired_gb: float = 0.0
    health: Health = field(default_factory=Health)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe view used by ``sovereign monitor --json``."""
        return asdict(self)


# --------------------------------------------------------------------- banks


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _open_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None


def _file_skills() -> dict[str, Path]:
    """Unique skill names on disk, local overrides winning over the repo."""
    found: dict[str, Path] = {}
    for directory in (USER_SKILLS_DIR, REPO_SKILLS_DIR):
        if not directory.is_dir():
            continue
        try:
            paths = directory.glob("*.md")
        except OSError:
            continue
        for path in paths:
            found.setdefault(path.stem, path)
    return found


def _category(name: str) -> str:
    try:
        return SkillDB._category_from_name(name)
    except Exception:
        return "general"


def _bank_from_rows(
    name: str,
    total: int,
    rows: list[tuple[str, str, int, int]],
    *,
    installed: int = 0,
    size_mb: float = 0.0,
    source: str = "",
    detail: str = "",
) -> BankStats:
    categories = Counter(category or "general" for _name, category, _uses, _rating in rows)
    used = [(row[0], row[2]) for row in rows if row[2] > 0]
    top = used[:6] if used else [(row[0], row[2]) for row in rows[:6]]
    return BankStats(
        name=name,
        total=total,
        installed=installed or total,
        categories=tuple(categories.most_common(8)),
        top=tuple(top),
        size_mb=size_mb,
        source=source,
        detail=detail,
    )


def skill_bank() -> BankStats:
    """Total skill bank: structured index when present, files otherwise."""
    files = _file_skills()
    candidates = (DATA_DIR / "skills.db", PROJECT_ROOT / "skills_index.db")
    for path in candidates:
        conn = _open_readonly(path)
        if conn is None:
            continue
        try:
            if not {"name", "category"} <= _table_columns(conn, "skills"):
                continue
            columns = _table_columns(conn, "skills")
            uses = "usage_count" if "usage_count" in columns else "0"
            rating = "rating" if "rating" in columns else "0"
            installed_col = "installed" if "installed" in columns else "1"
            rows = conn.execute(
                f"SELECT name, category, {uses}, {rating} FROM skills "
                f"WHERE {installed_col} = 1 ORDER BY {rating} DESC, {uses} DESC LIMIT 400"
            ).fetchall()
            total = int(conn.execute("SELECT COUNT(DISTINCT name) FROM skills").fetchone()[0])
            installed = int(
                conn.execute(
                    f"SELECT COUNT(DISTINCT name) FROM skills WHERE {installed_col} = 1"
                ).fetchone()[0]
            )
            return _bank_from_rows(
                "skill bank",
                max(total, len(files)),
                list(rows),
                installed=max(installed, len(files)),
                size_mb=round(path.stat().st_size / (1024 * 1024), 1),
                source=str(path),
                detail=f"indexed · {len(files)} on disk",
            )
        except sqlite3.Error:
            continue
        finally:
            conn.close()

    rows = [(name, _category(name), 0, 0) for name in sorted(files)]
    total_bytes = 0
    for path in files.values():
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    size_mb = round(total_bytes / (1024 * 1024), 1)
    return _bank_from_rows(
        "skill bank",
        len(files),
        rows,
        size_mb=size_mb,
        source="filesystem",
        detail="not indexed · sovereign skill-db sync",
    )


def _prompt_templates() -> list[Path]:
    directory = LOCAL_AI_ROOT / "config" / "skills"
    if not directory.is_dir():
        return []
    try:
        return sorted(directory.glob("*.md"))
    except OSError:
        return []


def prompt_bank() -> BankStats:
    """Prompt bank: versioned SQLite prompts plus Markdown templates."""
    templates = _prompt_templates()
    path = DATA_DIR / "prompts.db"
    conn = _open_readonly(path)
    total = 0
    rows: list[tuple[str, str, int, int]] = []
    if conn is not None:
        try:
            columns = _table_columns(conn, "prompts")
            if "name" in columns:
                total = int(conn.execute("SELECT COUNT(DISTINCT name) FROM prompts").fetchone()[0])
                category = "category" if "category" in columns else "'general'"
                uses = "usage_count" if "usage_count" in columns else "0"
                rating = "'0'"
                rows = conn.execute(
                    f"SELECT name, {category}, {uses}, {rating} FROM prompts "
                    f"ORDER BY {uses} DESC, updated_at DESC LIMIT 400"
                ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
    if total:
        detail = f"v{total} stored"
        if templates:
            detail += f" · {len(templates)} template files"
        return _bank_from_rows(
            "prompt bank",
            total,
            list(rows),
            size_mb=round(path.stat().st_size / (1024 * 1024), 1),
            source=str(path),
            detail=detail,
        )
    return BankStats(
        name="prompt bank",
        total=len(templates),
        installed=len(templates),
        top=tuple((template.stem, 0) for template in templates[:6]),
        source="filesystem",
        detail=f"{len(templates)} template files · sovereign prompts add <name>",
    )


def banks() -> tuple[BankStats, BankStats]:
    """Cached bank stats; the skill tree has >20k files and is not re-walked."""
    global _BANK_CACHE, _BANK_CACHE_AT
    now = time.monotonic()
    if _BANK_CACHE and now - _BANK_CACHE_AT < BANK_CACHE_SECONDS:
        return _BANK_CACHE["skills"], _BANK_CACHE["prompts"]
    skills = skill_bank()
    prompts = prompt_bank()
    _BANK_CACHE = {"skills": skills, "prompts": prompts}
    _BANK_CACHE_AT = now
    return skills, prompts


# ------------------------------------------------------------------ projects


def _session_records(limit: int = 60) -> list[tuple[Path, dict[str, Any], float]]:
    """Recent session files with their header record and mtime."""
    if not SESSIONS_DIR.is_dir():
        return []
    try:
        paths = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    found: list[tuple[Path, dict[str, Any], float]] = []
    for path in paths[:limit]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                line = handle.readline()
            record = json.loads(line) if line.strip() else {}
            found.append((path, record, path.stat().st_mtime))
        except (OSError, ValueError):
            continue
    return found


def _cwd_for(pid: int) -> str:
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in result.stdout.splitlines():
        if line.startswith("n") and len(line) > 1:
            return line[1:].strip()
    return ""


def _model_from_command(command: str) -> str:
    parts = command.split()
    for flag in ("--model", "-m"):
        if flag in parts:
            index = parts.index(flag)
            if index + 1 < len(parts):
                return parts[index + 1].strip("'\"")
    return ""


_AGENT_MARKERS = (
    "qwen",
    "codex",
    "claude",
    "opencode",
    "aider",
    "cursor-agent",
    "windsurf",
    "zed",
)


def _running_agents(limit: int = 8) -> list[LiveProject]:
    """Agent processes that are running right now, with their working project."""
    try:
        result = subprocess.run(
            ["/bin/ps", "-Ao", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[LiveProject] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw_pid, _, command = stripped.partition(" ")
        try:
            pid = int(raw_pid)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        low = command.lower()
        if "sovereign_code" in low or "ollama runner" in low:
            continue
        tokens = [Path(token).name for token in command.split()]
        if not any(token.startswith(marker) for token in tokens for marker in _AGENT_MARKERS):
            continue
        path = _cwd_for(pid)
        if not path:
            continue
        # GUI helpers and shell daemons sit in the home folder or in
        # /Applications; they are not a project using a model.
        home = str(Path.home().resolve())
        if path in {home, "/"} or path.startswith("/Applications"):
            continue
        found.append(
            LiveProject(
                name=Path(path).name or path,
                path=path,
                model=_model_from_command(command),
                pid=pid,
                last_seen=time.time(),
                source="process",
                active=True,
            )
        )
        if len(found) >= limit:
            break
    return found


def live_projects(limit: int = 8) -> list[LiveProject]:
    """Which project is using a model now, and which used one recently.

    Two sources, merged by folder: running agent processes (live) and the
    append-only session headers the dashboard/CLI styles record (recent).
    """
    global _PROJECT_CACHE, _PROJECT_CACHE_AT
    now_mono = time.monotonic()
    if _PROJECT_CACHE and now_mono - _PROJECT_CACHE_AT < PROJECT_CACHE_SECONDS:
        return _PROJECT_CACHE[:limit]

    merged: dict[str, LiveProject] = {}
    for process in _running_agents():
        merged[process.path] = process
    for _path, record, modified in _session_records():
        cwd = str(record.get("cwd") or "").strip()
        if not cwd:
            continue
        model = str(record.get("model") or "")
        active = time.time() - modified <= ACTIVE_WINDOW_SECONDS
        previous = merged.get(cwd)
        if previous and (previous.active or previous.source == "process"):
            if not previous.model and model:
                merged[cwd] = LiveProject(
                    previous.name,
                    previous.path,
                    model,
                    previous.pid,
                    max(previous.last_seen, modified),
                    previous.source,
                    previous.active,
                )
            continue
        merged[cwd] = LiveProject(
            name=Path(cwd).name or cwd,
            path=cwd,
            model=model,
            last_seen=modified,
            source="session",
            active=active,
        )
    projects = sorted(
        merged.values(),
        key=lambda item: (item.active, item.last_seen),
        reverse=True,
    )
    _PROJECT_CACHE = projects
    _PROJECT_CACHE_AT = now_mono
    return projects[:limit]


# ------------------------------------------------------------------ activity


def metrics_path() -> Path:
    return LOCAL_AI_ROOT / "data" / "logs" / "tiers.jsonl"


def _tail_text(path: Path, max_bytes: int = 256 * 1024) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()  # discard the partial first line
            return handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def recent_activity(limit: int = 8) -> list[Activity]:
    """The newest gateway requests, newest first."""
    events: list[Activity] = []
    for line in _tail_text(metrics_path()):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        events.append(
            Activity(
                at=float(event.get("ts") or 0.0),
                tier=str(event.get("tier") or "?"),
                model=str(event.get("model") or "?"),
                ms=int(float(event.get("ms") or 0)),
                tokens=int(event.get("tokens") or 0),
                tools=bool(event.get("tools")),
                reason=str(event.get("reason") or ""),
                prompt_tokens=int(event.get("prompt_tokens") or 0),
                completion_tokens=int(event.get("completion_tokens") or 0),
                stream=bool(event.get("stream")),
            )
        )
    events.sort(key=lambda item: item.at, reverse=True)
    return events[:limit]


def activity_stats(events: list[Activity], *, now: float | None = None) -> ActivityStats:
    """Aggregate latency, tokens, tool use, and request rate for the window."""
    if not events:
        return ActivityStats()
    times = sorted(max(0, int(event.ms)) for event in events)
    midpoint = times[len(times) // 2]
    p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
    tiers = Counter(event.tier for event in events)
    top_tier, top_count = tiers.most_common(1)[0]
    moment = time.time() if now is None else now
    last_minute = sum(1 for event in events if 0 <= moment - event.at <= 60)
    return ActivityStats(
        requests=len(events),
        tokens=sum(event.total_tokens for event in events),
        tools=sum(1 for event in events if event.tools),
        streams=sum(1 for event in events if event.stream),
        p50_ms=midpoint,
        p95_ms=p95,
        per_minute=float(last_minute),
        top_tier=top_tier,
        top_tier_count=top_count,
    )


_SPARK_LEVELS = "▁▂▃▄▅▆▇█"


def sparkline(
    values: list[float] | tuple[float, ...],
    *,
    width: int = 20,
    minimum: float | None = None,
    maximum: float | None = None,
) -> str:
    """A tiny fixed-width trend line for the monitor's history strip."""
    width = max(1, int(width))
    points = [float(value) for value in values]
    points = points[-width:]
    if not points:
        return "·" * width
    low = min(points) if minimum is None else float(minimum)
    high = max(points) if maximum is None else float(maximum)
    if high <= low:
        high = low + 1.0
    bars = []
    for value in points:
        ratio = max(0.0, min(1.0, (value - low) / (high - low)))
        index = min(len(_SPARK_LEVELS) - 1, int(ratio * len(_SPARK_LEVELS)))
        bars.append(_SPARK_LEVELS[index])
    return "·" * (width - len(bars)) + "".join(bars)


def assess(report: LiveReport) -> Health:
    """Turn raw counters into a conservative health verdict."""
    critical: list[str] = []
    warn: list[str] = []
    memory = report.memory
    if not memory.known:
        warn.append("memory counters unavailable")
    elif memory.free_pct < 8:
        critical.append(f"low RAM ({memory.free_pct:.0f}% free)")
    elif memory.free_pct < 18:
        warn.append(f"RAM pressure ({memory.free_pct:.0f}% free)")

    if report.swap_used_gb >= 6:
        critical.append(f"heavy swap ({report.swap_used_gb:.1f} GB)")
    elif report.swap_used_gb >= 2:
        warn.append(f"swap in use ({report.swap_used_gb:.1f} GB)")

    if report.disk_free_gb and report.disk_free_gb < 5:
        critical.append(f"disk almost full ({report.disk_free_gb:.0f} GB)")
    elif report.disk_free_gb and report.disk_free_gb < 20:
        warn.append(f"low disk ({report.disk_free_gb:.0f} GB)")

    down = [service.name for service in report.services if not service.up]
    critical_services = {"Ollama", "Tier gateway"}
    if any(name in critical_services for name in down):
        critical.append("core service offline: " + ", ".join(down))
    elif down:
        warn.append("service offline: " + ", ".join(down))

    if report.models_resident > 1:
        warn.append(f"{report.models_resident} models resident")
    if report.errors:
        warn.append(report.errors[0])

    if critical:
        return Health("critical", critical[0], tuple((critical + warn)[:4]))
    if warn:
        return Health("warn", warn[0], tuple(warn[:4]))
    return Health("ok", "all systems nominal")


# -------------------------------------------------------------------- system


def _service_lines(settings) -> list[ServiceLine]:
    from .config import DEFAULT_GATEWAY, DEFAULT_OLLAMA, DEFAULT_ROUTER

    def port_of(url: str, fallback: int) -> int:
        tail = url.rstrip("/").rsplit(":", 1)
        return int(tail[1]) if len(tail) == 2 and tail[1].isdigit() else fallback

    services = [
        ("Ollama", port_of(settings.ollama_url or DEFAULT_OLLAMA, 11434), "model server"),
        ("LiteLLM gateway", port_of(settings.gateway_url or DEFAULT_GATEWAY, 4000), "aliases"),
        ("Tier gateway", port_of(settings.router_url or DEFAULT_ROUTER, 4010), "auto routing"),
        ("Anthropic bridge", 4001, "Claude"),
    ]
    return [
        ServiceLine(name, port, port_open("127.0.0.1", port, timeout=0.15), note)
        for name, port, note in services
    ]


def _loaded(views: dict[str, ModelView] | None) -> list[tuple[str, float, int | None, str]]:
    if not views:
        return []
    loaded: list[tuple[str, float, int | None, str]] = []
    seen: set[int] = set()
    for view in views.values():
        if not view.loaded or id(view) in seen:
            continue
        seen.add(id(view))
        loaded.append((view.tag, view.vram_gb or view.size_gb, view.context, view.runner or ""))
    return sorted(loaded, key=lambda item: item[1], reverse=True)


def collect_live(settings, snapshot: Any | None = None) -> LiveReport:
    """Collect everything the monitor shows. Safe to call from a worker thread."""
    report = LiveReport()
    try:
        report.skills, report.prompts = banks()
    except Exception as exc:  # a broken database must not blank the dashboard
        report.errors.append(f"banks: {exc}")
    try:
        report.projects = live_projects()
    except Exception as exc:
        report.errors.append(f"projects: {exc}")
    events = recent_activity(limit=500)
    report.activity = events[:8]
    report.activity_stats = activity_stats(events)
    report.memory = read_memory()
    report.swap_used_gb, report.swap_total_gb = swap_usage_gb()
    report.disk_free_gb = disk_free_gb()
    report.wired_gb = wired_limit_gb(report.memory.total_gb)
    try:
        report.load = os.getloadavg()
    except OSError:
        report.load = (0.0, 0.0, 0.0)
    report.cpu_count = os.cpu_count() or 0
    report.services = _service_lines(settings)
    if snapshot is not None:
        report.loaded = _loaded(snapshot.views)
        report.models_installed = len(snapshot.installed)
        report.models_resident = len(report.loaded)
        report.resident_gb = round(sum(item[1] for item in report.loaded), 2)
        report.potential_free_gb = snapshot.potential_free_gb
        report.gateway_requests = metrics_count()
        # A running agent often has no --model flag (the client reads its own
        # config). With exactly one resident model, that model is the honest
        # answer for "which model is this project using".
        if len(report.loaded) == 1:
            only = report.loaded[0][0]
            report.projects = [
                replace(project, model=project.model or only) for project in report.projects
            ]
    report.health = assess(report)
    return report


def metrics_count(limit: int = 500) -> int:
    """How many requests are in the recent metrics window."""
    return len([line for line in _tail_text(metrics_path()) if line.strip()])


def format_age(timestamp: float) -> str:
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def demo_report() -> LiveReport:
    """Deterministic report used by the headless dashboard tests."""
    report = LiveReport()
    report.skills = BankStats(
        "skill bank",
        total=22924,
        installed=22924,
        categories=(("agent", 812), ("legal", 640), ("security", 530), ("language", 421)),
        top=(("code-review", 0), ("write-tests", 0), ("refactor", 0)),
        size_mb=95.3,
        source="skills_index.db",
        detail="indexed · 22924 on disk",
    )
    report.prompts = BankStats(
        "prompt bank",
        total=8,
        installed=8,
        categories=(("code", 5), ("review", 3)),
        top=(("code-review", 0), ("write-tests", 0)),
        source="config/skills",
        detail="8 template files",
    )
    report.projects = [
        LiveProject(
            name="sovereign-code",
            path=str(PROJECT_ROOT),
            model="qwen3.5:4b",
            pid=0,
            last_seen=time.time() - 120,
            source="process",
            active=True,
        )
    ]
    report.activity = [
        Activity(time.time() - 92, "fast", "qwen3.5:4b", 892, 18, False, "alias fast"),
        Activity(time.time() - 610, "balanced", "qwen3.5:9b", 26101, 22, True, "alias balanced"),
    ]
    report.services = [
        ServiceLine("Ollama", 11434, True, "model server"),
        ServiceLine("LiteLLM gateway", 4000, True, "aliases"),
        ServiceLine("Tier gateway", 4010, True, "auto routing"),
        ServiceLine("Anthropic bridge", 4001, True, "Claude"),
    ]
    report.loaded = [("qwen3.5:4b", 2.8, 8192, "runner")]
    report.models_installed = 9
    report.models_resident = 1
    report.resident_gb = 2.8
    report.potential_free_gb = 18.8
    report.memory = Memory(24.0, 16.0, 67.0)
    report.swap_used_gb, report.swap_total_gb = 0.4, 2.0
    report.disk_free_gb = 220.0
    report.load = (1.2, 1.1, 0.9)
    report.cpu_count = 12
    report.wired_gb = 18.0
    report.gateway_requests = 500
    report.activity_stats = ActivityStats(
        requests=500,
        tokens=83_400,
        tools=212,
        streams=388,
        p50_ms=1_840,
        p95_ms=12_400,
        per_minute=7.0,
        top_tier="deep",
        top_tier_count=214,
    )
    report.health = Health(
        "warn",
        "model resident",
        ("swap in use (0.4 GB)", "1 model resident"),
    )
    return report
