"""Small macOS system probes used by the CLI and TUI."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import launch_agent_path

_GIB = 1024**3
_LABEL = "com.user.sovereign-code"


@dataclass(frozen=True)
class Memory:
    total_gb: float
    free_gb: float
    free_pct: float

    @property
    def label(self) -> str:
        return f"{self.total_gb:.0f} GB · {self.free_pct:.0f}% free"


def _run(args: list[str], timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def total_memory_gb() -> float:
    out = _run(["sysctl", "-n", "hw.memsize"]).strip()
    try:
        return round(int(out) / _GIB, 1)
    except ValueError:
        return 0.0


def read_memory() -> Memory:
    total = total_memory_gb()
    output = _run(["vm_stat"])
    page_size = 16384
    match = re.search(r"page size of (\d+) bytes", output)
    if match:
        page_size = int(match.group(1))
    pages: dict[str, int] = {}
    for line in output.splitlines():
        m = re.match(r"([^:]+):\s+(\d+)\.", line)
        if m:
            pages[m.group(1).strip()] = int(m.group(2))
    free_pages = sum(
        pages.get(key, 0) for key in ("Pages free", "Pages inactive", "Pages speculative")
    )
    free_gb = round(free_pages * page_size / _GIB, 1)
    if total <= 0:
        total = 24.0
    free_gb = min(free_gb, total)
    pct = round((free_gb / total) * 100, 0) if total else 0.0
    return Memory(total_gb=total, free_gb=free_gb, free_pct=pct)


def disk_free_gb(path: Path | None = None) -> float:
    try:
        usage = shutil.disk_usage(path or Path.home())
        return round(usage.free / _GIB, 1)
    except OSError:
        return 0.0


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def load_average() -> tuple[float, float, float]:
    try:
        return tuple(round(v, 2) for v in os.getloadavg())  # type: ignore[return-value]
    except OSError:
        return (0.0, 0.0, 0.0)


def login_agent_installed() -> bool:
    return launch_agent_path(_LABEL).is_file()


def login_agent_loaded() -> bool:
    if os.uname().sysname != "Darwin":
        return False
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def qwen_config_path() -> Path:
    return Path.home() / ".qwen" / "settings.json"


def qwen_memory_path() -> Path:
    return Path.home() / ".qwen" / "QWEN.md"


def is_loopback(url: str) -> bool:
    return any(token in url for token in ("127.0.0.1", "localhost", "::1"))
