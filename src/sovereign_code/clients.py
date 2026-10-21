"""Local coding clients and their verified capabilities."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import LOCAL_AI_ROOT, PROJECT_ROOT, Settings
from .router import Task, choose
from .system import command_exists

AGENT_MODEL = "qwen2.5-coder:14b"
CODE_MODEL = "qwen2.5-coder:14b"
CLAUDE_ALIAS = "local-claude"
CODEX_ALIAS = "local-code"

# Role alias each client uses through the LiteLLM gateway. The alias is stable;
# the gateway config maps the alias to the best installed model for that role.
CLIENT_ROLE_ALIAS: dict[str, tuple[str, str]] = {
    "codex": ("code", CODEX_ALIAS),
    "chatgpt": ("chat", "local-chat"),
    "claude": ("claude", CLAUDE_ALIAS),
    "qwen": ("agent", "local-agent"),
    "opencode": ("agent", "local-agent"),
}

_ROLE_TASK: dict[str, Task] = {
    "code": Task.CODE,
    "chat": Task.CHAT,
    # Claude Code is chat-only locally (its streamed tool calls are unreliable
    # through LiteLLM + Ollama), so its best model is the 64k chat model behind
    # local-claude, not the agent model.
    "claude": Task.CHAT,
    "agent": Task.AGENT,
}


def resolve_client_models(
    views: dict[str, Any],
    free_gb: float | None = None,
    max_context: int = 32768,
) -> dict[str, tuple[str, str]]:
    """Map each client to (gateway alias, best installed tag) via the router.

    The alias is what the client sends to the gateway; the tag is the concrete
    Ollama model the router picked as best for that role given what is installed.
    """
    resolved: dict[str, tuple[str, str]] = {}
    for client, (role, alias) in CLIENT_ROLE_ALIAS.items():
        selection = choose(_ROLE_TASK[role], views, free_gb, max_context=max_context)
        resolved[client] = (alias, selection.tag or "")
    return resolved


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
model_context_window = 32768
# NOTE: model_max_output_tokens is NOT recognised by codex-cli 0.163 — adding it
# only produces an "unrecognized configuration setting" warning. Codex prints a
# cosmetic "Model metadata for `local-code` not found" line for any custom model
# id; it falls back to the context window above and works correctly.

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


def local_clients(resolved: dict[str, tuple[str, str]] | None = None) -> list[ClientInfo]:
    """What each client is and which model it will actually use.

    `resolved` is the router's answer for the models that are installed. Without
    it the table shows a hard-coded default, which is how the Claude row used
    to advertise `qwen3.5:4b` while the router was picking `qwen3.5:9b`.
    """
    picks = resolved or {}

    def pick(client: str, fallback: str) -> str:
        return picks.get(client, ("", fallback))[1] or fallback

    return [
        ClientInfo(
            key="qwen",
            name="Qwen Code",
            command="qwen",
            capability="agent",
            model=pick("qwen", AGENT_MODEL),
            detail="Writes files and runs commands; the default local coding agent.",
        ),
        ClientInfo(
            key="opencode",
            name="OpenCode",
            command="opencode",
            capability="agent",
            model=f"ollama/{pick('opencode', AGENT_MODEL)}",
            detail="Local agentic coder; fully configured for fast Ollama models.",
        ),
        ClientInfo(
            key="codex",
            name="ChatGPT / Codex",
            command="codex",
            capability="agent",
            model=pick("codex", CODE_MODEL),
            detail="Codex --oss mode: verifies tool calls against Ollama and edits files.",
        ),
        ClientInfo(
            key="claude",
            name="Claude Code",
            command="claude",
            capability="agent",
            model="local-agent (via sovereign bridge)",
            detail="Anthropic bridge turns streamed tool calls into real edits.",
        ),
        ClientInfo(
            key="codium",
            name="VS Codium / Continue",
            command="codium",
            capability="editor",
            model="Continue → local-agent (gateway)",
            detail="Opens the project with the Continue extension and local models.",
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
        # Codex 0.163 removed `wire_api = "chat"` and its Responses translation
        # through LiteLLM streams tool calls as text. Its built-in OSS path
        # speaks to Ollama directly and executes tools correctly.
        argv = [
            "codex",
            "--oss",
            "--local-provider",
            "ollama",
            "-m",
            agent_model,
            "-C",
            str(target),
        ]
        return LaunchPlan(
            argv,
            target,
            env,
            agent_model,
            "Codex OSS mode; edits are real tool calls against Ollama.",
        )

    if client == "claude":
        env.update(
            {
                # The bridge is non-streaming internally; Claude Code still
                # receives a normal Anthropic SSE stream with tool_use blocks.
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:4001",
                "ANTHROPIC_AUTH_TOKEN": "local",
                "ANTHROPIC_API_KEY": "local",
                "ANTHROPIC_MODEL": "local-agent",
                "ANTHROPIC_SMALL_FAST_MODEL": "local-chat",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "local-agent",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "local-agent",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "local-chat",
                "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "32768",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "API_TIMEOUT_MS": "600000",
                "DISABLE_TELEMETRY": "1",
            }
        )
        argv = ["claude", "--model", "local-agent"]
        return LaunchPlan(
            argv,
            target,
            env,
            "local-agent",
            "Claude Code through the sovereign Anthropic bridge.",
        )

    if client == "opencode":
        # OpenCode's interactive command has no --model flag: it takes the
        # model from its own config. `OPENCODE_CONFIG_CONTENT` is OpenCode's
        # inline-config hook, so the model is pinned for this child process
        # only — no user file is rewritten.
        pinned = _pin_opencode_model(env, agent_model)
        argv = ["opencode", str(target)]
        if pinned:
            note = "OpenCode local coding agent (model pinned for this session)"
        else:
            note = (
                "OpenCode local coding agent; it uses the model from your OpenCode "
                f"config because '{agent_model}' is not in that config's model list"
            )
        return LaunchPlan(argv, target, env, f"local/{agent_model}", note)

    if client == "codium":
        return LaunchPlan(
            ["codium", str(target)],
            target,
            env,
            "Continue → local-agent",
            "VS Codium with Continue; model routing is in ~/.continue/config.yaml.",
        )

    raise ValueError(f"unsupported client: {client}")


def _pin_opencode_model(env: dict[str, str], agent_model: str) -> bool:
    """Pin OpenCode's model for this session. Returns False when it cannot.

    The user's OpenCode config may list its models explicitly. Pinning a model
    that is not in that list would make OpenCode fail to start, so in that case
    the launch is left alone and the caller says so.
    """
    from .tools import opencode_models, read_text

    config = Path.home() / ".config" / "opencode" / "opencode.json"
    available = opencode_models(read_text(config))
    if available and agent_model not in available:
        return False
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"model": f"local/{agent_model}"})
    return True


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
    for client in ("qwen", "codex", "claude", "opencode"):
        path = wrapper_path(client)
        path.write_text(
            f'#!/bin/bash\nset -euo pipefail\nexec "{launcher}" launch {client} "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
        link = link_dir / path.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(path)
        written.append(path)

    # Cloud-native wrappers: no gateway, no override, no fake key, so they use
    # the real subscription login. `codex-local`/`claude-local` stay local.
    claude_cloud = bin_dir / "claude-cloud"
    claude_cloud.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        "# Uses your Claude subscription login (no local gateway overrides).\n"
        'exec claude "$@"\n',
        encoding="utf-8",
    )
    claude_cloud.chmod(0o755)
    claude_link = link_dir / claude_cloud.name
    if claude_link.is_symlink() or claude_link.exists():
        claude_link.unlink()
    claude_link.symlink_to(claude_cloud)
    written.append(claude_cloud)

    cloud = bin_dir / "codex-chatgpt"
    cloud.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        "# Uses ~/.codex and your ChatGPT subscription login (no local overrides).\n"
        'exec codex "$@"\n',
        encoding="utf-8",
    )
    cloud.chmod(0o755)
    cloud_link = link_dir / cloud.name
    if cloud_link.is_symlink() or cloud_link.exists():
        cloud_link.unlink()
    cloud_link.symlink_to(cloud)
    written.append(cloud)
    return written
