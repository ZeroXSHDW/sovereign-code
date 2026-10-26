"""Keep the local stack alive.

The tier gateway, the Anthropic bridge and the local chat web UI are detached
processes with a pid file. Nothing restarts them when they die, and a dead
tier gateway is indistinguishable from a broken ChatGPT app: the app answers
with a gateway error and looks like it wants a sign-in.

The guardian checks the ports and puts back what is missing. It is deliberately
dumb — a port check plus the existing `ensure_running` helpers — so it cannot
make things worse than not running it. When the services are installed as
launchd agents it restarts them through launchd instead, so the job that
launchd supervises is the one that gets restarted.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .config import LOG_DIR, Settings

# How often the guardian looks. Short enough that a dead gateway is back
# before a person notices, long enough not to wake the machine for nothing.
DEFAULT_INTERVAL = 30.0

BRIDGE_PORT = 4001
WEB_PORT = 4020

LOG_PATH = LOG_DIR / "guardian.jsonl"


@dataclass
class Service:
    """One supervised service."""

    name: str
    port: int
    url: str
    running: Callable[[], bool]
    start: Callable[[], bool]
    stop: Callable[[], bool] | None = None
    note: str = ""
    label: str = ""

    @property
    def ok(self) -> bool:
        return self.running()


@dataclass
class ServiceState:
    """The result of one guardian check."""

    name: str
    port: int
    url: str
    up: bool
    restarted: bool = False
    detail: str = ""
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.up

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "port": self.port,
            "url": self.url,
            "up": self.up,
            "restarted": self.restarted,
            "detail": self.detail,
            "note": self.note,
        }


def _port(url: str) -> int:
    """The port in a URL, or 0 when there is none."""
    tail = url.rstrip("/").rsplit(":", 1)
    if len(tail) != 2 or not tail[1].isdigit():
        return 0
    return int(tail[1])


def _start_litellm(settings: Settings) -> bool:
    """Start the LiteLLM gateway detached, without a Terminal window.

    The gateway venv lives in ~/Documents, which launchd cannot list, but it
    can run a program by its full path — and this process inherits whatever
    consent it was started with.
    """
    from .services import gateway_executable, gateway_python, gateway_root

    root = gateway_root()
    executable = gateway_executable()
    if not executable.is_file():
        return False
    log_path = root / "gateway.log"
    env = dict(os.environ)
    cmd = [
        str(gateway_python()),
        str(executable),
        "--config",
        str(root / "config.yaml"),
        "--host",
        "127.0.0.1",
        "--port",
        str(_port(settings.gateway_url) or 4000),
    ]
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as handle:
            subprocess.Popen(
                cmd,
                stdout=handle,
                stderr=handle,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                cwd=str(root),
                env=env,
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _launchd_first(label: str, fallback: Callable[[], bool]) -> Callable[[], bool]:
    """Restart through launchd when the job is loaded, else start it here."""

    def start() -> bool:
        from .services import is_loaded, kickstart

        if is_loaded(label):
            return kickstart(label)
        return fallback()

    return start


def _start_supervised_mlx() -> bool:
    from . import mlx

    state = mlx.read_state()
    model = str(state.get("model") or "")
    if not model:
        return False
    saved_draft = state.get("draft")
    draft = "off" if saved_draft == "" else (str(saved_draft) if saved_draft is not None else None)
    kv_bits = int(str(state["kv_bits"])) if "kv_bits" in state else 8
    started, _detail = mlx.start_server(
        model=model,
        port=int(str(state.get("port") or mlx.DEFAULT_MLX_PORT)),
        max_tokens=int(str(state.get("max_tokens") or 4096)),
        draft=draft,
        kv_bits=kv_bits,
        draft_tokens=int(str(state.get("draft_tokens") or 4)),
        decode_concurrency=int(str(state.get("decode_concurrency") or 4)),
    )
    return started


def services(settings: Settings | None = None) -> list[Service]:
    """The services the guardian looks after."""
    from .bridge import ensure_running as bridge_start
    from .bridge import port_open as bridge_open
    from .bridge import stop as bridge_stop
    from .services import BRIDGE_LABEL, GATEWAY_LABEL, TIER_LABEL
    from .tier_gateway import ensure_running as router_start
    from .tier_gateway import port_open as router_open
    from .tier_gateway import stop as router_stop

    settings = settings or Settings.load()
    router_port = _port(settings.router_url) or 4010
    gateway_port = _port(settings.gateway_url) or 4000
    gateway = settings.gateway_url
    services = [
        Service(
            name="LiteLLM gateway",
            port=gateway_port,
            url=f"{gateway.rstrip('/')}/v1",
            running=lambda: _port_open("127.0.0.1", gateway_port),
            start=_launchd_first(GATEWAY_LABEL, lambda: _start_litellm(settings)),
            note="the alias gateway the tier gateway proxies to",
            label=GATEWAY_LABEL,
        ),
        Service(
            name="tier gateway",
            port=router_port,
            url=f"{settings.router_url.rstrip('/')}/v1",
            running=lambda: router_open(port=router_port),
            start=_launchd_first(
                TIER_LABEL,
                lambda: router_start(upstream=settings.gateway_url, port=router_port),
            ),
            stop=router_stop,
            note="the ChatGPT app and Codex talk to this",
            label=TIER_LABEL,
        ),
        Service(
            name="Anthropic bridge",
            port=BRIDGE_PORT,
            url=f"http://127.0.0.1:{BRIDGE_PORT}/v1",
            running=lambda: bridge_open(port=BRIDGE_PORT),
            start=_launchd_first(
                BRIDGE_LABEL,
                lambda: bridge_start(gateway_url=settings.router_url, port=BRIDGE_PORT),
            ),
            stop=bridge_stop,
            note="Claude Code and Claude Desktop talk to this",
            label=BRIDGE_LABEL,
        ),
    ]
    from . import mlx

    if mlx.supervised():
        port = mlx.mlx_port()
        services.append(
            Service(
                name="MLX",
                port=port,
                url=f"{mlx.mlx_url().rstrip('/')}/v1",
                running=mlx.supervised_ok,
                start=_start_supervised_mlx,
                note="the supervised model saved in data/mlx-server.json",
            )
        )
    return services


def _port_open(host: str, port: int) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def check(settings: Settings | None = None, autostart: bool = True) -> list[ServiceState]:
    """Check every service and put back the missing ones."""
    states: list[ServiceState] = []
    for service in services(settings):
        up = service.running()
        restarted = False
        detail = "running" if up else "not running"
        if not up and autostart:
            try:
                restarted = bool(service.start())
            except Exception as exc:  # a failed start is a result, not a crash
                detail = f"start failed: {exc}"
            else:
                detail = "restarted" if restarted else "start failed"
                up = service.running()
        states.append(
            ServiceState(
                name=service.name,
                port=service.port,
                url=service.url,
                up=up,
                restarted=restarted,
                detail=detail,
                note=service.note,
            )
        )
    return states


def publish_session_env(settings: Settings | None = None) -> bool:
    """Publish the environment the desktop apps need to be local.

    `launchctl setenv` reaches every app launched later in the login session,
    which is the only way to reach an app opened from the Dock. The values are
    only written when they differ, so the launchd log stays quiet.
    """
    from .services import session_env, session_env_values

    wanted = session_env(settings)
    current = session_env_values()
    changed = False
    for key, value in wanted.items():
        if current.get(key) != value:
            subprocess.run(
                ["launchctl", "setenv", key, value],
                capture_output=True,
                check=False,
                timeout=5.0,
            )
            changed = True
    return changed


def repair_clients() -> list[str]:
    """Put the desktop apps back on the local path when they drift.

    The ChatGPT app rewrites its own config when a setting changes in its UI,
    and that silently sends it back to the cloud. The repair only happens while
    the local mode is the current one: the saved cloud copy exists only then,
    and `sovereign chatgpt --cloud` / `sovereign claude --cloud` remove it.
    """
    from .client_setup import (
        claude_cloud_backup_path,
        claude_forced_local,
        codex_cloud_backup_path,
        codex_forced_local,
        install_claude_settings,
        install_codex_forced_local,
    )

    repaired: list[str] = []
    if codex_cloud_backup_path().is_file() and not codex_forced_local():
        try:
            install_codex_forced_local()
            repaired.append("ChatGPT config")
        except OSError:
            pass
    if claude_cloud_backup_path().is_file() and not claude_forced_local():
        try:
            install_claude_settings()
            repaired.append("Claude settings")
        except OSError:
            pass
    return repaired


def log(states: list[ServiceState]) -> None:
    """Record what the guardian did."""
    changed = [state for state in states if state.restarted]
    if not changed:
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            for state in changed:
                handle.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "service": state.name,
                            "port": state.port,
                            "detail": state.detail,
                        }
                    )
                    + "\n"
                )
    except OSError:
        pass


def watch(interval: float = DEFAULT_INTERVAL, settings: Settings | None = None) -> None:
    """Keep checking until interrupted."""
    settings = settings or Settings.load()
    while True:
        states = check(settings)
        log(states)
        publish_session_env(settings)
        repair_clients()
        time.sleep(max(5.0, interval))
