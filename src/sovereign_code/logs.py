"""Resolve and tail the local stack's logs."""

from __future__ import annotations

from pathlib import Path

from .config import LOCAL_AI_ROOT, LOG_DIR, PROJECT_ROOT

# The watchdog used to be a launch agent that wrote into /tmp, which is
# world-readable and cleared on reboot. It now lives in the stack's own log
# directory; the old path is still read so an existing install keeps working.
WATCHDOG_LOG = LOG_DIR / "watchdog.log"
LEGACY_WATCHDOG_LOG = Path("/tmp/sovereign-gateway-watchdog.log")  # noqa: S108 - legacy read-only path
TARGETS = ("gateway", "watchdog", "dashboard", "bridge", "tier", "loop")


def log_path(target: str) -> Path:
    if target == "gateway":
        return LOCAL_AI_ROOT / "gateway" / "gateway.log"
    if target == "watchdog":
        return WATCHDOG_LOG
    if target == "dashboard":
        return PROJECT_ROOT / "logs" / "login.err.log"
    if target == "bridge":
        return LOCAL_AI_ROOT / "data" / "logs" / "bridge.log"
    if target == "tier":
        return LOCAL_AI_ROOT / "data" / "logs" / "tier-gateway.log"
    if target == "loop":
        return LOG_DIR / "service-loop.log"
    raise ValueError(f"unknown log target: {target}")


def resolve_log_path(target: str) -> Path:
    """The log that actually exists, falling back to the legacy location."""
    path = log_path(target)
    if target == "watchdog" and not path.exists() and LEGACY_WATCHDOG_LOG.exists():
        return LEGACY_WATCHDOG_LOG
    return path


def tail_lines(path: Path, count: int = 40) -> list[str]:
    """Return the last `count` lines, tolerating binary or partial output."""
    if count <= 0:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-count:]
