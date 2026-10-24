"""Opt-in 24/7 coding loop.

``sovereign pipeline`` and ``sovereign orchestrate`` run one task to completion.
The loop answers the next question: *what should the agent work on now, and how
do we keep doing that safely overnight?*

One iteration:

1. preflight the project's own checks (a failing tree outranks new work);
2. pick the next task from ``docs/ROADMAP.md`` / ``TODO.md`` / ``TODO``
   comments, then a rotating improvement focus when that backlog is empty;
3. load the few relevant skills from the 22k-skill bank (cards first, bodies
   only for the winners) and the matching playbook;
4. hand a bounded, local-only prompt to a headless coding agent - OpenCode in
   ``--auto`` mode by default;
5. run the project's checks again and record the result under
   ``data/loop/runs/``.

The loop is deliberately opt-in. ``sovereign loop enable`` flips a per-project
state file, ``sovereign loop install`` (or ``enable`` without
``--foreground``) registers a launchd job, and ``disable``/``uninstall`` stop
it. Nothing here runs by itself until the user asks for it.

Safety rules baked into the prompt and the runner:

* local provider only, no cloud model;
* no commit, push, or dependency install;
* one small change with a test, verified by the project's own checks;
* a dirty git tree blocks the loop unless ``--allow-dirty`` is explicit;
* a task that keeps failing is retried at most ``max_attempts`` times, then
  the loop pauses instead of spinning.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .checks import detect_checks, run_checks
from .config import DATA_DIR
from .repomap import IGNORED_DIRS, LANGUAGE_BY_SUFFIX
from .safefile import ensure_private_dir, write_private

LOOP_DIR = DATA_DIR / "loop"
STATE_VERSION = 1
ROADMAP_CANDIDATES = (
    "docs/ROADMAP.md",
    "ROADMAP.md",
    "docs/TODO.md",
    "TODO.md",
    "BACKLOG.md",
)
# Directory names that are data or generated output, never project work.
SKIP_DIRS = frozenset(
    set(IGNORED_DIRS)
    | {
        ".opencode",
        ".kilo",
        "skills",
        "runtime",
        "logs",
        "htmlcov",
        "coverage.xml",
    }
)
# Files larger than this are not scanned for TODO comments.
MAX_SCAN_BYTES = 512 * 1024
MAX_SCAN_FILES = 2500
PROMPT_LIMIT = 24_000
CHECK_TASK_KEY = "checks-failing"
IMPROVE_FOCUS = (
    (
        "tests",
        "Find one behaviour in this project that has no test, and add the "
        "smallest focused test that proves it.",
    ),
    (
        "docs",
        "Find one documented command, flag, or claim that is wrong or missing, "
        "and make the documentation match the code.",
    ),
    (
        "quality",
        "Find one small correctness or robustness defect and fix it with a regression test.",
    ),
    (
        "security",
        "Audit one input-handling path and harden it with a regression test.",
    ),
    (
        "performance",
        "Measure one hot path, make one small improvement, and add a guard "
        "that keeps it from regressing.",
    ),
    (
        "dx",
        "Improve one unclear error message or CLI surface, with a test.",
    ),
)
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$")
_TODO = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b\s*[:\-]?\s*(.*)", re.IGNORECASE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_BULLET = re.compile(r"^\s*[-*+]\s+")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _slug(target: Path) -> str:
    return _digest(str(target.expanduser().resolve()))


@dataclass(frozen=True)
class Task:
    """One unit of work the loop can hand to the coding agent."""

    key: str
    title: str
    prompt: str
    source: str = ""
    priority: int = 50

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LoopConfig:
    """Everything one loop run needs to know."""

    directory: Path
    agent: str = "opencode"
    agent_model: str = "auto"
    interval: float = 900.0
    max_runs: int = 0
    agent_timeout: float = 3600.0
    check_timeout: float = 900.0
    checks: tuple[str, ...] = ()
    verify: bool = True
    skill_cards: int = 3
    skill_tokens: int = 1200
    idle: str = "improve"
    max_attempts: int = 3
    require_clean: bool = True
    allow_dirty: bool = False
    require_change: bool = True
    dry_run: bool = False

    def check_commands(self) -> list[str]:
        if not self.verify:
            return []
        if self.checks:
            return list(self.checks)
        return detect_checks(self.directory)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["directory"] = str(self.directory)
        return payload


@dataclass
class LoopState:
    """Persisted state for one project's loop."""

    version: int = STATE_VERSION
    enabled: bool = False
    target: str = ""
    runs: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    focus_index: int = 0
    last_run_at: str = ""
    last_task: str = ""
    last_result: str = ""
    last_check_ok: bool | None = None
    last_failure: str = ""
    paused: bool = False
    completed: dict[str, str] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class LoopRun:
    """The result of one loop iteration."""

    task: Task | None
    ok: bool
    agent_ok: bool
    checks_ok: bool | None
    output: str
    check_log: str
    started_at: str
    finished_at: str
    run_dir: str = ""
    state: LoopState | None = None

    def summary(self) -> str:
        name = self.task.title if self.task else "no task"
        verified = {True: "checks passed", False: "checks failed", None: "not verified"}
        head = f"{'ok' if self.ok else 'failed'} · {name} · {verified[self.checks_ok]}"
        tail = self.output.strip().splitlines()
        return f"{head} · {tail[-1][:160]}" if tail else head


class LoopError(RuntimeError):
    """A loop precondition that should be shown to the user, not retried."""


class LoopLocked(LoopError):
    """Another loop process already owns this project."""


# --------------------------------------------------------------- state files


def loop_dir() -> Path:
    return ensure_private_dir(LOOP_DIR)


def state_path(target: Path) -> Path:
    return loop_dir() / f"{_slug(target)}.json"


def lock_path(target: Path) -> Path:
    return loop_dir() / f"{_slug(target)}.lock"


def load_state(target: Path) -> LoopState:
    """Read the project's state, tolerating a missing or corrupt file."""
    path = state_path(target)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return LoopState(target=str(target.expanduser().resolve()))
    if not isinstance(data, dict):
        return LoopState(target=str(target.expanduser().resolve()))
    known = {item.name for item in LoopState.__dataclass_fields__.values()}
    payload = {key: value for key, value in data.items() if key in known}
    try:
        state = LoopState(**payload)
    except TypeError:
        return LoopState(target=str(target.expanduser().resolve()))
    state.target = str(target.expanduser().resolve())
    return state


def save_state(state: LoopState, target: Path) -> Path:
    state.target = str(target.expanduser().resolve())
    ensure_private_dir(state_path(target).parent)
    return write_private(
        state_path(target),
        json.dumps(state.as_dict(), indent=2, sort_keys=True) + "\n",
    )


def set_enabled(target: Path, enabled: bool) -> LoopState:
    """Turn the loop on or off for one project, clearing a pause on enable."""
    state = load_state(target)
    state.enabled = enabled
    if enabled:
        # Re-enabling is also the "I fixed it, try again" action: forget the
        # old failure and let the next iteration preflight the checks.
        state.paused = False
        state.consecutive_failures = 0
        state.last_check_ok = None
        state.last_failure = ""
        state.attempts.pop(CHECK_TASK_KEY, None)
    save_state(state, target)
    return state


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class _Lock:
    """A per-project pid lock so two loops never edit the same tree."""

    def __init__(self, target: Path) -> None:
        self.path = lock_path(target)
        self.held = False

    def __enter__(self) -> _Lock:
        ensure_private_dir(self.path.parent)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                other = int(self.path.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                other = 0
            if _pid_alive(other):
                raise LoopLocked(
                    f"the loop is already running for this project (pid {other})"
                ) from None
            # Stale lock from a crash: take it over.
            try:
                self.path.unlink()
            except OSError as exc:
                raise LoopLocked(f"could not clear a stale loop lock: {exc}") from None
            return self.__enter__()
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.held = False


# ------------------------------------------------------------ task discovery


def roadmap_tasks(root: Path) -> list[Task]:
    """Unchecked roadmap/backlog items, in file order."""
    tasks: list[Task] = []
    seen: set[str] = set()
    for relative in ROADMAP_CANDIDATES:
        path = root / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        open_item: list[str] = []
        start = 0
        in_fence = False
        for number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            match = _CHECKBOX.match(line)
            if match:
                _flush_roadmap(tasks, seen, open_item, relative, start)
                checked, title = match.group(1), match.group(2).strip()
                if checked.strip():
                    open_item = []
                else:
                    open_item = [title] if title else []
                    start = number
                continue
            if not open_item:
                continue
            stripped = line.strip()
            if not stripped or _HEADING.match(line) or _BULLET.match(line):
                _flush_roadmap(tasks, seen, open_item, relative, start)
                open_item = []
                continue
            open_item.append(stripped)
        _flush_roadmap(tasks, seen, open_item, relative, start)
    return tasks


def _flush_roadmap(
    tasks: list[Task], seen: set[str], parts: list[str], relative: str, line: int
) -> None:
    if not parts:
        return
    title = " ".join(part for part in parts if part).strip()
    if not title:
        return
    key = _digest(f"roadmap:{relative}:{title}")
    if key in seen:
        return
    seen.add(key)
    tasks.append(
        Task(
            key=key,
            title=title,
            prompt=(
                f"Complete this roadmap item from {relative}:\n\n{title}\n\n"
                "Keep the change small enough to review in one sitting."
            ),
            source=f"{relative}:{line}",
            priority=10,
        )
    )


def _source_files(root: Path) -> Iterable[Path]:
    count = 0
    for current, dirs, files in os.walk(root, topdown=True):
        dirs[:] = sorted(
            name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")
        )
        for name in sorted(files):
            if count >= MAX_SCAN_FILES:
                return
            path = Path(current) / name
            if path.suffix.lower() not in LANGUAGE_BY_SUFFIX:
                continue
            try:
                if path.stat().st_size > MAX_SCAN_BYTES or path.is_symlink():
                    continue
            except OSError:
                continue
            count += 1
            yield path


def todo_tasks(root: Path, limit: int = 200) -> list[Task]:
    """``TODO``/``FIXME`` comments in the project's source files."""
    tasks: list[Task] = []
    seen: set[str] = set()
    for path in _source_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            match = _TODO.search(line)
            if not match:
                continue
            marker, body = match.group(1).upper(), match.group(2).strip()
            title = f"{marker}: {body or 'address this comment'}"
            key = _digest(f"todo:{relative}:{number}:{title}")
            if key in seen:
                continue
            seen.add(key)
            tasks.append(
                Task(
                    key=key,
                    title=title[:200],
                    prompt=(
                        f"Resolve this {marker} in {relative}:{number}:\n\n"
                        f"{line.strip()}\n\nRemove the comment once the behaviour is fixed."
                    ),
                    source=f"{relative}:{number}",
                    priority=30,
                )
            )
            if len(tasks) >= limit:
                return tasks
    return tasks


def failing_check_task(failure: str) -> Task:
    """The highest-priority task: the project's own checks are red."""
    return Task(
        key=CHECK_TASK_KEY,
        title="Make the project checks pass",
        prompt=(
            "The project's checks are currently failing. Reproduce the first "
            "failure, fix the root cause, and add or update a test that keeps "
            "it fixed.\n\nCheck output:\n\n" + failure[-8000:]
        ),
        source="checks",
        priority=0,
    )


def improvement_task(state: LoopState) -> Task:
    """A rotating, bounded self-improvement task when the backlog is empty."""
    index = state.focus_index % len(IMPROVE_FOCUS)
    focus, prompt = IMPROVE_FOCUS[index]
    return Task(
        key=f"improve-{focus}-{index}",
        title=f"One small {focus} improvement",
        prompt=(
            f"{prompt}\n\n"
            "Read AGENTS.md, the roadmap, and the relevant skills before you "
            "choose. Pick one small, concrete change; do not refactor broadly."
        ),
        source="loop:improve",
        priority=90,
    )


def select_task(
    root: Path,
    state: LoopState,
    *,
    failure: str = "",
    idle: str = "improve",
    max_attempts: int = 3,
) -> Task | None:
    """Choose the next task, honouring completed and repeatedly failed items."""
    attempts = state.attempts
    if failure:
        if attempts.get(CHECK_TASK_KEY, 0) < max_attempts:
            return failing_check_task(failure)
        return None
    for task in sorted(roadmap_tasks(root), key=lambda item: item.priority):
        if task.key in state.completed:
            continue
        if attempts.get(task.key, 0) >= max_attempts:
            continue
        return task
    for task in todo_tasks(root):
        if task.key in state.completed:
            continue
        if attempts.get(task.key, 0) >= max_attempts:
            continue
        return task
    if idle == "wait":
        return None
    return improvement_task(state)


# --------------------------------------------------------------- the prompt


def _project_brief(root: Path) -> str:
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")[:8000]
            except OSError:
                continue
    checks = detect_checks(root)
    check_block = "\n".join(checks) if checks else "no test command was detected"
    return (
        f"# {root.name}\n\n"
        "No AGENTS.md was found. Detect the stack from the files, follow the "
        "existing style, and keep changes small.\n\n"
        f"Checks:\n```sh\n{check_block}\n```\n"
    )


def relevant_skills(
    task_text: str,
    *,
    cards: int = 3,
    max_tokens: int = 1200,
    bodies: int = 2,
    body_chars: int = 4000,
) -> str:
    """The cards, playbook, and a few safe skill bodies for one task.

    Cards are cheap and keep the prompt small. Only the top ``bodies`` winners
    are expanded, each capped, and a skill that the safety scanner rates above
    ``low`` is shown as a warning instead of being silently trusted.
    """
    if cards <= 0:
        return ""
    try:
        from .skillrouter import playbook, route
        from .skills_install import get_skill
        from .skills_safety import scan
    except Exception:
        return ""
    try:
        ranked, note = route(task_text, limit=cards, max_tokens=max_tokens, scan_risk=False)
    except Exception:
        return ""
    lines = ["## Skills that apply", ""]
    for index, step in enumerate(playbook(task_text), start=1):
        lines.append(f"{index}. {step}")
    if ranked:
        lines.extend(["", "### Skill cards", ""])
        for card in ranked:
            lines.append(f"- **{card.name}** — {card.description} ({card.category})")
    lines.extend(["", "### Loaded guidance", ""])
    loaded = 0
    for card in ranked:
        if loaded >= bodies:
            break
        found = get_skill(card.name)
        if found is None:
            continue
        warning = scan(found.body).warning()
        if warning:
            lines.append(f"[{card.name}] {warning}")
            continue
        body = found.body.strip()
        if len(body) > body_chars:
            body = body[:body_chars].rstrip() + "\n…[truncated]"
        lines.append(f"#### {card.name}\n\n{body}\n")
        loaded += 1
    if loaded == 0 and not ranked:
        lines.append("No skill matched this task; follow the project brief and checks.")
    lines.append(f"\n({note})")
    return "\n".join(lines).strip()


def build_prompt(
    task: Task,
    root: Path,
    *,
    checks: Iterable[str] = (),
    skills: str = "",
    consecutive_failures: int = 0,
) -> str:
    """The bounded, local-only instruction handed to the coding agent."""
    check_list = list(checks)
    check_block = "\n".join(f"- `{command}`" for command in check_list) or "- (none detected)"
    retry = ""
    if consecutive_failures:
        retry = (
            f"\nThe previous {consecutive_failures} run(s) did not pass. Prefer a smaller, "
            "more certain change this time.\n"
        )
    parts = [
        f"You are working unattended in `{root}`. There is no human to answer questions.",
        "",
        "## Project brief",
        "",
        _project_brief(root),
        "",
        "## Current task",
        "",
        f"**{task.title}**",
        f"Source: `{task.source}`" if task.source else "",
        "",
        task.prompt,
        retry,
        skills,
        "",
        "## Rules for this run",
        "",
        "- Work only inside the project directory.",
        "- Use local models only; never call a cloud provider or send code off-device.",
        "- Make the smallest useful change that completes the task.",
        "- Add or update a test for every behaviour change.",
        "- Do not commit, push, tag, or install dependencies.",
        "- Run the project's checks before you stop, and fix what you broke.",
        "- When the task is done, stop. Do not ask a question and do not wait for input.",
        "",
        "## Verification",
        "",
        check_block,
        "",
        "The loop will run these again after you exit; passing them is the definition of done.",
    ]
    text = "\n".join(part for part in parts if part is not None).strip()
    if len(text) > PROMPT_LIMIT:
        text = text[: PROMPT_LIMIT - 40].rstrip() + "\n\n…[prompt truncated to fit]\n"
    return text


# ------------------------------------------------------------------ execution


def _git_status(root: Path) -> str:
    """Porcelain status for a git worktree, or "" when it is not one."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _git_signature(root: Path) -> str:
    """A content-sensitive fingerprint of the worktree.

    ``git status --porcelain`` alone cannot tell "the agent edited a file that
    was already dirty" from "nothing changed": the status line is identical.
    Hashing the diff as well closes that gap, which matters when
    ``--allow-dirty`` is used.
    """
    status = _git_status(root)
    try:
        diff = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff", "--no-color"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60.0,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        diff = ""
    return hashlib.sha256((status + "\0" + diff).encode("utf-8")).hexdigest()


def check_guard(root: Path, config: LoopConfig) -> str:
    """Return an error when the loop must not touch the tree, else ""."""
    if not root.is_dir():
        return f"not a directory: {root}"
    if config.allow_dirty or not config.require_clean or not _is_git_repo(root):
        return ""
    dirty = _git_status(root)
    if dirty:
        return (
            "the git working tree has uncommitted changes; commit or stash them, "
            "or pass --allow-dirty"
        )
    return ""


def make_runner(config: LoopConfig, settings: Any = None) -> Callable[[str], tuple[bool, str]]:
    """A headless OpenCode (or other client) run, bound to the project."""
    from .agents import build_headless, run_headless
    from .config import Settings

    resolved = settings or Settings.load()

    def run(prompt: str) -> tuple[bool, str]:
        model = config.agent_model
        if model == "auto" and config.agent not in {"opencode", "codex", "claude"}:
            # Qwen Code has no "auto" model. Use the configured default, or the
            # same coder the interactive launcher uses.
            from .clients import AGENT_MODEL

            model = resolved.default_model or AGENT_MODEL
        try:
            plan = build_headless(
                config.agent,
                "local",
                config.directory,
                prompt,
                resolved,
                model,
                unattended=True,
                wall_time=max(60, int(config.agent_timeout) - 30),
                max_tool_calls=200,
            )
        except ValueError as exc:
            return False, str(exc)
        return run_headless(plan, timeout=config.agent_timeout)

    return run


def make_verifier(config: LoopConfig) -> Callable[[], tuple[bool, str]]:
    commands = config.check_commands()

    def verify() -> tuple[bool, str]:
        outcome = run_checks(config.directory, commands, timeout=config.check_timeout)
        return outcome.ok, outcome.log

    return verify


def _new_run_dir(task: Task | None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = task.key if task else "no-task"
    path = LOOP_DIR / "runs" / f"{stamp}-{name}"
    suffix = 1
    while path.exists():
        suffix += 1
        path = LOOP_DIR / "runs" / f"{stamp}-{name}-{suffix}"
    return ensure_private_dir(path)


def _write(path: Path, text: str) -> None:
    write_private(path, text if text.endswith("\n") else text + "\n")


def run_once(
    config: LoopConfig,
    *,
    state: LoopState | None = None,
    runner: Callable[[str], tuple[bool, str]] | None = None,
    verifier: Callable[[], tuple[bool, str]] | None = None,
    settings: Any = None,
    log: Callable[[str], None] | None = None,
) -> LoopRun:
    """Run one task to completion and persist the result.

    ``runner`` and ``verifier`` are injectable so the loop can be tested
    without spawning OpenCode or the project's whole test suite.
    """
    target = config.directory.expanduser().resolve()
    config = _with_directory(config, target)
    state = state or load_state(target)
    started = _now()
    say = log or (lambda _message: None)

    blocked = check_guard(target, config)
    if blocked:
        run = LoopRun(
            task=None,
            ok=False,
            agent_ok=False,
            checks_ok=None,
            output=f"blocked: {blocked}",
            check_log="",
            started_at=started,
            finished_at=_now(),
            state=state,
        )
        state.last_run_at = run.finished_at
        state.last_result = run.output
        state.failures += 1
        state.consecutive_failures += 1
        save_state(state, target)
        say(run.output)
        return run

    check_commands = config.check_commands()
    verify = verifier or (make_verifier(config) if check_commands else None)

    # Preflight the checks once per project (and again after every failure).
    failure = ""
    if verify is not None:
        failure = state.last_failure if state.last_check_ok is False else ""
        if state.last_check_ok is None:
            ok, log_text = verify()
            state.last_check_ok = ok
            state.last_failure = "" if ok else log_text
            failure = "" if ok else log_text
    else:
        # Switching to --no-verify must not leave a stale check-fix task in
        # front of the backlog.
        state.last_check_ok = None
        state.last_failure = ""

    task = select_task(
        target,
        state,
        failure=failure,
        idle=config.idle,
        max_attempts=config.max_attempts,
    )
    if task is None:
        if state.last_check_ok is False:
            state.paused = True
            state.last_result = (
                "paused: the project checks still fail after "
                f"{state.attempts.get(CHECK_TASK_KEY, 0)} repair attempt(s)"
            )
        else:
            state.last_result = "idle: no task found (use --idle improve to keep working)"
        state.last_run_at = _now()
        save_state(state, target)
        say(state.last_result)
        return LoopRun(
            task=None,
            ok=not state.paused,
            agent_ok=False,
            checks_ok=state.last_check_ok,
            output=state.last_result,
            check_log="",
            started_at=started,
            finished_at=_now(),
            state=state,
        )

    skills = relevant_skills(
        task.title,
        cards=config.skill_cards,
        max_tokens=config.skill_tokens,
    )
    prompt = build_prompt(
        task,
        target,
        checks=check_commands,
        skills=skills,
        consecutive_failures=state.consecutive_failures,
    )
    run_dir = _new_run_dir(task)
    _write(run_dir / "task.json", json.dumps(task.as_dict(), indent=2))
    _write(run_dir / "prompt.md", prompt)

    if config.dry_run:
        run = LoopRun(
            task=task,
            ok=True,
            agent_ok=False,
            checks_ok=None,
            output=f"dry run: would run {config.agent} in {target}",
            check_log="",
            started_at=started,
            finished_at=_now(),
            run_dir=str(run_dir),
            state=state,
        )
        say(run.output)
        return run

    saga = _recorder(prompt, target)
    if saga is not None:
        try:
            saga.stage_start("loop", role="edit", model=config.agent_model)
        except Exception:
            pass

    before = _git_signature(target)
    runner_fn = runner or make_runner(config, settings)
    say(f"working: {task.title}")
    try:
        agent_ok, output = runner_fn(prompt)
    except Exception as exc:  # a runner crash must not kill the 24/7 service
        agent_ok, output = False, f"agent failed to start: {exc}"
    after = _git_signature(target)
    changed = before != after if _is_git_repo(target) else agent_ok

    checks_ok: bool | None = None
    check_log = ""
    if verify is not None:
        checks_ok, check_log = verify()
        state.last_check_ok = checks_ok
        if checks_ok:
            state.last_failure = ""
            state.attempts.pop(CHECK_TASK_KEY, None)
        else:
            state.last_failure = check_log

    if config.require_change and _is_git_repo(target) and not changed:
        agent_ok = False
        output += "\n\nNo files were changed by the agent."
    ok = agent_ok and checks_ok is not False

    _write(run_dir / "agent.log", output)
    if check_log:
        _write(run_dir / "checks.log", check_log)
    state.runs += 1
    state.last_run_at = _now()
    state.last_task = task.title
    if ok:
        state.successes += 1
        state.consecutive_failures = 0
        state.completed[task.key] = state.last_run_at
        state.attempts.pop(task.key, None)
        if task.key.startswith("improve-"):
            state.focus_index += 1
    else:
        state.failures += 1
        state.consecutive_failures += 1
        state.attempts[task.key] = state.attempts.get(task.key, 0) + 1
        if state.attempts[task.key] >= config.max_attempts:
            state.paused = True
    if checks_ok is True:
        verified = "checks passed"
    elif checks_ok is False:
        verified = "checks failed"
    else:
        verified = "not verified"
    state.last_result = f"{'ok' if ok else 'failed'} · {task.title} · {verified}"
    save_state(state, target)

    run = LoopRun(
        task=task,
        ok=ok,
        agent_ok=agent_ok,
        checks_ok=checks_ok,
        output=output,
        check_log=check_log,
        started_at=started,
        finished_at=state.last_run_at,
        run_dir=str(run_dir),
        state=state,
    )
    _write(run_dir / "result.json", json.dumps(run.state.as_dict() if run.state else {}, indent=2))
    if saga is not None:
        try:
            saga.stage_end("loop", role="edit", model=config.agent_model, ok=ok, output=output)
            saga.finish(ok, checks_ok, run.summary())
        except Exception:
            pass
    say(run.summary())
    return run


def _with_directory(config: LoopConfig, target: Path) -> LoopConfig:
    if target == config.directory:
        return config
    return replace(config, directory=target)


def _recorder(prompt: str, target: Path) -> Any:
    try:
        from .harness import RunRecorder

        recorder = RunRecorder(prompt, str(target))
        recorder.start()
        return recorder
    except Exception:
        return None


def run_forever(
    config: LoopConfig,
    *,
    settings: Any = None,
    state: LoopState | None = None,
    runner: Callable[[str], tuple[bool, str]] | None = None,
    verifier: Callable[[], tuple[bool, str]] | None = None,
    max_runs: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] | None = None,
) -> int:
    """Keep running iterations until disabled, paused, or the budget is spent."""
    target = config.directory.expanduser().resolve()
    config = _with_directory(config, target)
    state = state or load_state(target)
    say = log or (lambda _message: None)
    limit = config.max_runs if max_runs is None else max_runs
    say(f"loop target: {target}")
    try:
        with _Lock(target):
            completed = 0
            while True:
                state = load_state(target)
                if not state.enabled:
                    say("loop disabled")
                    return 0
                if state.paused:
                    say(f"loop paused: {state.last_result}")
                    return 0
                if limit and completed >= limit:
                    say(f"loop reached max runs ({limit})")
                    return 0
                run_once(
                    config,
                    state=state,
                    runner=runner,
                    verifier=verifier,
                    settings=settings,
                    log=say,
                )
                completed += 1
                if limit and completed >= limit:
                    say(f"loop reached max runs ({limit})")
                    return 0
                state = load_state(target)
                if not state.enabled or state.paused:
                    continue
                if config.interval > 0:
                    say(f"sleeping {config.interval:.0f}s before the next task")
                    sleep(config.interval)
    except LoopLocked as exc:
        # Another instance is already doing the work. This is not a failure:
        # the launchd job restarts only on a non-zero exit, so returning 1
        # here would make it retry every ThrottleInterval forever.
        say(str(exc))
        return 0
    except KeyboardInterrupt:
        say("loop stopped")
        return 0


__all__ = [
    "CHECK_TASK_KEY",
    "IMPROVE_FOCUS",
    "LOOP_DIR",
    "LoopConfig",
    "LoopError",
    "LoopLocked",
    "LoopRun",
    "LoopState",
    "Task",
    "build_prompt",
    "check_guard",
    "failing_check_task",
    "improvement_task",
    "load_state",
    "make_runner",
    "make_verifier",
    "roadmap_tasks",
    "run_forever",
    "run_once",
    "save_state",
    "select_task",
    "set_enabled",
    "state_path",
    "todo_tasks",
]
