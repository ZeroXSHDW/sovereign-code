"""Project checks: decide what "correct" means for a directory, then run it.

The multi-model pipeline is only trustworthy if the last word comes from the
project's own tests, not from a model's opinion of itself.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_LOG = 6000


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
    """Best guess at the project's test command, or [] when unknown."""
    makefile = directory / "Makefile"
    if makefile.is_file():
        try:
            text = makefile.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
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
    return []


def run_checks(directory: Path, commands: list[str], timeout: float = 900.0) -> CheckResult:
    """Run each command in `directory`; all must pass."""
    if not commands:
        return CheckResult(True, "no checks detected (use --checks to specify)")

    ok = True
    chunks: list[str] = []
    for command in commands:
        try:
            result = subprocess.run(
                command,
                shell=True,
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
