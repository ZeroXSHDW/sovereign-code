"""Local coding clients and their verified capabilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import LOCAL_AI_ROOT, PROJECT_ROOT, Settings
from .system import command_exists

AGENT_MODEL = "gemma4:12b"
CODE_MODEL = "qwen2.5-coder:14b"
CLAUDE_ALIAS = "local-claude"
CODEX_ALIAS = "local-code"


def qwen_home_path() -> Path:
    return LOCAL_AI_ROOT / "qwen"


def codex_home_path() -> Path:
    return LOCAL_AI_ROOT / "config" / "codex"


@dataclass(frozen=True)
class ClientInfo:
    key: str
    name: str
    command: str
    capability: str
    model: str
    detail: str

    @property
    def installed(self) -> bool:
        return command_exists(self.command)


@dataclass(frozen=True)
class LaunchPlan:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    model: str
    note: str = ""


def codex_profile_path() -> Path:
    return codex_home_path() / "local.config.toml"


CODEX_PROFILE = """\
# Sovereign Code local profile. Launch with: codex --profile local
# Uses the loopback LiteLLM gateway and never calls a cloud endpoint.
# Lives in ~/Documents/local-ai/config/codex (CODEX_HOME for local launches).
model = "local-code"
model_provider = "sovereign-local"
model_context_window = 20480

[model_providers.sovereign-local]
name = "Sovereign local gateway"
base_url = "http://127.0.0.1:4000/v1"
env_key = "SOVEREIGN_API_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
"""


def write_codex_profile() -> Path:
    path = codex_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CODEX_PROFILE, encoding="utf-8")
    return path


def local_clients() -> list[ClientInfo]:
    return [
        ClientInfo(
            key="qwen",
            name="Qwen Code",
            command="qwen",
            capability="agent",
            model=AGENT_MODEL,
            detail="Writes files and runs commands; the default local coding agent.",
        ),
        ClientInfo(
            key="opencode",
            name="OpenCode",
            command="opencode",
            capability="agent",
            model=f"ollama/{AGENT_MODEL}",
            detail="Choose the Ollama model in the TUI, or run with -m ollama/gemma4:12b.",
        ),
        ClientInfo(
            key="codex",
            name="ChatGPT / Codex",
            command="codex",
            capability="chat",
            model=f"{CODEX_ALIAS} ({CODE_MODEL} via gateway)",
            detail="Local profile is ready; use Qwen Code for reliable local edits.",
        ),
        ClientInfo(
            key="claude",
            name="Claude Code",
            command="claude",
            capability="chat",
            model=f"{CLAUDE_ALIAS} (qwen3.5:4b via gateway)",
            detail="Launcher points it at loopback; use Qwen Code for local edits.",
        ),
    ]


def plan_launch(
    client: str,
    target: Path,
    settings: Settings,
    agent_model: str = AGENT_MODEL,
    yolo: bool = False,
) -> LaunchPlan:
    """Build an exec plan without mutating the environment or current process."""
    target = target.expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"not a directory: {target}")
    env = os.environ.copy()

    if client == "qwen":
        env["QWEN_HOME"] = str(qwen_home_path())
        argv = [
            "qwen",
            "--model",
            agent_model,
            "--approval-mode",
            "yolo" if yolo else "default",
        ]
        return LaunchPlan(argv, target, env, agent_model)

    if client == "codex":
        if not codex_profile_path().is_file():
            raise ValueError(
                f"missing {codex_profile_path()}; run sovereign install-clients"
            )
        env["SOVEREIGN_API_KEY"] = "local"
        env["CODEX_HOME"] = str(codex_home_path())
        argv = ["codex", "--profile", "local", "-C", str(target)]
        return LaunchPlan(
            argv,
            target,
            env,
            CODEX_ALIAS,
            "Codex local chat; use Qwen Code for reliable local file edits.",
        )

    if client == "claude":
        env.update(
            {
                "ANTHROPIC_BASE_URL": settings.gateway_url,
                "ANTHROPIC_AUTH_TOKEN": "local",
                "ANTHROPIC_API_KEY": "local",
                "ANTHROPIC_MODEL": CLAUDE_ALIAS,
                "ANTHROPIC_SMALL_FAST_MODEL": "local-chat",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": CLAUDE_ALIAS,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": CLAUDE_ALIAS,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "local-chat",
                "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "65536",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_TELEMETRY": "1",
            }
        )
        argv = ["claude", "--model", CLAUDE_ALIAS]
        return LaunchPlan(
            argv,
            target,
            env,
            CLAUDE_ALIAS,
            "Claude local chat; use Qwen Code for reliable local file edits.",
        )

    raise ValueError(f"unsupported client: {client}")


def wrapper_path(client: str) -> Path:
    return LOCAL_AI_ROOT / "bin" / f"{client}-local"


def install_client_wrappers() -> list[Path]:
    """Install wrappers under Documents, symlinked into ~/.local/bin for PATH."""
    bin_dir = LOCAL_AI_ROOT / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    link_dir = Path.home() / ".local" / "bin"
    link_dir.mkdir(parents=True, exist_ok=True)
    launcher = PROJECT_ROOT / "bin" / "sovereign"
    written: list[Path] = []
    for client in ("qwen", "codex", "claude"):
        path = wrapper_path(client)
        path.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            f'exec "{launcher}" launch {client} "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
        link = link_dir / path.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(path)
        written.append(path)
    return written
