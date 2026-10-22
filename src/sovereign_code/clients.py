"""Local coding clients and their verified capabilities."""

from __future__ import annotations

import json
import os
import subprocess
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
    # Claude Code's launch plan follows the quality route (`best`); the bridge
    # executes its tool calls. The status fallback keeps the long-context
    # `local-claude` alias so a picker slot never inherits a 32k cap.
    "claude": Task.CHAT,
    "agent": Task.AGENT,
}

# Codex streams a ~12.7k-token prompt (system + tool schemas) and needs a real
# 32k window, so the router's 27B is the wrong pick for it: that model cannot
# allocate 32k on 24 GB and the MLX runner dies with a Metal OOM. Codex gets the
# strongest installed model that actually fits the window.
CODEX_PREFERENCE: tuple[str, ...] = (
    "qwen3-coder:30b",
    "qwen3.5:9b",
    "qwen2.5-coder:14b",
)


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
        tag = selection.tag or ""
        if client == "codex":
            # Codex needs the 32k window more than it needs the best reasoner.
            tag = codex_model_tag(views) or tag
        resolved[client] = (alias, tag)
    return resolved


def codex_model_tag(views: dict[str, Any]) -> str:
    """The strongest installed model that can hold Codex's ~32k working window.

    Empty when none of the preferences are installed, so callers can fall back
    to whatever the router picked.
    """
    for candidate in CODEX_PREFERENCE:
        view = views.get(candidate)
        if view is not None and view.installed:
            return candidate
    return ""


def qwen_home_path() -> Path:
    return LOCAL_AI_ROOT / "qwen"


def codex_home_path() -> Path:
    return LOCAL_AI_ROOT / "config" / "codex"


def chatgpt_login_status() -> str:
    """Whether Codex has a real ChatGPT session: 'logged-in', 'logged-out', 'missing'.

    Cloud mode uses the account's own OAuth session in the default CODEX_HOME, so
    the first thing to check is whether `codex login` was ever completed.
    """
    try:
        result = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "missing"
    output = f"{result.stdout}{result.stderr}".lower()
    if "not logged in" in output:
        return "logged-out"
    return "logged-in" if result.returncode == 0 else "logged-out"


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
# Talks to the tier gateway on 4010. `best` uses the 30B coder for code and
# GLM for reasoning; `ultra` keeps the 27B. `wire_api = "responses"` is required
# by Codex 0.163. The token comes from a command, so the profile needs no
# environment variable: a missing `env_key` would put the sign-in gate back.
model = "best"
model_provider = "sovereign-tier"
model_context_window = 32768
model_catalog_json = "__CATALOG__"

[model_providers.sovereign-tier]
name = "Sovereign tier gateway"
base_url = "http://127.0.0.1:4010/v1"
wire_api = "responses"
supports_websockets = false

[model_providers.sovereign-tier.auth]
command = "/bin/echo"
args = ["local"]
"""

# The local routes, and the context window each one can hold.
CODEX_CATALOG_ROUTES: tuple[tuple[str, str, int], ...] = (
    ("best", "Best — 30B code / GLM reasoning", 32768),
    ("auto", "Auto — fast for simple, deep for hard", 32768),
    ("deep", "Deep — 30B coder", 32768),
    ("balanced", "Balanced — 9B, 65k", 65536),
    ("ultra", "Ultra — 27B reasoning", 16384),
    ("fast", "Fast — 4B", 8192),
)

# A short instruction set for the case where Codex has no cached prompt of its
# own to copy. The full template is much better, so it is preferred.
FALLBACK_INSTRUCTIONS = """\
You are Codex, a local coding agent. You and the user share one workspace, and
your job is to carry the request through until it is genuinely handled.

Work in the workspace, make the change, and verify it with the project's own
tests. Keep the diff minimal and reviewable. Use the tools you have: read a
file before you edit it, run the tests after you change something, and say
plainly what you did and what is left.
"""

CODEX_CACHE = Path.home() / ".codex" / "models_cache.json"


def codex_catalog_path() -> Path:
    return codex_home_path() / "model-catalog.json"


def _cached_instructions() -> dict | None:
    """The prompt template Codex already uses, from its own cache.

    Codex refuses a model catalog entry without instructions, and the ones it
    ships with are tuned for a model that is far stronger than a local one.
    """
    try:
        data = json.loads(CODEX_CACHE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    for model in data.get("models") or []:
        messages = model.get("model_messages")
        if isinstance(messages, dict) and messages.get("instructions_template"):
            return messages
    return None


def codex_model_catalog() -> dict:
    """A model catalog Codex can read, describing the local routes.

    Without one, Codex falls back to metadata for a model it has never heard
    of: the wrong context window, and a warning on every turn.
    """
    messages = _cached_instructions() or {"instructions_template": FALLBACK_INSTRUCTIONS}
    models = []
    for priority, (slug, name, context) in enumerate(CODEX_CATALOG_ROUTES, start=1):
        models.append(
            {
                "slug": slug,
                "display_name": name,
                "description": f"Sovereign local route: {slug}.",
                "default_reasoning_level": "medium",
                "supported_reasoning_levels": [
                    {"effort": "medium", "description": "The local model decides."}
                ],
                "shell_type": "unified_exec",
                "visibility": "list",
                "supported_in_api": True,
                "priority": priority,
                "additional_speed_tiers": [],
                "service_tiers": [],
                "available_access_programs": {"cyber": ["standard"]},
                "availability_nux": None,
                "upgrade": None,
                "context_window": context,
                "max_context_window": context,
                "effective_context_window_percent": 100,
                "truncation_policy": {"mode": "tokens", "limit": 10000},
                "input_modalities": ["text"],
                "supports_image_detail_original": False,
                "apply_patch_tool_type": "freeform",
                "web_search_tool_type": "text",
                "use_responses_lite": False,
                "supports_reasoning_effort_updates": False,
                "supports_experimental_context": False,
                "supports_search_tool": False,
                "include_skills_usage_instructions": False,
                "include_plugin_usage_instructions": True,
                "include_apps_usage_instructions": False,
                "default_reasoning_summary": "none",
                "support_verbosity": True,
                "default_verbosity": "low",
                "experimental_supported_tools": [],
                "node_repl_auto_review_required": False,
                "node_repl_disabled": True,
                "tool_mode": "code_mode_only",
                "multi_agent_version": "v2",
                "model_messages": messages,
            }
        )
    return {"models": models}


def write_codex_catalog() -> Path:
    """Write the model catalog Codex reads and return its path."""
    path = codex_catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(codex_model_catalog(), indent=1) + "\n", encoding="utf-8")
    return path


def write_codex_profile() -> Path:
    path = codex_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog = write_codex_catalog()
    text = CODEX_PROFILE.replace("__CATALOG__", str(catalog))
    path.write_text(text, encoding="utf-8")
    # `codex -C` (without --profile) loads this file from CODEX_HOME.
    home = codex_home_path() / "config.toml"
    home.write_text(text, encoding="utf-8")
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
            model=f"auto (router pick {pick('qwen', AGENT_MODEL)})",
            detail="Tier gateway: fast for small work, deep for hard work.",
        ),
        ClientInfo(
            key="opencode",
            name="OpenCode",
            command="opencode",
            capability="agent",
            model=f"sovereign/auto (router pick {pick('opencode', AGENT_MODEL)})",
            detail="Tier gateway with correct streaming tool calls and MCP.",
        ),
        ClientInfo(
            key="codex",
            name="ChatGPT / Codex",
            command="codex",
            capability="agent",
            model=f"auto (router pick {pick('codex', CODE_MODEL)})",
            detail="Tier gateway Responses API; --cloud uses the ChatGPT subscription.",
        ),
        ClientInfo(
            key="claude",
            name="Claude Code",
            command="claude",
            capability="agent",
            model="best (quality) · picker: sonnet→deep, opus→ultra, haiku→fast",
            detail="Anthropic bridge turns streamed tool calls into real edits.",
        ),
        ClientInfo(
            key="chatgpt",
            name="ChatGPT desktop",
            command="open",
            capability="MCP",
            model=f"tier gateway (auto) + local MCP (router pick {pick('chatgpt', 'qwen3.5:9b')})",
            detail="Forced local by sovereign chatgpt --local: no OpenAI sign-in.",
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
    cloud: bool = False,
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

    if client == "codex" and cloud:
        # Real ChatGPT. Uses the default CODEX_HOME so Codex picks up the
        # account's OAuth session, and passes no --model so its own model list
        # wins. Nothing here touches Ollama or the local gateway.
        argv = ["codex", "-C", str(target)]
        return LaunchPlan(
            argv,
            target,
            env,
            "ChatGPT (cloud)",
            "Cloud mode: prompts, code and diffs leave this Mac.",
        )

    if client == "codex":
        if cloud:
            # Native ChatGPT subscription login; no CODEX_HOME override and no
            # local provider. This is the real cloud Codex, not a local alias.
            return LaunchPlan(
                ["codex", "-C", str(target)],
                target,
                env,
                "ChatGPT (cloud)",
                "Codex with the ChatGPT subscription login; local MCP tools remain available.",
            )
        if not (codex_home_path() / "config.toml").is_file():
            raise ValueError("missing local Codex config; run sovereign install-clients")
        env["SOVEREIGN_API_KEY"] = "local"
        env["CODEX_HOME"] = str(codex_home_path())
        argv = ["codex"]
        if agent_model and agent_model != "auto":
            argv += ["-m", agent_model]
        argv += ["-C", str(target)]
        if yolo:
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        return LaunchPlan(
            argv,
            target,
            env,
            agent_model,
            "Codex through the tier gateway: fast for simple turns, deep for hard ones.",
        )

    if client == "claude":
        if cloud:
            return LaunchPlan(
                ["claude"],
                target,
                env,
                "Claude (cloud)",
                "Claude Code with the Claude subscription login; no local bridge overrides.",
            )
        if agent_model == "auto":
            # The same slot mapping the settings file uses, so Claude Code's
            # own picker offers the local models: Sonnet on the 30B coder,
            # Opus on the 27B, Haiku on the 4B. The default turn follows the
            # quality route, and a prompt that does not fit the model is
            # answered by the 64k 9B instead of being rejected.
            from .tier_gateway import CLAUDE_SLOT_MODELS

            env.update(
                {
                    # The bridge streams text deltas and returns tool_use blocks
                    # as complete Anthropic content blocks.
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4001",
                    "ANTHROPIC_AUTH_TOKEN": "local",
                    "ANTHROPIC_API_KEY": "local",
                    "ANTHROPIC_MODEL": "best",
                    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "65536",
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8192",
                    "CLAUDE_CODE_ALLOW_OTHER_MODELS": "1",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                    "DISABLE_AUTO_COMPACT": "1",
                    "API_TIMEOUT_MS": "900000",
                    "DISABLE_TELEMETRY": "1",
                }
            )
            for slot, (model_id, _route) in CLAUDE_SLOT_MODELS.items():
                env[slot] = model_id
            return LaunchPlan(
                ["claude"],
                target,
                env,
                "best",
                "Claude Code through the sovereign Anthropic bridge, with the local "
                "model picker (Sonnet, Opus and Haiku map to local models).",
            )
        # An explicit gateway alias (local-glm, cloud-kimi-k3, …) is honored;
        # a raw Ollama tag is not, because Claude needs the 64k local model.
        claude_model = (
            agent_model
            if agent_model.startswith("local-") or agent_model.startswith("cloud-")
            else "local-claude"
        )
        env.update(
            {
                # The bridge streams text deltas and returns tool_use blocks as
                # complete Anthropic content blocks.
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:4001",
                "ANTHROPIC_AUTH_TOKEN": "local",
                "ANTHROPIC_API_KEY": "local",
                # Claude Code's own prompt is ~34k tokens, so a 32k coder is
                # rejected before the first turn. `local-claude` is 64k and
                # tool-capable; the bridge handles its tool calls.
                "ANTHROPIC_MODEL": claude_model,
                # One resident model only on 24 GB: pointing the small/fast
                # slot at another alias makes Claude swap models mid-task.
                "ANTHROPIC_SMALL_FAST_MODEL": claude_model,
                "ANTHROPIC_DEFAULT_SONNET_MODEL": claude_model,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": claude_model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": claude_model,
                "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "65536",
                "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8192",
                "CLAUDE_CODE_ALLOW_OTHER_MODELS": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                "DISABLE_AUTO_COMPACT": "1",
                "API_TIMEOUT_MS": "900000",
                "DISABLE_TELEMETRY": "1",
            }
        )
        argv = ["claude", "--model", claude_model]
        if yolo:
            argv.append("--dangerously-skip-permissions")
        return LaunchPlan(
            argv,
            target,
            env,
            claude_model,
            "Claude Code through the sovereign Anthropic bridge.",
        )

    if client == "opencode":
        # OpenCode's interactive command has no --model flag: it takes the
        # model from its own config. `OPENCODE_CONFIG_CONTENT` is OpenCode's
        # inline-config hook, so the model is pinned for this child process
        # only — no user file is rewritten.
        pinned = _pin_opencode_model(env, agent_model)
        argv = ["opencode"]
        if yolo:
            argv.append("--auto")
        argv.append(str(target))
        if pinned:
            note = "OpenCode local coding agent (model pinned for this session)"
        else:
            note = (
                "OpenCode local coding agent; it uses the model from your OpenCode "
                f"config because '{agent_model}' is not in that config's model list"
            )
        label = f"sovereign/{agent_model}" if agent_model == "auto" else f"local/{agent_model}"
        return LaunchPlan(argv, target, env, label, note)

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

    if agent_model == "auto":
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"model": "sovereign/auto"})
        return True
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
    for client in ("qwen", "codex", "claude", "opencode", "codium"):
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
        "# Uses your Claude subscription login. The local ~/.claude/settings.json\n"
        "# is moved aside for the run and restored on exit.\n"
        'settings="$HOME/.claude/settings.json"\n'
        'backup="$HOME/.claude/settings.json.sovereign-cloud"\n'
        'restore() { if [ -f "$backup" ]; then mv -f "$backup" "$settings"; fi; }\n'
        "trap restore EXIT\n"
        'if [ -f "$settings" ]; then mv -f "$settings" "$backup"; fi\n'
        'claude "$@"\n',
        encoding="utf-8",
    )
    claude_cloud.chmod(0o755)
    claude_link = link_dir / claude_cloud.name
    if claude_link.is_symlink() or claude_link.exists():
        claude_link.unlink()
    claude_link.symlink_to(claude_cloud)
    written.append(claude_cloud)

    # The ChatGPT app's config is forced local, so the cloud wrappers put the
    # saved cloud config in place for the run and put the local one back.
    cloud_script = (
        "#!/bin/bash\nset -euo pipefail\n"
        "# Uses your ChatGPT subscription login. The saved cloud config is put in\n"
        "# place for the run and the local one is restored on exit.\n"
        'config="$HOME/.codex/config.toml"\n'
        'cloud="$HOME/.codex/config.toml.sovereign-cloud"\n'
        'local_copy="$HOME/.codex/config.toml.sovereign-local"\n'
        'restore() { if [ -f "$local_copy" ]; then mv -f "$local_copy" "$config"; fi; }\n'
        "trap restore EXIT\n"
        'if [ -f "$cloud" ]; then\n'
        '  if [ -f "$config" ]; then mv -f "$config" "$local_copy"; fi\n'
        '  cp -f "$cloud" "$config"\n'
        "fi\n"
        'codex "$@"\n'
    )
    for name in ("codex-chatgpt", "chatgpt-cloud"):
        path = bin_dir / name
        path.write_text(cloud_script, encoding="utf-8")
        path.chmod(0o755)
        link = link_dir / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(path)
        written.append(path)

    local_chatgpt = bin_dir / "chatgpt-local"
    local_chatgpt.write_text(
        f'#!/bin/bash\nset -euo pipefail\nexec "{launcher}" launch codex "$@"\n',
        encoding="utf-8",
    )
    local_chatgpt.chmod(0o755)
    local_link = link_dir / local_chatgpt.name
    if local_link.is_symlink() or local_link.exists():
        local_link.unlink()
    local_link.symlink_to(local_chatgpt)
    written.append(local_chatgpt)
    return written
