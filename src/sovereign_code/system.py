"""Small macOS system probes used by the CLI and TUI."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from .config import launch_agent_path

_GIB = 1024**3
_LABEL = "com.user.sovereign-code"


@dataclass(frozen=True)
class Memory:
    total_gb: float
    free_gb: float
    free_pct: float
    # False when the probe itself failed. "0 GB free" and "I could not read the
    # memory counters" are different facts, and treating the second as the
    # first collapsed every model to a 2k context.
    known: bool = True

    @property
    def label(self) -> str:
        if not self.known:
            return f"{self.total_gb:.0f} GB · free unknown"
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
    if total <= 0:
        total = 24.0
    if "Pages free" not in pages:
        # vm_stat failed or returned something unrecognised. Report "unknown"
        # rather than "0 GB free": the router treats a real zero as a signal to
        # shrink the context window to its floor.
        return Memory(total_gb=total, free_gb=0.0, free_pct=0.0, known=False)
    free_pages = sum(
        pages.get(key, 0) for key in ("Pages free", "Pages inactive", "Pages speculative")
    )
    free_gb = round(free_pages * page_size / _GIB, 1)
    free_gb = min(free_gb, total)
    pct = round((free_gb / total) * 100, 0) if total else 0.0
    return Memory(total_gb=total, free_gb=free_gb, free_pct=pct)


def disk_free_gb(path: Path | None = None) -> float:
    try:
        usage = shutil.disk_usage(path or Path.home())
        return round(usage.free / _GIB, 1)
    except OSError:
        return 0.0


def models_to_evict(
    target_gb: float,
    residents: list[tuple[str, float]],
    wired_gb: float,
    reserve_gb: float = 2.0,
) -> list[str]:
    """Residents to unload before loading a `target_gb` model.

    Ollama does not return an error when a load cannot fit the GPU budget — it
    waits, and because parallel requests are off that blocks every later caller.
    When the target needs nearly the whole budget, make room up front instead.
    """
    if target_gb <= wired_gb - reserve_gb:
        return []
    return [name for name, size in residents if size > 0]


def wired_limit_gb(total_gb: float) -> float:
    """Apple-silicon GPU-wired memory ceiling.

    macOS reports 0 for `iogpu.wired_limit_mb` when the default policy applies,
    which reserves roughly 75% of unified memory for the GPU. A model larger
    than this cannot be loaded no matter how much "free" RAM the OS reports —
    and with parallel requests disabled Ollama will hang waiting rather than
    returning an error, which takes the whole server down for later callers.
    """
    out = _run(["sysctl", "-n", "iogpu.wired_limit_mb"]).strip()
    try:
        mb = int(out)
    except ValueError:
        mb = 0
    if mb > 0:
        return round(mb / 1024, 1)
    return round(max(total_gb, 0.0) * 0.75, 1)


def _to_gb(number: str, unit: str) -> float:
    try:
        value = float(number)
    except ValueError:
        return 0.0
    return round(value / 1024, 2) if unit.upper().startswith("M") else round(value, 2)


def swap_usage_gb() -> tuple[float, float]:
    """(used_gb, total_gb) from `sysctl vm.swapusage`; (0, 0) when unknown."""
    out = _run(["sysctl", "-n", "vm.swapusage"])
    used = re.search(r"used = ([0-9.]+)([MG])", out)
    total = re.search(r"total = ([0-9.]+)([MG])", out)
    if not used or not total:
        return (0.0, 0.0)
    return (
        _to_gb(used.group(1), used.group(2)),
        _to_gb(total.group(1), total.group(2)),
    )


def ollama_runner_models() -> list[str]:
    """Models with a live `ollama runner` process (may outlive /api/ps)."""
    out = _run(["/bin/ps", "-Ao", "command"], timeout=4.0)
    models: list[str] = []
    for line in out.splitlines():
        marker = "ollama runner --model "
        if marker in line:
            name = line.split(marker, 1)[1].split()[0]
            if name not in models:
                models.append(name)
    return models


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def listening_addresses(port: int) -> list[str]:
    """The bind addresses of every listener on ``port``.

    A URL of ``http://127.0.0.1:4010`` only says what the client dials; it
    says nothing about what the server bound. A process listening on
    ``0.0.0.0`` is reachable from the network even when every config file
    points at loopback, so "loopback only" has to be checked against the
    socket, not the config.

    The answer is cached for a few seconds: the dashboard asks several times
    a minute, and each answer costs an ``lsof`` subprocess.

    Returns an empty list when nothing is listening or the probe fails.
    """
    cached = _LISTENING_CACHE.get(port)
    now = time.monotonic()
    if cached is not None and now - cached[0] < LISTENING_CACHE_SECONDS:
        return cached[1]
    addresses = _probe_listening(port)
    _LISTENING_CACHE[port] = (now, addresses)
    return addresses


_LISTENING_CACHE: dict[int, tuple[float, list[str]]] = {}
LISTENING_CACHE_SECONDS = 5.0


def _probe_listening(port: int) -> list[str]:
    if os.uname().sysname != "Darwin":
        return []
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    addresses: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 9:
            continue
        # NAME is the "host:port" column; strip the port off the host.
        name = fields[8]
        if name.startswith("["):  # IPv6, e.g. [::1]:4010
            host = name.rsplit("]:", 1)[0].lstrip("[")
        else:
            host = name.rsplit(":", 1)[0]
        if host and host not in addresses:
            addresses.append(host)
    return addresses


def bound_to_loopback(port: int) -> bool:
    """True when every listener on ``port`` is bound to a loopback address.

    Returns False when the port is closed, because "nothing is listening" is
    not evidence that the service is loopback-only.
    """
    addresses = listening_addresses(port)
    if not addresses:
        return False
    return all(is_loopback_host(address) for address in addresses)


def exposed_ports(*ports: int) -> dict[int, list[str]]:
    """The ports that have a listener bound to a non-loopback address.

    An empty result means every listener found is loopback-only. Ports with
    no listener at all are not reported: a closed port is not exposed.
    """
    exposed: dict[int, list[str]] = {}
    for port in ports:
        addresses = listening_addresses(port)
        if not addresses:
            continue
        outside = [address for address in addresses if not is_loopback_host(address)]
        if outside:
            exposed[port] = outside
    return exposed


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def login_agent_installed() -> bool:
    return launch_agent_path(_LABEL).is_file()


def login_agent_loaded() -> bool:
    if os.uname().sysname != "Darwin":
        return False
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{_LABEL}"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def qwen_config_path() -> Path:
    return Path.home() / ".qwen" / "settings.json"


def qwen_memory_path() -> Path:
    return Path.home() / ".qwen" / "QWEN.md"


_LOOPBACK_HOSTS = {"localhost", "::1", "0:0:0:0:0:0:0:1"}


def is_loopback_host(host: str) -> bool:
    """True for a bare host name that resolves to this machine.

    The host-only counterpart of :func:`is_loopback`, used when the address
    comes from a socket rather than from a URL.
    """
    name = host.strip().strip("[]").lower()
    if not name:
        return False
    if name in _LOOPBACK_HOSTS:
        return True
    try:
        return ip_address(name).is_loopback
    except ValueError:
        return False


def is_loopback(url: str) -> bool:
    """True only for a host that really resolves to this machine.

    A substring test accepted "http://notlocalhost.example.com" and
    "http://127.0.0.1.evil.test", which would have silenced the loopback
    warning that guards the "nothing leaves the Mac" promise.
    """
    text = url.strip()
    if not text:
        return False
    if "://" not in text:
        text = f"http://{text}"
    try:
        host = (urlsplit(text).hostname or "").strip("[]").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
