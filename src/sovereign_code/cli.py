"""Command-line entry point for Sovereign Code."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from . import __version__
from .clients import (
    codex_profile_path,
    install_client_wrappers,
    local_clients,
    plan_launch,
    wrapper_path,
)
from .config import (
    LOCAL_AI_ROOT,
    PROJECT_ROOT,
    Settings,
    dashboard_command_path,
    ensure_layout,
    launch_agent_path,
    write_default_config,
)
from .models import build_views, sort_views
from .ollama import OllamaClient
from .router import Task, choose, mode_label
from .status import Snapshot, collect
from .system import command_exists, login_agent_installed, qwen_config_path, qwen_memory_path
from .verify import CORE_ALIASES, EXPECTED_ALIASES, probe_aliases

LABEL = "com.user.sovereign-code"
console = Console()

GATEWAY_WATCHDOG = (
    Path.home() / "Library" / "LaunchAgents" / "com.user.ailocalgateway.watchdog.plist"
)


def _settings() -> Settings:
    ensure_layout()
    return Settings.load()


def _snapshot(settings: Settings) -> Snapshot:
    return asyncio.run(collect(settings))


def _status(snap: Snapshot) -> None:
    header = f"[bold #b794f4]Sovereign Code[/] [dim]{__version__}[/]  ·  local-first coding console"
    state = "online" if snap.ollama_up else "offline"
    console.print(Panel(header, subtitle=f"Ollama {snap.version} · {state}", expand=False))
    if snap.error:
        console.print(f"[yellow]Ollama note:[/] {snap.error}")

    table = Table(title="Runtime", show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold #8a8aa0")
    table.add_column()
    table.add_row("Ollama", f"{snap.settings.ollama_url}  [{'green' if snap.ollama_up else 'red'}]{state}[/]")
    gateway = "online" if snap.gateway.up else "offline"
    table.add_row("Gateway", f"{snap.settings.gateway_url}  [{'green' if snap.gateway.up else 'yellow'}]{gateway}[/]")
    table.add_row("Memory", snap.memory.label)
    table.add_row("Disk free", f"{snap.disk_free_gb:.0f} GB")
    table.add_row("Loopback", "yes" if snap.loopback else "[red]NO[/]")
    table.add_row("Login terminal", "installed" if snap.login_installed else "not installed")
    table.add_row("Models", f"{len(snap.installed)} installed · {len(snap.loaded)} loaded")
    console.print(table)

    if snap.loaded:
        console.print("\n[bold]Loaded[/]")
        for view in snap.loaded:
            console.print(
                f"  [green]{view.tag}[/]  ctx {view.context or '?'} · "
                f"{view.size_gb:.1f} GB"
            )

    coder = snap.recommended_coder or snap.best_coder
    if coder:
        style = "green" if coder.installed else "yellow"
        console.print(
            f"\n[bold]Coder[/]  [{style}]{coder.tag}[/]  {coder.status}"
        )
        if not coder.installed:
            console.print("  [dim]best coder not installed[/]")
            if snap.best_coder:
                console.print(f"  [dim]fallback: {snap.best_coder.tag}[/]")
            console.print(f"  [dim]pull: ollama pull {coder.tag}[/]")
    if snap.chat_selection and snap.chat_selection.model:
        console.print(
            f"[bold]Chat [/]  {snap.chat_selection.model.tag}  "
            f"[dim]({snap.chat_selection.context} ctx)[/]"
        )


def _models(snap: Snapshot) -> None:
    table = Table(title="Local models", header_style="bold #b794f4")
    table.add_column("", width=2)
    table.add_column("Model", style="bold")
    table.add_column("Role")
    table.add_column("Size", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("Status")
    table.add_column("Notes", overflow="fold")
    for view in sort_views(snap.views.values()):
        marker = "▶" if view.loaded else ("●" if view.installed else "↓")
        status = "loaded" if view.loaded else ("installed" if view.installed else "missing")
        style = "green" if view.installed else "yellow"
        table.add_row(
            marker,
            view.tag,
            view.spec.role,
            f"{view.size_gb:.1f}G",
            str(view.context or view.spec.max_context),
            f"[{style}]{status}[/]",
            view.spec.summary,
        )
    console.print(table)
    console.print("[dim]Pull the recommended coder:[/] sovereign pull-recommended")


def _verify(snap: Snapshot, all_aliases: bool = False, timeout: float = 120.0) -> int:
    if not snap.gateway.up:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway")
        return 1
    aliases = EXPECTED_ALIASES if all_aliases else CORE_ALIASES
    available = set(snap.gateway.models)
    missing = [alias for alias in aliases if alias not in available]
    if missing:
        console.print(f"[red]Missing aliases in gateway:[/] {', '.join(missing)}")

    console.print(
        f"[dim]Sending a tiny completion through {len(aliases)} aliases "
        f"(timeout {timeout:.0f}s each)...[/]"
    )
    results = probe_aliases(snap.settings.gateway_url, aliases, timeout)

    table = Table(box=None, padding=(0, 1))
    table.add_column("Alias", style="bold")
    table.add_column("Result")
    table.add_column("Time", justify="right")
    table.add_column("Reply", style="dim")
    for result in results:
        mark = "[green]PASS[/]" if result.ok else "[red]FAIL[/]"
        table.add_row(result.alias, mark, f"{result.seconds:.1f}s", result.detail)
    console.print(table)

    passed = sum(1 for result in results if result.ok)
    failed = len(results) - passed + len(missing)
    style = "green" if failed == 0 else "red"
    console.print(f"[{style}]{passed}/{len(aliases)} aliases replied[/]")
    return 0 if failed == 0 else 1


def _doctor(snap: Snapshot) -> int:
    checks: list[tuple[str, str, str, str]] = []  # status, name, detail, hint

    def add(ok: bool, name: str, detail: str, hint: str = "", warn: bool = False) -> None:
        checks.append(("PASS" if ok else ("WARN" if warn else "FAIL"), name, detail, hint))

    add(snap.ollama_up, "Ollama API", f"{snap.settings.ollama_url} · {snap.version}", "open Ollama.app")
    add(snap.loopback, "Loopback only", "Ollama and gateway are on 127.0.0.1", "never bind 0.0.0.0")
    best = snap.recommended_coder
    add(
        bool(best and best.installed),
        "Best coder",
        best.tag if best and best.installed else (
            f"14B missing; fallback is {snap.best_coder.tag}" if snap.best_coder else "no coder"
        ),
        f"ollama pull {best.tag}" if best and not best.installed else "",
        warn=True,
    )
    agent_sel = choose(
        Task.AGENT,
        snap.views,
        snap.potential_free_gb,
        max_context=snap.settings.max_context,
    )
    agent = agent_sel.model
    add(
        bool(agent),
        "Agent model",
        f"{agent.tag} · {agent_sel.context} ctx" if agent else "no agent-capable model",
        "ollama pull gemma4:12b" if not agent else "",
        warn=True,
    )
    add(snap.gateway.up, "LiteLLM gateway", f"{len(snap.gateway.models)} models", "launchctl kickstart -k gui/$(id -u)/com.user.ailocalgateway", warn=True)
    add(
        (LOCAL_AI_ROOT / "gateway" / "config.yaml").is_file(),
        "Local AI root",
        str(LOCAL_AI_ROOT),
        "sovereign install-clients",
        warn=True,
    )
    add(command_exists("qwen"), "Qwen Code CLI", shutil.which("qwen") or "missing", "npm i -g @qwen-code/qwen-code", warn=True)
    add(qwen_memory_path().is_file(), "Qwen global rules", str(qwen_memory_path()), "recreate ~/.qwen/QWEN.md", warn=True)
    add(
        codex_profile_path().is_file(),
        "Codex local profile",
        str(codex_profile_path()),
        "sovereign install-clients",
        warn=True,
    )
    add(
        wrapper_path("qwen").is_file(),
        "Client wrappers",
        "qwen-local, codex-local, claude-local" if wrapper_path("qwen").is_file() else "missing",
        "sovereign install-clients",
        warn=True,
    )
    add(login_agent_installed(), "Login terminal", "launch agent installed" if login_agent_installed() else "not installed", "sovereign install-login", warn=True)
    add(
        GATEWAY_WATCHDOG.is_file(),
        "Gateway watchdog",
        "5-minute health check" if GATEWAY_WATCHDOG.is_file() else "not installed",
        "install local-ai/launchd/com.user.ailocalgateway.watchdog.plist",
        warn=True,
    )
    add(snap.disk_free_gb >= 5, "Disk space", f"{snap.disk_free_gb:.0f} GB free", "free at least 5 GB", warn=True)
    add(snap.memory.free_gb >= 2, "Free memory", f"{snap.memory.free_gb:.1f} GB", "unload a model: ollama stop <tag>", warn=True)

    table = Table(title="Doctor", header_style="bold #b794f4")
    table.add_column("", width=4)
    table.add_column("Check", style="bold")
    table.add_column("Detail")
    table.add_column("Fix", style="dim")
    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    for status, name, detail, hint in checks:
        table.add_row(f"[{colors[status]}]{status}[/]", name, detail, hint)
    console.print(table)
    failed = sum(1 for c in checks if c[0] == "FAIL")
    warned = sum(1 for c in checks if c[0] == "WARN")
    console.print(f"[bold]{len(checks) - failed - warned} pass[/] · {warned} warn · {failed} fail")
    return 1 if failed else 0


def _install_login(start_now: bool = False) -> int:
    command = dashboard_command_path()
    if not command.is_file():
        console.print(f"[red]Missing dashboard launcher:[/] {command}")
        return 1
    command.chmod(0o755)
    plist = launch_agent_path(LABEL)
    plist.parent.mkdir(parents=True, exist_ok=True)
    text = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>Terminal</string>
    <string>{html.escape(str(command))}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>{html.escape(str(PROJECT_ROOT / 'logs' / 'login.out.log'))}</string>
  <key>StandardErrorPath</key><string>{html.escape(str(PROJECT_ROOT / 'logs' / 'login.err.log'))}</string>
</dict>
</plist>
"""
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    plist.write_text(text, encoding="utf-8")
    plist.chmod(0o644)
    console.print(f"[green]Installed[/] {plist}")
    if start_now:
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, check=False)
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            console.print(f"[yellow]launchctl bootstrap:[/] {result.stderr.strip()}")
        else:
            console.print("[green]Started[/] — Terminal should open with the live dashboard.")
    else:
        console.print("[dim]It will open automatically at your next login.[/]")
        console.print("[dim]Test it now:[/] sovereign install-login --start-now")
    return 0


def _uninstall_login() -> int:
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, check=False)
    plist = launch_agent_path(LABEL)
    if plist.exists():
        plist.unlink()
        console.print(f"[green]Removed[/] {plist}")
    else:
        console.print("[dim]Login agent was not installed.[/]")
    return 0


def _pull_recommended(settings: Settings) -> int:
    snap = _snapshot(settings)
    tag = "qwen2.5-coder:14b"
    if snap.views.get(tag) and snap.views[tag].installed:
        console.print(f"[green]{tag} is already installed.[/]")
        return 0
    console.print(f"Pulling [bold]{tag}[/] — this is the best coder that fits 24 GB.")
    client = OllamaClient(settings.ollama_url)

    async def run() -> None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed:.0f}/{task.total:.0f} units"),
            console=console,
        ) as progress:
            task = progress.add_task(f"pulling {tag}", total=None)
            async for event in client.pull(tag):
                total = event.get("total")
                completed = event.get("completed")
                if total and completed is not None:
                    if progress.tasks[task].total != float(total):
                        progress.update(task, total=float(total))
                    progress.update(task, completed=float(completed))
                status = event.get("status")
                if status:
                    progress.update(task, description=f"{tag}: {status}")
            progress.update(task, description=f"{tag}: done")

    asyncio.run(run())
    console.print(f"[green]Ready.[/] Test it: qwen --model {tag}")
    return 0


def _code(path: str, yolo: bool = False, prompt: str | None = None) -> int:
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        console.print(f"[red]Not a directory:[/] {target}")
        return 1
    if not command_exists("qwen"):
        console.print("[red]qwen is not on PATH.[/] Install: npm i -g @qwen-code/qwen-code")
        return 1
    settings = _settings()
    snap = _snapshot(settings)
    selection = choose(
        Task.AGENT,
        snap.views,
        snap.potential_free_gb,
        max_context=settings.max_context,
    )
    if not selection.model:
        console.print("[red]No local model installed.[/] Run: sovereign pull-recommended")
        return 1
    tag = selection.tag or "qwen2.5-coder:7b"
    console.print(f"[bold]Qwen Code[/] · model [green]{tag}[/] · {selection.context} ctx · {target}")
    if not qwen_memory_path().is_file():
        console.print("[yellow]Warning:[/] ~/.qwen/QWEN.md is missing; Qwen may write into ~/.qwen/projects.")
    os.chdir(target)
    os.environ["QWEN_HOME"] = str(LOCAL_AI_ROOT / "qwen")
    args = ["qwen", "--model", tag, "--approval-mode", "yolo" if yolo else "default"]
    if prompt:
        args.extend(["-p", prompt])
    os.execvp(args[0], args)
    return 0


def _gateway(snap: Snapshot) -> int:
    """Show where the gateway lives, whether it is up, and how it is supervised."""
    gateway_dir = LOCAL_AI_ROOT / "gateway"
    supervisor = bool(
        subprocess.run(
            ["pgrep", "-f", "run_gateway.sh"],
            capture_output=True,
            check=False,
        ).stdout.strip()
    )
    table = Table(title="LiteLLM gateway", header_style="bold #b794f4")
    table.add_column("", width=4)
    table.add_column("Item", style="bold")
    table.add_column("Value", overflow="fold")
    state = "[green]PASS[/]" if snap.gateway.up else "[red]FAIL[/]"
    table.add_row(state, "Gateway", f"{snap.settings.gateway_url} · {len(snap.gateway.models)} aliases")
    table.add_row(
        "[green]PASS[/]" if supervisor else "[yellow]WARN[/]",
        "Supervisor",
        "run_gateway.sh running" if supervisor else "not running (watchdog restarts it)",
    )
    table.add_row(
        "[green]PASS[/]" if GATEWAY_WATCHDOG.is_file() else "[yellow]WARN[/]",
        "Watchdog",
        "every 5 minutes" if GATEWAY_WATCHDOG.is_file() else "not installed",
    )
    table.add_row("", "Config", str(gateway_dir / "config.yaml"))
    table.add_row("", "Log", str(gateway_dir / "gateway.log"))
    table.add_row("", "Restart", "launchctl kickstart -k gui/$(id -u)/com.user.ailocalgateway")
    console.print(table)
    return 0 if snap.gateway.up else 1


def _clients(snap: Snapshot) -> None:
    table = Table(title="Local coding clients", header_style="bold #b794f4")
    table.add_column("Client", style="bold")
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Local model")
    table.add_column("Notes", overflow="fold")
    for client in local_clients():
        status = "[green]ready[/]" if client.installed else "[yellow]missing[/]"
        style = "green" if client.capability == "agent" else "cyan"
        table.add_row(
            client.name,
            status,
            f"[{style}]{client.capability}[/]",
            client.model,
            client.detail,
        )
    console.print(table)
    console.print(
        "[dim]Agent clients can write files. Chat clients are verified for local "
        "conversation; use Qwen Code for reliable local edits.[/]"
    )


def _launch(client: str, path: str, yolo: bool = False) -> int:
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        console.print(f"[red]Not a directory:[/] {target}")
        return 1
    info = {item.key: item for item in local_clients()}.get(client)
    if info is None:
        console.print(f"[red]Unknown client:[/] {client}")
        return 1
    if not info.installed:
        console.print(f"[red]{info.name} is not installed.[/] `{info.command}` is not on PATH.")
        return 1
    snap = _snapshot(_settings())
    selection = choose(
        Task.AGENT,
        snap.views,
        snap.potential_free_gb,
        max_context=snap.settings.max_context,
    )
    agent_model = selection.tag or "gemma4:12b"
    try:
        plan = plan_launch(client, target, snap.settings, agent_model, yolo=yolo)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        if client == "codex":
            console.print("[dim]Run: sovereign install-clients[/]")
        return 1
    console.print(
        f"[bold]{info.name}[/] · model [green]{plan.model}[/] · {target}"
    )
    if plan.note:
        console.print(f"[yellow]{plan.note}[/]")
    if client == "qwen" and yolo:
        console.print(
            "[yellow]YOLO mode: every local tool call is auto-approved for this session.[/]"
        )
    os.chdir(target)
    try:
        os.execvpe(plan.argv[0], plan.argv, plan.env)
    except OSError as exc:
        console.print(f"[red]Could not launch {info.name}:[/] {exc}")
        return 1
    return 0


def _install_clients() -> int:
    from .clients import write_codex_profile

    profile = write_codex_profile()
    console.print(f"[green]Codex profile[/] {profile}")
    for path in install_client_wrappers():
        console.print(f"[green]Wrapper      [/] {path}")
    console.print(
        "[dim]Use qwen-local, codex-local, or claude-local from any terminal. "
        "They do not change cloud app settings.[/]"
    )
    return 0


def _free(settings: Settings) -> int:
    snap = _snapshot(settings)
    if not snap.loaded:
        console.print("[dim]No models are resident.[/]")
        return 0
    client = OllamaClient(settings.ollama_url)

    async def run() -> None:
        for view in snap.loaded:
            try:
                await client.unload(view.tag)
                console.print(f"[green]Unloaded[/] {view.tag}")
            except Exception as exc:
                console.print(f"[yellow]Could not unload {view.tag}:[/] {exc}")

    asyncio.run(run())
    return 0


def _env(settings: Settings) -> None:
    snap = _snapshot(settings)
    tag = snap.chat_selection.tag if snap.chat_selection else "qwen3.5:4b"
    lines = [
        f'export OLLAMA_HOST="{settings.ollama_host}"',
        f'export OPENAI_BASE_URL="{settings.gateway_url}/v1"',
        'export OPENAI_API_KEY="local"',
        f'export SOVEREIGN_MODEL="{tag}"',
        f'export SOVEREIGN_OLLAMA_HOST="{settings.ollama_host}"',
        f'export ANTHROPIC_BASE_URL="{settings.gateway_url}"',
        'export ANTHROPIC_AUTH_TOKEN="local"',
        'export ANTHROPIC_API_KEY="local"',
        'export ANTHROPIC_MODEL="local-claude"',
        'export ANTHROPIC_SMALL_FAST_MODEL="local-chat"',
        'export CLAUDE_CODE_MAX_CONTEXT_TOKENS="65536"',
    ]
    print("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sovereign",
        description="Terminal-first local AI coding console.",
    )
    parser.add_argument("--version", action="version", version=f"sovereign {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("dashboard", help="open the live terminal dashboard (default)")
    sub.add_parser("status", help="one-shot system status")
    sub.add_parser("models", help="list installed and recommended models")
    sub.add_parser("doctor", help="check the local stack and print fixes")
    verify = sub.add_parser("verify", help="send a test completion through the gateway aliases")
    verify.add_argument("--all", action="store_true", help="test all nine aliases")
    verify.add_argument(
        "--timeout", type=float, default=120.0, help="per-alias timeout in seconds"
    )
    sub.add_parser("gateway", help="show gateway status, paths, and restart command")
    sub.add_parser("env", help="print shell exports for local OpenAI-compatible clients")
    sub.add_parser("clients", help="show local coding clients and their capabilities")
    sub.add_parser("install-clients", help="write the local Codex profile and client wrappers")
    sub.add_parser("free", help="unload all resident models")

    launch = sub.add_parser("launch", help="launch a local coding client in a project")
    launch.add_argument("client", choices=("qwen", "codex", "claude"))
    launch.add_argument("path", nargs="?", default=".")
    launch.add_argument("--yolo", action="store_true", help="auto-approve Qwen Code tool calls")
    sub.add_parser("pull-recommended", help="pull qwen2.5-coder:14b")
    sub.add_parser("init", help="create config/data directories and default config")

    chat = sub.add_parser("chat", help="open the dashboard in chat mode")
    chat.add_argument("--model", default=None)

    code = sub.add_parser("code", help="launch Qwen Code in a project with the best local model")
    code.add_argument("path", nargs="?", default=".")
    code.add_argument("--yolo", action="store_true", help="auto-approve tool calls (use with care)")
    code.add_argument("-p", "--prompt", default=None, help="run one prompt headlessly, then exit")

    login = sub.add_parser("install-login", help="open the dashboard in Terminal at login")
    login.add_argument("--start-now", action="store_true")
    sub.add_parser("uninstall-login", help="remove the login terminal agent")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "dashboard"
    settings = _settings()

    if command == "init":
        path = write_default_config()
        console.print(f"[green]Config[/] {path}")
        console.print(f"[green]Data  [/] {settings.config_path.parent}")
        cmd = dashboard_command_path()
        if cmd.is_file():
            cmd.chmod(0o755)
        return 0
    if command == "dashboard":
        from .tui.app import SovereignApp

        SovereignApp(settings=settings).run()
        return 0
    if command == "chat":
        from .tui.app import SovereignApp

        if getattr(args, "model", None):
            settings.default_model = args.model
        SovereignApp(settings=settings, mode="chat").run()
        return 0
    if command == "status":
        _status(_snapshot(settings))
        return 0
    if command == "models":
        _models(_snapshot(settings))
        return 0
    if command == "doctor":
        return _doctor(_snapshot(settings))
    if command == "verify":
        return _verify(_snapshot(settings), all_aliases=args.all, timeout=args.timeout)
    if command == "gateway":
        return _gateway(_snapshot(settings))
    if command == "env":
        _env(settings)
        return 0
    if command == "clients":
        _clients(_snapshot(settings))
        return 0
    if command == "install-clients":
        return _install_clients()
    if command == "launch":
        return _launch(args.client, args.path, yolo=args.yolo)
    if command == "free":
        return _free(settings)
    if command == "pull-recommended":
        return _pull_recommended(settings)
    if command == "install-login":
        return _install_login(start_now=args.start_now)
    if command == "uninstall-login":
        return _uninstall_login()
    if command == "code":
        return _code(args.path, yolo=args.yolo, prompt=args.prompt)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
