"""launchd services for the local stack.

Only the pieces a client needs run as launchd agents: the LiteLLM gateway,
the tier gateway and the Anthropic bridge. They start at login, so they are
back after a reboot, and launchd restarts them when they die.

The old always-on chat web UI and the 30-second guardian loop are intentionally
not installed. They spent RAM/CPU continuously for work nobody was asking for;
the login dashboard is a passive monitor now and chat is explicit.

macOS protects ~/Documents, and a launchd job cannot list a directory there.
It can, however, run a program by its full path, so every service is started
with an absolute interpreter and an absolute config path. That is what makes
this work without a Terminal window in the way, and it is why the gateway
supervisor used to need one.
"""

from __future__ import annotations

import html
import os
import plistlib
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import LOCAL_AI_ROOT, PROJECT_ROOT, Settings

LABEL_PREFIX = "com.user.sovereign"
AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = LOCAL_AI_ROOT / "data" / "logs"

GATEWAY_LABEL = f"{LABEL_PREFIX}.gateway"
TIER_LABEL = f"{LABEL_PREFIX}.tier"
BRIDGE_LABEL = f"{LABEL_PREFIX}.bridge"
WEBCHAT_LABEL = f"{LABEL_PREFIX}.webchat"
GUARDIAN_LABEL = f"{LABEL_PREFIX}.guardian"

# The chat web UI and the 24/7 guardian used to be installed as services.
# They are deliberately no longer part of the stack: the dashboard is now a
# read-only monitor, and an always-on chat server plus a restart loop was RAM
# and CPU spent on nothing. The labels stay here so an upgrade can remove the
# old jobs instead of leaving them running.
RETIRED_LABELS = (WEBCHAT_LABEL, GUARDIAN_LABEL)


@dataclass
class Service:
    """One launchd agent."""

    label: str
    name: str
    argv: tuple[str, ...]
    port: int = 0
    detail: str = ""
    keep_alive: bool = True
    working_dir: str = ""
    env: dict[str, str] = field(default_factory=dict)
    log_name: str = ""

    @property
    def plist_path(self) -> Path:
        return AGENT_DIR / f"{self.label}.plist"

    @property
    def installed(self) -> bool:
        return self.plist_path.is_file()

    @property
    def log_path(self) -> Path:
        return LOG_DIR / (self.log_name or f"{self.label}.log")


def gateway_root() -> Path:
    return LOCAL_AI_ROOT / "gateway"


def gateway_python() -> Path:
    return gateway_root() / "venv" / "bin" / "python3"


def gateway_executable() -> Path:
    return gateway_root() / "venv" / "bin" / "litellm"


def cloud_env() -> dict[str, str]:
    """The optional provider keys for the gateway's cloud passthrough.

    The file is read, not sourced, so a value with spaces or quotes cannot
    break the plist.
    """
    path = gateway_root() / "cloud.env"
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key:
            values[key] = value.strip().strip("'\"")
    return values


def _port_of(url: str, default: int) -> int:
    tail = url.rstrip("/").rsplit(":", 1)
    if len(tail) == 2 and tail[1].isdigit():
        return int(tail[1])
    return default


def gateway_supervisor() -> Path:
    """The script that runs LiteLLM and restarts it when it crashes.

    It exits cleanly when another instance already owns the port, which keeps
    launchd from restarting this job into a fight with the server that is up.
    """
    return gateway_root() / "run_gateway.sh"


def gateway_argv(port: int) -> tuple[str, ...]:
    """The command that runs the LiteLLM gateway under launchd.

    Two macOS rules shape this. A launchd job may read files in ~/Documents
    but may not *execute* a script there, so the gateway is started through
    its interpreter instead of `run_gateway.sh`. And the port is checked
    first: a job that finds the port taken exits cleanly, and launchd leaves
    it alone instead of restarting it into a fight.
    """
    root = gateway_root()
    return (
        "/bin/bash",
        "-c",
        "if (exec 3<>/dev/tcp/127.0.0.1/"
        f"{port}"
        ") 2>/dev/null; then exit 0; fi; "
        f'cd "{root}" && exec "{root}/venv/bin/python3" "{root}/venv/bin/litellm" '
        f'--config "{root}/config.yaml" --host 127.0.0.1 --port {port}',
    )


def service_definitions(settings: Settings | None = None) -> list[Service]:
    """The services that make up the local stack, in start order."""
    settings = settings or Settings.load()
    python = sys.executable
    router_port = _port_of(settings.router_url, 4010)
    gateway_port = _port_of(settings.gateway_url, 4000)
    return [
        Service(
            label=GATEWAY_LABEL,
            name="LiteLLM gateway",
            argv=gateway_argv(gateway_port),
            port=gateway_port,
            detail="the alias gateway behind the tier gateway",
            working_dir=str(gateway_root()),
            env=cloud_env(),
            log_name="service-gateway.log",
        ),
        Service(
            label=TIER_LABEL,
            name="Tier gateway",
            argv=(
                python,
                "-m",
                "sovereign_code",
                "router",
                "--port",
                str(router_port),
                "--upstream",
                settings.gateway_url,
                "--ollama",
                settings.ollama_url,
            ),
            port=router_port,
            detail="what ChatGPT, Codex, Claude and OpenCode talk to",
            working_dir=str(PROJECT_ROOT),
            log_name="service-tier.log",
        ),
        Service(
            label=BRIDGE_LABEL,
            name="Anthropic bridge",
            argv=(
                python,
                "-m",
                "sovereign_code",
                "bridge",
                "--port",
                "4001",
                "--gateway",
                settings.router_url,
            ),
            port=4001,
            detail="what Claude Code and Claude Desktop talk to",
            working_dir=str(PROJECT_ROOT),
            log_name="service-bridge.log",
        ),
    ]


def plist_text(service: Service) -> str:
    """The launchd plist for one service."""
    payload: dict[str, object] = {
        "Label": service.label,
        "ProgramArguments": list(service.argv),
        "RunAtLoad": True,
        "LimitLoadToSessionType": "Aqua",
        "ThrottleInterval": 10,
        "StandardOutPath": str(service.log_path),
        "StandardErrorPath": str(service.log_path),
    }
    if service.keep_alive:
        # Restart only after a failure. A clean exit means another instance
        # already owns the port, and restarting would only fight it.
        payload["KeepAlive"] = {"SuccessfulExit": False}
    if service.working_dir:
        payload["WorkingDirectory"] = service.working_dir
    if service.env:
        payload["EnvironmentVariables"] = {str(k): str(v) for k, v in service.env.items()}
    return plistlib.dumps(payload).decode("utf-8")


def _has_provenance(path: Path) -> bool:
    """Whether the file carries the macOS provenance attribute.

    A file another app created carries it, and launchd cannot open such a
    file for a job's output: the job then fails to spawn with EX_CONFIG and
    never starts at all.
    """
    try:
        result = subprocess.run(
            ["xattr", "-p", "com.apple.provenance", str(path)],
            capture_output=True,
            check=False,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _usable_log(path: Path) -> None:
    """Leave launchd a log file it can actually open."""
    if not path.exists() or not _has_provenance(path):
        return
    try:
        path.replace(path.with_name(f"{path.name}.{int(time.time())}.old"))
    except OSError:
        pass


def write_plist(service: Service) -> Path:
    """Write the plist for one service and return its path."""
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    service.log_path.parent.mkdir(parents=True, exist_ok=True)
    _usable_log(service.log_path)
    path = service.plist_path
    path.write_text(plist_text(service), encoding="utf-8")
    # A plist that carries provider keys is a secret: keep it to the user.
    path.chmod(0o600 if service.env else 0o644)
    return path


def _launchctl(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["launchctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")


def domain() -> str:
    return f"gui/{os.getuid()}"


def load_service(service: Service) -> bool:
    """Register the service with launchd and start it."""
    _launchctl("bootout", f"{domain()}/{service.label}")
    result = _launchctl("bootstrap", domain(), str(service.plist_path))
    if result.returncode != 0:
        return False
    _launchctl("kickstart", f"{domain()}/{service.label}")
    return True


def unload_service(service: Service) -> bool:
    """Stop the service and take it out of the launchd domain."""
    result = _launchctl("bootout", f"{domain()}/{service.label}")
    return result.returncode == 0


def unload_label(label: str) -> bool:
    """Stop a job by label and take it out of the launchd domain."""
    result = _launchctl("bootout", f"{domain()}/{label}")
    return result.returncode == 0


# The Terminal-based gateway jobs the launchd services replace. One opened a
# Terminal window at every login to start a supervisor; the other checked the
# gateway every five minutes and did the same when it was down.
SUPERSEDED_LABELS = ("com.user.ailocalgateway", "com.user.ailocalgateway.watchdog")


def retire_superseded() -> list[tuple[str, str]]:
    """Retire the jobs the launchd services replace.

    The plist is kept next to the original, so putting the old way back is a
    rename away.
    """
    rows: list[tuple[str, str]] = []
    for label in SUPERSEDED_LABELS:
        path = AGENT_DIR / f"{label}.plist"
        if not path.is_file():
            continue
        unload_label(label)
        backup = path.with_name(f"{path.name}.superseded")
        try:
            path.replace(backup)
        except OSError as exc:
            rows.append((label, f"could not retire: {exc}"))
            continue
        rows.append((label, f"retired → {backup.name}"))
    return rows


def restore_superseded() -> list[tuple[str, str]]:
    """Put the retired jobs back."""
    rows: list[tuple[str, str]] = []
    for label in SUPERSEDED_LABELS:
        backup = AGENT_DIR / f"{label}.plist.superseded"
        if not backup.is_file():
            continue
        path = AGENT_DIR / f"{label}.plist"
        try:
            backup.replace(path)
        except OSError as exc:
            rows.append((label, f"could not restore: {exc}"))
            continue
        _launchctl("bootstrap", domain(), str(path))
        rows.append((label, f"restored · {label}"))
    return rows


def kickstart(service: Service) -> bool:
    """Restart one service."""
    result = _launchctl("kickstart", "-k", f"{domain()}/{service.label}")
    return result.returncode == 0


def is_loaded(label: str) -> bool:
    """Whether launchd knows the job."""
    result = _launchctl("print", f"{domain()}/{label}", timeout=5.0)
    return result.returncode == 0


def service_pid(label: str) -> int:
    """The pid of a running job, or 0."""
    result = _launchctl("print", f"{domain()}/{label}", timeout=5.0)
    if result.returncode != 0:
        return 0
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("pid ="):
            try:
                return int(stripped.split("=", 1)[1].strip())
            except ValueError:
                return 0
    return 0


@dataclass
class ServiceState:
    """What launchd says about one service right now."""

    service: Service
    installed: bool = False
    loaded: bool = False
    pid: int = 0
    serving: bool = False
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.installed and self.loaded and (self.pid > 0 or not self.service.port)

    @property
    def state(self) -> str:
        if not self.installed:
            return "not installed"
        if not self.loaded:
            return "not loaded"
        if self.pid > 0:
            return "running"
        if self.service.port and not self.serving:
            return "stopped"
        return "loaded"


def service_states(
    settings: Settings | None = None,
) -> list[ServiceState]:
    """The state of every service, from launchd and the ports."""
    from .system import port_open

    states: list[ServiceState] = []
    for service in service_definitions(settings):
        serving = bool(service.port and port_open("127.0.0.1", service.port))
        states.append(
            ServiceState(
                service=service,
                installed=service.installed,
                loaded=is_loaded(service.label),
                pid=service_pid(service.label),
                serving=serving,
            )
        )
    return states


def _wait_closed(port: int, timeout: float = 8.0) -> bool:
    """Wait for a port to be free again."""
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                pass
        except OSError:
            return True
        time.sleep(0.3)
    return False


def stop_detached(service: Service) -> bool:
    """Stop a hand-started instance so the launchd service can take the port.

    Without this the new service finds the port busy, exits cleanly, and the
    stack keeps running outside launchd — which is exactly what breaks after a
    reboot.
    """
    from .system import port_open

    if not service.port or not port_open("127.0.0.1", service.port):
        return False
    if service.label == GATEWAY_LABEL:
        # The supervisor script and the LiteLLM process it started.
        subprocess.run(["pkill", "-f", "run_gateway.sh"], capture_output=True, check=False)
        subprocess.run(["pkill", "-f", "litellm --config"], capture_output=True, check=False)
    elif service.label == TIER_LABEL:
        from .tier_gateway import stop

        stop()
    elif service.label == BRIDGE_LABEL:
        from .bridge import stop

        stop()
    elif service.label == WEBCHAT_LABEL:
        from .webchat import stop

        stop()
    return _wait_closed(service.port)


def install_services(settings: Settings | None = None, start: bool = True) -> list[tuple[str, str]]:
    """Write and load every service. Returns (service, result) rows."""
    rows: list[tuple[str, str]] = retire_services()
    for service in service_definitions(settings):
        path = write_plist(service)
        if not start:
            rows.append((service.name, f"written · {path}"))
            continue
        stop_detached(service)
        if load_service(service):
            rows.append((service.name, f"loaded · {service.label}"))
        else:
            rows.append((service.name, f"could not load {service.label}"))
    return rows


def uninstall_services(settings: Settings | None = None) -> list[tuple[str, str]]:
    """Stop every service and remove its plist."""
    rows: list[tuple[str, str]] = retire_services()
    for service in service_definitions(settings):
        unload_service(service)
        if service.plist_path.is_file():
            service.plist_path.unlink()
            rows.append((service.name, f"removed · {service.label}"))
        else:
            rows.append((service.name, f"not installed · {service.label}"))
    return rows


def retire_services() -> list[tuple[str, str]]:
    """Stop and remove the old 24/7 chat and guardian jobs.

    An upgrade that only stops installing them would leave the old plists in
    ``~/Library/LaunchAgents``, so launchd would keep starting them at login.
    """
    rows: list[tuple[str, str]] = []
    for label in RETIRED_LABELS:
        path = AGENT_DIR / f"{label}.plist"
        loaded = is_loaded(label)
        if loaded:
            unload_label(label)
        if path.is_file():
            try:
                path.unlink()
            except OSError as exc:
                rows.append((label, f"could not remove: {exc}"))
                continue
            rows.append((label, "removed · retired"))
        elif loaded:
            rows.append((label, "stopped · retired"))
    return rows


def repair_services(settings: Settings | None = None) -> list[tuple[str, str]]:
    """Rewrite the plists and reload the jobs."""
    rows: list[tuple[str, str]] = []
    for service in service_definitions(settings):
        write_plist(service)
        if load_service(service):
            rows.append((service.name, "reloaded"))
        else:
            rows.append((service.name, "could not reload"))
    return rows


def restart_services(settings: Settings | None = None) -> list[tuple[str, str]]:
    """Restart every service through launchd."""
    rows: list[tuple[str, str]] = []
    for service in service_definitions(settings):
        if not service.installed:
            rows.append((service.name, "not installed"))
            continue
        if kickstart(service):
            rows.append((service.name, "restarted"))
        else:
            rows.append((service.name, "could not restart"))
    return rows


def session_env(settings: Settings | None = None) -> dict[str, str]:
    """The environment the desktop apps need to be local.

    `launchctl setenv` publishes a variable to the whole login session, so any
    app the user opens afterwards inherits it. That is the only way to reach
    an app launched from the Dock, which gets no shell environment.
    """
    settings = settings or Settings.load()
    return {
        "CODEX_APP_SERVER_OPENAI_BASE_URL": f"{settings.router_url.rstrip('/')}/v1",
        "SOVEREIGN_API_KEY": "local",
    }


def set_session_env(settings: Settings | None = None) -> dict[str, str]:
    """Publish the desktop-app environment to the login session."""
    values = session_env(settings)
    for key, value in values.items():
        _launchctl("setenv", key, value)
    return values


def clear_session_env() -> None:
    """Take the local environment back out of the login session."""
    for key in ("CODEX_APP_SERVER_OPENAI_BASE_URL", "SOVEREIGN_API_KEY"):
        _launchctl("unsetenv", key)


def session_env_values() -> dict[str, str]:
    """The environment variables currently published to the session."""
    result = _launchctl("getenv", "CODEX_APP_SERVER_OPENAI_BASE_URL", timeout=5.0)
    values: dict[str, str] = {}
    if result.returncode == 0 and result.stdout.strip():
        values["CODEX_APP_SERVER_OPENAI_BASE_URL"] = result.stdout.strip()
    result = _launchctl("getenv", "SOVEREIGN_API_KEY", timeout=5.0)
    if result.returncode == 0 and result.stdout.strip():
        values["SOVEREIGN_API_KEY"] = result.stdout.strip()
    return values


def _escaped(value: str) -> str:
    return html.escape(value)
