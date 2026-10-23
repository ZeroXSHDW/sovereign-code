"""Spawn full interactive terminals and run unrestricted local commands.

The dashboard and the MCP server both need the same primitive: give the user
(or a model acting for the user) a real shell with no allow-list, either as the
current account or through an interactive ``sudo`` prompt. Nothing here stores
or forwards a password: root commands use the macOS authorization dialog, and
interactive root shells prompt inside the new Terminal window.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .safefile import write_private

MAX_OUTPUT = 100_000
_SUDO = re.compile(r"^\s*(sudo|doas)\s+(.*)$", re.DOTALL)


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… truncated ({len(text)} chars total)"


def shell_path() -> str:
    """The user's login shell, falling back to the system zsh."""
    value = os.environ.get("SHELL", "").strip()
    if value:
        candidate = Path(value)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    for fallback in ("/bin/zsh", "/bin/bash", "/bin/sh"):
        if Path(fallback).is_file():
            return fallback
    return "/bin/sh"


def _workdir(cwd: str | Path | None) -> Path:
    path = Path(cwd).expanduser() if cwd else Path.cwd()
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")
    return path


def session_command(
    *,
    sudo: bool = False,
    cwd: str | Path | None = None,
    command: str = "",
    full_access: bool = True,
) -> str:
    """Build the shell line a new terminal window runs."""
    shell = shell_path()
    parts = [f"cd {shlex.quote(str(_workdir(cwd)))}"]
    if full_access:
        parts.extend(
            (
                "export SOVEREIGN_TERMINAL_FULL_ACCESS=1",
                "export SOVEREIGN_MCP_COMPUTER=1",
                "export SOVEREIGN_MCP_UNRESTRICTED=1",
            )
        )
    text = command.strip()
    if sudo and text:
        parts.append(f"sudo -- {shlex.quote(shell)} -lc {shlex.quote(text)}")
        parts.append(f"exec {shlex.quote(shell)} -l")
    elif sudo:
        parts.append("sudo -s")
    elif text:
        parts.append(text)
        parts.append(f"exec {shlex.quote(shell)} -l")
    else:
        parts.append(f"exec {shlex.quote(shell)} -l")
    return "; ".join(parts)


def _apple_script(script: str) -> str:
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    return f'tell application "Terminal"\nactivate\ndo script "{escaped}"\nend tell'


def _command_file(line: str) -> Path:
    folder = DATA_DIR / "terminals"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"sovereign-{time.time_ns()}.command"
    write_private(path, f"#!/bin/sh\n{line}\n")
    path.chmod(0o700)
    return path


def spawn_terminal(
    *,
    sudo: bool = False,
    cwd: str | Path | None = None,
    command: str = "",
    full_access: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Open a new Terminal window with a regular or root shell."""
    workdir = _workdir(cwd)
    line = session_command(sudo=sudo, cwd=workdir, command=command, full_access=full_access)
    result: dict[str, Any] = {
        "ok": True,
        "sudo": sudo,
        "cwd": str(workdir),
        "shell": shell_path(),
        "full_access": full_access,
        "command": line,
    }
    if dry_run:
        result["method"] = "dry-run"
        return result
    if sys.platform != "darwin":
        raise ValueError("opening a new terminal window is supported on macOS only")
    opened = subprocess.run(
        ["osascript", "-e", _apple_script(line)],
        capture_output=True,
        text=True,
        check=False,
    )
    if opened.returncode == 0:
        result["method"] = "osascript"
        return result
    path = _command_file(line)
    fallback = subprocess.run(
        ["open", "-a", "Terminal", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    result["ok"] = fallback.returncode == 0
    result["method"] = "command-file"
    result["path"] = str(path)
    if not result["ok"]:
        result["error"] = (fallback.stderr or opened.stderr or "could not open Terminal").strip()
    return result


def _run_privileged(command: str, workdir: Path, timeout: int) -> dict[str, Any]:
    wrapped = f"cd {shlex.quote(str(workdir))} && {{ {command} ; }} 2>&1"
    try:
        completed = subprocess.run(
            [
                "osascript",
                "-e",
                "on run argv",
                "-e",
                "do shell script (item 1 of argv) with administrator privileges",
                "-e",
                "end run",
                "--",
                wrapped,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": f"timed out after {timeout}s",
            "cwd": str(workdir),
            "privileged": True,
        }
    except OSError as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "cwd": str(workdir),
            "privileged": True,
        }
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": _truncate(completed.stdout or ""),
        "stderr": _truncate(completed.stderr or ""),
        "cwd": str(workdir),
        "privileged": True,
    }


def run_shell(
    command: str,
    *,
    cwd: str | Path | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run any shell command, using the macOS auth dialog for a leading sudo."""
    text = command.strip()
    if not text:
        raise ValueError("command is empty")
    workdir = _workdir(cwd)
    budget = max(1, min(600, int(timeout or 120)))
    privileged = bool(_SUDO.match(text))
    if privileged and sys.platform == "darwin":
        body = _SUDO.match(text)
        if body is not None:
            return _run_privileged(body.group(2), workdir, budget)
    try:
        completed = subprocess.run(  # noqa: S602 - unrestricted shell access is the point
            text,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=budget,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": f"timed out after {budget}s",
            "cwd": str(workdir),
            "privileged": privileged,
        }
    except OSError as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "cwd": str(workdir),
            "privileged": privileged,
        }
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": _truncate(completed.stdout or ""),
        "stderr": _truncate(completed.stderr or ""),
        "cwd": str(workdir),
        "privileged": privileged,
    }


__all__ = [
    "run_shell",
    "session_command",
    "shell_path",
    "spawn_terminal",
]
