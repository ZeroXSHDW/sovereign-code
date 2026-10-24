"""Write the per-client configuration that makes every tool use the same stack.

The goal is one setup command, no hand-editing: Codex and OpenCode get working
providers and an MCP server; Claude Code gets the Anthropic bridge and MCP;
Claude Desktop gets MCP; Qwen gets MCP; Continue gets a config with the same
models and the curated prompt skills.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import LOCAL_AI_ROOT, Settings
from .safefile import write_private
from .tier_gateway import CLAUDE_MODEL_ROUTES, CLAUDE_SLOT_MODELS

# A client config is kept beside the live one so `--cloud` can hand it back
# exactly what it had before, instead of guessing at a default.
CLOUD_BACKUP_SUFFIX = ".sovereign-cloud"

# Ollama tags this release retired. Every client-config writer drops them so a
# fresh install cannot keep pointing at a model no alias references any more.
# One set, three call sites: keep them in step when the next model is retired.
RETIRED_MODELS = frozenset({"deepseek-r1:8b", "qwen2.5-coder:7b"})


def client_cli_version(name: str) -> str:
    """The first line of a client CLI's ``--version`` output, or ''.

    The subcommands this module shells out to (``codex plugin``,
    ``claude mcp``, ``qwen mcp``/``extensions``) are not stable across
    major releases, so a client that reports a version we have not exercised
    is surfaced instead of silently misfiring. Returns the empty string when
    the CLI is missing or versioning fails, so '' always means "unknown".
    """
    command = shutil.which(name)
    if not command:
        return ""
    try:
        result = subprocess.run(
            [command, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0] if output else ""


def released_version(line: str) -> str:
    """The x.y[.z] inside a `--version` line ("codex-cli 0.164.0" -> "0.164.0")."""
    match = re.search(r"\d+\.\d+(?:\.\d+)?", line)
    return match.group(0) if match else ""


# The client major versions this module's subcommands were written against.
# A CI release job updates these when it verifies a new client major; the
# guard below only warns, it never blocks, so an unknown version still works.
SUPPORTED_CLIENT_VERSIONS: dict[str, tuple[str, ...]] = {
    "codex": ("0.163", "0.164"),
    "claude": ("2.",),
    "opencode": ("2.",),
    "qwen": ("0.25", "0.26"),
}


def unsupported_clients() -> dict[str, str]:
    """Clients whose installed major differs from the versions we exercise.

    Returns ``{name: version}`` for any installed client whose numeric version
    does not start with one of the supported prefixes. This is a warning path
    for ``doctor``; it never blocks an install.
    """
    unsupported: dict[str, str] = {}
    for name, prefixes in SUPPORTED_CLIENT_VERSIONS.items():
        version = client_cli_version(name)
        if not version:
            continue
        numeric = released_version(version) or version
        if not any(numeric.startswith(prefix) for prefix in prefixes):
            unsupported[name] = version
    return unsupported


def sovereign_argv() -> list[str]:
    """Absolute command for the MCP server, safe for desktop app launchers.

    Do not resolve symlinks: `.venv/bin/python` is a symlink to Homebrew's
    Python, and resolving it drops the virtualenv, so `sovereign_code` cannot
    be imported by the launching app.
    """
    # Prefer the venv's `python` entry point: some launchers (uv run) expose
    # sys.executable as `python3`, but desktop clients and tests look for a
    # binary whose name is `python`.
    exe = Path(sys.executable)
    candidate = exe.with_name("python")
    command = str(candidate) if candidate.exists() else str(exe)
    return [command, "-m", "sovereign_code", "mcp"]


BACKUP_KEEP = 5


def _backup(path: Path) -> None:
    """Keep a copy of a user config, at most BACKUP_KEEP per file.

    Every `install-clients` run used to add a timestamped copy forever: three
    client configs reached 187 stale files. Identical content is not copied
    again, and only the newest BACKUP_KEEP are kept.
    """
    if not path.is_file():
        return
    existing = sorted(path.parent.glob(f"{path.name}.bak-*"))
    if existing:
        try:
            if existing[-1].read_bytes() == path.read_bytes():
                return
        except OSError:
            pass
    target = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    try:
        shutil.copy2(path, target)
    except OSError:
        return
    for old in sorted(path.parent.glob(f"{path.name}.bak-*"))[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def _write(path: Path, text: str) -> Path:
    """Write one of the user's client config files.

    These files can carry the user's own cloud credentials — the live
    ``~/.claude/settings.json`` still has ``ANTHROPIC_API_KEY`` in it when
    the user has been signed in — so they are written 0600 rather than with
    the process umask.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    write_private(path, text)
    return path


def codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def claude_desktop_config_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def opencode_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "opencode.json"


def continue_config_path() -> Path:
    return Path.home() / ".continue" / "config.yaml"


def complementary_mcp_servers() -> dict[str, dict[str, Any]]:
    """The reference MCP servers wired alongside Sovereign.

    Paths are derived from the current home directory: the previous revision
    hardcoded ``/Users/user/Documents``, which silently exposed the wrong
    directories (or none) on any other account.
    """
    home = Path.home()
    roots = [str(home / "Documents"), str(home / "Downloads")]
    servers: dict[str, dict[str, Any]] = {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", *roots],
        },
        "memory": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
        },
        # Full browser automation independent of Sovereign's policy-checked
        # browser, for when an agent needs raw CDP access.
        "playwright": {
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest"],
        },
    }
    # Deeper git history/blame and arbitrary HTTP fetching come from the
    # official Python reference servers. Their npm names do not exist, so the
    # old npx entries failed to start on every client; uvx is the supported
    # runner and is already required to install this project.
    uvx = shutil.which("uvx")
    if uvx:
        servers["git"] = {"command": uvx, "args": ["mcp-server-git"]}
        servers["fetch"] = {"command": uvx, "args": ["mcp-server-fetch"]}
    return servers


def codex_mcp_env() -> dict[str, str]:
    """The environment block for a Codex/Claude MCP server entry.

    ``env`` is a string array in Codex's MCP TOML, so the computer-control
    flag is written explicitly rather than left to the server's permissive
    default.
    """
    return {"SOVEREIGN_MCP_COMPUTER": "1"}


def install_codex_mcp(path: Path | None = None) -> Path:
    target = path or codex_config_path()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    command, *args = sovereign_argv()
    parts = [
        "[mcp_servers.sovereign]\n"
        f'command = "{command}"\n'
        f"args = [{', '.join(json.dumps(arg) for arg in args)}]\n"
        'env = ["SOVEREIGN_MCP_COMPUTER=1"]\n'
        "startup_timeout_sec = 30"
    ]
    for name, spec in complementary_mcp_servers().items():
        args_text = ", ".join(json.dumps(str(arg)) for arg in spec["args"])
        parts.append(
            f"[mcp_servers.{name}]\n"
            f"command = {json.dumps(str(spec['command']))}\n"
            f"args = [{args_text}]"
        )
    block = "\n\n".join(parts) + "\n"
    marker = "[mcp_servers.sovereign]"
    if marker in text:
        import re

        # Remove every block this function owns before appending the new
        # versions. Replacing only the sovereign block left the previous
        # filesystem/memory tables behind, so the next run produced duplicate
        # TOML tables and the client refused the whole config.
        for name in ("sovereign", *complementary_mcp_servers()):
            text = re.sub(
                rf"(?ms)^\[mcp_servers\.{re.escape(name)}\].*?(?=^\[|\Z)",
                "",
                text,
            )
        return _write(target, text.rstrip() + "\n\n" + block)
    return _write(target, text.rstrip() + "\n\n" + block)


def install_claude_desktop_mcp(path: Path | None = None) -> Path:
    target = path or claude_desktop_config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    command, *args = sovereign_argv()
    servers["sovereign"] = {"command": command, "args": args, "env": dict(codex_mcp_env())}
    for name, spec in complementary_mcp_servers().items():
        servers.setdefault(name, spec)
    return _write(target, json.dumps(data, indent=2) + "\n")


def install_claude_code_mcp() -> str:
    if shutil.which("claude") is None:
        return "claude not installed"
    command = sovereign_argv()
    server_name = "sovereign"
    try:
        subprocess.run(
            ["claude", "mcp", "remove", server_name, "-s", "user"],
            capture_output=True,
            text=True,
            check=False,
        )
        result = subprocess.run(
            [
                "claude",
                "mcp",
                "add",
                server_name,
                "-s",
                "user",
                "-e",
                *[f"{key}={value}" for key, value in codex_mcp_env().items()],
                "--",
                *command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"claude mcp failed: {exc}"
    if result.returncode != 0:
        return (result.stderr or result.stdout or "failed")[:200]
    # The complementary reference servers ride alongside Sovereign for Claude
    # Code, same as the desktop clients.
    extras: list[str] = []
    for name, spec in complementary_mcp_servers().items():
        # `mcp add` refuses a name that already exists, so a re-install used
        # to report every reference server as failed.
        subprocess.run(
            ["claude", "mcp", "remove", name, "-s", "user"],
            capture_output=True,
            text=True,
            check=False,
        )
        r = subprocess.run(
            [
                "claude",
                "mcp",
                "add",
                name,
                "-s",
                "user",
                "--",
                str(spec["command"]),
                *[str(arg) for arg in spec["args"]],
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        extras.append(f"{name}:{'added' if r.returncode == 0 else 'failed'}")
    return "added" + (f" ({', '.join(extras)})" if extras else "")


def install_qwen_mcp() -> str:
    if shutil.which("qwen") is None:
        return "qwen not installed"
    command = sovereign_argv()
    try:
        subprocess.run(
            ["qwen", "mcp", "remove", "sovereign"], capture_output=True, text=True, check=False
        )
        result = subprocess.run(
            [
                "qwen",
                "mcp",
                "add",
                "sovereign",
                "--env",
                *[f"{k}={v}" for k, v in codex_mcp_env().items()],
                *command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"qwen mcp failed: {exc}"
    if result.returncode != 0:
        return (result.stderr or result.stdout or "failed")[:200]
    extras: list[str] = []
    for name, spec in complementary_mcp_servers().items():
        subprocess.run(
            ["qwen", "mcp", "remove", name],
            capture_output=True,
            text=True,
            check=False,
        )
        r = subprocess.run(
            ["qwen", "mcp", "add", name, str(spec["command"]), *[str(arg) for arg in spec["args"]]],
            capture_output=True,
            text=True,
            check=False,
        )
        extras.append(f"{name}:{'added' if r.returncode == 0 else 'failed'}")
    return "added" + (f" ({', '.join(extras)})" if extras else "")


OPENCODE_MODELS = {
    "qwen3.8:27b": ("Qwen 3.8 27B — current-gen coder/agent", 32768),
    "qwen3-coder:30b": ("Qwen3 Coder 30B — strongest coder", 32768),
    "glm-4.7-flash": ("GLM-4.7 Flash — strongest reasoning", 32768),
    "gpt-oss:20b": ("GPT-OSS 20B — fastest strong tool caller", 16384),
    "gemma4:12b": ("Gemma 4 12B — vision", 32768),
    "qwen3.5:9b": ("Qwen3.5 9B — fast general", 32768),
    "qwen3.5:4b": ("Qwen3.5 4B — fastest", 32768),
    "qwen2.5-coder:14b": ("Qwen2.5 Coder 14B — dense fallback", 32768),
}


OPENCODE_PACKAGE = "@opencode/ai/providers/openai-compatible"


def _opencode_model(
    name: str, title: str, context: int, max_context: int, output: int = 8192
) -> dict[str, object]:
    """One V2 model entry: explicit tools, media, and context limits."""
    return {
        "name": title,
        "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
        "limit": {
            "context": advertised_context(name, context, max_context),
            "output": output,
        },
    }


def _opencode_permissions() -> list[dict[str, str]]:
    """V2 permission rules. Last match wins, so the broad default stays first."""
    return [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "shell", "resource": "rm -rf *", "effect": "deny"},
        {"action": "shell", "resource": "sudo *", "effect": "deny"},
        {"action": "shell", "resource": "git push *", "effect": "ask"},
        {"action": "shell", "resource": "git commit *", "effect": "ask"},
        {"action": "external_directory", "resource": "*", "effect": "ask"},
    ]


def _opencode_agents() -> dict[str, dict[str, object]]:
    """Read-only helpers a coding session can delegate to."""
    read_only = [{"action": "edit", "resource": "*", "effect": "deny"}]
    return {
        "reviewer": {
            "description": "Review the working tree without editing files",
            "mode": "subagent",
            "model": "sovereign/auto",
            "system": (
                "Review the current changes for correctness, security, and missing "
                "tests. Do not edit files. Return concrete findings with file:line "
                "and a short verdict."
            ),
            "permissions": read_only,
        },
        "planner": {
            "description": "Plan a change before any file is edited",
            "mode": "subagent",
            "model": "sovereign/best",
            "system": (
                "Read the relevant code and tests, then produce a small ordered "
                "implementation plan with acceptance checks. Do not edit files."
            ),
            "permissions": read_only,
        },
    }


def _opencode_commands() -> dict[str, dict[str, object]]:
    """Reusable slash commands for the work a coding session repeats."""
    return {
        "check": {
            "description": "Run the project's own checks",
            "template": (
                "Call the sovereign run_checks MCP tool for this project. Report the "
                "exact failing command and output, then fix only what is needed."
            ),
        },
        "review": {
            "description": "Review the working tree without editing",
            "agent": "reviewer",
            "template": (
                "Review the current working tree. Focus on correctness, security, and "
                "missing tests. Return findings with file:line and a short verdict."
            ),
        },
        "plan": {
            "description": "Plan a change before editing",
            "agent": "planner",
            "template": (
                "Read the relevant code and tests, then write a small ordered "
                "implementation plan with acceptance checks. Do not edit."
            ),
        },
    }


def opencode_config(include_cloud: bool = False, max_context: int | None = None) -> dict[str, Any]:
    """The native OpenCode V2 configuration this project writes.

    The cloud provider block is only included when ``include_cloud`` is set.
    Writing it unconditionally put an OpenRouter provider and eight remote
    models into the user's live config, so a prompt typed in OpenCode could
    leave the machine even though the whole project is local-first. It is now
    opt-in, the way the README describes it.

    V2 names the maps ``providers`` and ``mcp.servers``, uses ordered
    ``permissions`` rules, and adds subagents, commands, todo tracking and
    background compaction. The previous ``provider``/``permission``/``mcp``
    shapes still parse as deprecated V1 fields, but writing them keeps a new
    install on the old feature set.
    """
    command = sovereign_argv()
    if max_context is None:
        try:
            from .config import Settings

            max_context = Settings.load().max_context
        except Exception:
            max_context = 32768
    max_context = max(2048, int(max_context))
    providers: dict[str, dict[str, object]] = {
        "local": {
            "name": "Sovereign Ollama",
            "package": OPENCODE_PACKAGE,
            "settings": {
                "baseURL": "http://127.0.0.1:11434/v1",
                "apiKey": "ollama",
            },
            "models": {
                name: _opencode_model(name, title, context, max_context)
                for name, (title, context) in OPENCODE_MODELS.items()
            },
        },
        "sovereign": {
            "name": "Sovereign tier gateway",
            "package": OPENCODE_PACKAGE,
            "settings": {
                "baseURL": "http://127.0.0.1:4010/v1",
                "apiKey": "local",
            },
            "models": {
                "best": _opencode_model(
                    "best", "Best — 30B code / GLM reasoning", 32768, max_context
                ),
                "auto": _opencode_model(
                    "auto", "Auto — fast for simple, deep for hard", 32768, max_context
                ),
                "fast": _opencode_model(
                    "fast", "Fast — small model, short tasks", 8192, max_context, 4096
                ),
                "balanced": _opencode_model(
                    "balanced", "Balanced — 9B, tools and multi-turn", 16384, max_context
                ),
                "deep": _opencode_model(
                    "deep", "Deep — 30B code / GLM reasoning", 32768, max_context
                ),
                "ultra": _opencode_model(
                    "ultra", "Ultra — 27B for the hardest reasoning", 16384, max_context
                ),
            },
        },
        "openrouter": {
            "name": "OpenRouter",
            "package": OPENCODE_PACKAGE,
            "settings": {
                "baseURL": "https://openrouter.ai/api/v1",
                "apiKey": "{env:OPENROUTER_API_KEY}",
            },
            "models": {
                name: _opencode_model(name, title, 131072, 131072)
                for name, title in (
                    ("moonshotai/kimi-k3", "Kimi K3"),
                    ("moonshotai/kimi-k2.6", "Kimi K2.6"),
                    ("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
                    ("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro"),
                    ("z-ai/glm-5.3", "GLM 5.3"),
                    ("z-ai/glm-5.3-flash", "GLM 5.3 Flash"),
                    ("z-ai/glm-5.2", "GLM 5.2"),
                )
            },
        },
    }
    if not include_cloud:
        providers.pop("openrouter", None)
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": "sovereign/auto",
        # No `small_model`: OpenCode 2.x marks it deprecated and validates it
        # against the models.dev catalog, so a local alias fails the schema.
        # Ponytail: the "lazy senior dev" ruleset that makes agents write ~53%
        # less code, ~41% faster and ~26% cheaper, while keeping every safety
        # guard. It ships as an OpenCode plugin plus /ponytail commands.
        "plugins": ["@dietrichgebert/ponytail"],
        "permissions": _opencode_permissions(),
        "agents": _opencode_agents(),
        "commands": _opencode_commands(),
        "experimental": {"todo": True, "background_compaction": True},
        "compaction": {"auto": True, "keep": {"tokens": 6000}, "buffer": 6000},
        # Format after edits and stop generated trees from waking the watcher.
        "formatter": True,
        "watcher": {
            "ignore": [
                "node_modules/**",
                "dist/**",
                "build/**",
                "coverage/**",
                ".venv/**",
                "venv/**",
                "runtime/**",
            ]
        },
        "providers": providers,
        "mcp": {
            "servers": {
                "sovereign": {
                    "type": "local",
                    "command": command,
                    "environment": {"SOVEREIGN_MCP_COMPUTER": "1"},
                },
                # Servers are enabled by default in OpenCode 2.x; the only key
                # is `disabled`, and an `enabled` key fails the config schema.
                **{
                    name: {
                        "type": "local",
                        "command": [str(spec["command"]), *[str(arg) for arg in spec["args"]]],
                    }
                    for name, spec in complementary_mcp_servers().items()
                },
            },
        },
    }


def _normalise_provider(value: dict[str, Any]) -> dict[str, Any]:
    """Translate a V1 provider block to V2 and keep the user's model overrides."""
    normalized: dict[str, Any] = {
        key: item
        for key, item in value.items()
        if key not in {"npm", "options", "models", "tool_call"}
    }
    if "package" not in normalized and isinstance(value.get("npm"), str):
        normalized["package"] = value["npm"]
    if "settings" not in normalized and isinstance(value.get("options"), dict):
        normalized["settings"] = value["options"]
    models: dict[str, dict[str, Any]] = {}
    for name, model in (value.get("models") or {}).items():
        if not isinstance(model, dict):
            continue
        item = {key: val for key, val in model.items() if key != "tool_call"}
        capabilities = dict(item.get("capabilities") or {})
        if model.get("tool_call"):
            capabilities.setdefault("tools", True)
        capabilities.setdefault("tools", True)
        capabilities.setdefault("input", ["text"])
        capabilities.setdefault("output", ["text"])
        item["capabilities"] = capabilities
        models[str(name)] = item
    if models:
        normalized["models"] = models
    return normalized


def _v1_permission_rules(value: object) -> list[dict[str, str]]:
    """Map a V1 ``permission`` object to ordered V2 rules, if it is one."""
    if not isinstance(value, dict):
        return []
    actions = {
        "edit": "edit",
        "bash": "shell",
        "read": "read",
        "glob": "glob",
        "grep": "grep",
        "webfetch": "webfetch",
        "websearch": "websearch",
    }
    rules: list[dict[str, str]] = []
    for key, effect in value.items():
        action = actions.get(str(key))
        if action and isinstance(effect, str) and effect in {"allow", "ask", "deny"}:
            rules.append({"action": action, "resource": "*", "effect": effect})
    return rules


def _merge_permission_rules(base: list[dict[str, Any]], extra: object) -> list[dict[str, str]]:
    """Append user rules without duplicating the generated ones."""
    rules: list[dict[str, str]] = [rule for rule in base if isinstance(rule, dict)]
    seen = {(rule.get("action"), rule.get("resource"), rule.get("effect")) for rule in rules}
    if isinstance(extra, list):
        for rule in extra:
            if not isinstance(rule, dict):
                continue
            key = (rule.get("action"), rule.get("resource"), rule.get("effect"))
            if key in seen:
                continue
            seen.add(key)
            rules.append(rule)
    return rules


def install_opencode_mcp(
    path: Path | None = None, include_cloud: bool = False, max_context: int | None = None
) -> Path:
    target = path or opencode_config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raw = {}
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    # Preserve the user's other settings and providers; add the working local
    # provider, and the MCP server. Cloud providers are only added when the
    # user asks for them, so a local-first install stays local-first.
    merged: dict[str, Any] = opencode_config(include_cloud=include_cloud, max_context=max_context)
    providers: dict[str, Any] = merged["providers"]
    user_providers: dict[str, Any] = {}
    for key in ("providers", "provider"):
        candidate = data.get(key)
        if isinstance(candidate, dict):
            user_providers = candidate
            break
    for key, value in user_providers.items():
        if not isinstance(value, dict):
            continue
        existing = providers.get(key, {})
        incoming = _normalise_provider(value)
        merged_models = {**existing.get("models", {})}
        merged_models.update(incoming.pop("models", {}))
        for retired in RETIRED_MODELS:
            merged_models.pop(retired, None)
        providers[key] = {**existing, **incoming, "models": merged_models}
    for key, value in data.items():
        if key in {
            "provider",
            "providers",
            "mcp",
            "model",
            "small_model",
            "plugins",
            "permission",
            "permissions",
            "agents",
            "commands",
        }:
            continue
        merged[key] = value
    # Preserve the user's agents, commands and plugins. Their entries win over
    # the generated ones; plugin order keeps ponytail pinned first.
    for key in ("agents", "commands"):
        user_value = data.get(key)
        if isinstance(user_value, dict):
            merged[key] = {**merged.get(key, {}), **user_value}
    user_plugins = data.get("plugins")
    if isinstance(user_plugins, list):
        merged["plugins"] = merged.get("plugins", []) + [
            item for item in user_plugins if item not in merged.get("plugins", [])
        ]
    # The tier gateway is the default. `auto` already sends small turns to the
    # 9B, so no separate small_model is written (2.x deprecates it).
    merged["model"] = "sovereign/auto"
    merged.pop("small_model", None)
    # V1 used `permission`; V2 uses ordered `permissions`. Keep the user's
    # later rules so their explicit deny/ask choices still win.
    extra_rules = data.get("permissions")
    if not isinstance(extra_rules, list):
        extra_rules = _v1_permission_rules(data.get("permission"))
    merged["permissions"] = _merge_permission_rules(
        list(merged.get("permissions") or []), extra_rules
    )
    # Our server entry must win over a stale command path, while other MCP
    # servers the user added are preserved. V1 kept the server map at the top
    # level of `mcp`; 2.x only reads `mcp.servers` and marks the old shape
    # deprecated, so the entries are moved instead of copied twice.
    candidate_mcp = data.get("mcp")
    user_mcp: dict[str, Any] = candidate_mcp if isinstance(candidate_mcp, dict) else {}
    user_servers: dict[str, Any] = {}
    if isinstance(user_mcp.get("servers"), dict):
        user_servers.update(user_mcp["servers"])
    for name, entry in user_mcp.items():
        if name not in {"servers", "timeout"} and isinstance(entry, dict):
            user_servers.setdefault(name, entry)
    generated_mcp = merged.get("mcp")
    generated_servers: dict[str, Any] = {}
    if isinstance(generated_mcp, dict):
        generated_servers = generated_mcp.get("servers", {})
    merged_mcp: dict[str, Any] = {
        "servers": {
            name: _normalise_mcp_server(entry)
            for name, entry in {**user_servers, **generated_servers}.items()
        }
    }
    if isinstance(user_mcp.get("timeout"), dict):
        merged_mcp["timeout"] = user_mcp["timeout"]
    merged["mcp"] = merged_mcp
    return _write(target, json.dumps(merged, indent=2) + "\n")


def _normalise_mcp_server(entry: object) -> dict[str, Any]:
    """Translate the V1 `enabled` flag to 2.x `disabled`, and keep the rest."""
    server = dict(entry) if isinstance(entry, dict) else {}
    if "enabled" in server:
        enabled = bool(server.pop("enabled"))
        if not enabled:
            server["disabled"] = True
    return server


CONTINUE_CONFIG = """\
name: Sovereign Local
version: 1.0.0
schema: v1

models:
  - name: Sovereign Best — 30B code / GLM reasoning
    provider: openai
    model: best
    apiBase: http://127.0.0.1:4010/v1
    apiKey: local
    roles: [chat, edit, apply]
    defaultCompletionOptions:
      contextLength: 32768
  - name: Sovereign Auto — fast/deep tier gateway
    provider: openai
    model: auto
    apiBase: http://127.0.0.1:4010/v1
    apiKey: local
    roles: [chat, edit, apply]
    defaultCompletionOptions:
      contextLength: 32768
  - name: Sovereign Deep — code/reasoning
    provider: openai
    model: deep
    apiBase: http://127.0.0.1:4010/v1
    apiKey: local
    roles: [chat]
    defaultCompletionOptions:
      contextLength: 32768
  - name: Sovereign Ultra — hardest reasoning
    provider: openai
    model: ultra
    apiBase: http://127.0.0.1:4010/v1
    apiKey: local
    roles: [chat]
    defaultCompletionOptions:
      contextLength: 16384
  - name: Qwen 3.8 27B — current-gen coder
    provider: ollama
    model: qwen3.8:27b
    apiBase: http://127.0.0.1:11434
    roles: [chat, edit, apply]
    defaultCompletionOptions:
      contextLength: 32768
  - name: Qwen3 Coder 30B — best coder
    provider: ollama
    model: qwen3-coder:30b
    apiBase: http://127.0.0.1:11434
    roles: [chat, edit, apply]
    defaultCompletionOptions:
      contextLength: 32768
  - name: GLM-4.7 Flash — best reasoning
    provider: ollama
    model: glm-4.7-flash
    apiBase: http://127.0.0.1:11434
    roles: [chat]
    defaultCompletionOptions:
      contextLength: 32768
  - name: Qwen3.5 9B — fast general
    provider: ollama
    model: qwen3.5:9b
    apiBase: http://127.0.0.1:11434
    roles: [chat]
    defaultCompletionOptions:
      contextLength: 32768
  - name: Qwen3.5 4B — autocomplete
    provider: ollama
    model: qwen3.5:4b
    apiBase: http://127.0.0.1:11434
    roles: [autocomplete]
    defaultCompletionOptions:
      contextLength: 8192

context:
  - provider: code
  - provider: diff
  - provider: terminal
  - provider: problems
  - provider: folder
  - provider: codebase
"""


CONTINUE_RULES = """\
# Sovereign local rules

- Everything runs on this Mac through Ollama on 127.0.0.1; do not call a cloud API.
- Prefer the strongest installed model for the task; `sovereign clients` shows it.
- Keep changes minimal and reviewable; state files and verify with the project's own tests.
- Available skills live in `~/.continue/prompts`; invoke them from the slash menu.
"""


def install_continue_rules(path: Path | None = None) -> Path:
    target = path or (Path.home() / ".continue" / "rules" / "sovereign.md")
    return _write(target, CONTINUE_RULES)


def install_continue_config(path: Path | None = None) -> Path:
    target = path or continue_config_path()
    # Continue's YAML has no safe merge without a YAML dependency. Keep an
    # existing user config, but add Qwen 3.8 once when it is missing.
    if target.is_file() and target.stat().st_size > 0:
        text = target.read_text(encoding="utf-8")
        original = text
        prefix = ""
        if "Sovereign Auto" not in text:
            prefix += (
                "  - name: Sovereign Auto — fast/deep tier gateway\n"
                "    provider: openai\n"
                "    model: auto\n"
                "    apiBase: http://127.0.0.1:4010/v1\n"
                "    apiKey: local\n"
                "    roles: [chat, edit, apply]\n"
                "    defaultCompletionOptions:\n"
                "      contextLength: 32768\n"
                "  - name: Sovereign Deep — code/reasoning\n"
                "    provider: openai\n"
                "    model: deep\n"
                "    apiBase: http://127.0.0.1:4010/v1\n"
                "    apiKey: local\n"
                "    roles: [chat]\n"
                "    defaultCompletionOptions:\n"
                "      contextLength: 32768\n"
                "  - name: Sovereign Ultra — hardest reasoning\n"
                "    provider: openai\n"
                "    model: ultra\n"
                "    apiBase: http://127.0.0.1:4010/v1\n"
                "    apiKey: local\n"
                "    roles: [chat]\n"
                "    defaultCompletionOptions:\n"
                "      contextLength: 16384\n"
            )
        text = text.replace(
            "Sovereign Deep — 27B for hard tasks", "Sovereign Deep — code/reasoning"
        )
        text = text.replace("Qwen2.5 Coder 7B — autocomplete", "Qwen3.5 4B — autocomplete").replace(
            "model: qwen2.5-coder:7b", "model: qwen3.5:4b"
        )
        if "Sovereign Ultra" not in text:
            ultra = (
                "  - name: Sovereign Ultra — hardest reasoning\n"
                "    provider: openai\n"
                "    model: ultra\n"
                "    apiBase: http://127.0.0.1:4010/v1\n"
                "    apiKey: local\n"
                "    roles: [chat]\n"
                "    defaultCompletionOptions:\n"
                "      contextLength: 16384\n"
            )
            marker = "  - name: Qwen 3.8 27B"
            if marker in text:
                text = text.replace(marker, ultra + marker, 1)
        if "qwen3.8:27b" not in text:
            prefix += (
                "  - name: Qwen 3.8 27B — current-gen coder\n"
                "    provider: ollama\n"
                "    model: qwen3.8:27b\n"
                "    apiBase: http://127.0.0.1:11434\n"
                "    roles: [chat, edit, apply]\n"
                "    defaultCompletionOptions:\n"
                "      contextLength: 32768\n"
            )
        if prefix and "models:" in text:
            text = text.replace("models:\n", "models:\n" + prefix, 1)
        if text != original:
            return _write(target, text)
        return target
    return _write(target, CONTINUE_CONFIG)


def qwen_settings_path() -> Path:
    return Path.home() / ".qwen" / "settings.json"


def install_qwen_router(path: Path | None = None) -> Path:
    """Register the tier gateway as Qwen Code's default OpenAI provider."""
    target = path or qwen_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return target
    if not isinstance(data, dict):
        return target
    providers = data.setdefault("modelProviders", {})
    openai = providers.setdefault("openai", [])
    if not isinstance(openai, list):
        openai = []
        providers["openai"] = openai
    tier_ids = {"best", "auto", "fast", "balanced", "deep", "ultra"}
    retired = RETIRED_MODELS
    keep = [
        entry
        for entry in openai
        if entry.get("id") not in tier_ids and entry.get("id") not in retired
    ]
    for model, name in (
        ("best", "Best — 30B code / GLM reasoning"),
        ("auto", "Auto — fast/deep tier gateway"),
        ("fast", "Fast — small model"),
        ("balanced", "Balanced — 9B"),
        ("deep", "Deep — code/reasoning"),
        ("ultra", "Ultra — 27B reasoning"),
    ):
        keep.append(
            {
                "baseUrl": "http://127.0.0.1:4010/v1",
                "envKey": "SOVEREIGN_ROUTER_KEY",
                "id": model,
                "name": name,
            }
        )
    providers["openai"] = keep
    for provider_id, entries in list(providers.items()):
        if provider_id == "openai" or not isinstance(entries, list):
            continue
        providers[provider_id] = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and entry.get("id") in retired)
        ]
    data.setdefault("env", {})["SOVEREIGN_ROUTER_KEY"] = "local"
    data["model"] = {"name": "best"}
    security = data.setdefault("security", {})
    auth = security.setdefault("auth", {})
    auth["baseUrl"] = "http://127.0.0.1:4010/v1"
    auth["selectedType"] = "openai"
    return _write(target, json.dumps(data, indent=2) + "\n")


def _mcp_entry() -> dict[str, Any]:
    command, *args = sovereign_argv()
    return {
        "command": command,
        "args": args,
        "env": dict(codex_mcp_env()),
    }


def install_mcp_manifest(path: Path) -> Path:
    """Write/merge an `mcpServers.sovereign` JSON manifest."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    servers["sovereign"] = _mcp_entry()
    for name, spec in complementary_mcp_servers().items():
        servers.setdefault(name, spec)
    return _write(path, json.dumps(data, indent=2) + "\n")


def install_chatgpt_connectors() -> list[Path]:
    """Make the MCP server discoverable by the ChatGPT desktop app.

    The app imports `claude_desktop_config.json` from its user-data directory
    and also scans `.mcp.json` manifests. We write the same entry in all the
    places it looks, without touching unrelated servers.
    """
    home = Path.home()
    candidates = [
        home / ".mcp.json",
        home / ".codex" / ".mcp.json",
        home / ".codex" / "claude_desktop_config.json",
        home / "Library" / "Application Support" / "Codex" / "claude_desktop_config.json",
    ]
    written: list[Path] = []
    for path in candidates:
        try:
            written.append(install_mcp_manifest(path))
        except OSError:
            continue
    return written


def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


CLAUDE_LOCAL_ENV = {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4001",
    "ANTHROPIC_AUTH_TOKEN": "local",
    "ANTHROPIC_API_KEY": "local",
    # The default turn follows the quality route: the 30B coder for code, GLM
    # for reasoning, the 9B for a short prompt.
    "ANTHROPIC_MODEL": "best",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "65536",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8192",
    "DISABLE_AUTO_COMPACT": "1",
}

# Knobs an earlier release wrote and the current Claude Code no longer reads.
# They are removed on install so a settings file does not accumulate dead
# environment variables that look like settings.
CLAUDE_OBSOLETE_ENV = (
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS",
)

# The picker slots. Each one carries the model id Claude Code knows, and the
# local route that id resolves to, so the picker offers the local models and
# Claude never sees a model name it does not recognise.
CLAUDE_MODEL_SLOTS: dict[str, tuple[str, str]] = dict(CLAUDE_SLOT_MODELS)
CLAUDE_MODEL_SLOTS["ANTHROPIC_MODEL"] = ("best", "best")

for _slot, (_model_id, _route) in CLAUDE_MODEL_SLOTS.items():
    CLAUDE_LOCAL_ENV[_slot] = _model_id


def install_claude_settings(path: Path | None = None) -> Path:
    """Make Claude Code/Cowork default to the local bridge via settings.env."""
    target = path or claude_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    backup = claude_cloud_backup_path(target)
    if not backup.exists() and not claude_forced_local(target):
        # Keep the cloud settings so `restore_claude_cloud` can hand them back.
        # A settings file that is already local is not a cloud copy.
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        backup.chmod(0o600)
    env = data.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    env.update(CLAUDE_LOCAL_ENV)
    for key in CLAUDE_OBSOLETE_ENV:
        env.pop(key, None)
    return _write(target, json.dumps(data, indent=2) + "\n")


def codex_needs_openai_signin(path: Path | None = None) -> bool:
    """Whether the app would ask for an OpenAI account to run.

    A custom provider that does not set `requires_openai_auth` and does not
    read a key from the environment needs no account at all.
    """
    target = path or codex_config_path()
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return True
    provider_id = str(data.get("model_provider") or "")
    if not provider_id:
        # No provider chosen: the built-in OpenAI one is used.
        return True
    provider = (data.get("model_providers") or {}).get(provider_id) or {}
    if not isinstance(provider, dict):
        provider = {}
    if provider.get("requires_openai_auth"):
        return True
    return provider_id == "openai"


def _provider_token(provider: dict[str, Any]) -> str:
    """The bearer token Codex would use for this provider."""
    token = str(provider.get("experimental_bearer_token") or "")
    if token:
        return token
    auth = provider.get("auth")
    if not isinstance(auth, dict):
        return ""
    command = str(auth.get("command") or "")
    if not command:
        return ""
    args = [str(item) for item in (auth.get("args") or [])]
    try:
        result = subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def codex_probe_local(path: Path | None = None, timeout: float = 120.0) -> tuple[bool, str]:
    """Send one short request through the app's own provider config.

    This is the end-to-end proof that the local path works: the base URL and
    the token come from the same file the app reads, so a pass means the app
    would answer without an OpenAI sign-in.
    """
    target = path or codex_config_path()
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return False, f"unreadable config: {exc}"
    provider_id = str(data.get("model_provider") or "")
    provider = (data.get("model_providers") or {}).get(provider_id) or {}
    if not isinstance(provider, dict):
        provider = {}
    base = str(provider.get("base_url") or data.get("openai_base_url") or "").rstrip("/")
    if not base:
        return False, "no provider base_url"
    # Only HTTP(S) is a provider. `file:` would make urllib read a local file
    # and hand it back as if it were a model response.
    if not base.startswith(("http://", "https://")):
        return False, f"provider base_url is not http(s): {base}"
    token = _provider_token(provider)
    if not token:
        return False, "provider has no usable token"
    model = str(data.get("model") or "auto")
    body = json.dumps(
        {"model": model, "input": "Reply with exactly: LOCAL", "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - the scheme is checked above
        f"{base}/responses",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) only
            payload = json.loads(response.read().decode("utf-8", "replace"))
            tier = response.headers.get("x-sovereign-tier") or "?"
            return True, f"{model} → {tier} tier · {_response_text(payload)}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from {base}"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _response_text(payload: Any) -> str:
    """The plain text of a Responses API payload."""
    if not isinstance(payload, dict):
        return ""
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                return str(part.get("text") or "").strip()
    return str(payload.get("output_text") or "").strip()


def claude_cloud_backup_path(path: Path | None = None) -> Path:
    target = path or claude_settings_path()
    return target.with_name(target.name + CLOUD_BACKUP_SUFFIX)


def claude_forced_local(path: Path | None = None) -> bool:
    """Whether Claude Code/Cowork is pointed at the local bridge."""
    target = path or claude_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    env = data.get("env")
    if not isinstance(env, dict):
        return False
    return env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:4001"


def restore_claude_cloud(path: Path | None = None) -> Path | None:
    """Put the Claude settings back to their cloud default.

    The saved cloud settings are used when there is one; otherwise the local
    bridge keys are stripped from the live settings.
    """
    target = path or claude_settings_path()
    backup = claude_cloud_backup_path(target)
    if backup.is_file():
        saved = backup.read_text(encoding="utf-8")
        target.write_text(saved, encoding="utf-8")
        target.chmod(0o600)
        backup.unlink()
        return target
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    env = data.get("env")
    if isinstance(env, dict):
        for key in (*CLAUDE_LOCAL_ENV, *CLAUDE_OBSOLETE_ENV):
            env.pop(key, None)
        if not env:
            data.pop("env", None)
    _write(target, json.dumps(data, indent=2) + "\n")
    return target


CODEX_LOCAL_PROVIDER = """\
[model_providers.sovereign-tier]
name = "Sovereign tier gateway"
base_url = "http://127.0.0.1:4010/v1"
wire_api = "responses"
supports_websockets = false

[model_providers.sovereign-tier.auth]
command = "/bin/echo"
args = ["local"]
"""

# Codex 0.163 v2 profiles live in <name>.config.toml, not `[profiles.name]`.
CODEX_LOCAL_PROFILE = """\
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

# The provider the ChatGPT/Codex app is pinned to when it runs local-only.
CODEX_LOCAL_PROVIDER_ID = "sovereign-tier"

# Top-level keys that decide which model the app talks to. Forcing them to a
# local provider with `requires_openai_auth = false` is what removes the
# OpenAI sign-in gate.
CODEX_ROUTING_KEYS = ("model", "model_provider", "model_context_window", "openai_base_url")

# Marks the block this module owns, so re-running it replaces the block
# instead of stacking a second copy on top.
LOCAL_MARKER = "# sovereign:local-only"


def install_codex_local_provider(path: Path | None = None) -> Path:
    """Expose a local provider/profile to the ChatGPT app without changing its cloud default."""
    from .clients import write_codex_catalog

    target = path or codex_config_path()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    import re

    text = re.sub(r"(?ms)^\[model_providers\.sovereign-tier\].*?(?=^\[|\Z)", "", text)
    text = re.sub(r"(?ms)^\[profiles\.sovereign\].*?(?=^\[|\Z)", "", text)
    result = _write(target, text.rstrip() + "\n\n" + CODEX_LOCAL_PROVIDER)
    # The profile names the local routes, so Codex needs a model catalog that
    # describes them: without one it warns on every turn and guesses a
    # context window that does not fit the model.
    catalog = write_codex_catalog()
    profile = CODEX_LOCAL_PROFILE.replace("__CATALOG__", str(catalog))
    _write(target.with_name("sovereign.config.toml"), profile)
    return result


# --- TOML surgery -------------------------------------------------------
#
# The Codex config is hand-edited by the ChatGPT app itself, so it cannot be
# rewritten from scratch: the app's plugins, marketplaces and MCP servers have
# to survive. These helpers edit the document in place instead of parsing it
# into a dict and writing it back, which would drop every comment and any key
# this version of Codex does not know about.


def _toml_bracket_delta(line: str) -> int:
    """Net `[`/`]` count for one TOML line, ignoring quoted strings."""
    depth = 0
    quote = ""
    escaped = False
    for char in line:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "#":
            break
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth


def _split_top_level(text: str) -> tuple[list[str], list[str]]:
    """Split a TOML document into top-level key lines and table sections."""
    head: list[str] = []
    body: list[str] = []
    in_table = False
    depth = 0
    for line in text.splitlines():
        if not in_table and depth <= 0 and line.lstrip().startswith("["):
            in_table = True
        (body if in_table else head).append(line)
        depth += _toml_bracket_delta(line)
        if depth < 0:
            depth = 0
    return head, body


def _drop_keys(lines: list[str], keys: tuple[str, ...]) -> list[str]:
    """Remove top-level keys, including any multi-line value they own."""
    import re

    out: list[str] = []
    depth = 0
    dropping = False
    for line in lines:
        if depth <= 0 and not dropping:
            match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*=", line)
            dropping = bool(match and match.group(1) in keys)
        if dropping:
            depth += _toml_bracket_delta(line)
            if depth <= 0:
                dropping = False
            continue
        out.append(line)
        depth += _toml_bracket_delta(line)
    return out


def _section_bounds(body: list[str], header: str) -> tuple[int, int] | None:
    """Line range of a table section, or None when it is not there."""
    start: int | None = None
    depth = 0
    for index, line in enumerate(body):
        stripped = line.strip()
        if depth <= 0 and stripped.startswith("["):
            if start is None:
                if stripped == header:
                    start = index
            else:
                return start, index
        depth += _toml_bracket_delta(line)
        if depth < 0:
            depth = 0
    if start is None:
        return None
    return start, len(body)


def _upsert_section(
    body: list[str],
    header: str,
    section: list[str],
    keep_unknown: bool = False,
    drop: tuple[str, ...] = (),
) -> list[str]:
    """Replace a table section, or append it when it is missing.

    `keep_unknown` carries over keys the section already had that this module
    does not write, so a hand-tuned provider entry is not thrown away. Keys
    in `drop` are removed even then: a leftover `env_key` would put the
    sign-in gate back.
    """
    bounds = _section_bounds(body, header)
    if bounds is None:
        result = list(body)
        if result and result[-1].strip():
            result.append("")
        result.extend(section)
        return result
    start, end = bounds
    if keep_unknown:
        managed = {line.split("=", 1)[0].strip() for line in section if "=" in line}
        extra = [
            line
            for line in body[start + 1 : end]
            if "=" in line
            and not line.strip().startswith("#")
            and line.split("=", 1)[0].strip() not in managed
            and line.split("=", 1)[0].strip() not in drop
        ]
        section = section + extra
    replacement = list(section)
    if end < len(body) and replacement and replacement[-1].strip():
        replacement.append("")
    # A second copy of the same table would be a duplicate key in TOML.
    return body[:start] + replacement + _remove_section(body[end:], header)


def _tidy(lines: list[str]) -> list[str]:
    """Collapse repeated blank lines and trim the edges."""
    out: list[str] = []
    for line in lines:
        if not line.strip() and (not out or not out[-1].strip()):
            continue
        out.append(line.rstrip())
    while out and not out[-1].strip():
        out.pop()
    return out


def _remove_section(body: list[str], header: str) -> list[str]:
    """Drop every copy of a table section."""
    out = list(body)
    while True:
        bounds = _section_bounds(out, header)
        if bounds is None:
            return out
        start, end = bounds
        out = out[:start] + out[end:]


def _insert_after(body: list[str], anchor: str, section: list[str]) -> list[str]:
    """Put a section directly after the anchor section."""
    bounds = _section_bounds(body, anchor)
    if bounds is None:
        return body
    at = bounds[1]
    prefix = [""] if at > 0 and body[at - 1].strip() else []
    return body[:at] + prefix + section + [""] + body[at:]


def forced_local_lines(router_url: str, catalog_path: str = "") -> list[str]:
    """Top-level keys that pin the app to the local tier gateway."""
    lines = [
        f"{LOCAL_MARKER} every model call goes to the tier gateway on",
        "# this Mac, so the app needs no OpenAI sign-in.",
        'model = "best"',
        f'model_provider = "{CODEX_LOCAL_PROVIDER_ID}"',
        "model_context_window = 32768",
        f'openai_base_url = "{router_url.rstrip("/")}/v1"',
    ]
    if catalog_path:
        # Codex needs a model catalog to know the local routes. Without one it
        # warns on every turn and assumes a context window that does not fit.
        lines.append(f'model_catalog_json = "{catalog_path}"')
    return lines


def _strip_local_marker(lines: list[str]) -> list[str]:
    """Remove the block this module wrote, so a rewrite does not stack copies."""
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(LOCAL_MARKER):
            skipping = True
            continue
        if skipping and stripped.startswith("#"):
            continue
        skipping = False
        out.append(line)
    return out


def local_provider_section(router_url: str) -> list[str]:
    """The provider table for the local tier gateway.

    The token is not read from an environment variable: an app launched from
    Finder or the Dock inherits no shell environment, and a missing key puts
    the sign-in gate straight back. Codex reads the token from a command
    instead, so nothing has to be exported for the provider to work.
    """
    return [
        f"[model_providers.{CODEX_LOCAL_PROVIDER_ID}]",
        'name = "Sovereign tier gateway"',
        f'base_url = "{router_url.rstrip("/")}/v1"',
        'wire_api = "responses"',
        "supports_websockets = false",
    ]


def local_provider_auth_section() -> list[str]:
    """The command Codex runs to get the provider token.

    Codex refuses to combine this with `env_key`, `experimental_bearer_token`
    or `requires_openai_auth`, so the provider table stays free of them.
    """
    return [
        f"[model_providers.{CODEX_LOCAL_PROVIDER_ID}.auth]",
        'command = "/bin/echo"',
        'args = ["local"]',
    ]


def codex_cloud_backup_path(path: Path | None = None) -> Path:
    target = path or codex_config_path()
    return target.with_name(target.name + CLOUD_BACKUP_SUFFIX)


def codex_forced_local(path: Path | None = None, router_url: str | None = None) -> bool:
    """Whether the app config is pinned to the local provider.

    All parts have to hold: the routing keys point at the local provider, the
    provider is there, it does not ask for OpenAI credentials, and it can get
    a token without an environment variable.
    """
    target = path or codex_config_path()
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    url = (router_url or Settings.load().router_url).rstrip("/")
    if data.get("model_provider") != CODEX_LOCAL_PROVIDER_ID:
        return False
    if data.get("openai_base_url") != f"{url}/v1":
        return False
    provider = (data.get("model_providers") or {}).get(CODEX_LOCAL_PROVIDER_ID) or {}
    if provider.get("requires_openai_auth"):
        return False
    if provider.get("env_key"):
        # A missing environment variable would put the sign-in gate back.
        return False
    token = provider.get("experimental_bearer_token") or (provider.get("auth") or {}).get("command")
    return bool(token)


def install_codex_forced_local(path: Path | None = None, router_url: str | None = None) -> Path:
    """Pin the ChatGPT/Codex app to the local tier gateway. No sign-in needed.

    The first run keeps a copy of the untouched config so `restore_codex_cloud`
    can hand the app back exactly what it had.
    """
    target = path or codex_config_path()
    url = (router_url or Settings.load().router_url).rstrip("/")
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""

    backup = codex_cloud_backup_path(target)
    if not backup.exists() and not codex_forced_local(target, url):
        # Keep the untouched config so `restore_codex_cloud` can hand the app
        # back exactly what it had. A config that is already local is not a
        # cloud copy.
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(text, encoding="utf-8")
        backup.chmod(0o600)

    head, body = _split_top_level(text)
    head = _strip_local_marker(head)
    head = _drop_keys(head, CODEX_ROUTING_KEYS)
    from .clients import write_codex_catalog

    catalog = write_codex_catalog()
    head = _drop_keys(head, ("model_catalog_json",))
    header = f"[model_providers.{CODEX_LOCAL_PROVIDER_ID}]"
    auth_header = f"[model_providers.{CODEX_LOCAL_PROVIDER_ID}.auth]"
    body = _remove_section(body, auth_header)
    body = _upsert_section(
        body,
        header,
        local_provider_section(url),
        keep_unknown=True,
        drop=("env_key", "requires_openai_auth", "experimental_bearer_token"),
    )
    body = _insert_after(body, header, local_provider_auth_section())
    body = _upsert_section(body, "[analytics]", ["[analytics]", "enabled = false"])
    document = "\n".join(
        [*_tidy([*forced_local_lines(url, str(catalog)), "", *head]), "", *_tidy(body)]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, document.strip() + "\n")
    target.chmod(0o600)
    return target


def restore_codex_cloud(path: Path | None = None) -> Path | None:
    """Put the saved cloud config back. Returns None when there is no backup.

    The backup is dropped afterwards, so the next force-local run snapshots the
    config that is live right now instead of an older copy.
    """
    target = path or codex_config_path()
    backup = codex_cloud_backup_path(target)
    if not backup.is_file():
        return None
    saved = backup.read_text(encoding="utf-8")
    target.write_text(saved, encoding="utf-8")
    target.chmod(0o600)
    backup.unlink()
    return target


def codex_configured_model(path: Path | None = None) -> str:
    """The model the ChatGPT/Codex app is configured to use."""
    target = path or codex_config_path()
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ""
    return str(data.get("model") or "").strip()


def claude_configured_models(path: Path | None = None) -> dict[str, str]:
    """The model each Claude slot points at."""
    target = path or claude_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    env = data.get("env") if isinstance(data, dict) else None
    if not isinstance(env, dict):
        return {}
    slots: dict[str, str] = {}
    for key in CLAUDE_MODEL_SLOTS:
        value = str(env.get(key) or "").strip()
        if value:
            slots[key] = value
    return slots


def claude_slot_routes(path: Path | None = None) -> dict[str, str]:
    """The local route each Claude slot ends up on."""
    routes: dict[str, str] = {}
    for key, value in claude_configured_models(path).items():
        route = CLAUDE_MODEL_ROUTES.get(value)
        if route is None:
            route = CLAUDE_MODEL_SLOTS.get(key, ("", ""))[1]
        routes[key] = route
    return routes


def unknown_client_models() -> list[str]:
    """Configured model names the local stack cannot serve.

    A client that asks for a name the gateway cannot route gets an error
    instead of an answer, so the drift is worth reporting.
    """
    from .mlx import MLX_ALIASES
    from .tier_gateway import CLAUDE_MODEL_ROUTES, catalog_ids, installed_models

    known = catalog_ids(installed_models()) | set(CLAUDE_MODEL_ROUTES) | set(MLX_ALIASES)
    names = [codex_configured_model()]
    names.extend(claude_slot_routes().values())
    return sorted({name for name in names if name and name not in known})


def install_ponytail() -> str:
    """Register the DietrichGebert/ponytail plugin with Codex.

    Codex (and its ChatGPT desktop side) load ponytail as a plugin with two
    tiny Node.js lifecycle hooks. The marketplace and plugin must be added
    before the hooks can be trusted in the ``/hooks`` view.
    """
    if shutil.which("codex") is None:
        return "codex not installed"
    try:
        add = subprocess.run(
            ["codex", "plugin", "marketplace", "add", "DietrichGebert/ponytail"],
            capture_output=True,
            text=True,
            check=False,
        )
        install = subprocess.run(
            ["codex", "plugin", "add", "ponytail@ponytail"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"codex plugin failed: {exc}"
    if install.returncode == 0:
        return "installed (review /hooks, start a new thread)"
    detail = (install.stderr or install.stdout or add.stderr or add.stdout or "").strip()
    return f"partial: {detail[:200]}" if add.returncode == 0 else f"failed: {detail[:200]}"


def install_ponytail_claude() -> str:
    """Register ponytail with Claude Code via its plugin marketplace.

    Claude Code's plugin install has to be two separate prompts in an
    interactive session. This reports an explicit manual status instead of
    pretending the install completed, so `install_all` output is honest.
    """
    if shutil.which("claude") is None:
        return "claude not installed"
    return (
        "manual: run in Claude Code `/plugin marketplace add DietrichGebert/ponytail` "
        "then `/plugin install ponytail@ponytail`"
    )


def install_ponytail_qwen() -> str:
    """Register ponytail with Qwen Code as an extension."""
    if shutil.which("qwen") is None:
        return "qwen not installed"
    try:
        result = subprocess.run(
            ["qwen", "extensions", "install", "DietrichGebert/ponytail:ponytail"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"qwen extension failed: {exc}"
    # Distinguish a real install from a half-completed one, like the Codex path.
    if result.returncode == 0:
        return "installed (reload Qwen Code)"
    detail = (result.stderr or result.stdout or "").strip()
    return f"failed: {detail[:200]}"


def install_all() -> list[tuple[str, str]]:
    """Configure every client. Returns (component, result) rows."""
    rows: list[tuple[str, str]] = []
    for label, fn in (
        ("Codex MCP", install_codex_mcp),
        ("Claude Desktop MCP", install_claude_desktop_mcp),
        ("Claude local settings", install_claude_settings),
        ("Codex local provider/profile", install_codex_local_provider),
        ("ChatGPT app local (no sign-in)", install_codex_forced_local),
        (
            "ChatGPT MCP connectors",
            lambda: f"{len(install_chatgpt_connectors())} manifests",
        ),
        ("OpenCode config + MCP", install_opencode_mcp),
        ("Continue config", install_continue_config),
        ("Continue rules", install_continue_rules),
        ("Qwen Code tier provider", install_qwen_router),
        ("Ponytail ruleset", install_ponytail),
    ):
        try:
            rows.append((label, str(fn())))
        except Exception as exc:  # setup must report, not abort the others
            rows.append((label, f"failed: {exc}"))
    rows.append(("Claude Code MCP", install_claude_code_mcp()))
    rows.append(("Qwen Code MCP", install_qwen_mcp()))
    rows.append(("Ponytail Claude Code", install_ponytail_claude()))
    rows.append(("Ponytail Qwen", install_ponytail_qwen()))
    unsupported = unsupported_clients()
    if unsupported:
        rows.append(
            (
                "Client version",
                "unverified " + ", ".join(f"{name} {ver}" for name, ver in unsupported.items()),
            )
        )
    return rows


def desktop_configs() -> dict[str, Path]:
    return {
        "codex": codex_config_path(),
        "claude_desktop": claude_desktop_config_path(),
        "opencode": opencode_config_path(),
        "continue": continue_config_path(),
        "local_ai": LOCAL_AI_ROOT,
    }


def codium_command() -> str:
    for name in ("codium", "codium-insiders"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def codium_settings_path() -> Path:
    """The user settings file of the installed VS Codium build."""
    mac = Path.home() / "Library" / "Application Support" / "VSCodium" / "User" / "settings.json"
    mac_insiders = (
        Path.home()
        / "Library"
        / "Application Support"
        / "VSCodium - Insiders"
        / "User"
        / "settings.json"
    )
    linux = Path.home() / ".config" / "VSCodium" / "User" / "settings.json"
    if mac_insiders.is_file() or (shutil.which("codium-insiders") and not shutil.which("codium")):
        return mac_insiders
    if mac.parent.is_dir() or not linux.parent.is_dir():
        return mac
    return linux


def install_codium_continue(path: Path | None = None) -> str:
    """Install Continue into VS Codium and point its user settings locally."""
    command = codium_command()
    if not command:
        return "codium not installed"
    extension = "Continue.continue"
    installed = False
    try:
        listed = subprocess.run(
            [command, "--list-extensions"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        installed = extension.lower() in (listed.stdout or "").lower()
        if not installed:
            result = subprocess.run(
                [command, "--install-extension", extension, "--force"],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            installed = result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        return f"codium extension failed: {exc}"

    target = path or codium_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, UnicodeDecodeError, ValueError):
        data = {}
    data.update(
        {
            "continue.enableTabAutocomplete": True,
            "continue.telemetryEnabled": False,
            "telemetry.telemetryLevel": "off",
        }
    )
    _write(target, json.dumps(data, indent=2) + "\n")
    install_continue_config()
    install_continue_rules()
    return f"Continue {'ready' if installed else 'installed (reopen Codium)'} · {target}"


MLX_BASE_URL = "http://127.0.0.1:8081/v1"

MLX_MODELS: dict[str, tuple[str, int]] = {
    "mlx-qwen3-14b-4bit": ("MLX Qwen3 14B 4-bit — strongest MLX coder", 32768),
    "mlx-qwen3-8b-4bit": ("MLX Qwen3 8B 4-bit — fast general", 32768),
    "mlx-qwen3-4b-4bit": ("MLX Qwen3 4B 4-bit — fastest", 16384),
    "mlx-qwen2.5-coder-7b-4bit": ("MLX Qwen2.5 Coder 7B 4-bit — small coder", 32768),
    "mlx-llama-3.1-8b-instruct-4bit": ("MLX Llama 3.1 8B 4-bit — chat", 32768),
}

MLX_ROUTES: dict[str, str] = {
    "mlx": "MLX Auto — best available MLX model",
    "mlx-code": "MLX Code — strongest MLX coder",
    "mlx-balanced": "MLX Balanced — 8B class",
    "mlx-fast": "MLX Fast — 4B class",
    "mlx-chat": "MLX Chat — Llama 3.1 8B",
}


def mlx_provider_models() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "name": title,
            "tool_call": True,
            "limit": {"context": context, "output": 8192},
        }
        for name, (title, context) in MLX_MODELS.items()
    }


def advertised_context(tag: str, claimed: int, cap: int) -> int:
    """The window OpenCode may fill for a model, never more than we can serve.

    A client that is told 32768 for a model whose catalog entry says 16384, or
    for a model running at 2048 under memory pressure, sends prompts the gateway
    cannot fit. The advertised limit is the smallest of the claim, the catalog
    ceiling and the user's ``max_context``.
    """
    from .models import CATALOG

    spec = CATALOG.get(tag)
    ceiling = min(claimed, cap)
    if spec is not None:
        ceiling = min(ceiling, spec.max_context)
    return max(2048, ceiling)
