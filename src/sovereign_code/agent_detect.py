"""Coding-agent detection for the one-command connect script.

Detects which code agents are installed on this machine (command on PATH,
application bundle, config directory) and returns a structured report that the
``agent-connect.sh`` script and the ``sovereign agents`` command use to write
per-agent configs pointing at the Sovereign gateways.

Detected agents: opencode, codex/chatgpt, claude, qwen, cursor, windsurf, zed,
aider, continue, copilot, junie, amp, roo/cline.

Nothing here touches the network; it is pure local inspection so it is safe to
run inside `curl ... | sh`.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()


@dataclass(frozen=True)
class AgentReport:
    key: str
    name: str
    installed: bool
    command: str | None = None
    config_dir: Path | None = None
    app_bundle: Path | None = None
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "installed": self.installed,
            "command": self.command,
            "config_dir": str(self.config_dir) if self.config_dir else None,
            "app_bundle": str(self.app_bundle) if self.app_bundle else None,
            "details": dict(self.details),
        }


# macOS application bundles worth checking (after PATH commands).
APP_BUNDLES: dict[str, str] = {
    "cursor": "/Applications/Cursor.app",
    "windsurf": "/Applications/Windsurf.app",
    "zed": "/Applications/Zed.app",
    "claude": "/Applications/Claude.app",
    "opencode": "/Applications/OpenCode.app",
    "codex": "/Applications/Codex.app",
    "qwen": "/Applications/Qwen.app",
    "junie": "/Applications/Junie.app",
    "amp": "/Applications/Amp.app",
    "cline": "/Applications/Roost.app",  # Roo Cline ships as Roost.app
    "copilot": "/Applications/GitHub Copilot.app",
    "continue": "/Applications/Continue.app",
    "aider": "/Applications/Aider.app",
}

# Config directories per agent (created even when the binary is not on PATH).
CONFIG_DIRS: dict[str, Path] = {
    "opencode": HOME / ".config" / "opencode",
    "codex": HOME / ".codex",
    "claude": HOME / ".claude",
    "qwen": HOME / ".config" / "qwen",
    "cursor": HOME / ".cursor",
    "windsurf": HOME / ".codeium" / "windsurf",
    "zed": HOME / ".config" / "zed",
    "aider": HOME / ".aider",
    "continue": HOME / ".continue",
    "copilot": HOME / ".github" / "copilot",
    "junie": HOME / ".junie",
    "amp": HOME / ".amp",
    "cline": HOME / ".cline",
    "roo": HOME / ".roo",
}


def _command_for(key: str) -> str | None:
    aliases = {
        "codex": ("codex", "openai-codex"),
        "claude": ("claude", "claude-code"),
        "qwen": ("qwen", "qwen-code"),
        "cursor": ("cursor",),
        "windsurf": ("windsurf",),
        "zed": ("zed",),
        "aider": ("aider", "aider-chat"),
        "continue": ("continue",),
        "copilot": ("github-copilot", "gh-copilot"),
        "junie": ("junie",),
        "amp": ("amp",),
        "cline": ("cline", "roo-cline"),
        "roo": ("roo", "roo-cline"),
        "opencode": ("opencode",),
    }
    for candidate in aliases.get(key, (key,)):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _version(command: str | None) -> str | None:
    if not command:
        return None
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = (result.stdout or result.stderr or "").strip()
        return output.splitlines()[0] if output else None
    except (OSError, subprocess.SubprocessError):
        return None


def detect_agent(key: str) -> AgentReport:
    """Detect a single agent by key."""
    command = _command_for(key)
    installed = bool(command)
    config_dir = CONFIG_DIRS.get(key)
    app_bundle = Path(APP_BUNDLES[key]) if key in APP_BUNDLES else None
    if app_bundle is not None and not app_bundle.exists():
        app_bundle = None
    details: dict[str, str] = {}
    if command:
        version = _version(command)
        if version:
            details["version"] = version
        if config_dir and config_dir.is_dir():
            details["config_exists"] = "yes"
    if app_bundle:
        details["app_bundle"] = str(app_bundle)
    return AgentReport(
        key=key,
        name=key.replace("-", " ").title(),
        installed=installed,
        command=command,
        config_dir=config_dir if config_dir and config_dir.is_dir() else None,
        app_bundle=app_bundle,
        details=details,
    )


def detect_all() -> list[AgentReport]:
    """Detect every known agent, installed ones first."""
    keys = [
        "opencode",
        "codex",
        "claude",
        "qwen",
        "cursor",
        "windsurf",
        "zed",
        "aider",
        "continue",
        "copilot",
        "junie",
        "amp",
        "cline",
        "roo",
    ]
    reports = [detect_agent(key) for key in keys]
    reports.sort(key=lambda r: (not r.installed, r.name))
    return reports


def installed_agents() -> list[AgentReport]:
    """Only the agents that are actually installed."""
    return [r for r in detect_all() if r.installed]


def any_installed() -> bool:
    return bool(installed_agents())


def agent_keys_installed() -> list[str]:
    return [r.key for r in installed_agents()]


def missing_agents() -> list[AgentReport]:
    return [r for r in detect_all() if not r.installed]


def summarize() -> str:
    installed = installed_agents()
    if not installed:
        return "No coding agents detected on this machine."
    lines = [f"{len(installed)} coding agent(s) detected:"]
    for report in installed:
        bits = [report.name]
        if report.command:
            bits.append(f"cmd={report.command}")
        if report.config_dir:
            bits.append(f"config={report.config_dir}")
        if report.app_bundle:
            bits.append(f"app={report.app_bundle}")
        lines.append("  - " + " | ".join(bits))
    return "\n".join(lines)


def gateway_targets() -> dict[str, str]:
    """Map each installed agent to the local gateway it should point at.

    These are the addresses `agent-connect.sh` writes into each agent's config.
    """
    return {
        "opencode": "http://127.0.0.1:4010/v1",
        "codex": "http://127.0.0.1:4010/v1",
        "claude": "http://127.0.0.1:4001",
        "qwen": "http://127.0.0.1:4010/v1",
        "cursor": "http://127.0.0.1:4010/v1",
        "windsurf": "http://127.0.0.1:4010/v1",
        "zed": "http://127.0.0.1:4010/v1",
        "aider": "http://127.0.0.1:4010/v1",
        "continue": "http://127.0.0.1:4010/v1",
        "copilot": "http://127.0.0.1:4010/v1",
        "junie": "http://127.0.0.1:4010/v1",
        "amp": "http://127.0.0.1:4010/v1",
        "cline": "http://127.0.0.1:4010/v1",
        "roo": "http://127.0.0.1:4010/v1",
    }
