"""Headless (non-interactive) command builders for the coding clients.

``clients.plan_launch`` builds *interactive* sessions. Long automated cycles
need one-shot runs that read a prompt, edit files and exit. Each client can run
in ``local`` mode (through the local gateway / Ollama) or ``cloud`` mode (the
user's ChatGPT / Claude subscription login, no local overrides).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .clients import plan_launch
from .config import Settings

CLIENTS = ("qwen", "codex", "claude", "opencode")
MODES = ("local", "cloud")


@dataclass(frozen=True)
class HeadlessPlan:
    client: str
    mode: str
    argv: list[str]
    cwd: Path
    env: dict[str, str]


def build_headless(
    client: str,
    mode: str,
    target: Path,
    prompt: str,
    settings: Settings,
    agent_model: str,
    unattended: bool = False,
    wall_time: int | None = None,
    max_tool_calls: int | None = 12,
) -> HeadlessPlan:
    """Build a one-shot run. ``unattended`` auto-approves tool calls (opt-in)."""
    if client not in CLIENTS:
        raise ValueError(f"unknown client: {client}")
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    target = target.expanduser().resolve()
    local = mode == "local"

    # Interactive plan supplies the local env (gateway URL, QWEN_HOME, CODEX_HOME...).
    env = plan_launch(client, target, settings, agent_model).env if local else os.environ.copy()

    if client == "qwen":
        if not local:
            raise ValueError("qwen only runs locally; use codex, claude or opencode for cloud")
        # The prompt is positional: `-p` appends whatever arrives on stdin, so
        # a run that inherits a terminal waits for input that never comes.
        argv = [
            "qwen", "--model", agent_model,
            "--approval-mode", "yolo" if unattended else "auto-edit",
        ]  # fmt: skip
        # Let the agent stop itself cleanly instead of being killed: a runaway
        # loop otherwise looks identical to a hung process. The prompt stays
        # last because it is positional.
        if wall_time:
            argv += ["--max-wall-time", f"{int(wall_time)}s"]
        if max_tool_calls is not None:
            argv += ["--max-tool-calls", str(int(max_tool_calls))]
        argv.append(prompt)
    elif client == "codex":
        argv = ["codex", "exec", "-C", str(target), "--sandbox", "workspace-write"]
        if local:
            # Codex's Responses translation through LiteLLM streams tool calls
            # as text. Its OSS path talks to Ollama directly and executes them.
            argv += ["--oss", "--local-provider", "ollama", "-m", agent_model]
        argv += ["--skip-git-repo-check", prompt]
    elif client == "claude":
        if local:
            from .bridge import ensure_running

            if not ensure_running(settings.gateway_url):
                raise ValueError("the Claude bridge did not start")
        argv = ["claude", "-p", prompt, "--permission-mode", "acceptEdits"]
        if local:
            argv += ["--model", env.get("ANTHROPIC_MODEL", "local-agent")]
    else:  # opencode
        argv = ["opencode", "run"]
        if local:
            argv += ["-m", f"local/{agent_model}"]
        if unattended:
            argv.append("--auto")
        argv.append(prompt)
    return HeadlessPlan(client, mode, argv, target, env)


def run_headless(plan: HeadlessPlan, timeout: float | None = 3600.0) -> tuple[bool, str]:
    """Run the plan and return (ok, tail-of-output)."""
    try:
        process = subprocess.run(
            plan.argv,
            cwd=str(plan.cwd),
            env=plan.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, f"{plan.argv[0]} is not installed"
    except PermissionError as exc:
        return False, f"{plan.argv[0]} is not executable: {exc}"
    except subprocess.TimeoutExpired:
        limit = f"{timeout:.0f}s" if timeout else "no limit"
        return False, f"{plan.client} timed out after {limit}"
    output = (process.stdout or "") + (process.stderr or "")
    if process.returncode != 0:
        output += f"\n[exit {process.returncode}]"
    return process.returncode == 0, output[-6000:]


def make_agent_runner(
    client: str,
    mode: str,
    target: Path,
    settings: Settings,
    agent_model: str,
    unattended: bool,
    timeout: float | None = 3600.0,
) -> Callable[[str], tuple[bool, str]]:
    """Return ``run(prompt) -> (ok, output)`` bound to one client and project."""

    def run(prompt: str) -> tuple[bool, str]:
        try:
            plan = build_headless(client, mode, target, prompt, settings, agent_model, unattended)
        except ValueError as exc:
            return False, str(exc)
        return run_headless(plan, timeout)

    return run
