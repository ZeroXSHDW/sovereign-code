"""Configuration and filesystem layout for Sovereign Code."""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "sovereign-code"
DEFAULT_OLLAMA = "127.0.0.1:11434"
DEFAULT_GATEWAY = "http://127.0.0.1:4000"


def _home() -> Path:
    return Path.home()


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


CONFIG_DIR = _env_path(
    "SOVEREIGN_CONFIG_DIR", _home() / "Documents" / "local-ai" / "config" / "sovereign"
)
DATA_DIR = _env_path("SOVEREIGN_DATA_DIR", _home() / "Documents" / "local-ai" / "data")
SESSIONS_DIR = DATA_DIR / "sessions"
LOG_DIR = DATA_DIR / "logs"


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
LOCAL_AI_ROOT = Path.home() / "Documents" / "local-ai"


@dataclass
class Settings:
    ollama_host: str = DEFAULT_OLLAMA
    gateway_url: str = DEFAULT_GATEWAY
    default_model: str | None = None
    default_task: str = "code"
    max_context: int = 32768
    temperature: float = 0.25
    theme: str = "sovereign"
    login_enabled: bool = True
    workspace: str = "~/Documents"
    # 0 disables automatic pruning; the dashboard prunes at startup otherwise.
    session_retention_days: float = 0.0
    session_keep: int = 50

    @property
    def ollama_url(self) -> str:
        host = self.ollama_host.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        return host

    @property
    def config_path(self) -> Path:
        return CONFIG_DIR / "config.toml"

    @classmethod
    def load(cls) -> Settings:
        settings = cls()
        overrides = {
            "ollama_host": os.environ.get("SOVEREIGN_OLLAMA_HOST"),
            "gateway_url": os.environ.get("SOVEREIGN_GATEWAY_URL"),
            "default_model": os.environ.get("SOVEREIGN_MODEL"),
        }
        path = CONFIG_DIR / "config.toml"
        if path.is_file():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
            for key in asdict(settings):
                if key in data and data[key] is not None:
                    setattr(settings, key, data[key])
        for key, value in overrides.items():
            if value:
                setattr(settings, key, value)
        if not settings.default_model:
            settings.default_model = None
        settings.max_context = max(2048, int(settings.max_context))
        settings.temperature = min(2.0, max(0.0, float(settings.temperature)))
        settings.session_retention_days = max(0.0, float(settings.session_retention_days))
        settings.session_keep = max(0, int(settings.session_keep))
        return settings

    def save(self) -> Path:
        ensure_layout()
        lines = [
            "# Sovereign Code configuration",
            f'ollama_host = "{self.ollama_host}"',
            f'gateway_url = "{self.gateway_url}"',
            f"default_model = {_toml_value(self.default_model)}",
            f'default_task = "{self.default_task}"',
            f"max_context = {int(self.max_context)}",
            f"temperature = {float(self.temperature)}",
            f'theme = "{self.theme}"',
            f"login_enabled = {str(self.login_enabled).lower()}",
            f'workspace = "{self.workspace}"',
            f"session_retention_days = {float(self.session_retention_days)}",
            f"session_keep = {int(self.session_keep)}",
            "",
        ]
        self.config_path.write_text("\n".join(lines), encoding="utf-8")
        return self.config_path


def _toml_value(value: str | None) -> str:
    if value is None:
        return '""'
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def ensure_layout() -> None:
    for directory in (CONFIG_DIR, DATA_DIR, SESSIONS_DIR, LOG_DIR):
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
