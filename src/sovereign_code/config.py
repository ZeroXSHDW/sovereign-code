"""Configuration and filesystem layout for Sovereign Code."""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

APP_NAME = "sovereign-code"
DEFAULT_OLLAMA = "127.0.0.1:11434"
DEFAULT_GATEWAY = "http://127.0.0.1:4000"
# The latency-aware tier gateway in front of LiteLLM. Clients that ask for
# "auto" hit this; explicit aliases still work through it too.
DEFAULT_ROUTER = "http://127.0.0.1:4010"
# The Anthropic Messages bridge that Claude Code talks to. It sits beside the
# tier gateway and speaks the Anthropic protocol.
DEFAULT_BRIDGE_PORT = 4001


def _home() -> Path:
    return Path.home()


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def find_project_root() -> Path:
    """Locate the checkout (works for editable installs and source runs)."""
    env = os.environ.get("SOVEREIGN_PROJECT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] if len(here.parents) > 2 else here.parent,
        Path.cwd(),
        _home() / "Documents" / APP_NAME,
    ]
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "sovereign_code"
        ).is_dir():
            return candidate
    return _home() / "Documents" / APP_NAME


PROJECT_ROOT = find_project_root()
# The checkout owns its runtime by default: one folder contains the code, the
# gateway, the model catalog, sessions and logs. An older install under
# ~/Documents/local-ai is still honoured until `sovereign setup` moves it in,
# so upgrading does not strand a working stack (or 90 GB of model weights).
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
LEGACY_LOCAL_AI_ROOT = _home() / "Documents" / "local-ai"


def _runtime_root() -> Path:
    value = os.environ.get("SOVEREIGN_HOME")
    if value:
        return Path(value).expanduser()
    if RUNTIME_ROOT.is_dir():
        return RUNTIME_ROOT
    if LEGACY_LOCAL_AI_ROOT.is_dir():
        return LEGACY_LOCAL_AI_ROOT
    return RUNTIME_ROOT


LOCAL_AI_ROOT = _runtime_root()
CONFIG_DIR = _env_path("SOVEREIGN_CONFIG_DIR", LOCAL_AI_ROOT / "config" / "sovereign")
DATA_DIR = _env_path("SOVEREIGN_DATA_DIR", LOCAL_AI_ROOT / "data")
SESSIONS_DIR = DATA_DIR / "sessions"
LOG_DIR = DATA_DIR / "logs"


@dataclass
class Settings:
    ollama_host: str = DEFAULT_OLLAMA
    gateway_url: str = DEFAULT_GATEWAY
    router_url: str = DEFAULT_ROUTER
    default_model: str | None = None
    default_task: str = "code"
    max_context: int = 32768
    temperature: float = 0.25
    theme: str = "sovereign"
    login_enabled: bool = True
    # True keeps every gateway request on this Mac; `sovereign mode unrestricted`
    # sets it to False so provider routes can be used. The environment variable
    # SOVEREIGN_LOCAL_ONLY, when set, still overrides this value.
    local_only: bool = True
    workspace: str = "~/Documents"
    # 0 disables automatic pruning; the dashboard prunes at startup otherwise.
    session_retention_days: float = 0.0
    session_keep: int = 50
    # How often the live monitor refreshes its report.
    monitor_refresh_seconds: float = 5.0

    def __post_init__(self) -> None:
        # Not a dataclass field: it must never be written to the TOML file.
        self.parse_error: str = ""

    @property
    def ollama_url(self) -> str:
        host = self.ollama_host.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        return host

    @property
    def bridge_url(self) -> str:
        """The Anthropic bridge that Claude Code talks to.

        The bridge always runs next to the tier gateway, so it inherits the
        gateway's host and uses its own port.
        """
        host = urlsplit(self.router_url).hostname or "127.0.0.1"
        return f"http://{host}:{DEFAULT_BRIDGE_PORT}"

    @property
    def config_path(self) -> Path:
        return CONFIG_DIR / "config.toml"

    @classmethod
    def load(cls) -> Settings:
        settings = cls()
        overrides = {
            "ollama_host": os.environ.get("SOVEREIGN_OLLAMA_HOST"),
            "gateway_url": os.environ.get("SOVEREIGN_GATEWAY_URL"),
            "router_url": os.environ.get("SOVEREIGN_ROUTER_URL"),
            "default_model": os.environ.get("SOVEREIGN_MODEL"),
        }
        path = CONFIG_DIR / "config.toml"
        if path.is_file():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                data = {}
                settings.parse_error = f"config could not be read: {exc}"
            except tomllib.TOMLDecodeError as exc:
                data = {}
                settings.parse_error = f"config is not valid TOML: {exc}"
            for key in asdict(settings):
                if key in data and data[key] is not None:
                    setattr(settings, key, data[key])
        for key, value in overrides.items():
            if value:
                setattr(settings, key, value)
        if not settings.default_model:
            settings.default_model = None
        settings._coerce()
        return settings

    def _coerce(self) -> None:
        """Bring every field to its declared type, ignoring bad values.

        A hand-edited config with `max_context = "abc"` used to raise a
        ValueError out of `load()` and kill every command in the CLI.
        """
        self.ollama_host = str(self.ollama_host)
        self.gateway_url = str(self.gateway_url)
        self.router_url = str(self.router_url)
        self.default_model = str(self.default_model) if self.default_model else None
        self.theme = str(self.theme)
        self.workspace = str(self.workspace)
        self.login_enabled = _as_bool(self.login_enabled)
        self.local_only = _as_bool(self.local_only)
        self.max_context = max(2048, _as_int(self.max_context, 32768))
        self.temperature = min(2.0, max(0.0, _as_float(self.temperature, 0.25)))
        self.session_retention_days = max(0.0, _as_float(self.session_retention_days, 0.0))
        self.session_keep = max(0, _as_int(self.session_keep, 50))
        self.monitor_refresh_seconds = min(
            60.0, max(1.0, _as_float(self.monitor_refresh_seconds, 5.0))
        )
        self.default_task = _as_task(self.default_task)

    def save(self) -> Path:
        ensure_layout()
        lines = [
            "# Sovereign Code configuration",
            f"ollama_host = {_toml_value(self.ollama_host)}",
            f"gateway_url = {_toml_value(self.gateway_url)}",
            f"router_url = {_toml_value(self.router_url)}",
            f"default_model = {_toml_value(self.default_model)}",
            f"default_task = {_toml_value(self.default_task)}",
            f"max_context = {int(self.max_context)}",
            f"temperature = {float(self.temperature)}",
            f"theme = {_toml_value(self.theme)}",
            f"login_enabled = {str(self.login_enabled).lower()}",
            f"local_only = {str(self.local_only).lower()}",
            f"workspace = {_toml_value(self.workspace)}",
            f"session_retention_days = {float(self.session_retention_days)}",
            f"session_keep = {int(self.session_keep)}",
            f"monitor_refresh_seconds = {float(self.monitor_refresh_seconds)}",
            "",
        ]
        self.config_path.write_text("\n".join(lines), encoding="utf-8")
        return self.config_path


def _as_int(value: object, fallback: int) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


def _as_float(value: object, fallback: float) -> float:
    try:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_task(value: object) -> str:
    """Keep `default_task` a task the router actually knows."""
    from .router import Task

    name = str(value).strip().lower()
    return name if name in {task.value for task in Task} else "code"


def _toml_value(value: str | None) -> str:
    """Render a string as a TOML basic string.

    Every string field goes through here. Interpolating a raw value between
    quotes produced malformed TOML for any value containing a quote or a
    backslash, and the next load then silently fell back to the defaults.
    """
    if value is None:
        return '""'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + escaped + '"'


def ensure_layout() -> None:
    for directory in (
        CONFIG_DIR,
        DATA_DIR,
        SESSIONS_DIR,
        LOG_DIR,
        DATA_DIR / "runs",
        LOCAL_AI_ROOT / "gateway",
        LOCAL_AI_ROOT / "bin",
        LOCAL_AI_ROOT / "models",
        LOCAL_AI_ROOT / "config" / "skills",
    ):
        directory.mkdir(parents=True, exist_ok=True)


def write_default_config(force: bool = False) -> Path:
    ensure_layout()
    path = CONFIG_DIR / "config.toml"
    if force or not path.is_file():
        return Settings().save()
    return path


def launch_agent_path(label: str = "com.user.sovereign-code") -> Path:
    return _home() / "Library" / "LaunchAgents" / f"{label}.plist"


def dashboard_command_path() -> Path:
    return PROJECT_ROOT / "bin" / "sovereign-dashboard.command"
