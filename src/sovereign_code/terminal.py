"""Spawn full interactive terminals and run unrestricted local commands.

The dashboard and the MCP server both need the same primitive: give the user
(or a model acting for the user) a real shell with no allow-list, either as the
current account or through an interactive ``sudo`` prompt. Nothing here stores
or forwards a password: root commands use the macOS authorization dialog, and
interactive root shells prompt inside the new Terminal window.
"""

from __future__ import annotations

import atexit
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .safefile import ensure_private_dir, open_private, write_private
from .system import system_binary

MAX_OUTPUT = 400_000
_SUDO = re.compile(r"^\s*(sudo|doas)\s+(.*)$", re.DOTALL)

# Keep background Popen objects alive so their __del__ does not emit a
# ResourceWarning while the launched process is still running. Processes are
# reaped and the set is cleared at interpreter exit.
_BACKGROUND_PROCS: set[subprocess.Popen[bytes]] = set()


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
    # Through `available()` so mypy keeps the platform opaque: compared
    # inline, a Linux run narrows sys.platform and marks the rest of this
    # function unreachable, which fails `mypy --platform linux` in CI.
    if not available():
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
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run any shell command, using the macOS auth dialog for a leading sudo."""
    text = command.strip()
    if not text:
        raise ValueError("command is empty")
    workdir = _workdir(cwd)
    budget = max(1, min(7200, int(timeout or 120)))
    privileged = bool(_SUDO.match(text))
    if privileged and sys.platform == "darwin":
        # Run the whole command, not just the part after "sudo". The
        # authentication dialog already gives us root, so keeping the original
        # text means "sudo -u www cmd" still runs cmd as www (root may sudo),
        # while the old version executed the literal string "-u www cmd" and
        # failed with "-u: command not found".
        return _run_privileged(text, workdir, budget)
    try:
        import os as _os

        merged_env = _os.environ.copy()
        if env:
            merged_env.update(env)
        completed = subprocess.run(  # noqa: S602 - unrestricted shell access is the point
            text,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=budget,
            check=False,
            env=merged_env,
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


def tmux_available() -> bool:
    """Return True when tmux is installed and usable."""
    return system_binary("tmux") is not None


def _prune_background_logs(folder: Path, keep: int = 50) -> None:
    """Keep background command logs from growing without bound."""
    for old in sorted(folder.glob("bg-*.log"), reverse=True)[keep:]:
        try:
            old.unlink()
        except OSError:
            continue


def _cleanup_background_processes() -> None:
    """Terminate and reap any background processes we still track."""
    for proc in list(_BACKGROUND_PROCS):
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:
            pass
        _BACKGROUND_PROCS.discard(proc)


atexit.register(_cleanup_background_processes)


def run_background(
    command: str,
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Launch ``command`` detached and return its pid + log path."""
    text = command.strip()
    if not text:
        raise ValueError("command is empty")
    workdir = _workdir(cwd)
    folder = DATA_DIR / "terminals"
    ensure_private_dir(folder)
    _prune_background_logs(folder)
    log_path = folder / f"bg-{time.time_ns()}.log"
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    merged_env["SOVEREIGN_TERMINAL_FULL_ACCESS"] = "1"
    merged_env["SOVEREIGN_MCP_COMPUTER"] = "1"
    try:
        with open_private(log_path, "w") as fh:
            proc = subprocess.Popen(  # noqa: S602 - unrestricted shell access is the point
                text,
                shell=True,
                cwd=str(workdir),
                stdout=fh,
                stderr=subprocess.STDOUT,
                env=merged_env,
                start_new_session=True,
            )
    except OSError as exc:
        return {"ok": False, "error": str(exc), "cwd": str(workdir)}
    _BACKGROUND_PROCS.add(proc)
    return {
        "ok": True,
        "pid": proc.pid,
        "log": str(log_path),
        "cwd": str(workdir),
    }


def tmux_session(
    name: str,
    *,
    command: str = "",
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    """Create (or attach to) a named tmux session running ``command``."""
    if not tmux_available():
        return {"ok": False, "error": "tmux not installed"}
    workdir = _workdir(cwd)
    base = ["tmux", "new-session", "-d", "-s", name, "-c", str(workdir)]
    if command.strip():
        base.append(command.strip())
    completed = subprocess.run(base, capture_output=True, text=True, check=False)
    if completed.returncode != 0 and "duplicate session" not in (completed.stderr or ""):
        return {"ok": False, "stderr": completed.stderr.strip(), "cwd": str(workdir)}
    return {"ok": True, "session": name, "cwd": str(workdir)}


def available() -> bool:
    """Return True when a real terminal can be opened on this platform."""
    return sys.platform == "darwin"


def list_terminals() -> list[Path]:
    """List recorded terminal command files (newest first)."""
    folder = DATA_DIR / "terminals"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("sovereign-*.command"), reverse=True)


def cleanup_terminals(keep: int = 20) -> int:
    """Remove old recorded terminal command files, keeping the newest ``keep``."""
    files = list_terminals()
    removed = 0
    for path in files[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def info() -> dict[str, Any]:
    """Describe the terminal environment available to Sovereign Code."""
    return {
        "platform": sys.platform,
        "shell": shell_path(),
        "available": available(),
        "max_output": MAX_OUTPUT,
        "max_timeout": 7200,
    }


# Convenient aliases matching the rest of the codebase's naming.
run = run_shell
spawn = spawn_terminal


__all__ = [
    "available",
    "cleanup_terminals",
    "info",
    "list_terminals",
    "run",
    "run_background",
    "run_shell",
    "session_command",
    "shell_path",
    "spawn",
    "spawn_terminal",
    "tmux_available",
    "tmux_session",
]
