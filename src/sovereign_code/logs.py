"""Resolve and tail the local stack's logs."""

from __future__ import annotations

from pathlib import Path

from .config import LOCAL_AI_ROOT, PROJECT_ROOT

WATCHDOG_LOG = Path("/tmp/sovereign-gateway-watchdog.log")
TARGETS = ("gateway", "watchdog", "dashboard", "bridge")


def log_path(target: str) -> Path:
    if target == "gateway":
        return LOCAL_AI_ROOT / "gateway" / "gateway.log"
    if target == "watchdog":
        return WATCHDOG_LOG
    if target == "dashboard":
        return PROJECT_ROOT / "logs" / "login.err.log"
    if target == "bridge":
        return LOCAL_AI_ROOT / "data" / "logs" / "bridge.log"
    raise ValueError(f"unknown log target: {target}")


def tail_lines(path: Path, count: int = 40) -> list[str]:
    """Return the last `count` lines, tolerating binary or partial output."""
    if count <= 0:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-count:]
