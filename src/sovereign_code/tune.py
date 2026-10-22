"""Apply and verify Ollama runtime tuning on Apple-silicon Macs.

The Ollama app reads a stored ``context_length`` from its own SQLite settings
and exports the rest of its environment at launch. Two things go wrong in
practice:

* the app keeps a hidden UI process alive, so quitting only the server means
  the old settings are re-applied on the next launch;
* the tuning variables live in the login agent, but an app started before that
  agent ran never inherits them.

This module keeps the logic pure enough to test: the only side effects are
``restart_ollama`` and the SQLite write.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from pathlib import Path

DEFAULT_CONTEXT = 32768


def desired_env(context: int = DEFAULT_CONTEXT) -> dict[str, str]:
    """The environment the server should be running with."""
    return {
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
        "OLLAMA_KEEP_ALIVE": "15m",
        # One model at a time. With 2, Ollama tries to keep the previous model
        # and load the next; when the pair cannot fit the ~18 GB wired budget it
        # waits forever instead of evicting, which blocks every later request.
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_CONTEXT_LENGTH": str(int(context)),
    }


def parse_server_env(ps_output: str) -> dict[str, str]:
    """Extract OLLAMA_* assignments from `ps eww` output."""
    env: dict[str, str] = {}
    for token in ps_output.split():
        if token.startswith("OLLAMA_") and "=" in token:
            key, value = token.split("=", 1)
            env[key] = value
    return env


def env_drift(
    current: dict[str, str], desired: dict[str, str]
) -> list[tuple[str, str | None, str]]:
    """(key, current, wanted) for every setting that does not match."""
    return [
        (key, current.get(key), value)
        for key, value in desired.items()
        if current.get(key) != value
    ]


def ollama_db_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Ollama" / "db.sqlite"


def read_context_length(path: Path | None = None) -> int | None:
    """The app's stored context_length, or None when it cannot be read."""
    db = path or ollama_db_path()
    if not db.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            row = con.execute("SELECT context_length FROM settings WHERE id = 1").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


def write_context_length(value: int, path: Path | None = None) -> bool:
    """Persist context_length. Returns True when the row changed."""
    db = path or ollama_db_path()
    if not db.is_file():
        return False
    try:
        with sqlite3.connect(db) as con:
            cur = con.execute("UPDATE settings SET context_length = ? WHERE id = 1", (int(value),))
            con.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def _current_server_pid() -> str | None:
    try:
        out = subprocess.run(
            ["pgrep", "-f", "ollama serve"], capture_output=True, text=True, check=False
        ).stdout.split()
    except OSError:
        return None
    return out[0] if out else None


def current_server_env() -> dict[str, str]:
    """Environment of the running `ollama serve`, or {} when it is down."""
    pid = _current_server_pid()
    if not pid:
        return {}
    try:
        out = subprocess.run(
            ["ps", "eww", "-p", pid], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return {}
    return parse_server_env(out)


def set_session_env(values: dict[str, str]) -> None:
    for key, value in values.items():
        subprocess.run(["launchctl", "setenv", key, value], check=False)


_OLLAMA_PATTERNS = (
    "Ollama.app/Contents/MacOS/Ollama",
    "Ollama.app/Contents/Resources/ollama serve",
)


def _any_process(patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern], capture_output=True, text=True, check=False
            )
        except OSError:
            continue
        if result.returncode == 0 and result.stdout.strip():
            return True
    return False


def restart_ollama(timeout: float = 10.0, env: dict[str, str] | None = None) -> None:
    """Fully restart the app so a fresh server inherits the new environment.

    The UI process must die too: `osascript quit` alone leaves it hidden, and it
    respawns the server with the settings it still holds in memory.

    `open -a Ollama` is ignored while the old app is still shutting down, which
    left no server running at all. Wait for both processes to disappear first,
    then launch, and retry once if the launch did not take.
    """
    # `open -a Ollama` passes this process's environment to the app, which can
    # override launchctl. Apply the desired tuning here so a stale shell value
    # (for example OLLAMA_MAX_LOADED_MODELS=2) cannot win.
    if env:
        os.environ.update(env)
    # The quit can report "User cancelled" when the app is busy; the hard kill
    # below is authoritative, so keep that noise out of the CLI.
    subprocess.run(
        ["osascript", "-e", 'quit app "Ollama"'], capture_output=True, text=True, check=False
    )
    for pattern in _OLLAMA_PATTERNS:
        subprocess.run(["pkill", "-f", pattern], check=False)

    deadline = time.monotonic() + timeout
    while _any_process(_OLLAMA_PATTERNS) and time.monotonic() < deadline:
        time.sleep(0.25)
    if _any_process(_OLLAMA_PATTERNS):
        for pattern in _OLLAMA_PATTERNS:
            subprocess.run(["pkill", "-9", "-f", pattern], check=False)
        time.sleep(0.5)

    subprocess.run(["open", "-a", "Ollama"], check=False)


def supported() -> bool:
    return os.uname().sysname == "Darwin"
