"""Write the per-client configuration that makes every tool use the same stack.

The goal is one setup command, no hand-editing: Codex and OpenCode get working
providers and an MCP server; Claude Code gets the Anthropic bridge and MCP;
Claude Desktop gets MCP; Qwen gets MCP; Continue gets a config with the same
models and the curated prompt skills.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import LOCAL_AI_ROOT


def sovereign_argv() -> list[str]:
    """Absolute command for the MCP server, safe for desktop app launchers."""
    return [str(Path(sys.executable).resolve()), "-m", "sovereign_code", "mcp"]


def _backup(path: Path) -> None:
    if not path.is_file():
        return
    target = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    try:
        shutil.copy2(path, target)
    except OSError:
        pass


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    path.write_text(text, encoding="utf-8")
    return path


def codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def claude_desktop_config_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def opencode_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "opencode.json"


def continue_config_path() -> Path:
    return Path.home() / ".continue" / "config.yaml"


def install_codex_mcp(path: Path | None = None) -> Path:
    target = path or codex_config_path()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    command, *args = sovereign_argv()
    block = (
        "[mcp_servers.sovereign]\n"
        f'command = "{command}"\n'
        f"args = [{', '.join(json.dumps(arg) for arg in args)}]\n"
        "startup_timeout_sec = 30\n"
    )
    marker = "[mcp_servers.sovereign]"
    if marker in text:
        import re

        text = re.sub(
            r"(?ms)^\[mcp_servers\.sovereign\].*?(?=^\[|\Z)",
            block + "\n",
            text,
        )
        return _write(target, text)
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
    servers["sovereign"] = {"command": command, "args": args}
    return _write(target, json.dumps(data, indent=2) + "\n")


def install_claude_code_mcp() -> str:
    if shutil.which("claude") is None:
        return "claude not installed"
    command = sovereign_argv()
    try:
        subprocess.run(
            ["claude", "mcp", "remove", "sovereign", "-s", "user"],
            capture_output=True,
            text=True,
            check=False,
        )
        result = subprocess.run(
            ["claude", "mcp", "add", "-s", "user", "sovereign", "--", *command],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"claude mcp failed: {exc}"
    return "added" if result.returncode == 0 else (result.stderr or result.stdout or "failed")[:200]


def install_qwen_mcp() -> str:
    if shutil.which("qwen") is None:
        return "qwen not installed"
    command = sovereign_argv()
    try:
        subprocess.run(
            ["qwen", "mcp", "remove", "sovereign"], capture_output=True, text=True, check=False
        )
        result = subprocess.run(
            ["qwen", "mcp", "add", "sovereign", *command],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"qwen mcp failed: {exc}"
    return "added" if result.returncode == 0 else (result.stderr or result.stdout or "failed")[:200]


OPENCODE_MODELS = {
    "qwen3-coder:30b": ("Qwen3 Coder 30B — strongest coder", 32768),
    "glm-4.7-flash": ("GLM-4.7 Flash — strongest reasoning", 32768),
    "gpt-oss:20b": ("GPT-OSS 20B — fastest strong tool caller", 16384),
    "gemma4:12b": ("Gemma 4 12B — vision", 32768),
    "qwen3.5:9b": ("Qwen3.5 9B — fast general", 32768),
    "qwen3.5:4b": ("Qwen3.5 4B — fastest", 32768),
    "deepseek-r1:8b": ("DeepSeek R1 8B — visible reasoning", 32768),
    "qwen2.5-coder:14b": ("Qwen2.5 Coder 14B — dense fallback", 32768),
    "qwen2.5-coder:7b": ("Qwen2.5 Coder 7B — small / FIM", 32768),
}


def opencode_config() -> dict:
    command = sovereign_argv()
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": "local/qwen3-coder:30b",
        "small_model": "local/qwen2.5-coder:7b",
        "provider": {
            "local": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Sovereign Ollama",
                "options": {
                    "baseURL": "http://127.0.0.1:11434/v1",
                    "apiKey": "ollama",
                },
                "models": {
                    name: {
                        "name": title,
                        "tool_call": True,
                        "limit": {"context": context, "output": 8192},
                    }
                    for name, (title, context) in OPENCODE_MODELS.items()
                },
            },
            "openrouter": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "OpenRouter",
                "options": {
                    "baseURL": "https://openrouter.ai/api/v1",
                    "apiKey": "{env:OPENROUTER_API_KEY}",
                },
                "models": {
                    "moonshotai/kimi-k3": {
                        "name": "Kimi K3",
                        "tool_call": True,
                        "limit": {"context": 131072, "output": 8192},
                    },
                    "moonshotai/kimi-k2.6": {
                        "name": "Kimi K2.6",
                        "tool_call": True,
                        "limit": {"context": 131072, "output": 8192},
                    },
                    "deepseek/deepseek-v4.1-flash": {
                        "name": "DeepSeek V4.1 Flash",
                        "tool_call": True,
                        "limit": {"context": 131072, "output": 8192},
                    },
                    "deepseek/deepseek-v4-pro": {
                        "name": "DeepSeek V4 Pro",
                        "tool_call": True,
                        "limit": {"context": 131072, "output": 8192},
                    },
                    "z-ai/glm-5.3": {
                        "name": "GLM 5.3",
                        "tool_call": True,
                        "limit": {"context": 131072, "output": 8192},
                    },
                    "z-ai/glm-5.3-flash": {
                        "name": "GLM 5.3 Flash",
                        "tool_call": True,
                        "limit": {"context": 131072, "output": 8192},
                    },
                    "z-ai/glm-5.2": {
                        "name": "GLM 5.2",
                        "tool_call": True,
                        "limit": {"context": 131072, "output": 8192},
                    },
                },
            },
        },
        "mcp": {
            "sovereign": {
                "type": "local",
                "command": command,
                "enabled": True,
            }
        },
    }


def install_opencode_mcp(path: Path | None = None) -> Path:
    target = path or opencode_config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    # Preserve a real user model choice, but make sure the working provider,
    # OpenRouter models, and MCP server are present.
    merged = opencode_config()
    merged.update({key: value for key, value in data.items() if key in {"model", "small_model"}})
    return _write(target, json.dumps(merged, indent=2) + "\n")


CONTINUE_CONFIG = """\
name: Sovereign Local
version: 1.0.0
schema: v1

models:
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
  - name: Qwen2.5 Coder 7B — autocomplete
    provider: ollama
    model: qwen2.5-coder:7b
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


def install_continue_config(path: Path | None = None) -> Path:
    target = path or continue_config_path()
    return _write(target, CONTINUE_CONFIG)


def install_all() -> list[tuple[str, str]]:
    """Configure every client. Returns (component, result) rows."""
    rows: list[tuple[str, str]] = []
    for label, fn in (
        ("Codex MCP", install_codex_mcp),
        ("Claude Desktop MCP", install_claude_desktop_mcp),
        ("OpenCode config + MCP", install_opencode_mcp),
        ("Continue config", install_continue_config),
    ):
        try:
            rows.append((label, str(fn())))
        except Exception as exc:  # setup must report, not abort the others
            rows.append((label, f"failed: {exc}"))
    rows.append(("Claude Code MCP", install_claude_code_mcp()))
    rows.append(("Qwen Code MCP", install_qwen_mcp()))
    return rows


def desktop_configs() -> dict[str, Path]:
    return {
        "codex": codex_config_path(),
        "claude_desktop": claude_desktop_config_path(),
        "opencode": opencode_config_path(),
        "continue": continue_config_path(),
        "local_ai": LOCAL_AI_ROOT,
    }
