"""Command-line entry point for Sovereign Code."""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import getpass
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Any, cast

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from . import __version__
from .agent_detect import (
    detect_all,
    gateway_targets,
    installed_agents,
)
from .agent_detect import (
    summarize as agent_summary,
)
from .agents import build_headless, run_headless
from .backup import create_backup
from .bench import DEFAULT_MODELS, DEFAULT_PROMPT, bench_alias
from .browser.executor import chromium_path
from .checks import detect_checks, run_checks
from .clients import (
    codex_profile_path,
    install_client_wrappers,
    local_clients,
    plan_launch,
    resolve_client_models,
    wrapper_path,
)
from .cloud import (
    ALIAS_TARGETS,
    PROVIDERS,
    ProviderError,
    apply_cloud,
    cloud_enabled,
    install_gateway_aliases,
    is_cloud_tag,
    probe_cloud,
    provider_chat,
    provider_key,
    provider_status,
    read_cloud_status,
    requested_models,
    route_for,
    set_provider_key,
)
from .config import (
    DATA_DIR,
    LOCAL_AI_ROOT,
    PROJECT_ROOT,
    Settings,
    dashboard_command_path,
    ensure_layout,
    launch_agent_path,
    write_default_config,
)
from .direct import apply_writes, build_messages, parse_blocks, relevant_files, undo_writes
from .gateway_config import (
    default_path as gateway_config_path,
)
from .gateway_config import (
    render as render_gateway_config,
)
from .gateway_config import (
    write as write_gateway_config,
)
from .harness import log_download
from .http import shared_client
from .logs import TARGETS, resolve_log_path, tail_lines
from .memory import add_memory, clear_memory, project_context, read_memory
from .models import CATALOG, CLOUD_TAG_ALIASES, CLOUD_TAGS, MODEL_STACKS, TASK_PREFERENCE
from .ollama import OllamaClient, OllamaError
from .pipeline import run_pipeline
from .promptdb import PromptDB
from .router import Task, choose
from .search import (
    DEFAULT_EMBED,
    EmbedError,
    build_index,
    index_path_for,
    search_query,
)
from .sessions import (
    export_sessions,
    prune_sessions,
    scan_sessions,
    search_sessions,
    select_prunable,
)
from .skilldb import SkillDB
from .skills import list_skills, read_skill, render_skill
from .stats import collect_stats, human_size
from .status import Snapshot, collect
from .summarize import SourceError, complete, read_text_source, summarize_text
from .system import (
    command_exists,
    listening_addresses,
    login_agent_installed,
    models_to_evict,
    ollama_runner_models,
    port_open,
    qwen_memory_path,
    swap_usage_gb,
    wired_limit_gb,
)
from .system import (
    is_loopback_host as _is_loopback_host,
)
from .tune import DEFAULT_CONTEXT, desired_env, env_drift, read_context_length, write_context_length
from .verify import (
    CORE_ALIASES,
    EXPECTED_ALIASES,
    check_embedding,
    configured_aliases,
    probe_aliases,
    probe_liveness,
)

LABEL = "com.user.sovereign-code"
console = Console()

# Client name -> the executable that must be on PATH to use it as the agent.
AGENT_CLIENTS: dict[str, str] = {
    "qwen": "qwen",
    "codex": "codex",
    "claude": "claude",
    "opencode": "opencode",
}

GATEWAY_WATCHDOG = (
    Path.home() / "Library" / "LaunchAgents" / "com.user.ailocalgateway.watchdog.plist"
)

DEFAULT_QWEN_RULES = """# Sovereign Code local rules
- Everything runs on this machine; never send code or data to a network service.
- Prefer the verified local agent model (gemma4:12b) for edits and tool calls.
- Keep generated changes minimal and reviewable.
"""


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
    table.add_row(
        "Ollama", f"{snap.settings.ollama_url}  [{'green' if snap.ollama_up else 'red'}]{state}[/]"
    )
    gateway = "online" if snap.gateway.up else "offline"
    table.add_row(
        "Gateway",
        f"{snap.settings.gateway_url}  [{'green' if snap.gateway.up else 'yellow'}]{gateway}[/]",
    )
    router = "online" if snap.router_up else "offline"
    table.add_row(
        "Tier gateway",
        f"{snap.settings.router_url}  [{'green' if snap.router_up else 'yellow'}]{router}[/]",
    )
    table.add_row("Memory", snap.memory.label)
    table.add_row("GPU budget", f"{wired_limit_gb(snap.memory.total_gb):.1f} GB wired")
    table.add_row("Disk free", f"{snap.disk_free_gb:.0f} GB")
    table.add_row("Loopback", "yes" if snap.loopback else "[red]NO[/]")
    table.add_row("Login terminal", "installed" if snap.login_installed else "not installed")
    from .services import service_states

    services = service_states(snap.settings)
    if services:
        up = sum(1 for state in services if state.pid > 0 or state.serving)
        table.add_row(
            "Services",
            f"{up}/{len(services)} running [dim](sovereign autostart)[/]",
        )
    local_installed = [view for view in snap.installed if not view.spec.cloud]
    cloud_registered = [view for view in snap.installed if view.spec.cloud]
    models_line = f"{len(local_installed)} local installed · {len(snap.loaded)} loaded"
    if cloud_registered:
        models_line += f" · {len(cloud_registered)} cloud registered"
    table.add_row("Models", models_line)
    cloud = "[green]enabled[/]" if snap.cloud_enabled else "[dim]disabled[/]"
    table.add_row("Cloud", f"{cloud} [dim](sovereign cloud)[/]")
    console.print(table)

    if snap.loaded:
        console.print("\n[bold]Loaded[/]")
        for view in snap.loaded:
            engine = f" · [cyan]{view.runner}[/]" if view.runner else ""
            console.print(
                f"  [green]{view.tag}[/]  ctx {view.context or '?'} · {view.size_gb:.1f} GB{engine}"
            )

    coder = snap.recommended_coder or snap.best_coder
    if coder:
        style = "green" if coder.installed else "yellow"
        console.print(f"\n[bold]Coder[/]  [{style}]{coder.tag}[/]  {coder.status}")
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


def _status_json(snap: Snapshot) -> int:
    """Machine-readable status, for scripts and the menu bar app."""
    import json as _json

    from .client_setup import claude_forced_local, codex_forced_local, codex_needs_openai_signin
    from .services import service_states, session_env_values

    payload = {
        "version": __version__,
        "ollama": {
            "up": snap.ollama_up,
            "url": snap.settings.ollama_url,
            "version": snap.version,
        },
        "gateway": {
            "up": snap.gateway.up,
            "url": snap.settings.gateway_url,
            "models": len(snap.gateway.models),
        },
        "router": {"up": snap.router_up, "url": snap.settings.router_url},
        "memory": {
            "total_gb": round(snap.memory.total_gb, 1),
            "free_gb": round(snap.memory.free_gb, 1),
            "free_pct": round(snap.memory.free_pct, 1),
            "known": snap.memory.known,
        },
        "disk_free_gb": round(snap.disk_free_gb, 1),
        "loopback": snap.loopback,
        "cloud_enabled": snap.cloud_enabled,
        "loaded": [
            {
                "tag": view.tag,
                "context": view.context,
                "size_gb": round(view.size_gb, 2),
                "runner": view.runner or "",
            }
            for view in snap.loaded
        ],
        "installed": sorted({view.tag for view in snap.installed if not view.spec.cloud}),
        "apps": {
            "chatgpt": {
                "local": codex_forced_local(),
                "signin_required": codex_needs_openai_signin(),
            },
            "claude": {"local": claude_forced_local()},
        },
        "services": [
            {
                "name": state.service.name,
                "label": state.service.label,
                "installed": state.installed,
                "loaded": state.loaded,
                "running": state.pid > 0,
                "serving": state.serving,
                "port": state.service.port,
            }
            for state in service_states()
        ],
        "session_env": session_env_values(),
    }
    print(_json.dumps(payload, indent=2))
    return 0


def _models_remote(snap: Snapshot, query: str | None = None) -> int:
    from .models import REMOTE_CATALOG

    installed = {view.tag for view in cast(list[Any], snap.installed)}
    rows = []
    for tag, (desc, _size_gb) in sorted(REMOTE_CATALOG.items()):
        if query and query.lower() not in tag.lower():
            continue
        spec = CATALOG.get(tag)
        if spec and spec.cloud:
            status = "[cyan]registered[/]" if tag in installed else "[cyan]cloud[/]"
            desc = f"{desc} — remote, needs Ollama Cloud"
        elif tag in installed:
            status = "[green]installed[/]"
        else:
            status = "[dim]pull[/]"
        rows.append((tag, status, desc))
    if not rows:
        console.print(f"[dim]No models match '{query}'.[/]")
        return 0
    table = Table(title="Available models (Ollama library)", header_style="bold #b794f4")
    table.add_column("Model", style="bold")
    table.add_column("Status")
    table.add_column("Notes")
    for tag, status, description in rows:
        table.add_row(tag, status, description)
    console.print(table)
    console.print("[dim]Download with: sovereign pull <tag> · run with: sovereign run <tag> '…'[/]")
    return 0


def _run(
    settings: Settings,
    model: str,
    prompt: str | None,
    context: int,
    temperature: float,
    system: str | None,
    no_pull: bool,
    keep_alive: str,
    think: bool | None,
) -> int:
    model = ALIAS_TARGETS.get(model, CLOUD_TAG_ALIASES.get(model, model))
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?", model):
        console.print(f"[red]Invalid model tag:[/] {model}")
        return 1
    if not prompt:
        console.print("[red]Give a prompt:[/] sovereign run <model> 'question'")
        return 1
    client = OllamaClient(settings.ollama_url)

    async def installed() -> bool:
        data = await client.tags()
        names = [str(item.get("name", "")) for item in data.get("models", [])]
        return any(name == model or name.startswith(model + ":") for name in names)

    # A model that is already local always wins. A `:cloud` tag is never local
    # weights, so a configured provider route may serve it even when Ollama has
    # it registered.
    was_installed = asyncio.run(installed())
    if was_installed and not is_cloud_tag(model):
        route = ("ollama", "", "", "")
    else:
        route = route_for(model)

    if not was_installed and route[0] == "ollama":
        if no_pull:
            console.print(f"[red]{model} is not installed.[/] Run: sovereign pull {model}")
            return 1
        console.print(f"[dim]{model} is not installed; pulling it first…[/]")
        if _pull(settings, model, "run on demand") != 0:
            return 1

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if route[0] != "ollama":
        # `run` talks to the provider directly, so it works immediately after
        # --set-key without re-installing gateway aliases.
        console.print(f"[dim]Running {model} via {route[0]} · {route[1]}…[/]\n")
        try:
            answer = provider_chat(
                route,
                messages,
                max_tokens=max(512, min(context, 8192)),
                temperature=temperature,
            )
        except ProviderError as exc:
            console.print(f"[red]{exc}[/]")
            return 1
        console.print(Text(answer))
        console.print()
        return 0

    console.print(
        f"[dim]Running {model} (ctx={context}, temp={temperature}, keep_alive={keep_alive})…[/]\n"
    )
    try:

        async def stream() -> None:
            async for chunk in client.chat_stream(
                model,
                messages,
                context=context,
                temperature=temperature,
                think=think,
                keep_alive=keep_alive,
            ):
                if chunk.content:
                    console.print(Text(chunk.content), end="")
                if chunk.thinking:
                    console.print(Text(chunk.thinking, style="dim #8a8aa0"), end="")

        asyncio.run(stream())
    except OllamaError as exc:
        console.print(f"\n[red]{exc}[/]")
        return 1
    console.print()
    return 0


def _rm(model: str) -> int:
    model = CLOUD_TAG_ALIASES.get(model, model)
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?", model):
        console.print(f"[red]Invalid model tag:[/] {model}")
        return 1
    console.print(f"[dim]Removing {model}…[/]")
    result = subprocess.run(["ollama", "rm", model], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        console.print(f"[red]{detail}[/]")
        return 1
    console.print(f"[green]Removed {model}.[/]")
    return 0


def _model_info(settings: Settings, tag: str) -> int:
    tag = CLOUD_TAG_ALIASES.get(tag, tag)
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?", tag):
        console.print(f"[red]Invalid model tag:[/] {tag}")
        return 1
    client = OllamaClient(settings.ollama_url)
    try:
        data = asyncio.run(client.show(tag))
    except OllamaError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    details = data.get("details") or {}
    model_info = data.get("model_info") or {}
    table = Table(title=f"Model info · {tag}", header_style="bold #b794f4")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for field, value in [
        ("Parameter size", details.get("parameter_size")),
        ("Quantization", details.get("quantization_level")),
        ("Family", ", ".join(details.get("families") or []) or details.get("family")),
        ("Context length", model_info.get("context_length")),
        ("Format", details.get("format")),
    ]:
        if value not in (None, ""):
            table.add_row(field, str(value))
    console.print(table)
    spec = CATALOG.get(tag)
    if spec and spec.cloud:
        console.print(
            "[cyan]Cloud model[/] · served by ollama.com · no local weights · "
            "prompts leave this Mac"
        )
        if not cloud_enabled():
            console.print("[yellow]Cloud is disabled.[/] Run: sovereign cloud --enable")
        return 0
    snap = _snapshot(settings)
    view = snap.views.get(tag)
    if view and view.installed:
        console.print(
            f"[green]Installed[/] · {view.size_gb:.1f} GB · "
            f"{'loaded' if view.loaded else 'not loaded'}"
        )
    else:
        console.print(f"[dim]Not installed locally.[/]  Run: sovereign pull {tag}")
    return 0


def _parse_gateway_aliases(path: Path) -> list[tuple[str, str]]:
    """Return [(alias, ollama_tag)] from the gateway config.yaml model_list."""
    aliases: list[tuple[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return aliases
    current_alias: str | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- model_name:"):
            current_alias = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("model:") and current_alias is not None:
            value = stripped.split(":", 1)[1].strip()
            tag = value[len("ollama/") :] if value.startswith("ollama/") else value
            aliases.append((current_alias, tag))
            current_alias = None
    return aliases


def _gateway_aliases(snap: Snapshot) -> int:
    path = LOCAL_AI_ROOT / "gateway" / "config.yaml"
    aliases = _parse_gateway_aliases(path)
    if not aliases:
        console.print(f"[yellow]No gateway aliases found at[/] {path}")
        console.print("[dim]Run: sovereign gateway --restart[/]")
        return 1
    table = Table(title="Gateway aliases → Ollama models", header_style="bold #b794f4")
    table.add_column("Alias", style="bold")
    table.add_column("Ollama model", style="bold")
    table.add_column("Installed")
    table.add_column("Size", justify="right")
    missing = []
    for alias, tag in aliases:
        clean_tag = tag.strip("\"'")
        if clean_tag.startswith("openai/"):
            table.add_row(alias, "OpenAI cloud passthrough", "[dim]passthrough[/]", "-")
            continue
        view = snap.views.get(clean_tag) or (
            snap.views.get(f"{clean_tag}:latest")
            if ":" not in clean_tag
            else snap.views.get(clean_tag.removesuffix(":latest"))
        )
        if view and view.installed and view.spec.cloud:
            inst = "[cyan]cloud[/]"
            size = "remote"
        elif view and view.installed:
            inst = "[green]yes[/]"
            size = f"{view.size_gb:.1f} GB"
        else:
            inst = "[yellow]no[/]"
            size = "-"
            missing.append((alias, clean_tag))
        table.add_row(alias, clean_tag, inst, size)
    console.print(table)
    if any(":cloud" in tag for _alias, tag in aliases) and not cloud_enabled():
        console.print(
            "[yellow]Cloud is disabled:[/] the :cloud aliases will fail until "
            "`sovereign cloud --enable`."
        )
    if missing:
        console.print("\n[yellow]Aliases pointing to missing models:[/]")
        for alias, tag in missing:
            console.print(f"  {alias} → {tag}   (sovereign pull {tag})")
        console.print(
            "[dim]Codex / Claude / ChatGPT local clients route through these aliases via `sovereign env`.[/]"
        )
        return 1
    console.print("\n[green]All gateway aliases route to installed models.[/]")
    return 0


def _pull_stack(settings: Settings, name: str, yes: bool = False) -> int:
    from .models import REMOTE_CATALOG

    if name not in MODEL_STACKS:
        console.print(f"[red]Unknown stack:[/] {name}. Stacks: {', '.join(sorted(MODEL_STACKS))}")
        return 1
    stack = MODEL_STACKS[name]
    models = cast(list[Any], stack["models"])
    snap = _snapshot(settings)
    installed = {view.tag for view in cast(list[Any], snap.installed)}
    to_pull = [m for m in models if m not in installed]
    if not to_pull:
        console.print(f"[green]Stack '{name}' is already fully installed.[/]")
        return 0
    total_est = sum(REMOTE_CATALOG.get(m, ("", 0.0))[1] for m in to_pull)
    console.print(f"[bold]Stack {name}[/] · {len(to_pull)} model(s) to pull · ~{total_est:.0f} GB")
    console.print(f"[dim]{' · '.join(to_pull)}[/]")
    if snap.disk_free_gb < max(2.0, total_est + 2.0):
        console.print(
            f"[yellow]Warning:[/] only {snap.disk_free_gb:.0f} GB free; stack needs ~{total_est:.0f} GB. "
            "Free space or remove a model first (`sovereign rm <tag>`)."
        )
    if not yes:
        try:
            if input(
                f"Pull {len(to_pull)} model(s) for stack '{name}'? [y/N] "
            ).strip().lower() not in {"y", "yes"}:
                console.print("[dim]Cancelled.[/]")
                return 1
        except EOFError:
            console.print("[dim]Cancelled.[/]")
            return 1
    for tag in to_pull:
        console.print()
        if _pull(settings, tag, f"stack {name}") != 0:
            console.print(f"[red]Stopping stack at {tag}.[/]")
            return 1
    console.print(f"\n[green]Stack '{name}' complete.[/] Run: sovereign models")
    return 0


def _setup_stack(settings: Settings, name: str, yes: bool = False) -> int:
    code = _pull_stack(settings, name, yes=yes)
    if code != 0:
        return code
    snap = _snapshot(settings)
    return _gateway_aliases(snap)


def _setup(
    settings: Settings,
    *,
    models: str = "recommended",
    yes: bool = False,
    clients: bool = True,
    services: bool = True,
    login: bool = True,
    migrate: bool = True,
    dry_run: bool = False,
    open_monitor: bool = False,
) -> int:
    from . import setup as setup_mod

    steps = setup_mod.run_setup(
        settings,
        models=models,
        yes=yes,
        clients=clients,
        services=services,
        login=login,
        migrate=migrate,
        dry_run=dry_run,
    )
    for step in steps:
        mark = {"ok": "[green]OK[/]", "fail": "[red]FAIL[/]", "skip": "[dim]SKIP[/]"}.get(
            step.mark, step.mark
        )
        console.print(f"{mark}  {step.name:<14} {step.detail}")
    if any((not step.ok) and (not step.skipped) for step in steps):
        return 1
    for line in setup_mod.ready_summary():
        console.print(line)
    if open_monitor:
        from .tui.monitor import MonitorApp

        MonitorApp(settings=settings).run()
    return 0


def _context_label(tokens: int | None) -> str:
    """Compact context sizes: 1M reads better than 1048576 in a table."""
    if not tokens:
        return "?"
    if tokens >= 1_000_000:
        return f"{tokens / 1_048_576:.0f}M"
    if tokens >= 1024:
        return f"{round(tokens / 1024)}k"
    return str(tokens)


def _models(snap: Snapshot) -> None:
    local = [view for view in snap.all_models if not view.spec.cloud]
    cloud = [view for view in snap.all_models if view.spec.cloud]

    table = Table(title="Local models", header_style="bold #b794f4")
    table.add_column("", width=2)
    table.add_column("Model", style="bold")
    table.add_column("Role")
    table.add_column("Size", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("Status")
    table.add_column("Notes", overflow="fold")
    for view in local:
        marker = "▶" if view.loaded else ("●" if view.installed else "↓")
        status = "loaded" if view.loaded else ("installed" if view.installed else "missing")
        style = "green" if view.installed else "yellow"
        table.add_row(
            marker,
            view.tag,
            view.spec.role,
            f"{view.size_gb:.1f}G",
            _context_label(view.context or view.spec.max_context),
            f"[{style}]{status}[/]",
            view.spec.summary,
        )
    console.print(table)

    if cloud:
        ctable = Table(
            title="Cloud models · remote, prompts leave this Mac",
            header_style="bold #b794f4",
        )
        ctable.add_column("", width=2)
        ctable.add_column("Model", style="bold")
        ctable.add_column("Role")
        ctable.add_column("Context", justify="right")
        ctable.add_column("Status")
        ctable.add_column("Notes", overflow="fold")
        for view in cloud:
            if view.installed:
                status, style = "registered", "green"
            else:
                status, style = "not pulled", "yellow"
            ctable.add_row(
                "☁",
                view.tag,
                view.spec.role,
                _context_label(view.spec.max_context),
                f"[{style}]{status}[/]",
                view.spec.summary,
            )
        console.print(ctable)
        console.print(
            "[dim]Enable once with[/] sovereign cloud --enable "
            "[dim]then pull a tag;[/] sovereign cloud [dim]shows the mapping.[/]"
        )
    else:
        console.print("[dim]Pull the recommended coder:[/] sovereign pull-recommended")


def _verify(
    snap: Snapshot,
    all_aliases: bool = False,
    timeout: float = 120.0,
    embedding: bool = False,
) -> int:
    if not snap.gateway.up:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway")
        return 1

    # Fail fast: a hung Ollama answers /api/version but queues every completion,
    # so probing each alias would sit through the full timeout for each one.
    live = probe_liveness(snap.settings.ollama_url)
    if not live.ok:
        console.print(f"[red]Ollama is not serving:[/] {live.detail}")
        console.print("[dim]Restart it with: sovereign tune[/]")
        return 1

    aliases = (
        configured_aliases(LOCAL_AI_ROOT / "gateway" / "config.yaml") or EXPECTED_ALIASES
        if all_aliases
        else CORE_ALIASES
    )
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
    if embedding:
        ok, detail = check_embedding(snap.settings.ollama_url)
        mark = "[green]PASS[/]" if ok else "[red]FAIL[/]"
        console.print(f"Embedding  {mark} {detail}")
        failed += 0 if ok else 1
    style = "green" if failed == 0 else "red"
    console.print(f"[{style}]{passed}/{len(aliases)} aliases replied[/]")
    return 0 if failed == 0 else 1


def _bench(
    settings: Settings,
    models: list[str],
    max_tokens: int,
    prompt: str,
) -> int:
    import httpx

    base = settings.gateway_url.rstrip("/")
    try:
        shared_client().get(f"{base}/v1/models", timeout=3.0).raise_for_status()
    except httpx.HTTPError:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway --restart")
        return 1

    table = Table(title=f"Local throughput · max {max_tokens} tokens", header_style="bold #b794f4")
    table.add_column("Alias", style="bold")
    table.add_column("Prompt", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Speed", justify="right")
    for alias in models:
        console.print(f"[dim]Benchmarking {alias}…[/]")
        result = bench_alias(base, alias, prompt, max_tokens=max_tokens)
        if result.ok:
            speed = f"[green]{result.tokens_per_second:.1f} t/s[/]"
        else:
            speed = f"[red]{result.detail}[/]"
        table.add_row(
            alias,
            str(result.prompt_tokens),
            str(result.completion_tokens),
            f"{result.seconds:.1f}s",
            speed,
        )
    console.print(table)
    console.print(
        "[dim]First call per alias may include model load time; rerun for steady-state.[/]"
    )
    return 0


def _logs(target: str, lines: int = 40, follow: bool = False) -> int:
    path = resolve_log_path(target)
    if not path.is_file():
        console.print(f"[yellow]No {target} log at[/] {path}")
        if target == "gateway":
            console.print("[dim]Start it with: sovereign gateway --restart[/]")
        elif target == "dashboard":
            console.print("[dim]Install the login terminal: sovereign install-login[/]")
        return 1
    if follow:
        console.print(f"[dim]Following {path} — Ctrl+C to stop[/]")
        try:
            subprocess.call(["/usr/bin/tail", "-n", str(max(1, lines)), "-F", str(path)])
        except KeyboardInterrupt:
            pass
        return 0
    content = tail_lines(path, lines)
    console.print(f"[dim]{path} · last {len(content)} lines[/]")
    if content:
        sys.stdout.write("\n".join(content) + "\n")
    return 0


def _age(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def _coerce_setting(value: str, current: object) -> object:
    if current is None:
        return value if value != "" else None
    if isinstance(current, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def _config(settings: Settings, get_key: str | None, set_value: str | None) -> int:
    names = [field.name for field in dc_fields(settings)]
    if set_value is not None:
        key, separator, value = set_value.partition("=")
        key = key.strip()
        if not separator or key not in names:
            console.print("[red]Usage:[/] sovereign config --set KEY=VALUE")
            console.print(f"[dim]Keys: {', '.join(names)}[/]")
            return 1
        try:
            coerced = _coerce_setting(value.strip(), getattr(settings, key))
        except (ValueError, TypeError):
            console.print(f"[red]Could not set[/] {key} = {value!r}")
            return 1
        setattr(settings, key, coerced)
        settings.save()
        console.print(f"[green]Set[/] {key} = {coerced!r}")
        return 0
    if get_key is not None:
        key = get_key.strip()
        if key not in names:
            console.print(f"[red]Unknown key[/] {key}")
            return 1
        console.print(f"{key} = {getattr(settings, key)!r}")
        return 0
    table = Table(title="Sovereign config", header_style="bold #b794f4")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for name in names:
        table.add_row(name, repr(getattr(settings, name)))
    console.print(table)
    console.print("[dim]Edit a value: sovereign config --set KEY=VALUE[/]")
    return 0


def _stats() -> int:
    stats = collect_stats()
    table = Table(title="Local AI stack · disk usage", header_style="bold #b794f4")
    table.add_column("Component", style="bold")
    table.add_column("Size", justify="right")
    total = 0
    for name, info in stats.items():
        table.add_row(name, str(info["human"]))
        total += int(info["bytes"])
    console.print(table)
    console.print(f"[bold]Total[/] {human_size(total)}")
    console.print(
        "[dim]Generated dirs (legacy archive, browser profile, search index) can be "
        "removed manually if unneeded.[/]"
    )
    return 0


def _sessions(
    days: float = 30,
    keep: int = 50,
    prune: bool = False,
    dry_run: bool = False,
    limit: int = 20,
    search: str | None = None,
    export: str | None = None,
) -> int:
    if export:
        count = export_sessions(Path(export))
        console.print(f"[green]Exported {count} records[/] to {export}")
        return 0
    if search:
        matches = search_sessions(search)
        if not matches:
            console.print(f"[dim]No chats mention '{search}'.[/]")
            return 0
        table = Table(title=f"Chat search · {search}", header_style="bold #b794f4")
        table.add_column("Session", style="bold")
        table.add_column("Role")
        table.add_column("Snippet", overflow="fold")
        for match in matches:
            table.add_row(str(match["path"]), str(match["role"]), str(match["snippet"]))
        console.print(table)
        return 0
    infos = scan_sessions()
    if not infos:
        console.print("[dim]No chat sessions stored yet.[/]")
        return 0

    if prune:
        victims = select_prunable(infos, days=days, keep=keep)
        if not victims:
            console.print(
                f"[green]Nothing to prune[/] · {len(infos)} sessions, "
                f"keep newest {keep}, retention {days:g} days"
            )
            return 0
        if dry_run:
            for info in victims:
                console.print(f"[yellow]would delete[/] {info.path.name}")
            console.print(f"[dim]{len(victims)} of {len(infos)} sessions qualify[/]")
            return 0
        removed = prune_sessions(victims)
        console.print(f"[green]Removed {removed} sessions[/] · kept {len(infos) - removed}")
        return 0

    table = Table(title="Chat sessions", header_style="bold #b794f4")
    table.add_column("Session", style="bold")
    table.add_column("Model")
    table.add_column("Messages", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Age", justify="right")
    now = time.time()
    for info in infos[: max(1, limit)]:
        table.add_row(
            info.path.name,
            info.model,
            str(info.messages),
            f"{info.size_kb:.1f} KB",
            _age(now - info.modified),
        )
    console.print(table)
    total_kb = sum(info.size_kb for info in infos)
    console.print(
        f"[dim]{len(infos)} sessions · {total_kb:.1f} KB · "
        f"prune with: sovereign sessions --prune[/]"
    )
    return 0


def _browse(args, settings: Settings) -> int:
    try:
        import playwright  # noqa: F401
    except ImportError:
        console.print("[red]Playwright is not installed.[/]")
        console.print(
            "[dim].venv/bin/pip install playwright && .venv/bin/playwright install chromium[/]"
        )
        return 1

    from .browser.actions import BrowserPolicy, PolicyError, check_url, parse_action
    from .browser.agent import AuditLog, BrowserAgent, ModelPlanner
    from .browser.executor import BrowserError, BrowserSession

    policy = BrowserPolicy(
        allow_local=args.allow_local,
        allowed_domains=tuple(args.allow_domain),
    )
    if not args.url:
        console.print(
            "[red]Give a starting URL:[/] sovereign browse https://example.com --task '…'"
        )
        return 1
    raw_url = args.url if "://" in args.url else f"https://{args.url}"
    try:
        start_url = check_url(raw_url, policy)
    except PolicyError as exc:
        console.print(f"[red]Blocked URL:[/] {exc}")
        return 1

    profile = LOCAL_AI_ROOT / "data" / "browser" / "profile"
    session = BrowserSession(
        profile_dir=profile,
        policy=policy,
        headless=args.headless,
        timeout_ms=15000,
    )
    try:
        session.start(start_url)
    except Exception as exc:
        console.print(f"[red]Could not start Chromium:[/] {exc}")
        session.close()
        return 1

    if not args.task:
        console.print("[bold]Browser open.[/] Use it normally; press Enter here to close.")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            session.close()
        return 0

    import httpx

    try:
        probe = shared_client().get(f"{settings.gateway_url.rstrip('/')}/v1/models", timeout=3.0)
        if probe.status_code != 200:
            raise httpx.HTTPError("not ok")
    except httpx.HTTPError:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway --restart")
        session.close()
        return 1

    planner = ModelPlanner(settings.gateway_url, model=args.model)
    audit = None

    def confirm(message: str) -> bool:
        if args.yes:
            console.print(f"[yellow]{message}[/] [dim]auto-approved by --yes[/]")
            return True
        try:
            return input(f"{message} [y/N] ").strip().lower() in {"y", "yes"}
        except EOFError:
            return False

    def pause(message: str) -> None:
        console.print(f"[yellow]{message}[/]")
        try:
            input("Press Enter when ready…")
        except (EOFError, KeyboardInterrupt):
            pass

    try:
        if args.dry_run:
            observation = session.observe()
            console.print(
                f"[bold]{observation.get('title') or '(untitled)'}[/] · "
                f"{observation.get('url')} · {len(observation.get('elements', []))} elements"
            )
            if observation.get("captcha"):
                console.print("[yellow]CAPTCHA or bot check detected; the agent would hand off.[/]")
            raw = planner.plan(args.task, observation, [])
            console.print(Panel(Text(raw), title="first planned action", border_style="cyan"))
            try:
                action = parse_action(raw)
            except Exception as exc:
                console.print(f"[red]Invalid action:[/] {exc}")
                return 1
            console.print(f"[green]Parsed:[/] {action.kind} {action.as_dict()}")
            return 0

        audit = AuditLog()
        agent = BrowserAgent(
            session=session,
            planner=planner,
            policy=policy,
            max_steps=args.max_steps,
            headless=args.headless,
            confirm=confirm,
            pause=pause,
            audit=audit,
            screenshots_dir=(
                LOCAL_AI_ROOT / "data" / "browser" / "screenshots" if args.screenshots else None
            ),
        )
        result = agent.run(args.task)
    except (BrowserError, PolicyError) as exc:
        console.print(f"[red]Browser error:[/] {exc}")
        return 1
    except KeyboardInterrupt:
        console.print("[yellow]Stopped by user.[/]")
        return 130
    finally:
        session.close()
        if audit is not None:
            audit.close()

    style = "green" if result.stopped == "done" else "yellow"
    console.print(
        Panel(
            Text(result.summary),
            title=f"browse · {result.stopped} · {result.steps} steps",
            border_style=style,
        )
    )
    for index, text in enumerate(result.extracts, start=1):
        console.print(Panel(Text(text[:2000]), title=f"extract {index}", border_style="dim"))
    if audit is not None:
        console.print(f"[dim]Audit: {audit.path}[/]")
    return 0 if result.stopped in {"done", "handoff", "cancelled"} else 1


def _ensure_skill_index() -> str:
    """Open the skill index read-write so its indexes exist.

    The dashboard reads the index read-only, so it can never create the
    covering index itself. Opening it once here turns a 2.6 second scan on
    every refresh into a lookup that answers in under a millisecond.
    """
    from .skilldb import SkillDB

    path = DATA_DIR / "skills.db"
    if not path.is_file():
        return "no skill index yet · run: sovereign skill-db sync"
    with SkillDB(path) as store:
        count = store.count()
    return f"{count} skills indexed"


def _doctor_fix(settings: Settings, snap: Snapshot) -> int:
    from .clients import install_client_wrappers, write_codex_profile
    from .config import write_default_config

    rows: list[tuple[str, str, str]] = []

    def run(label: str, fn) -> None:
        try:
            result = fn()
            rows.append(("[green]FIXED[/]", label, str(result)))
        except Exception as exc:
            rows.append(("[red]FAILED[/]", label, str(exc)))

    run("config", lambda: write_default_config())

    # The skill index is created read-write, and the dashboard only ever
    # reads it. Without this the dashboard keeps paying a full scan of a
    # 400 MB table until something else opens the database.
    run("skill index", lambda: _ensure_skill_index())

    # A hung Ollama answers /api/version, so check that it actually serves and
    # recover it here rather than making the user work out why nothing replies.
    has_embed = any("embed" in view.tag for view in snap.installed)
    if snap.ollama_up and has_embed:
        live = probe_liveness(snap.settings.ollama_url)
        if not live.ok:
            from .tune import current_server_env, restart_ollama

            def _restart() -> str:
                restart_ollama(env=desired_env())
                for _ in range(30):
                    if probe_liveness(settings.ollama_url).ok:
                        break
                    time.sleep(1)
                env = current_server_env()
                return f"restarted (context {env.get('OLLAMA_CONTEXT_LENGTH', '?')})"

            run("ollama liveness", _restart)
    if not login_agent_installed():
        run("login agent", lambda: (_install_login(False), "installed")[1])
    run("client wrappers", lambda: f"{len(install_client_wrappers())} wrappers")
    run("codex profile", lambda: write_codex_profile())

    # The desktop apps can drift back to the cloud when their own settings are
    # changed, so the doctor puts them back on the local path.
    from .client_setup import (
        claude_forced_local,
        codex_forced_local,
        install_claude_settings,
        install_codex_forced_local,
    )

    if not codex_forced_local():
        run("chatgpt local config", lambda: install_codex_forced_local())
    if not claude_forced_local():
        run("claude local settings", lambda: install_claude_settings())

    def _launcher() -> str:
        command = dashboard_command_path()
        if not command.is_file():
            raise FileNotFoundError(f"missing {command}")
        command.chmod(0o755)
        return "chmod +x"

    run("dashboard launcher", _launcher)

    if not any("embed" in view.tag for view in snap.installed):

        def _embedding() -> str:
            code = _pull(settings, "nomic-embed-text", "embedding model")
            if code != 0:
                raise RuntimeError("pull failed")
            return "pulled nomic-embed-text"

        run("embedding model", _embedding)

    if not qwen_memory_path().is_file():

        def _rules() -> str:
            path = qwen_memory_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_QWEN_RULES, encoding="utf-8")
            return str(path)

        run("Qwen global rules", _rules)

    table = Table(title="Applied fixes", header_style="bold #b794f4")
    table.add_column("", width=7)
    table.add_column("Item", style="bold")
    table.add_column("Result", overflow="fold")
    for status, label, result in rows:
        table.add_row(status, label, result)
    console.print(table)
    console.print("[dim]Re-running doctor…[/]")
    return _doctor(_snapshot(settings))


def _undo(path: str | None = None) -> int:
    target = Path(path).expanduser().resolve() if path else Path.cwd()
    restored = undo_writes(target)
    if not restored:
        console.print("[dim]Nothing to undo: no recorded change.[/]")
        return 0
    console.print(f"[green]Restored {len(restored)} file(s):[/] " + ", ".join(restored))
    return 0


def _backup(keep: int | None = None) -> int:
    include = [LOCAL_AI_ROOT / "config" / "sovereign", LOCAL_AI_ROOT / "data"]
    exclude = {LOCAL_AI_ROOT / "data": ("browser", "index")}
    extra = {
        LOCAL_AI_ROOT / "config" / "codex" / "local.config.toml": "config/codex/local.config.toml"
    }
    try:
        path = create_backup(
            include,
            LOCAL_AI_ROOT / "backups",
            exclude=cast(dict[Any, Any], exclude),
            extra_files=extra,
            root=LOCAL_AI_ROOT,
        )
    except Exception as exc:
        console.print(f"[red]Backup failed:[/] {exc}")
        return 1
    console.print(f"[green]Backup[/] {path} ({path.stat().st_size / 1024:.1f} KB)")
    console.print(
        "[dim]Contains configs and data/ (sessions, logs, audit); excludes models, "
        "venv, Codex caches, and the browser profile.[/]"
    )
    if keep is not None:
        from .backup import prune_backups

        removed = prune_backups(LOCAL_AI_ROOT / "backups", keep)
        if removed:
            console.print(f"[dim]Pruned {removed} older backup(s) (keeping {keep}).[/]")
    return 0


def _index(settings: Settings, path: str, model: str, limit: int | None) -> int:
    root = Path(path or ".").expanduser().resolve()
    if not root.is_dir():
        console.print(f"[red]Not a directory:[/] {root}")
        return 1
    console.print(f"[dim]Indexing {root} with {model}…[/]")
    try:
        files, chunks, store = build_index(root, settings.ollama_url, model=model, limit=limit)
    except EmbedError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    console.print(f"[green]Indexed[/] {files} files · {chunks} chunks")
    console.print(f"[dim]Index: {store.db_path}[/]")
    store.close()
    return 0


def _search(settings: Settings, query: str, path: str, model: str, top: int) -> int:
    root = Path(path or ".").expanduser().resolve()
    db = index_path_for(root)
    if not db.is_file():
        console.print(f"[red]No index for {root}.[/] Run: sovereign index {path or '.'}")
        return 1
    try:
        results = search_query(settings.ollama_url, db, query, model=model, top=top)
    except EmbedError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    if not results:
        console.print("[dim]No matching chunks.[/]")
        return 0
    table = Table(title=f"Search · {query}", header_style="bold #b794f4")
    table.add_column("Score", justify="right")
    table.add_column("Location", style="bold")
    table.add_column("Snippet", overflow="fold")
    for result in results:
        snippet = " ".join(result.text.split())[:160]
        table.add_row(
            f"{result.score:.2f}",
            f"{result.path}:{result.line}",
            snippet,
        )
    console.print(table)
    return 0


def _summarize(
    settings: Settings,
    path: str | None,
    url: str | None,
    model: str,
    max_chars: int,
    max_tokens: int,
) -> int:
    try:
        text = read_text_source(path=path, url=url, max_chars=max_chars)
    except SourceError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    console.print(f"[dim]Summarizing {len(text)} chars via {model}…[/]")
    try:
        summary = summarize_text(settings.gateway_url, model, text, max_tokens=max_tokens)
    except SourceError as exc:
        console.print(f"[red]{exc}[/]")
        console.print("[dim]Start the gateway: sovereign gateway --restart[/]")
        return 1
    console.print(Panel(Text(summary), title="summary", border_style="cyan"))
    return 0


def _tune(context: int, dry_run: bool = False) -> int:
    """Apply and verify Ollama runtime tuning. macOS only."""
    from .tune import current_server_env, restart_ollama, set_session_env, supported

    if not supported():
        console.print("[red]tune is macOS-only.[/]")
        return 1

    target = max(2048, int(context))
    current = current_server_env()
    desired = desired_env(target)
    drift = env_drift(current, desired)
    db_context = read_context_length()
    db_change = db_context is not None and db_context != target

    if not current:
        console.print("[yellow]Ollama is not running.[/] Start it, then re-run tune.")
        return 1
    if not drift and not db_change:
        console.print(
            f"[green]Already tuned[/] · context {target} · q8 KV · flash attention active"
        )
        return 0

    table = Table(title="Planned changes", header_style="bold #b794f4")
    table.add_column("Setting")
    table.add_column("Now")
    table.add_column("Wanted")
    for key, old_value, wanted in drift:
        table.add_row(key, old_value or "[dim]unset[/]", wanted)
    if db_change:
        table.add_row("app context_length", str(db_context), str(target))
    console.print(table)

    if dry_run:
        console.print("[dim]Dry run: nothing applied.[/]")
        return 0

    set_session_env(desired)
    if db_change:
        write_context_length(target)
    console.print("[dim]Restarting Ollama so the server inherits the new env…[/]")
    restart_ollama(env=desired)
    for _ in range(30):
        if port_open("127.0.0.1", 11434):
            break
        time.sleep(1)

    after = current_server_env()
    remaining = env_drift(after, desired)
    if remaining:
        console.print("[yellow]Still differs after restart:[/]")
        for key, now, wanted in remaining:
            console.print(f"  {key}: {now or 'unset'} -> {wanted}")
        console.print("[dim]The app may hold a cached value; quit Ollama fully and retry.[/]")
        return 1
    console.print(f"[green]Tuned[/] · context {target} · q8 KV · flash attention active")
    return 0


def _doctor(snap: Snapshot) -> int:
    checks: list[tuple[str, str, str, str]] = []  # status, name, detail, hint

    def add(ok: bool, name: str, detail: str, hint: str = "", warn: bool = False) -> None:
        checks.append(("PASS" if ok else ("WARN" if warn else "FAIL"), name, detail, hint))

    add(
        snap.ollama_up,
        "Ollama API",
        f"{snap.settings.ollama_url} · {snap.version}",
        "open Ollama.app",
    )
    if snap.exposed_ports:
        exposed = ", ".join(
            f"{port} on {', '.join(addresses)}" for port, addresses in snap.exposed_ports.items()
        )
        add(
            False,
            "Loopback only",
            f"exposed: {exposed}",
            "bind the service to 127.0.0.1, never 0.0.0.0",
        )
    else:
        add(
            snap.loopback,
            "Loopback only",
            "Ollama and gateway are on 127.0.0.1",
            "never bind 0.0.0.0",
        )
    best = snap.recommended_coder
    add(
        bool(best and best.installed),
        "Best coder",
        best.tag
        if best and best.installed
        else (f"14B missing; fallback is {snap.best_coder.tag}" if snap.best_coder else "no coder"),
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

    # --- hardware guardrails -------------------------------------------------
    # Apple silicon reserves ~75% of unified memory for the GPU. A model that
    # fills that budget never leaves room for KV cache or a second model, and
    # Ollama *hangs* rather than erroring, blocking every later request until
    # it is restarted. Judge by weights + a small KV allowance, not by RAM.
    wired = wired_limit_gb(snap.memory.total_gb)
    coder_sel = snap.code_selection or agent_sel
    coder = coder_sel.model
    weights = max(coder.size_gb, coder.spec.size_gb) if coder else 0.0
    headroom = round(wired - weights, 1) if coder else wired
    fits = not coder or headroom >= 2.0
    add(
        fits,
        "GPU memory budget",
        f"{wired:.1f} GB wired of {snap.memory.total_gb:.0f} GB"
        + (f" · {coder.tag} uses {weights:.1f} GB" if coder else ""),
        (
            f"{coder.tag} needs the machine to itself; unload other models and lower "
            f"max_context ({coder_sel.context} now)"
            if not fits and coder is not None
            else ""
        ),
        warn=True,
    )

    swap_used, swap_total = swap_usage_gb()
    # macOS swaps routinely; only flag real thrash, not a 1 GB baseline.
    swapping = swap_used >= 4.0 or (swap_total >= 4.0 and swap_used / swap_total >= 0.85)
    add(
        not swapping,
        "Swap pressure",
        f"{swap_used:.1f} GB of {swap_total:.1f} GB used",
        "another app may be holding a large model; quit it or restart Ollama",
        warn=True,
    )

    runners = ollama_runner_models()
    loaded_tags = {view.tag for view in snap.loaded}
    orphans = [name for name in runners if name not in loaded_tags]
    add(
        not orphans,
        "Model runners",
        f"{len(runners)} live · {len(loaded_tags)} loaded" if runners else "none running",
        f"stale runner for {orphans[0]}; restart Ollama" if orphans else "",
        warn=True,
    )

    config_path = LOCAL_AI_ROOT / "gateway" / "config.yaml"
    reviewed_path = LOCAL_AI_ROOT / "gateway" / "config.sovereign-recommended.yaml"
    drifted = False
    if config_path.is_file() and reviewed_path.is_file():
        try:
            drifted = config_path.read_bytes() != reviewed_path.read_bytes()
        except OSError:
            drifted = False
    add(
        not drifted,
        "Gateway config",
        "matches reviewed config" if not drifted else "differs from reviewed config",
        f"diff {config_path.name} {reviewed_path.name}; another agent may have rewritten it",
        warn=True,
    )

    # Every model a client is configured to use must still exist locally.
    # Pruning (or another agent editing a config) can leave dangling references
    # that only surface later as a failed launch.
    from .tools import (
        continue_models as _continue_models,
    )
    from .tools import (
        gateway_models as _gateway_models,
    )
    from .tools import (
        opencode_models as _opencode_models,
    )
    from .tools import (
        qwen_models as _qwen_models,
    )
    from .tools import (
        read_text as _read_text,
    )

    home = Path.home()
    referenced: set[str] = set(
        _gateway_models(_read_text(LOCAL_AI_ROOT / "gateway" / "config.yaml")).values()
    )
    referenced.update(_opencode_models(_read_text(home / ".config" / "opencode" / "opencode.json")))
    referenced.update(_qwen_models(_read_text(home / ".qwen" / "settings.json")))
    referenced.update(_continue_models(_read_text(home / ".continue" / "config.yaml")))
    # Cloud aliases are expected to be absent from the local model list.
    referenced = {
        name for name in referenced if not name.startswith("cloud-") and not name.endswith(":cloud")
    }
    from .tier_gateway import MODEL_CONTEXT, catalog_ids

    referenced.update(MODEL_CONTEXT)
    # The models ChatGPT and Claude are configured to use are references too:
    # they are the names a client actually asks for.
    from .client_setup import claude_slot_routes, codex_configured_model

    codex_model = codex_configured_model()
    if codex_model:
        referenced.add(codex_model)
    # The Claude slots hold a Claude model id; the local route behind it is
    # what has to exist.
    referenced.update(claude_slot_routes().values())
    installed_names: set[str] = set()
    for view in snap.installed:
        installed_names.update({view.tag, view.tag.removesuffix(":latest")})
    # A name the catalog knows is a route; a name Ollama knows is a model.
    # Either one can be asked for, so only the rest is dangling.
    known = catalog_ids(set(installed_names)) | installed_names
    dangling = sorted(
        name
        for name in referenced
        if name not in known
        and name.removesuffix(":latest") not in known
        and f"{name}:latest" not in known
    )
    add(
        not dangling,
        "Client models",
        f"{len(referenced)} referenced · all available"
        if not dangling
        else f"missing: {', '.join(dangling[:3])}",
        "pull the model or point the client at an installed one",
        warn=True,
    )
    add(
        snap.gateway.up,
        "LiteLLM gateway",
        f"{len(snap.gateway.models)} models",
        "launchctl kickstart -k gui/$(id -u)/com.user.ailocalgateway",
        warn=True,
    )
    add(
        snap.router_up,
        "Tier gateway",
        f"{snap.settings.router_url} · auto/fast/balanced/deep/ultra",
        "sovereign router --start",
        warn=True,
    )
    # The bridge and the web chat are the same kind of detached process: a
    # dead one looks exactly like a broken app.
    from .guardian import check as _guardian_check

    for state in _guardian_check(snap.settings, autostart=False):
        if state.name == "tier gateway":
            continue
        add(
            state.up,
            state.name,
            f":{state.port} · {state.detail}",
            "sovereign guardian",
            warn=True,
        )
    # The desktop app is only local when its own config says so, and it must
    # not need an OpenAI account to run.
    from .client_setup import codex_forced_local, codex_needs_openai_signin

    app_local = codex_forced_local()
    app_signin = codex_needs_openai_signin()
    add(
        app_local and not app_signin,
        "ChatGPT app local",
        "local, no sign-in"
        if app_local and not app_signin
        else ("local but still needs a sign-in" if app_local else "pointed at the cloud"),
        "sovereign chatgpt --local",
        warn=True,
    )
    browser_exe = chromium_path()
    add(
        browser_exe is not None,
        "Browser engine",
        str(browser_exe) if browser_exe else "not installed",
        "pip install -e '.[browser]' && playwright install chromium",
        warn=True,
    )
    has_embed = any("embed" in view.tag for view in snap.installed)
    add(
        has_embed,
        "Embedding model",
        "nomic-embed-text" if has_embed else "not installed",
        "ollama pull nomic-embed-text",
        warn=True,
    )
    if has_embed and snap.ollama_up:
        live = probe_liveness(snap.settings.ollama_url)
        add(
            live.ok,
            "Generation liveness",
            live.detail if live.ok else f"not serving: {live.detail}",
            "restart Ollama: sovereign tune (or quit and reopen the app)",
            warn=True,
        )
    from .cloud import available_providers, cloud_env_path

    providers = available_providers()
    add(
        True,
        "Cloud providers",
        f"{', '.join(providers)} configured"
        if providers
        else "none (local-only; Ollama Cloud optional)",
        "sovereign cloud --set-key openrouter",
        warn=False,
    )
    key_file = cloud_env_path()
    if key_file.is_file():
        mode = key_file.stat().st_mode & 0o777
        add(
            mode & 0o077 == 0,
            "Cloud key file",
            f"{key_file} · {mode:o}",
            f"chmod 600 {key_file}",
            warn=True,
        )
    add(
        (LOCAL_AI_ROOT / "gateway" / "config.yaml").is_file(),
        "Local AI root",
        str(LOCAL_AI_ROOT),
        "sovereign install-clients",
        warn=True,
    )
    add(
        command_exists("qwen"),
        "Qwen Code CLI",
        shutil.which("qwen") or "missing",
        "npm i -g @qwen-code/qwen-code",
        warn=True,
    )
    add(
        qwen_memory_path().is_file(),
        "Qwen global rules",
        str(qwen_memory_path()),
        "recreate ~/.qwen/QWEN.md",
        warn=True,
    )
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
    add(
        login_agent_installed(),
        "Login terminal",
        "launch agent installed" if login_agent_installed() else "not installed",
        "sovereign install-login",
        warn=True,
    )
    from .services import service_states

    services = service_states(snap.settings)
    up = [state for state in services if state.pid > 0 or state.serving]
    installed = [state for state in services if state.installed]
    add(
        bool(installed) and len(up) == len(services),
        "Autostart services",
        f"{len(up)}/{len(services)} running"
        + (f" · {len(installed)} installed" if installed else " · not installed"),
        "sovereign autostart --install",
        warn=True,
    )
    add(
        snap.disk_free_gb >= 5,
        "Disk space",
        f"{snap.disk_free_gb:.0f} GB free",
        "free at least 5 GB",
        warn=True,
    )
    add(
        snap.memory.free_gb >= 2,
        "Free memory",
        f"{snap.memory.free_gb:.1f} GB",
        "unload a model: ollama stop <tag>",
        warn=True,
    )

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
  <key>StandardOutPath</key><string>{html.escape(str(PROJECT_ROOT / "logs" / "login.out.log"))}</string>
  <key>StandardErrorPath</key><string>{html.escape(str(PROJECT_ROOT / "logs" / "login.err.log"))}</string>
</dict>
</plist>
"""
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    plist.write_text(text, encoding="utf-8")
    plist.chmod(0o644)
    console.print(f"[green]Installed[/] {plist}")
    if start_now:
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, check=False
        )
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


def _pull(settings: Settings, tag: str, note: str = "") -> int:
    if tag in CLOUD_TAG_ALIASES:
        tag = CLOUD_TAG_ALIASES[tag]
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?", tag):
        console.print(f"[red]Invalid model tag:[/] {tag}")
        return 1
    spec = CATALOG.get(tag)
    if spec and spec.cloud and not cloud_enabled():
        console.print("[red]Ollama Cloud is disabled on this Mac.[/]")
        console.print("[dim]Enable it with:[/] sovereign cloud --enable")
        return 1
    snap = _snapshot(settings)
    if snap.views.get(tag) and snap.views[tag].installed:
        console.print(f"[green]{tag} is already installed.[/]")
        return 0
    from .models import REMOTE_CATALOG

    estimated_gb = REMOTE_CATALOG.get(tag, ("", 0.0))[1]
    if spec and spec.cloud:
        # Nothing is downloaded: Ollama registers the remote model locally.
        console.print(
            f"Registering [bold]{tag}[/] [cyan](cloud · runs on ollama.com)[/]"
            + (f" — {note}" if note else "")
        )
    else:
        size_text = f" (~{estimated_gb:.0f} GB)" if estimated_gb else ""
        if estimated_gb and snap.disk_free_gb < max(2.0, estimated_gb + 2.0):
            console.print(
                f"[yellow]Warning:[/] only {snap.disk_free_gb:.0f} GB free; {tag} is "
                f"~{estimated_gb:.0f} GB. You may run out of disk — free space or "
                "remove a model first (`sovereign rm <tag>`)."
            )
        console.print(f"Pulling [bold]{tag}[/]{size_text}" + (f" — {note}" if note else ""))
    client = OllamaClient(settings.ollama_url)
    log_download(tag, status="starting")

    async def run() -> None:
        last_log = 0.0
        final_total = 0
        final_completed = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"pulling {tag}", total=None)
            async for event in client.pull(tag):
                total = event.get("total")
                completed = event.get("completed")
                if total and completed is not None:
                    final_total = int(total)
                    final_completed = int(completed)
                    if progress.tasks[task].total != float(total):
                        progress.update(task, total=float(total))
                    progress.update(task, completed=float(completed))
                status = event.get("status")
                if status:
                    # A colon after `:cloud` would make Rich render an emoji.
                    progress.update(task, description=f"{tag} — {status}")
                    now = time.monotonic()
                    if now - last_log > 1.0:
                        last_log = now
                        log_download(
                            tag,
                            status=str(status),
                            completed=final_completed,
                            total=final_total,
                        )
            progress.update(task, description=f"{tag} — done")
        log_download(
            tag,
            status="done",
            completed=final_completed,
            total=final_total,
            done=True,
        )

    try:
        asyncio.run(run())
    except OllamaError as exc:
        log_download(tag, error=str(exc))
        console.print(f"[red]{exc}[/]")
        if spec and spec.cloud:
            console.print("[dim]Cloud models also need a one-time login:[/] ollama signin")
        return 1
    console.print(f"[green]{tag} installed.[/] Run: sovereign models")
    return 0


def _cloud(
    settings: Settings,
    *,
    enable: bool = False,
    disable: bool = False,
    install_aliases: bool = False,
    pull: bool = False,
    probe: bool = False,
    timeout: float = 12.0,
    set_key: str | None = None,
    key: str | None = None,
    prefer: str = "auto",
    install_opencode: bool = False,
) -> int:
    """Show, enable, and wire the frontier models over Ollama Cloud or a provider."""
    if enable and disable:
        console.print("[red]Choose --enable or --disable, not both.[/]")
        return 1
    if set_key:
        provider = PROVIDERS.get(set_key)
        if provider is None:
            console.print(f"[red]Unknown provider:[/] {set_key}. Try: {', '.join(PROVIDERS)}")
            return 1
        value = key
        if not value:
            import getpass

            value = getpass.getpass(f"{provider.name} API key (hidden): ")
        try:
            path = set_provider_key(provider.key, value)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return 1
        console.print(f"[green]Saved {provider.name} key[/] to {path} [dim](mode 600)[/]")
        console.print("[dim]Restart the gateway to apply:[/] sovereign gateway --restart")
        console.print(
            "[dim]Then route the aliases through it:[/] sovereign cloud --install-aliases"
        )
        probe = True
    if enable:
        console.print("[bold]Enabling Ollama Cloud[/] (persists across restarts)")
        for action in apply_cloud(True):
            console.print(f"  [green]·[/] {action}")
        console.print(
            "[yellow]Cloud models run on ollama.com.[/] Prompts and context leave "
            "this Mac when you use a :cloud tag."
        )
        console.print("One-time login is still required: [bold]ollama signin[/]")
        probe = True
    elif disable:
        console.print("[bold]Disabling Ollama Cloud[/]")
        for action in apply_cloud(False):
            console.print(f"  [green]·[/] {action}")
        console.print("[dim]Local models are unaffected.[/]")

    if install_aliases and prefer in PROVIDERS:
        provider = PROVIDERS[prefer]
        if not provider_key(provider):
            console.print(
                f"[red]No {provider.name} key.[/] Run: sovereign cloud --set-key {provider.key}"
            )
            return 1
    if install_aliases:
        paths = install_gateway_aliases(prefer=prefer)
        if not paths:
            console.print(f"[yellow]No gateway config found under[/] {LOCAL_AI_ROOT / 'gateway'}")
        for path in paths:
            console.print(f"[green]Cloud aliases written[/] {path}")
        if paths:
            console.print("[dim]Restart the gateway to apply:[/] sovereign gateway --restart")

    if install_opencode:
        from .client_setup import install_opencode_mcp

        path = install_opencode_mcp(include_cloud=True)
        console.print(f"[green]Cloud provider added to OpenCode[/] {path}")
        console.print(
            "[yellow]OpenCode can now reach remote models.[/] "
            "[dim]Prompts sent to them leave this Mac.[/]"
        )

    status = read_cloud_status()
    style = "green" if status.enabled else "yellow"
    console.print(f"\n[bold]Ollama Cloud[/]  [{style}]{status.detail}[/]")
    if not status.enabled:
        console.print("[dim]Enable with:[/] sovereign cloud --enable")

    ptable = Table(title="Provider keys (cloud.env / environment)", header_style="bold #b794f4")
    ptable.add_column("Provider", style="bold")
    ptable.add_column("Status")
    ptable.add_column("Detail")
    for _key, name, state, detail in provider_status():
        pstyle = "green" if state == "key set" else "dim"
        ptable.add_row(name, f"[{pstyle}]{state}[/]", detail)
    console.print(ptable)
    console.print(
        "[dim]Add a key:[/] sovereign cloud --set-key openrouter "
        "[dim](one key covers all eight; direct provider keys also work)[/]"
    )
    rtable = Table(title="Alias routes", header_style="bold #b794f4")
    rtable.add_column("Alias", style="bold", no_wrap=True)
    rtable.add_column("Route", no_wrap=True)
    rtable.add_column("Target")
    for alias, tag in ALIAS_TARGETS.items():
        route, provider_model, _base, _env = route_for(tag, alias, prefer=prefer)
        target = provider_model or tag
        style = "cyan" if route == "ollama" else "green"
        rtable.add_row(alias, f"[{style}]{route}[/]", target)
    console.print(rtable)
    console.print("[dim]Install them into the gateway:[/] sovereign cloud --install-aliases")

    snap = _snapshot(settings)
    table = Table(
        title="Requested models · where each name goes",
        header_style="bold #b794f4",
    )
    table.add_column("Requested", style="bold", no_wrap=True)
    table.add_column("Ollama tag", style="bold", no_wrap=True)
    table.add_column("Context", justify="right", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    notes: list[str] = []
    for name, tag, note in requested_models():
        spec = CATALOG.get(tag)
        view = snap.views.get(tag)
        if spec and spec.cloud:
            state = "registered" if view and view.installed else "not pulled"
            state_style = "green" if state == "registered" else "yellow"
        else:
            state = "local · installed" if view and view.installed else "local · missing"
            state_style = "green" if view and view.installed else "yellow"
        table.add_row(
            name,
            tag,
            _context_label(spec.max_context if spec else None),
            f"[{state_style}]{state}[/]",
        )
        notes.append(f"  {name} → {tag} — {note}")
    console.print(table)
    console.print("\n[bold]Mapping[/]")
    for line in notes:
        console.print(f"[dim]{line}[/]", overflow="fold")

    if probe:
        result = probe_cloud(settings, timeout=timeout)
        mark = "[green]PASS[/]" if result.ready else "[red]FAIL[/]"
        console.print(f"\nCloud probe  {mark} {result.detail}")

    if pull:
        if not status.enabled:
            console.print("[red]Enable cloud first:[/] sovereign cloud --enable")
            return 1
        if not cloud_enabled():
            console.print("[red]Cloud is still disabled after the enable step.[/]")
            return 1
        for tag in CLOUD_TAGS:
            if _pull(settings, tag, "cloud") != 0:
                return 1
        # Registration succeeds even on a plan that blocks generation, so
        # check an actual completion instead of declaring success.
        result = probe_cloud(settings, timeout=timeout)
        mark = "[green]PASS[/]" if result.ready else "[yellow]NOT USABLE[/]"
        console.print(f"\nCloud generation  {mark} {result.detail}")
    return 0


def _pull_recommended(settings: Settings) -> int:
    return _pull(settings, "qwen2.5-coder:14b", "the best coder that fits 24 GB")


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
    console.print(
        f"[bold]Qwen Code[/] · model [green]{tag}[/] · {selection.context} ctx · {target}"
    )
    if not qwen_memory_path().is_file():
        console.print(
            "[yellow]Warning:[/] ~/.qwen/QWEN.md is missing; Qwen may write into ~/.qwen/projects."
        )
    os.chdir(target)
    os.environ["QWEN_HOME"] = str(LOCAL_AI_ROOT / "qwen")
    args = ["qwen", "--model", tag, "--approval-mode", "yolo" if yolo else "default"]
    if prompt:
        context = project_context(target)
        args.extend(["-p", (context + "\n\n" + prompt) if context else prompt])
    os.execvp(args[0], args)  # noqa: S606 - exec replaces this process; no shell is involved
    return 0


def _gateway(snap: Snapshot) -> int:
    """Show where the gateway lives, whether it is up, and how it is supervised."""
    from .services import GATEWAY_LABEL, is_loaded, service_pid

    gateway_dir = LOCAL_AI_ROOT / "gateway"
    supervised = bool(service_pid(GATEWAY_LABEL)) or is_loaded(GATEWAY_LABEL)
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
    table.add_row(
        state, "Gateway", f"{snap.settings.gateway_url} · {len(snap.gateway.models)} aliases"
    )
    if supervisor:
        table.add_row("[green]PASS[/]", "Supervisor", "run_gateway.sh running")
    else:
        table.add_row(
            "[green]PASS[/]" if supervised else "[yellow]WARN[/]",
            "Supervisor",
            "launchd service" if supervised else "not running (sovereign autostart --install)",
        )
    from .services import service_states

    services = service_states(snap.settings)
    up = [state for state in services if state.pid > 0 or state.serving]
    table.add_row(
        "[green]PASS[/]" if up and len(up) == len(services) else "[yellow]WARN[/]",
        "Services",
        f"{len(up)}/{len(services)} running [dim](sovereign autostart)[/]",
    )
    router_up = port_open("127.0.0.1", 4010)
    table.add_row(
        "[green]PASS[/]" if router_up else "[yellow]WARN[/]",
        "Tier gateway",
        f"{snap.settings.router_url} · auto/fast/balanced/deep/ultra",
    )
    table.add_row("", "Config", str(gateway_dir / "config.yaml"))
    table.add_row("", "Log", str(gateway_dir / "gateway.log"))
    table.add_row("", "Restart", "sovereign gateway --restart")
    console.print(table)
    return 0 if snap.gateway.up else 1


def _gateway_restart(settings: Settings) -> int:
    import httpx

    base = settings.gateway_url.rstrip("/")

    def up() -> bool:
        try:
            return shared_client().get(f"{base}/health/liveliness", timeout=1.5).status_code == 200
        except httpx.HTTPError:
            return False

    console.print("[dim]Stopping supervisor and LiteLLM…[/]")
    for pattern in ("run_gateway.sh", "gateway/venv/bin/litellm"):
        subprocess.run(["pkill", "-f", pattern], check=False)
    deadline = time.monotonic() + 15
    while up() and time.monotonic() < deadline:
        time.sleep(0.5)
    if up():
        console.print("[red]Gateway is still serving; refusing to claim a restart.[/]")
        console.print("[dim]Inspect: sovereign logs gateway -n 80[/]")
        return 1

    console.print("[dim]Asking the login agent to start it again…[/]")
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.user.ailocalgateway"],
        check=False,
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if up():
            time.sleep(0.5)
            console.print("[green]Gateway restarted.[/]")
            from .tier_gateway import ensure_running as ensure_tier

            if ensure_tier(upstream=settings.gateway_url):
                console.print("[green]Tier gateway running.[/]")
            return _gateway(_snapshot(settings))
        time.sleep(1)

    console.print("[red]Gateway did not come back.[/] Check: sovereign logs gateway -n 80")
    return 1


def _bridge(
    host: str,
    port: int,
    gateway: str,
    model: str,
    start: bool,
    stop: bool,
    status: bool,
) -> int:
    """Run or manage the Anthropic bridge used by Claude Code."""
    from . import bridge as bridge_mod

    if stop:
        stopped = bridge_mod.stop()
        console.print("[green]Bridge stopped.[/]" if stopped else "[dim]Bridge was not running.[/]")
        return 0 if stopped else 1
    if status:
        running = bridge_mod.port_open(port=port)
        state = "[green]running[/]" if running else "[dim]stopped[/]"
        console.print(f"Claude bridge  {state}  [dim]http://{host}:{port}/v1/messages[/]")
        console.print(f"[dim]Gateway: {gateway} · default alias: {model}[/]")
        console.print(f"[dim]Log: {bridge_mod.log_path()}[/]")
        return 0 if running else 1
    if start:
        ok = bridge_mod.ensure_running(gateway, port)
        state = "[green]running[/]" if ok else "[red]failed to start[/]"
        console.print(f"Claude bridge  {state}  [dim]http://{host}:{port}[/]")
        if not ok:
            console.print("[dim]Check:[/] sovereign logs bridge -n 60")
        return 0 if ok else 1
    if gateway.rstrip("/").endswith(":4010"):
        from .tier_gateway import ensure_running as ensure_tier

        ensure_tier()
    console.print(
        f"[bold]Claude bridge[/] · http://{host}:{port} → {gateway} [dim](Ctrl+C to stop)[/]"
    )
    bridge_mod.serve(host, port, gateway, model)
    return 0


def _router(
    host: str,
    port: int,
    ollama: str,
    upstream: str,
    start: bool,
    stop: bool,
    status: bool,
    stats: bool,
    restart: bool = False,
) -> int:
    """Run or manage the latency-aware tier gateway."""
    from . import tier_gateway as tg

    if restart:
        tg.stop()
        time.sleep(1)
        start = True
    if stop:
        stopped = tg.stop()
        console.print("[green]Tier gateway stopped.[/]" if stopped else "[dim]Not running.[/]")
        return 0 if stopped else 1
    if status:
        running = tg.port_open(host, port)
        state = "[green]running[/]" if running else "[dim]stopped[/]"
        console.print(f"Tier gateway  {state}  [dim]http://{host}:{port}/v1[/]")
        if running:
            import httpx

            try:
                health = shared_client().get(f"http://{host}:{port}/health", timeout=3.0).json()
            except (httpx.HTTPError, ValueError):
                health = {}
            for tier, model in (health.get("tiers") or {}).items():
                console.print(f"  [bold]{tier:8}[/] {model}")
            console.print("  [dim]deep: code=qwen3-coder:30b · reasoning=glm-4.7-flash[/]")
            console.print(
                f"  [dim]local-only: {'yes' if health.get('local_only') else 'no'} · "
                f"upstream {upstream} · ollama {ollama}[/]"
            )
        return 0 if running else 1
    if stats:
        summary = tg.metrics_summary()
        if not summary.get("requests"):
            console.print("[dim]No tier requests recorded yet.[/]")
            return 0
        table = Table(title="Tier gateway · recent requests", header_style="bold #b794f4")
        table.add_column("Tier", style="bold")
        table.add_column("Requests", justify="right")
        table.add_column("Avg ms", justify="right")
        table.add_column("p50", justify="right")
        table.add_column("p95", justify="right")
        for tier, bucket in (summary.get("by_tier") or {}).items():
            table.add_row(
                tier,
                str(bucket["count"]),
                str(bucket["avg_ms"]),
                str(bucket.get("p50_ms", 0)),
                str(bucket.get("p95_ms", 0)),
            )
        console.print(table)
        return 0
    if start:
        ok = tg.ensure_running(upstream=upstream, ollama=ollama, port=port)
        state = "[green]running[/]" if ok else "[red]failed[/]"
        console.print(f"Tier gateway  {state}  [dim]http://{host}:{port}/v1[/]")
        if not ok:
            console.print("[dim]Check:[/] sovereign logs tier -n 60")
        return 0 if ok else 1
    console.print(
        f"[bold]Tier gateway[/] · http://{host}:{port} → {upstream} [dim](Ctrl+C to stop)[/]"
    )
    tg.serve(host, port, ollama, upstream)
    return 0


def _chatgpt(
    restart: bool = False,
    fix: bool = False,
    local: bool = False,
    cloud: bool = False,
    repair: bool = False,
) -> int:
    """Status and setup for the ChatGPT desktop app: MCP plus local-only mode."""
    from .client_setup import (
        claude_desktop_config_path,
        codex_config_path,
        codex_forced_local,
        install_chatgpt_connectors,
        install_claude_desktop_mcp,
        install_codex_forced_local,
        install_codex_mcp,
        restore_codex_cloud,
    )

    if fix:
        install_codex_mcp()
        install_claude_desktop_mcp()
        paths = install_chatgpt_connectors()
        console.print(f"[green]MCP manifests written[/] {len(paths)}")
    if repair:
        # The app rewrites its own config when settings change in its UI, which
        # can silently send it back to the cloud. Repair without a restart.
        if codex_forced_local():
            console.print("[green]ChatGPT is already local.[/]")
        else:
            install_codex_forced_local()
            console.print(
                "[green]ChatGPT config repaired.[/] It points at the tier gateway "
                "again; restart the app to pick it up."
            )
    if restart or local or cloud:
        subprocess.run(
            ["pkill", "-f", "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"], check=False
        )
        time.sleep(3)
        env = None
        if local:
            from .config import Settings

            # Two switches, because the app reads its model from two places:
            # the config file decides the provider, and the app-server env
            # decides where the built-in OpenAI provider points.
            install_codex_forced_local()
            router = Settings.load().router_url
            env = {
                **os.environ,
                "CODEX_APP_SERVER_OPENAI_BASE_URL": f"{router}/v1",
                "SOVEREIGN_API_KEY": "local",
            }
            # Launched from Finder or the Dock the app gets no shell
            # environment, so the key is published to the login session.
            subprocess.run(["launchctl", "setenv", "SOVEREIGN_API_KEY", "local"], check=False)
            subprocess.run(
                ["launchctl", "setenv", "CODEX_APP_SERVER_OPENAI_BASE_URL", f"{router}/v1"],
                check=False,
            )
            console.print(
                "[green]ChatGPT forced local.[/] The app talks to the tier gateway on "
                f"{router}/v1 and needs no OpenAI sign-in. Restore with: "
                "sovereign chatgpt --cloud"
            )
        if cloud:
            restored = restore_codex_cloud()
            for name in ("SOVEREIGN_API_KEY", "CODEX_APP_SERVER_OPENAI_BASE_URL"):
                subprocess.run(["launchctl", "unsetenv", name], check=False)
            console.print(
                "[green]ChatGPT restored to cloud.[/]"
                if restored
                else "[yellow]No cloud backup found; the app config was left alone.[/]"
            )
        subprocess.run(["open", "-a", "ChatGPT"], check=False, env=env)
        console.print("[green]ChatGPT restarted.[/]")

    table = Table(title="ChatGPT desktop · local MCP", header_style="bold #b794f4")
    table.add_column("Item", style="bold")
    table.add_column("Status")
    table.add_column("Path", overflow="fold")
    codex = codex_config_path()
    codex_ok = codex.is_file() and "[mcp_servers.sovereign]" in codex.read_text(
        encoding="utf-8", errors="ignore"
    )
    table.add_row("Codex MCP", "yes" if codex_ok else "no", str(codex))
    forced = codex_forced_local()
    table.add_row(
        "App model",
        "local · no sign-in" if forced else "cloud",
        "sovereign-tier → 4010" if forced else "OpenAI account",
    )
    from .client_setup import codex_configured_model
    from .tier_gateway import catalog_ids, installed_models

    app_model = codex_configured_model()
    known_models = catalog_ids(installed_models())
    table.add_row(
        "Catalog model",
        app_model or "unset",
        "in the local catalog" if app_model in known_models else "not in the catalog",
    )
    claude = claude_desktop_config_path()
    claude_ok = claude.is_file() and "sovereign" in claude.read_text(
        encoding="utf-8", errors="ignore"
    )
    table.add_row("Claude Desktop config", "yes" if claude_ok else "no", str(claude))
    manifests = [
        Path.home() / ".mcp.json",
        Path.home() / ".codex" / ".mcp.json",
        Path.home() / ".codex" / "claude_desktop_config.json",
        Path.home() / "Library" / "Application Support" / "Codex" / "claude_desktop_config.json",
    ]
    for path in manifests:
        ok = path.is_file() and "sovereign" in path.read_text(encoding="utf-8", errors="ignore")
        table.add_row("Manifest", "yes" if ok else "no", str(path))
    running = (
        subprocess.run(
            ["pgrep", "-f", "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        != ""
    )
    table.add_row("App", "running" if running else "stopped", "/Applications/ChatGPT.app")
    console.print(table)
    console.print(
        "[dim]In local mode the app's model calls go to the tier gateway on this "
        "Mac, so it works with no OpenAI sign-in and its MCP tools are the "
        "sovereign ones. Enable the `sovereign` connector in ChatGPT, or use "
        "Import from Claude Desktop. Switch back with: sovereign chatgpt --cloud[/]"
    )
    return 0 if (codex_ok and running) else 1


def _app_server_base() -> str:
    """The base URL the running ChatGPT app-server was started with."""
    result = subprocess.run(
        ["pgrep", "-f", "codex app-server"], capture_output=True, text=True, check=False
    )
    for pid in (line.strip() for line in result.stdout.splitlines()):
        if not pid:
            continue
        args = subprocess.run(
            ["ps", "-o", "command=", "-p", pid], capture_output=True, text=True, check=False
        ).stdout
        match = re.search(r'openai_base_url="([^"]+)"', args)
        if match:
            return match.group(1)
    return ""


def _chatgpt_verify() -> int:
    """Prove the ChatGPT app runs on this Mac and needs no OpenAI sign-in."""
    from .client_setup import (
        codex_config_path,
        codex_forced_local,
        codex_needs_openai_signin,
        codex_probe_local,
    )
    from .config import Settings

    router = Settings.load().router_url.rstrip("/")
    rows: list[tuple[str, bool, str]] = []

    config = codex_config_path()
    forced = codex_forced_local()
    rows.append(
        (
            "App config",
            forced,
            f"{config} → sovereign-tier" if forced else f"{config} still points at the cloud",
        )
    )

    signin = codex_needs_openai_signin()
    rows.append(
        (
            "OpenAI sign-in",
            not signin,
            "not required" if not signin else "the app will ask for an account",
        )
    )

    app_up = (
        subprocess.run(
            ["pgrep", "-f", "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        != ""
    )
    rows.append(("App", app_up, "running" if app_up else "stopped"))

    server = _app_server_base()
    rows.append(
        (
            "App server",
            server.startswith(router) if server else False,
            server or "not running",
        )
    )

    ok, detail = codex_probe_local()
    rows.append(("Local round trip", ok, detail))

    local_only = False
    try:
        health = shared_client().get(f"{router}/health", timeout=3.0).json()
        local_only = bool(health.get("local_only"))
        tiers = health.get("tiers") or {}
        detail = ", ".join(f"{tier}={model}" for tier, model in tiers.items())
    except Exception:
        detail = "gateway not reachable"
    rows.append(
        (
            "Tier gateway",
            local_only,
            ("local-only · " if local_only else "cloud allowed · ") + detail,
        )
    )

    table = Table(title="ChatGPT desktop · local proof", header_style="bold #b794f4")
    table.add_column("Check", style="bold")
    table.add_column("Result")
    table.add_column("Detail", overflow="fold")
    for name, ok, detail in rows:
        table.add_row(
            name,
            "[green]ok[/]" if ok else "[red]fail[/]",
            detail,
        )
    console.print(table)
    failed = [name for name, ok, _detail in rows if not ok]
    if failed:
        console.print(
            f"[yellow]Not fully local:[/] {', '.join(failed)}. Fix with: sovereign chatgpt --local"
        )
        return 1
    console.print(
        "[green]The ChatGPT desktop app is fully local.[/] Its model calls go to the "
        "tier gateway on this Mac and it needs no OpenAI sign-in."
    )
    return 0


def _claude(
    restart: bool = False, fix: bool = False, local: bool = False, cloud: bool = False
) -> int:
    """Status/setup for local Claude Code and the Claude desktop integration."""
    from . import bridge as bridge_mod
    from .client_setup import (
        claude_forced_local,
        install_claude_code_mcp,
        install_claude_settings,
        restore_claude_cloud,
    )

    if fix:
        path = install_claude_settings()
        console.print(f"[green]Claude local settings[/] {path}")
        console.print(f"[green]Claude Code MCP[/] {install_claude_code_mcp()}")
    if local:
        path = install_claude_settings()
        from .client_setup import claude_cloud_backup_path

        saved = claude_cloud_backup_path(path).exists()
        console.print(
            f"[green]Claude pointed at the local bridge.[/] {path} "
            + (
                "(the cloud settings are kept for `--cloud`)"
                if saved
                else "(`--cloud` removes the local keys again)"
            )
        )
    if cloud:
        restored = restore_claude_cloud()
        console.print(
            "[green]Claude restored to cloud.[/]"
            if restored
            else "[yellow]No cloud backup found; the settings were left alone.[/]"
        )
    if restart or local or cloud:
        subprocess.run(
            ["pkill", "-f", "/Applications/Claude.app/Contents/MacOS/Claude"], check=False
        )
        time.sleep(3)
        subprocess.run(["open", "-a", "Claude"], check=False)
        console.print("[green]Claude restarted.[/]")

    from .client_setup import claude_settings_path

    path = claude_settings_path()
    local_env = claude_forced_local()
    bridge_up = bridge_mod.port_open(port=4001)
    app_up = (
        subprocess.run(
            ["pgrep", "-f", "/Applications/Claude.app/Contents/MacOS/Claude"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        != ""
    )
    table = Table(title="Local Claude", header_style="bold #b794f4")
    table.add_column("Item", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    table.add_row("Claude settings", "local" if local_env else "not local", str(path))
    table.add_row(
        "Anthropic bridge",
        "running" if bridge_up else "stopped",
        "http://127.0.0.1:4001/v1",
    )
    table.add_row("Claude Code CLI", "installed", shutil.which("claude") or "missing")
    table.add_row("Claude desktop", "running" if app_up else "stopped", "/Applications/Claude.app")
    from .client_setup import claude_configured_models, claude_slot_routes
    from .tier_gateway import catalog_ids, installed_models

    slots = claude_configured_models()
    routes = claude_slot_routes()
    known_models = catalog_ids(installed_models())
    for key, value in slots.items():
        route = routes.get(key, value)
        table.add_row(
            key.replace("ANTHROPIC_", "").replace("_MODEL", ""),
            f"{value} → {route}",
            "in the catalog" if route in known_models else "not in the local catalog",
        )
    missing = sorted({route for route in routes.values() if route not in known_models})
    if missing:
        table.add_row("Unknown models", ", ".join(missing), "not in the local catalog")
    console.print(table)
    console.print(
        "[dim]`claude` and `claude-local` use the local bridge. Claude Desktop's chat "
        "still uses Anthropic cloud; its Claude Code/Cowork agent follows settings.json "
        "and the MCP server. Switch with: sovereign claude --local / --cloud[/]"
    )
    return 0 if (local_env and bridge_up) else 1


def _local(fix: bool = False, strict: bool = False, as_json: bool = False) -> int:
    """Verify that every local-capable agent path is actually local."""
    import json as _json

    from . import bridge as bridge_mod
    from .client_setup import (
        claude_settings_path,
        codex_config_path,
        install_claude_code_mcp,
        install_claude_settings,
        install_codex_forced_local,
        install_codex_local_provider,
        install_codex_mcp,
        install_continue_config,
        install_opencode_mcp,
        install_qwen_router,
        opencode_config_path,
    )

    if fix:
        install_claude_settings()
        install_codex_local_provider()
        install_codex_forced_local()
        install_claude_code_mcp()
        install_codex_mcp()
        install_opencode_mcp()
        install_qwen_router()
        install_continue_config()
        console.print("[green]All local client configurations rewritten.[/]")

    rows: list[tuple[str, str, str]] = []

    def add(name: str, ok: bool, detail: str, cloud: bool = False) -> None:
        rows.append((name, "cloud" if cloud else ("local" if ok else "NOT local"), detail))

    # Claude Code: settings.json must point at the bridge, and every model it
    # names must be one the local stack can serve.
    claude_local = False
    try:
        from .client_setup import claude_slot_routes
        from .tier_gateway import catalog_ids, installed_models

        path = claude_settings_path()
        settings = _json.loads(path.read_text(encoding="utf-8"))
        env = settings.get("env") or {}
        routes = claude_slot_routes(path)
        known = catalog_ids(installed_models())
        claude_local = (
            env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:4001"
            and bool(routes)
            and all(route in known for route in routes.values())
        )
        detail = env.get("ANTHROPIC_BASE_URL", "unset")
    except (OSError, ValueError):
        detail = "missing ~/.claude/settings.json"
    add("Claude Code agent", claude_local, detail)

    bridge_up = bridge_mod.port_open(port=4001)
    add("Anthropic bridge", bridge_up, "http://127.0.0.1:4001/v1")

    from .cloud import env_cloud_disabled

    ollama_local = env_cloud_disabled()
    add(
        "Ollama Cloud",
        ollama_local,
        "disabled" if ollama_local else "enabled; run sovereign cloud --disable",
    )

    # Codex local profile: provider must be the tier gateway on 4010.
    profile = Path.home() / ".codex" / "sovereign.config.toml"
    codex_local = False
    try:
        profile_text = profile.read_text(encoding="utf-8")
        codex_local = "sovereign-tier" in profile_text and 'model = "best"' in profile_text
        detail = str(profile)
    except OSError:
        detail = "missing ~/.codex/sovereign.config.toml"
    add("Codex local profile", codex_local, detail)

    base = codex_config_path()
    provider_local = False
    try:
        base_text = base.read_text(encoding="utf-8")
        provider_local = (
            "[model_providers.sovereign-tier]" in base_text
            and "http://127.0.0.1:4010/v1" in base_text
        )
    except OSError:
        base_text = ""
    add("Codex local provider", provider_local, str(base))

    wrappers = LOCAL_AI_ROOT / "bin"
    add(
        "chatgpt-local wrapper",
        (wrappers / "chatgpt-local").is_file(),
        str(wrappers / "chatgpt-local"),
    )
    add(
        "claude-local wrapper",
        (wrappers / "claude-local").is_file(),
        str(wrappers / "claude-local"),
    )

    # OpenCode: default must be the local tier provider.
    opencode_local = False
    opencode_detail = str(opencode_config_path())
    try:
        config = _json.loads(opencode_config_path().read_text(encoding="utf-8"))
        model = config.get("model")
        if isinstance(model, dict):
            model = f"{model.get('providerID')}/{model.get('model')}"
        provider = (config.get("provider") or {}).get("sovereign") or {}
        options = provider.get("options") or {}
        opencode_local = (
            str(model) in {"sovereign/best", "sovereign/auto"}
            and options.get("baseURL") == "http://127.0.0.1:4010/v1"
        )
        opencode_detail = f"{model} → {options.get('baseURL', 'unset')}"
    except (OSError, ValueError):
        opencode_detail = "unreadable opencode.json"
    add("OpenCode default", opencode_local, opencode_detail)

    # Gateway must be live, serving local models, and bound to loopback only.
    gateway_local = False
    gateway_detail = "not running"
    try:
        import httpx

        health = shared_client().get("http://127.0.0.1:4010/health", timeout=3.0).json()
        tiers = health.get("tiers") or {}
        enforced = bool(health.get("local_only"))
        gateway_local = (
            bool(tiers)
            and enforced
            and all(not is_cloud_tag(str(model)) for model in tiers.values())
        )
        gateway_detail = ("local-only · " if enforced else "cloud allowed · ") + ", ".join(
            f"{tier}={model}" for tier, model in tiers.items()
        )
    except (httpx.HTTPError, ValueError):
        pass

    # The health flag says the gateway *intends* to be local. The socket says
    # whether it actually is: a process bound to 0.0.0.0 is reachable from the
    # network no matter what the URL says.
    for port, label in ((4010, "Tier gateway"), (4001, "Anthropic bridge")):
        try:
            addresses = listening_addresses(port)
        except (ImportError, OSError):
            addresses = []
        if not addresses:
            continue
        exposed = [address for address in addresses if not _is_loopback_host(address)]
        if exposed:
            gateway_local = False
            gateway_detail += f" · {label} exposed on {', '.join(exposed)}"
    add("Tier gateway", gateway_local, gateway_detail)

    # Desktop app chat windows are closed cloud clients; report separately.
    add("Claude Desktop chat", False, "Anthropic cloud (closed app)", cloud=True)

    # The ChatGPT app can be pinned to the local provider, so it is checked
    # like any other agent path instead of being assumed cloud.
    from .client_setup import codex_forced_local, codex_needs_openai_signin

    forced = codex_forced_local()
    add(
        "ChatGPT desktop chat",
        forced,
        "local · no sign-in" if forced else "OpenAI cloud; fix: sovereign chatgpt --local",
    )
    signin = codex_needs_openai_signin()
    add(
        "ChatGPT sign-in",
        not signin,
        "not required" if not signin else "the app will ask for an OpenAI account",
    )

    required = [row for row in rows if row[0] != "Claude Desktop chat"]
    ok = all(status == "local" for _name, status, _detail in required)
    if as_json:
        import json as _json

        print(
            _json.dumps(
                {
                    "ok": ok,
                    "surfaces": [
                        {"name": name, "status": status, "detail": detail}
                        for name, status, detail in rows
                    ],
                },
                indent=2,
            )
        )
        return 0 if ok else 1
    table = Table(title="Local-only audit", header_style="bold #b794f4")
    table.add_column("Surface", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for name, status, detail in rows:
        table.add_row(name, status, detail)
    console.print(table)
    if ok:
        console.print(
            "[green]All local agent paths are local.[/] The ChatGPT desktop app runs "
            "on the tier gateway with no OpenAI sign-in; only the Claude Desktop "
            "chat window stays cloud because that app is a closed client."
        )
    else:
        console.print("[yellow]Some local paths are not configured.[/] Fix: sovereign local --fix")
    if strict and not ok:
        return 1
    return 0 if ok else 1


def _clients(snap: Snapshot) -> None:
    resolved = resolve_client_models(snap.views, snap.potential_free_gb, snap.settings.max_context)
    table = Table(title="Local coding clients", header_style="bold #b794f4")
    table.add_column("Client", style="bold")
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Local model")
    table.add_column("Notes", overflow="fold")
    for client in local_clients(resolved):
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
        "[dim]Qwen, Codex, Claude Code, and OpenCode execute local tools; Codex uses "
        "the tier gateway Responses API and Claude uses the sovereign bridge. "
        "VS Codium/Continue handles chat, edit, and autocomplete.[/]"
    )
    if any(tag for _alias, tag in resolved.values()):
        console.print(
            "[dim]Auto-resolved best models now:[/] "
            + ", ".join(f"{key} → {tag}" for key, (_alias, tag) in resolved.items() if tag)
        )
        console.print(
            '[dim]Point any OpenAI/Anthropic client at the gateway with: eval "$(sovereign env)"[/]'
        )


def _make_room(snap: Snapshot, tag: str, dry_run: bool = False) -> list[str]:
    """Unload residents that would stop `tag` from fitting the GPU budget.

    Ollama does not error when a load cannot fit — it waits, and every later
    request queues behind it. Freeing the machine up front is the only way to
    keep the rest of the stack responsive.
    """
    view = snap.views.get(tag)
    if view is None:
        return []
    evict = models_to_evict(
        max(view.size_gb, view.spec.size_gb),
        [(item.tag, item.size_gb) for item in snap.loaded if item.tag != tag],
        wired_limit_gb(snap.memory.total_gb),
    )
    if not evict:
        return []
    console.print(
        f"[dim]{'Would free' if dry_run else 'Freeing'} GPU memory for "
        f"{tag}: unloading {', '.join(evict)}[/]"
    )
    if dry_run:
        return evict

    async def _evict() -> None:
        ollama = OllamaClient(snap.settings.ollama_url)
        for name in evict:
            try:
                await ollama.unload(name)
            except OllamaError:
                pass

    asyncio.run(_evict())
    return evict


def _best(snap: Snapshot) -> int:
    """Show the effective model for every connected tool, strongest first."""
    from .tools import (
        codex_logged_in,
        continue_default,
        gateway_models,
        opencode_default,
        qwen_default,
        read_text,
    )

    home = Path.home()
    gateway = gateway_models(read_text(LOCAL_AI_ROOT / "gateway" / "config.yaml"))
    opencode = opencode_default(read_text(home / ".config" / "opencode" / "opencode.json"))
    qwen = qwen_default(read_text(home / ".qwen" / "settings.json"))
    cont = continue_default(read_text(home / ".continue" / "config.yaml"))
    chat = snap.chat_selection.tag if snap.chat_selection and snap.chat_selection.model else "-"
    codex_state = "logged in" if codex_logged_in() else "not logged in"

    table = Table(title="Strongest first · effective models", header_style="bold #b794f4")
    table.add_column("Tool")
    table.add_column("Model")
    table.add_column("How", style="dim")
    for tool, model, how in (
        ("Codex (local)", gateway.get("local-code", "-"), "codex-local"),
        ("Codex / ChatGPT", f"ChatGPT plan · {codex_state}", "codex login → codex-chatgpt"),
        ("Claude Code (local)", gateway.get("local-claude", "-"), "claude-local"),
        ("Claude Code (cloud)", "Claude subscription", "claude-cloud"),
        ("OpenCode", opencode or "-", "opencode"),
        ("Qwen Code", qwen or "-", "qwen-local"),
        ("VS Codium", cont or "-", "Continue"),
        ("Ollama chat", chat, "sovereign chat"),
    ):
        table.add_row(tool, model, how)
    console.print(table)
    console.print(
        "[dim]Local picks follow the measured ranking; cloud wrappers use your "
        "subscription with no local overrides.[/]"
    )
    return 0


def _watchdog(settings: Settings, restart: bool = True, interval: float = 8.0) -> int:
    """Recover a wedged Ollama or a dead tier gateway, without interrupting work."""
    from urllib.parse import urlsplit

    from .tier_gateway import ensure_running as ensure_tier
    from .tier_gateway import port_open as tier_port
    from .tune import restart_ollama
    from .watchdog import STUCK, classify, sample

    router = urlsplit(settings.router_url)
    if router.hostname and router.port and not tier_port(router.hostname, router.port):
        if ensure_tier(upstream=settings.gateway_url, ollama=settings.ollama_url):
            console.print("[green]tier gateway restarted[/]")
        else:
            console.print("[yellow]tier gateway is down and did not restart[/]")

    base = settings.ollama_url
    live = probe_liveness(base, timeout=12.0)
    if live.ok:
        console.print(f"[green]serving[/] · {live.detail}")
        return 0

    console.print(f"[yellow]not serving[/] · {live.detail} — sampling for progress")
    before = sample(base)
    time.sleep(interval)
    after = sample(base)
    verdict = classify(False, before, after)
    console.print(
        f"verdict [bold]{verdict}[/] · runner cpu {after.cpu:.0f}% · "
        f"{len(after.models)} model(s) resident"
    )
    if verdict != STUCK:
        console.print("[dim]Ollama is busy, not wedged. Leaving it alone.[/]")
        return 0

    if not restart:
        console.print("[yellow]Wedged.[/] Re-run without --no-restart to recover.")
        return 1

    console.print("[dim]Restarting Ollama…[/]")
    restart_ollama(env=desired_env())
    for _ in range(30):
        if probe_liveness(base, timeout=8.0).ok:
            console.print("[green]recovered[/]")
            return 0
        time.sleep(1)
    console.print("[red]Still not serving after restart.[/]")
    return 1


def _guardian(
    settings: Settings,
    status_only: bool = False,
    watch: bool = False,
    interval: float = 30.0,
    as_json: bool = False,
) -> int:
    """Check the gateway and the Anthropic bridge, and put back what is down.

    A dead tier gateway is what makes the ChatGPT app look like it wants a
    sign-in, and a dead bridge does the same to Claude. This is a manual
    one-shot by default; the 24/7 watch loop is no longer installed as a
    service. ``--watch`` still runs in the foreground if asked for.
    """
    import json as _json

    from . import guardian as guardian_mod

    if watch:
        if not as_json:
            console.print("[dim]Guardian watching. Ctrl-C to stop.[/]")
        try:
            guardian_mod.watch(interval=interval, settings=settings)
        except KeyboardInterrupt:
            if not as_json:
                console.print("[dim]Guardian stopped.[/]")
        return 0

    states = guardian_mod.check(settings, autostart=not status_only)
    guardian_mod.log(states)

    if as_json:
        payload = {
            "ok": all(state.up for state in states),
            "services": [state.as_dict() for state in states],
        }
        print(_json.dumps(payload, indent=2))
    else:
        for state in states:
            mark = "[green]up[/]" if state.up else "[red]down[/]"
            if state.restarted:
                mark = "[green]restarted[/]"
            console.print(f"{state.name:<20} {mark:<14} :{state.port}  {state.detail}")
            if state.note:
                console.print(f"  [dim]{state.note}[/]")

    return 0 if all(state.up for state in states) else 1


def _autostart_report(settings: Settings) -> dict:
    """What the machine will look like after a reboot.

    The report answers the question a user actually has: if the Mac restarts
    now, do ChatGPT, Claude and Codex still run on this Mac, and does the
    stack come back on its own?
    """
    from .client_setup import (
        claude_forced_local,
        codex_forced_local,
        unknown_client_models,
    )
    from .services import service_states, session_env_values

    states = service_states(settings)
    env = session_env_values()
    services = {
        state.service.name: {
            "label": state.service.label,
            "installed": state.installed,
            "loaded": state.loaded,
            "running": state.pid > 0,
            "serving": state.serving,
            "port": state.service.port,
        }
        for state in states
    }
    unknown = unknown_client_models()
    clients = {
        "ChatGPT": {
            "local": codex_forced_local(),
            "config": "~/.codex/config.toml",
            "needs": "the tier gateway",
        },
        "Claude": {
            "local": claude_forced_local(),
            "config": "~/.claude/settings.json",
            "needs": "the Anthropic bridge",
        },
        "Codex": {
            "local": codex_forced_local(),
            "config": "~/.codex/config.toml + the local profile",
            "needs": "the tier gateway",
        },
    }
    stack_ready = all(state.installed and state.loaded for state in states)
    session_ready = bool(env.get("CODEX_APP_SERVER_OPENAI_BASE_URL"))
    return {
        "ok": stack_ready and session_ready and not unknown,
        "stack": {
            "autostarts": stack_ready,
            "services": services,
        },
        "session_env": env,
        "clients": clients,
        "unknown_models": unknown,
        "verdict": (
            "The stack comes back on its own and every client stays local."
            if stack_ready and session_ready and not unknown
            else "Not everything survives a reboot yet — run: sovereign autostart --install"
        ),
    }


def _autostart(
    settings: Settings,
    install: bool = False,
    uninstall: bool = False,
    repair: bool = False,
    restart: bool = False,
    as_json: bool = False,
) -> int:
    """Install, inspect and remove the launchd services behind the local stack."""
    import json as _json

    from . import services as services_mod

    if restart:
        rows = services_mod.restart_services(settings)
        table = Table(title="Local stack services", header_style="bold #b794f4")
        table.add_column("Service", style="bold")
        table.add_column("Result", overflow="fold")
        for label, result in rows:
            table.add_row(label, result)
        console.print(table)
        return 0
    if install or repair:
        rows = (
            services_mod.repair_services(settings)
            if repair
            else services_mod.install_services(settings)
        )
        if install:
            # The old Terminal-based gateway job would open a window at every
            # login to start a supervisor the launchd service now owns.
            rows.extend(services_mod.retire_superseded())
        env = services_mod.set_session_env(settings)
        table = Table(title="Local stack services", header_style="bold #b794f4")
        table.add_column("Service", style="bold")
        table.add_column("Result", overflow="fold")
        for label, result in rows:
            table.add_row(label, result)
        console.print(table)
        console.print(
            f"[green]Session environment set[/] {', '.join(sorted(env))} — the ChatGPT "
            "app inherits it, so it is local from the first launch after a reboot."
        )
        return 0
    if uninstall:
        rows = services_mod.uninstall_services(settings)
        rows.extend(services_mod.restore_superseded())
        services_mod.clear_session_env()
        table = Table(title="Local stack services", header_style="bold #b794f4")
        table.add_column("Service", style="bold")
        table.add_column("Result", overflow="fold")
        for label, result in rows:
            table.add_row(label, result)
        console.print(table)
        console.print(
            "[dim]The session environment was cleared; the apps fall back to the cloud.[/]"
        )
        return 0

    report = _autostart_report(settings)
    if as_json:
        print(_json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    table = Table(title="Autostart · after a reboot", header_style="bold #b794f4")
    table.add_column("Service", style="bold")
    table.add_column("State")
    table.add_column("Port", justify="right")
    for name, info in report["stack"]["services"].items():
        if not info["installed"]:
            state = "[dim]not installed[/]"
        elif not info["loaded"]:
            state = "[yellow]not loaded[/]"
        elif info["running"]:
            state = "[green]running[/]"
        else:
            state = "[yellow]loaded[/]"
        table.add_row(name, state, str(info["port"] or "—"))
    for name, info in report["clients"].items():
        state = "[green]local[/]" if info["local"] else "[red]cloud[/]"
        table.add_row(name, state, info["needs"])
    console.print(table)
    env = report["session_env"]
    if env.get("CODEX_APP_SERVER_OPENAI_BASE_URL"):
        console.print(
            f"[green]Session environment[/] {env['CODEX_APP_SERVER_OPENAI_BASE_URL']} "
            "· the ChatGPT app inherits it"
        )
    else:
        console.print(
            "[yellow]No session environment[/] — the ChatGPT app would start against "
            "the cloud. Run: sovereign autostart --install"
        )
    if report["unknown_models"]:
        console.print(
            f"[yellow]Unknown models[/] {', '.join(report['unknown_models'])} — a client "
            "points at a model the gateway cannot route."
        )
    console.print(f"[dim]{report['verdict']}[/]")
    return 0 if report["ok"] else 1


def _prune(snap: Snapshot, apply: bool = False) -> int:
    """Report installed models that no alias, stack or task preference uses."""
    from .prune import parse_alias_targets, prune_candidates, referenced_tags

    config_path = LOCAL_AI_ROOT / "gateway" / "config.yaml"
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError:
        config_text = ""

    refs = referenced_tags(parse_alias_targets(config_text), MODEL_STACKS, TASK_PREFERENCE)
    candidates = prune_candidates([(view.tag, view.size_gb) for view in snap.installed], refs)
    if not candidates:
        console.print("[green]Nothing to prune[/] — every installed model is referenced.")
        return 0

    total = sum(size for _tag, size in candidates)
    table = Table(
        title=f"Unreferenced · {total:.1f} GB",
        header_style="bold #b794f4",
    )
    table.add_column("Model", style="bold")
    table.add_column("Size", justify="right")
    for tag, size in candidates:
        table.add_row(tag, f"{size:.1f} GB")
    console.print(table)

    if not apply:
        console.print("[dim]Dry run: nothing removed. Re-run with --apply to delete.[/]")
        return 0

    # Always leave a way back: record the exact pulls that would restore these.
    from datetime import datetime

    manifest = LOCAL_AI_ROOT / "data" / f"prune-{datetime.now():%Y%m%d-%H%M%S}.txt"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "# Restore the models removed by `sovereign prune --apply`:\n"
        + "".join(f"ollama pull {tag}\n" for tag, _size in candidates),
        encoding="utf-8",
    )
    console.print(f"[dim]Restore list written to {manifest}[/]")

    removed: list[str] = []
    for tag, _size in candidates:
        result = subprocess.run(["ollama", "rm", tag], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            removed.append(tag)
        else:
            console.print(f"[red]Could not remove {tag}:[/] {result.stderr.strip()[:120]}")
    if removed:
        console.print(f"[green]Removed[/] {', '.join(removed)} · {total:.1f} GB freed")
    return 0 if len(removed) == len(candidates) else 1


def _warm_model(settings: Settings, model: str | None, task: str) -> int:
    """Load the chosen model now so the first prompt is not a cold start."""
    snap = _snapshot(settings)
    if not snap.ollama_up:
        console.print("[red]Ollama is offline.[/]")
        return 1
    tasks = {"code": Task.CODE, "chat": Task.CHAT, "agent": Task.AGENT}
    want = tasks.get(task, Task.CODE)
    if model:
        view = snap.views.get(model)
        tag = model
        context = view.context if view and view.context else settings.max_context
    else:
        selection = choose(
            want, snap.views, snap.potential_free_gb, max_context=settings.max_context
        )
        if not selection.model:
            console.print("[yellow]No installed model to warm.[/]")
            return 1
        tag, context = cast(str, selection.tag), selection.context
        # The router prefers a conservative window; 2k would make the warmed
        # model useless for real work, so keep at least a usable floor.
        if context <= 4096:
            context = min(settings.max_context, 16384)

    _make_room(snap, tag)

    async def _preload() -> dict:
        client = OllamaClient(snap.settings.ollama_url)
        started = time.monotonic()
        data = await client.preload(tag, context)
        return {"data": data, "elapsed": time.monotonic() - started}

    try:
        result = asyncio.run(_preload())
    except OllamaError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    # With an empty prompt Ollama reports load_duration as 0 even when it had to
    # load, so wall time is the honest number here.
    elapsed = float(result["elapsed"])
    if elapsed < 0.5:
        console.print(f"[green]{tag}[/] already resident · {context} ctx")
    else:
        console.print(f"[green]{tag}[/] warmed in {elapsed:.1f}s · {context} ctx")
    return 0


def _launch(
    client: str,
    path: str,
    yolo: bool = False,
    dry_run: bool = False,
    model: str | None = None,
    cloud: bool = False,
) -> int:
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        console.print(f"[red]Not a directory:[/] {target}")
        return 1
    if cloud and client not in {"codex", "claude"}:
        console.print("[red]--cloud is only supported for codex and claude.[/]")
        return 1
    if cloud and client == "codex":
        from .clients import chatgpt_login_status

        state = chatgpt_login_status()
        if state != "logged-in":
            console.print("[red]Real ChatGPT needs a login.[/] Run: [bold]codex login[/]")
            if state == "missing":
                console.print("[dim]`codex` is not on PATH.[/]")
            return 1
        console.print(
            "[yellow]Cloud mode:[/] prompts, code and diffs are sent to OpenAI. "
            "The local router is not involved."
        )
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
    agent_model = model or selection.tag or "gemma4:12b"
    if client == "codex" and not model and not cloud:
        # The local Codex profile points at the tier gateway; `auto` lets the
        # gateway pick the model per turn.
        agent_model = "auto"
    if cloud and client not in {"codex", "claude"}:
        console.print(f"[red]{client} has no cloud mode.[/] Use codex or claude.")
        return 1
    if client in {"qwen", "opencode"} and not model:
        # Both clients have a tier provider; let the gateway pick per request.
        agent_model = "auto"
    if client == "claude" and not model and not cloud:
        # The bridge maps Claude's own model slots onto the local models, so
        # the picker in Claude Code offers them and the default turn follows
        # the quality route.
        agent_model = "auto"

    if client in {"qwen", "opencode", "codex"} and not cloud and not dry_run:
        from .tier_gateway import ensure_running as ensure_tier

        ensure_tier(upstream=snap.settings.gateway_url, ollama=snap.settings.ollama_url)

    if client == "claude" and not cloud and not dry_run:
        from .bridge import ensure_running

        if not ensure_running(snap.settings.router_url):
            console.print("[red]Claude bridge did not start.[/] See: sovereign logs bridge")
            return 1
    # Claude always runs the 64k chat model behind `local-claude`, so make room
    # for that instead of the router's 32k coder. VS Codium loads no model.
    if client == "codium":
        room_model = ""
    elif client == "claude":
        room_model = "qwen3.5:9b"
    else:
        room_model = agent_model
    if room_model and not cloud:
        _make_room(snap, room_model, dry_run)

    try:
        plan = plan_launch(client, target, snap.settings, agent_model, yolo=yolo, cloud=cloud)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        if client == "codex":
            console.print("[dim]Run: sovereign install-clients[/]")
        return 1
    console.print(f"[bold]{info.name}[/] · model [green]{plan.model}[/] · {target}")
    if plan.note:
        console.print(f"[yellow]{plan.note}[/]")
    if client == "qwen" and yolo:
        console.print(
            "[yellow]YOLO mode: every local tool call is auto-approved for this session.[/]"
        )
    if dry_run:
        console.print("[dim]Dry run: not launching.[/]")
        console.print(f"[dim]  argv: {' '.join(plan.argv)}[/]")
        return 0
    os.chdir(target)
    try:
        os.execvpe(plan.argv[0], plan.argv, plan.env)  # noqa: S606 - exec replaces this process
    except OSError as exc:
        console.print(f"[red]Could not launch {info.name}:[/] {exc}")
        return 1
    return 0


def _consult(
    settings: Settings,
    prompt: str,
    models: list[str] | None,
    tokens: int,
    domain_key: str | None = None,
) -> int:
    import httpx

    from .domains import (
        DOMAINS,
        FORCE_VERDICT,
        classify,
        verdict,
    )
    from .domains import (
        system_prompt as domain_system_prompt,
    )

    try:
        shared_client().get(
            settings.gateway_url.rstrip("/") + "/v1/models", timeout=3.0
        ).raise_for_status()
    except httpx.HTTPError:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway --restart")
        return 1

    # A domain decides which specialist model answers, which skill frames the
    # question, and which answer protocol the reply has to follow.
    if domain_key:
        domain = DOMAINS.get(domain_key)
        if domain is None:
            console.print(f"[red]Unknown domain:[/] {domain_key}")
            console.print(f"[dim]Known: {', '.join(sorted(DOMAINS))}[/]")
            return 1
    else:
        domain = classify(prompt)[0]
    console.print(f"[dim]Domain:[/] [bold]{domain.label}[/] [dim]({domain.key})[/]")

    if not models:
        # No explicit models: the domain's own alias is the specialist that
        # serves it, with a chat model as the second opinion.
        models = [domain.alias, domain.fallback]

    skill_body = ""
    if domain.skill:
        skill = read_skill(domain.skill)
        if skill:
            skill_body = render_skill(domain.skill, prompt)
        else:
            console.print(f"[dim]No skill named '{domain.skill}' — continuing without it.[/]")
    elif domain_key:
        console.print("[dim]This domain has no skill template; continuing without one.[/]")

    system = domain_system_prompt(domain)
    for model in models:
        console.print(f"[dim]Consulting {model}…[/]")
        user_prompt = skill_body or prompt
        try:
            answer = complete(
                settings.gateway_url,
                model,
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=tokens,
            )
        except SourceError as exc:
            console.print(f"[red]{model}: {exc}[/]")
            continue
        if verdict(answer) is None:
            # The protocol asks for a definite answer. One retry gets the
            # verdict without paying for a second full analysis.
            try:
                answer = complete(
                    settings.gateway_url,
                    model,
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": answer},
                        {"role": "user", "content": FORCE_VERDICT},
                    ],
                    max_tokens=max(tokens, 200),
                )
            except SourceError as exc:
                console.print(f"[dim]{model}: verdict retry failed ({exc})[/]")
        console.print(Panel(Text(answer), title=model, border_style="cyan"))
    return 0


def _backends(settings: Settings) -> int:
    """Which local inference servers are reachable right now."""
    from .backends import known_backends, probe

    table = Table(title="Local inference backends", header_style="bold #b794f4")
    table.add_column("Backend", style="bold")
    table.add_column("Status")
    table.add_column("URL", style="dim")
    table.add_column("Models", overflow="fold")
    for backend in known_backends(settings):
        status = probe(backend)
        table.add_row(
            backend.name,
            "[green]online[/]" if status.online else "[dim]offline[/]",
            backend.url,
            ", ".join(status.models) if status.models else "-",
        )
    console.print(table)
    console.print("[dim]Everything here is on loopback. Sovereign Code never calls a cloud API.[/]")
    return 0


def _domains(detect: str | None = None) -> int:
    from .domains import DOMAINS, classify

    if detect:
        console.print(f"[bold]Prompt[/] {detect}\n")
        for domain in classify(detect):
            console.print(
                f"  [bold cyan]{domain.key}[/]  {domain.label}  "
                f"[dim]{domain.alias} → {domain.fallback}[/]"
            )
        return 0

    table = Table(title="Specialist domains", header_style="bold #b794f4")
    table.add_column("Key", style="bold")
    table.add_column("Domain")
    table.add_column("Alias", style="cyan")
    table.add_column("Fallback")
    table.add_column("Skill")
    for key, domain in DOMAINS.items():
        table.add_row(
            key,
            domain.label,
            domain.alias,
            domain.fallback,
            domain.skill or "-",
        )
    console.print(table)
    console.print("[dim]sovereign consult '…' [--domain KEY][/]")
    return 0


def _pack(args) -> int:
    from . import packs

    action = args.action or "list"
    if action == "list":
        table = Table(title="Task packs", header_style="bold #b794f4")
        table.add_column("Key", style="bold")
        table.add_column("Pack")
        table.add_column("Domain")
        table.add_column("Task")
        table.add_column("Summary", overflow="fold")
        for key in sorted(packs.PACKS):
            pack = packs.PACKS[key]
            table.add_row(key, pack.label, pack.domain, str(pack.task), pack.summary)
        console.print(table)
        console.print(
            f"[dim]{len(packs.PACKS)} pack(s). `sovereign pack show KEY` · "
            f"`sovereign pack brief KEY --path AGENTS.md`[/]"
        )
        return 0

    p = packs.get_pack(args.key)
    if p is None:
        console.print(f"[red]No such pack:[/] {args.key}")
        console.print(f"[dim]Packs: {', '.join(sorted(packs.PACKS))}[/]")
        return 1

    if action == "show":
        console.print(f"[bold]{p.label}[/]  ({p.key})")
        console.print(f"domain: {p.domain} · task: {p.task.value}")
        console.print(p.summary)
        console.print()
        console.print("[bold]Guardrails[/]")
        for rule in p.guardrails:
            console.print(f"- {rule}")
        console.print()
        console.print("[bold]Steps[/]")
        for index, step in enumerate(p.steps, start=1):
            console.print(f"{index}. {step}")
        console.print()
        console.print("[bold]Deliverables[/]")
        for name in p.deliverables:
            console.print(f"- {name}")
        console.print()
        console.print("[bold]Model candidates[/]")
        for q in p.model_queries:
            console.print(f"- {q}")
        console.print()
        console.print("[bold]Suggested skills[/]")
        for name, desc in packs.pack_skills(p, limit=6):
            console.print(f"- **{name}** — {packs._first(desc)}")
        console.print()
        console.print("[dim]sovereign pack brief KEY --path AGENTS.md[/]")
        return 0

    if action == "models":
        from .hf import HFError

        try:
            found = packs.hf_candidates(p, limit=args.limit)
        except HFError as exc:
            console.print(f"[red]Hugging Face:[/] {exc}")
            return 1
        for query, hits in found.items():
            console.print(f"[bold]{query}[/]")
            for h in hits:
                if "error" in h:
                    console.print(f"  [red]{h['error']}[/]")
                else:
                    console.print(
                        f"  {h['id']}  downloads={h['downloads']} "
                        f"license={h['license']} gated={h['gated']}"
                    )
        console.print(
            "[dim]Candidates only — verify with `sovereign model-info` / `sovereign verify`.[/]"
        )
        return 0

    if action == "brief":
        path = Path(args.path)
        skills = packs.pack_skills(p, limit=12)
        packs.write_brief(path, p, skills)
        console.print(f"[green]Wrote[/] {path}  (block: sovereign-pack:{p.key})")
        if p.key == "pentest":
            scope = packs.scope_file(path.parent)
            if scope is not None:
                console.print(f"[green]Wrote[/] {scope}  (pentest scope template)")
            else:
                console.print(f"[dim]{path.parent / 'SCOPE.md'} already exists[/]")
        console.print("[dim]Re-run to refresh the block; markers prevent duplicates.[/]")
        return 0

    console.print(f"[red]Unknown pack action:[/] {action}")
    return 1


def _hf(args) -> int:
    from . import hf as hub

    action = args.action or "status"
    try:
        if action == "status":
            return _hf_status(args, hub)
        if action == "login":
            return _hf_login(args, hub)
        if action == "logout":
            return _hf_logout(hub)
        if action == "search":
            return _hf_search(args, hub)
        if action == "info":
            return _hf_info(args, hub)
        if action == "download":
            return _hf_download(args, hub)
        if action == "list":
            return _hf_list(args, hub)
        if action == "import":
            return _hf_import(args, hub)
        if action == "remove":
            return _hf_remove(args, hub)
        raise hub.HFError(f"unknown action: {action}")
    except hub.HFError as exc:
        console.print(f"[red]Hugging Face:[/] {exc}")
        return 1


def _hf_status(args, hub) -> int:
    from .system import disk_free_gb

    status = hub.token_status(verify=not args.no_verify)
    cache = hub.hub_cache_dir()
    downloads = hub.DOWNLOAD_ROOT
    datasets = hub.DATASET_DOWNLOAD_ROOT
    cache_bytes = hub.directory_size(cache) if cache.is_dir() else 0
    download_bytes = hub.directory_size(downloads) if downloads.is_dir() else 0
    dataset_bytes = hub.directory_size(datasets) if datasets.is_dir() else 0
    file_mode = ""
    if status.present:
        try:
            file_mode = oct(status.path.stat().st_mode & 0o777)
        except OSError:
            file_mode = ""
    payload = {
        "token": status.to_dict(),
        "file_mode": file_mode,
        "cli": {"path": hub.hf_cli_path() or "", "version": hub.hf_cli_version()},
        "cache_dir": str(cache),
        "cache_bytes": cache_bytes,
        "download_dir": str(downloads),
        "download_bytes": download_bytes,
        "dataset_dir": str(datasets),
        "dataset_bytes": dataset_bytes,
        "disk_free_gb": disk_free_gb(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    table = Table(title="Hugging Face Hub", header_style="bold #b794f4", box=None)
    table.add_column("Setting", style="bold #8a8aa0")
    table.add_column("Value")
    if status.present:
        source = (
            f"environment ({status.source})"
            if status.source in hub.TOKEN_ENV_VARS
            else "token file"
        )
        state = "verified" if status.verified else "found (not verified)"
        if status.account:
            state += f" · {status.account}"
        if status.error:
            state = f"[red]{status.error}[/]"
        table.add_row("Token", f"{state} · {source}")
    else:
        table.add_row("Token", "[yellow]not logged in[/]")
    table.add_row(
        "Token file",
        str(status.path) + (f" · mode {file_mode}" if file_mode else ""),
    )
    cli_version = hub.hf_cli_version()
    table.add_row(
        "HF CLI",
        f"{hub.hf_cli_path() or '[red]not installed[/]'}"
        + (f" · {cli_version}" if cli_version else ""),
    )
    table.add_row("Hub cache", f"{cache} · {human_size(cache_bytes)}")
    table.add_row("Model downloads", f"{downloads} · {human_size(download_bytes)}")
    table.add_row("Dataset downloads", f"{datasets} · {human_size(dataset_bytes)}")
    table.add_row("Disk free", f"{disk_free_gb():.1f} GB")
    console.print(table)
    if file_mode and file_mode != "0o600":
        console.print(
            f"[yellow]Warning:[/] {status.path} is mode {file_mode}; run `chmod 600` on it."
        )
    if not status.present:
        console.print(
            "[dim]Public search works without a token. Log in for gated/private models:[/]"
        )
        console.print("  sovereign hf login")
    elif status.error:
        console.print("[dim]Replace the token with:[/] sovereign hf login")
    return 0


def _hf_login(args, hub) -> int:
    if args.browser:
        executable = hub.hf_cli_path()
        if not executable:
            raise hub.HFError("the `hf` CLI is not installed; run `brew install hf`")
        result = subprocess.run([executable, "auth", "login"], check=False)
        return int(result.returncode)

    if args.token_stdin:
        token = sys.stdin.read()
    else:
        if not sys.stdin.isatty():
            raise hub.HFError(
                "no terminal for a hidden prompt; pipe a token with "
                "`pbpaste | sovereign hf login --token-stdin`"
            )
        token = getpass.getpass("Hugging Face token (hidden, not echoed): ")
    status = hub.save_token(token, verify=not args.no_verify)
    if status.verified:
        console.print(f"[green]Logged in[/] as {status.account or 'Hugging Face account'}")
    else:
        console.print("[green]Token saved[/] (not verified)")
    console.print(f"[dim]Stored in[/] {status.path} [dim]mode 0600[/]")
    env_name = next((name for name in hub.TOKEN_ENV_VARS if os.environ.get(name)), "")
    if env_name:
        console.print(
            f"[yellow]Note:[/] {env_name} is set and takes precedence over the saved token."
        )
    return 0


def _hf_logout(hub) -> int:
    removed = hub.forget_token()
    if removed:
        console.print("[green]Removed[/] the stored Hugging Face token.")
    else:
        console.print("[dim]No stored Hugging Face token.[/]")
    env_name = next((name for name in hub.TOKEN_ENV_VARS if os.environ.get(name)), "")
    if env_name:
        console.print(
            f"[yellow]Note:[/] {env_name} is still set in the environment and remains active."
        )
    return 0


def _hf_search(args, hub) -> int:
    query = args.target or ""
    repo_type = "dataset" if args.dataset else "model"
    if not query.strip():
        raise hub.HFError("usage: sovereign hf search <words> [--gguf] [--dataset]")
    token = hub.resolve_token()[0]
    filters = [str(item).strip() for item in args.filter if str(item).strip()]
    for prefix, value in (
        ("license", args.license),
        ("language", args.language),
        ("format", args.format),
    ):
        if value:
            filters.append(f"{prefix}:{value}")
    rows = hub.search_models(
        query,
        limit=args.limit,
        gguf_only=args.gguf,
        author=args.author,
        sort=args.sort,
        token=token or None,
        repo_type=repo_type,
        filters=filters,
        pipeline_tag=args.pipeline,
    )
    if args.json:
        print(json.dumps([row.to_dict() for row in rows], indent=2, default=str))
        return 0
    if not rows:
        console.print(f"[yellow]No {repo_type}s match[/] {query!r}")
        return 1
    label = "Datasets" if repo_type == "dataset" else "Models"
    table = Table(
        title=f"Hugging Face {label.lower()} · {query!r}",
        header_style="bold #b794f4",
    )
    table.add_column("Repository", style="bold", overflow="fold")
    table.add_column("Downloads", justify="right")
    table.add_column("Likes", justify="right")
    table.add_column("Updated")
    table.add_column("Meta", overflow="fold")
    for row in rows:
        name = row.id + (f" [magenta]· {row.gated}[/]" if row.gated else "")
        meta: list[str] = []
        if row.pipeline_tag:
            meta.append(row.pipeline_tag)
        meta.extend(row.tasks[:1])
        if row.license:
            meta.append(row.license)
        if row.languages:
            meta.append("/".join(row.languages[:2]))
        if row.formats:
            meta.append("/".join(row.formats[:2]))
        meta.extend(tag for tag in row.tags if tag in {"gguf", "mlx", "safetensors"})
        meta = list(dict.fromkeys(meta))
        table.add_row(
            name,
            f"{row.downloads:,}",
            f"{row.likes:,}",
            row.updated or "-",
            ", ".join(meta)[:100] or "-",
        )
    console.print(table)
    suffix = " --dataset" if args.dataset else ""
    console.print(f"[dim]Inspect with:[/] sovereign hf info <org/repo>{suffix}")
    return 0


def _hf_info(args, hub) -> int:
    repo = args.target or ""
    repo_type = "dataset" if args.dataset else "model"
    if not repo:
        raise hub.HFError("usage: sovereign hf info <org/repo> [--dataset]")
    token = hub.resolve_token()[0] or None
    info = hub.info_model(repo, token=token, repo_type=repo_type)
    if args.json:
        print(json.dumps(info.to_dict(), indent=2, default=str))
        return 0

    table = Table(
        title=f"Hugging Face {repo_type}",
        header_style="bold #b794f4",
        box=None,
    )
    table.add_column("Field", style="bold #8a8aa0")
    table.add_column("Value", overflow="fold")
    table.add_row("Repository", info.id)
    table.add_row("Type", info.repo_type)
    table.add_row("Downloads", f"{info.downloads:,}")
    table.add_row("Likes", f"{info.likes:,}")
    if info.pipeline_tag:
        table.add_row("Pipeline", info.pipeline_tag)
    if info.tasks:
        table.add_row("Task", ", ".join(info.tasks[:3]))
    if info.license:
        table.add_row("License", info.license)
    if info.languages:
        table.add_row("Languages", ", ".join(info.languages[:8]))
    if info.formats:
        table.add_row("Formats", ", ".join(info.formats[:8]))
    if info.base_models:
        table.add_row("Base models", ", ".join(info.base_models[:3]))
    table.add_row("Updated", info.updated or "-")
    if info.gated:
        table.add_row("Gated", info.gated)
    if info.private:
        table.add_row("Private", "yes")
    table.add_row("Repository storage", human_size(info.used_storage or info.total_file_size))
    if info.gguf:
        context = info.gguf.get("context_length")
        architecture = info.gguf.get("architecture")
        if context:
            table.add_row("GGUF context", f"{int(context):,} tokens")
        if architecture:
            table.add_row("GGUF architecture", str(architecture))
    console.print(table)

    if info.gguf_files:
        _hf_file_table("GGUF files", info.gguf_files, limit=None if args.files else 20)
    else:
        files = sorted(info.files, key=lambda item: item.size, reverse=True)
        _hf_file_table(
            "Files" if args.files else "Largest files",
            files,
            limit=None if args.files else 15,
        )
    if args.readme:
        text = hub.readme(repo, repo_type=repo_type, token=token, limit=6000)
        if text:
            console.print(Panel(Text(text), title="README", border_style="dim"))
        else:
            console.print("[dim]No README found.[/]")
    suffix = " --dataset" if args.dataset else ""
    example = '--include "*.parquet"' if repo_type == "dataset" else '--include "*Q4_K_M.gguf"'
    console.print(f"[dim]Download a subset:[/] sovereign hf download {info.id} {example}{suffix}")
    if info.gguf_files:
        console.print(
            f"[dim]Import into Ollama:[/] sovereign hf import {info.id} {example} --name <name>"
        )
    return 0


def _hf_file_table(title: str, files, limit: int | None = 15) -> None:
    rows = list(files)
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        return
    table = Table(title=title, header_style="bold #b794f4")
    table.add_column("File", overflow="fold")
    table.add_column("Size", justify="right")
    for item in rows:
        table.add_row(item.path, human_size(item.size) if item.size else "-")
    console.print(table)
    if limit is not None and len(files) > limit:
        console.print(f"[dim]… {len(files) - limit} more files; use --files to list all.[/]")


def _hf_selected_files(info, patterns: list[str], all_files: bool):
    if all_files:
        return list(info.files)
    return [
        item
        for item in info.files
        if any(fnmatch.fnmatch(item.path, pattern) for pattern in patterns)
    ]


def _hf_download(args, hub) -> int:
    import shlex

    repo = args.target or ""
    repo_type = "dataset" if args.dataset else "model"
    if not repo:
        raise hub.HFError("usage: sovereign hf download <org/repo> --include PATTERN [--dataset]")
    token = hub.resolve_token()[0] or None
    info = None
    try:
        info = hub.info_model(repo, token=token, repo_type=repo_type)
    except hub.HFError as exc:
        if not args.include and not args.download_all:
            raise
        console.print(f"[yellow]Could not inspect the repository first:[/] {exc}")

    if not args.include and not args.download_all:
        if info is not None:
            if info.gguf_files:
                _hf_file_table("GGUF files", info.gguf_files, limit=None)
            else:
                _hf_file_table("Files", info.files, limit=30)
        console.print(
            "[yellow]Pick files explicitly.[/] Add --include PATTERN (repeatable) "
            "or --all for the whole repository."
        )
        suffix = " --dataset" if args.dataset else ""
        example = '--include "*.parquet"' if args.dataset else '--include "*Q4_K_M.gguf"'
        console.print(f"[dim]Example:[/] sovereign hf download {repo} {example}{suffix}")
        return 1

    selected = _hf_selected_files(info, args.include, args.download_all) if info else []
    if info is not None and not selected:
        raise hub.HFError("no files matched the include patterns; check `sovereign hf info`")
    total = sum(item.size for item in selected)
    if info is not None:
        console.print(f"[dim]Selected[/] {len(selected)} file(s), {human_size(total)}")
        if total > 20 * 1024**3 and not args.yes:
            if not sys.stdin.isatty():
                raise hub.HFError("large download; re-run with --yes to confirm")
            answer = input(f"Download {human_size(total)}? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                console.print("[dim]Cancelled.[/]")
                return 1

    destination = (
        Path(args.local_dir).expanduser()
        if args.local_dir
        else hub.default_download_dir(repo, repo_type)
    )
    command = hub.build_download_command(
        repo,
        repo_type=repo_type,
        include=args.include,
        exclude=args.exclude,
        all_files=args.download_all,
        revision=args.revision,
        local_dir=destination,
        cache_dir=args.cache_dir,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
    )
    console.print(f"[bold]Hugging Face {repo_type}[/] {repo}")
    console.print(f"[dim]Destination:[/] {destination}")
    console.print(f"[dim]Command:[/] {shlex.join(command)}")
    if args.dry_run:
        console.print("[dim]Dry run: nothing was downloaded.[/]")
        return 0
    log_download(repo, source="huggingface", status="starting", total=int(total))
    try:
        destination, command = hub.download_model(
            repo,
            repo_type=repo_type,
            include=args.include,
            exclude=args.exclude,
            all_files=args.download_all,
            revision=args.revision,
            local_dir=destination,
            cache_dir=args.cache_dir,
            max_workers=args.max_workers,
            dry_run=False,
            token=token,
        )
    except Exception as exc:
        log_download(repo, source="huggingface", error=str(exc))
        raise
    log_download(
        repo,
        source="huggingface",
        status="done",
        completed=int(total),
        total=int(total),
        done=True,
    )
    console.print(f"[green]Downloaded[/] {repo} → {destination}")
    if info is not None and info.gguf_files:
        console.print(
            f"[dim]Import into Ollama:[/] sovereign hf import {repo} "
            f'--include "{args.include[0] if args.include else "*Q4_K_M.gguf"}" '
            "--name <name>"
        )
    return 0


def _hf_list(args, hub) -> int:
    repo_type = "dataset" if args.dataset else None
    rows = hub.local_repos(repo_type)
    if args.json:
        print(json.dumps([row.to_dict() for row in rows], indent=2, default=str))
        return 0
    if not rows:
        label = repo_type or "Hugging Face"
        console.print(f"[dim]No local {label} downloads or cache entries.[/]")
        return 0
    title = (
        "Local Hugging Face datasets"
        if repo_type == "dataset"
        else "Local Hugging Face repositories"
    )
    table = Table(title=title, header_style="bold #b794f4")
    table.add_column("Type")
    table.add_column("Repository", style="bold", overflow="fold")
    table.add_column("Storage")
    table.add_column("Size", justify="right")
    table.add_column("Modified")
    table.add_column("Path", overflow="fold")
    for row in rows:
        table.add_row(
            row.repo_type,
            row.repo_id,
            row.kind,
            human_size(row.bytes),
            row.modified or "-",
            str(row.path),
        )
    console.print(table)
    models = sum(1 for row in rows if row.repo_type == "model")
    datasets = sum(1 for row in rows if row.repo_type == "dataset")
    console.print(
        f"[dim]{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} · "
        f"{models} model(s), {datasets} dataset(s) · "
        f"total {human_size(sum(row.bytes for row in rows))}[/]"
    )
    return 0


def _hf_remove(args, hub) -> int:
    repo = args.target or ""
    repo_type = "dataset" if args.dataset else "model"
    if not repo:
        raise hub.HFError("usage: sovereign hf remove <org/repo> [--dataset] [--yes]")
    paths = hub.local_repo_paths(repo, repo_type)
    if not paths:
        console.print(f"[dim]No local copy of[/] {repo}")
        return 0
    sizes = [hub.directory_size(path) if path.is_dir() else path.stat().st_size for path in paths]
    total = sum(sizes)
    for path, size in zip(paths, sizes, strict=True):
        console.print(f"  {path} · {human_size(size)}")
    if not args.yes:
        if not sys.stdin.isatty():
            raise hub.HFError("refusing to delete without confirmation; re-run with --yes")
        answer = input(f"Delete {human_size(total)} for {repo}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            console.print("[dim]Cancelled.[/]")
            return 1
    removed = hub.remove_local(repo, repo_type)
    console.print(f"[green]Removed[/] {repo} · {len(removed)} local path(s), {human_size(total)}")
    return 0


def _hf_import(args, hub) -> int:
    import shlex
    import tempfile

    target = (args.target or "").strip()
    if not target:
        raise hub.HFError("usage: sovereign hf import <org/repo|file.gguf> --include PATTERN")
    if args.dataset:
        raise hub.HFError("Ollama imports model GGUFs, not dataset repositories")
    ollama = shutil.which("ollama")
    if not ollama:
        raise hub.HFError("the `ollama` CLI is not installed")
    if args.context is not None and args.context < 1:
        raise hub.HFError("--context must be a positive token count")

    token = hub.resolve_token()[0] or None
    info = None
    source_repo = target
    destination: Path
    candidate = Path(target).expanduser()
    if candidate.exists():
        if candidate.is_dir():
            destination = candidate
            files = sorted(candidate.glob("*.gguf"))
        elif candidate.is_file() and candidate.suffix.lower() == ".gguf":
            destination = candidate.parent
            files = [candidate]
        else:
            raise hub.HFError(f"not a GGUF file or directory: {candidate}")
        source_repo = candidate.stem if candidate.is_file() else candidate.name
    else:
        info = hub.info_model(target, token=token)
        destination = hub.default_download_dir(target)
        files = sorted(destination.rglob("*.gguf")) if destination.is_dir() else []

    if args.include:
        files = [
            path
            for path in files
            if any(
                fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern)
                for pattern in args.include
            )
        ]
    if not files:
        if info is None:
            raise hub.HFError(f"no GGUF files found in {destination}")
        if not args.include:
            _hf_file_table("GGUF files", info.gguf_files, limit=None)
            raise hub.HFError("choose one GGUF with --include PATTERN")
        selected = _hf_selected_files(info, args.include, False)
        if not selected:
            raise hub.HFError("no files matched the include patterns; check `sovereign hf info`")
        total = sum(item.size for item in selected)
        console.print(f"[dim]Selected[/] {len(selected)} file(s), {human_size(total)}")
        if total > 20 * 1024**3 and not args.yes:
            if not sys.stdin.isatty():
                raise hub.HFError("large download; re-run with --yes to confirm")
            answer = input(f"Download {human_size(total)}? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                console.print("[dim]Cancelled.[/]")
                return 1
        if args.dry_run:
            command = hub.build_download_command(
                target,
                include=args.include,
                exclude=args.exclude,
                local_dir=destination,
                max_workers=args.max_workers,
            )
            console.print(f"[dim]Would download:[/] {shlex.join(command)}")
            return 0
        destination, _ = hub.download_model(
            target,
            include=args.include,
            exclude=args.exclude,
            local_dir=destination,
            max_workers=args.max_workers,
            token=token,
        )
        files = sorted(destination.rglob("*.gguf"))
        files = [
            path
            for path in files
            if any(
                fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern)
                for pattern in args.include
            )
        ]
    if not files:
        raise hub.HFError("the download finished but no matching GGUF file was found")
    if len(files) > 1:
        names = ", ".join(path.name for path in files[:5])
        raise hub.HFError(
            f"multiple GGUF files matched ({names}); narrow --include to one quantization"
        )
    gguf = files[0]
    if hub.is_split_gguf(gguf):
        raise hub.HFError(
            "this is one part of a split GGUF; choose a single-file quantization "
            "or merge the parts first"
        )

    name = args.name or hub.ollama_model_name(source_repo, gguf)
    if not hub.valid_ollama_name(name):
        raise hub.HFError(f"invalid Ollama model name: {name!r}")
    content = hub.modelfile_text(gguf, context=args.context)
    if args.dry_run:
        console.print(Panel(Text(content), title=f"Modelfile for {name}", border_style="dim"))
        console.print(f"[dim]Command:[/] {ollama} create {name} -f <temporary Modelfile>")
        return 0

    modelfile: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            prefix="sovereign-",
            suffix=".Modelfile",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(content)
            modelfile = Path(handle.name)
        console.print(f"[bold]Importing[/] {gguf.name} as [bold]{name}[/]")
        result = subprocess.run(
            [ollama, "create", name, "-f", str(modelfile)],
            check=False,
        )
    finally:
        if modelfile is not None:
            modelfile.unlink(missing_ok=True)
    if result.returncode != 0:
        raise hub.HFError(f"ollama create exited with status {result.returncode}")
    console.print(f"[green]Imported[/] {name}")
    console.print(f"[dim]Run it:[/] ollama run {name}")
    return 0


def _skills(
    action: str = "list",
    target: str = "all",
    project: str | None = None,
    include_all: bool = False,
    names: list[str] | None = None,
    dry_run: bool = False,
    query: str | None = None,
    limit: int = 30,
) -> int:
    from .skills_install import TARGETS, install, installed_counts, load_curated

    if action == "search":
        from .skills import search_skills

        if not query:
            console.print("[red]Usage:[/] sovereign skills search <words>")
            return 1
        found = search_skills(query, limit=limit)
        if not found:
            console.print(f"[yellow]No skills match[/] {query!r}")
            return 1
        table = Table(title=f"Skills matching {query!r}", header_style="bold #b794f4")
        table.add_column("Name", style="bold")
        table.add_column("Description", overflow="fold")
        for name, description in found:
            table.add_row(name, description[:160])
        console.print(table)
        console.print("[dim]Install one with: sovereign skills install --name <name>[/]")
        return 0

    if action == "install":
        targets = (
            "all"
            if target == "all"
            else [part.strip() for part in target.split(",") if part.strip()]
        )
        try:
            written = install(
                targets=targets,
                names=names or [],
                include_all=include_all,
                project=Path(project).expanduser() if project else None,
                dry_run=dry_run,
            )
        except (OSError, ValueError) as exc:
            console.print(f"[red]Skill install failed:[/] {exc}")
            return 1
        table = Table(title="Installed skills", header_style="bold #b794f4")
        table.add_column("Target", style="bold")
        table.add_column("Count", justify="right")
        for key, paths in written.items():
            table.add_row(key, str(len(paths)))
        console.print(table)
        if dry_run:
            console.print("[dim]Dry run: nothing was written.[/]")
        else:
            console.print("[dim]Clients read SKILL.md; Continue reads prompt files.[/]")
        return 0

    rows = list_skills()
    table = Table(title="Skills", header_style="bold #b794f4")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    # The checkout ships tens of thousands of skills; printing all of them is
    # not a listing, it is a wall. Show a useful slice and point at search.
    for name, description in rows[:40]:
        table.add_row(name, description)
    if rows:
        console.print(table)
        if len(rows) > 40:
            console.print(
                f"[dim]… {len(rows) - 40} more. Run one by name: "
                "sovereign skill <name> --prompt '…'[/]"
            )
    else:
        console.print("[yellow]No prompt skills in config/skills yet.[/]")

    curated = load_curated()
    counts = installed_counts()
    itable = Table(title="Curated library", header_style="bold #b794f4")
    itable.add_column("Target", style="bold")
    itable.add_column("Installed", justify="right")
    itable.add_column("Source")
    for key in ("claude", "codex", "qwen", "opencode", "continue"):
        source = str(TARGETS[key]()) if key in TARGETS else "~/.continue/prompts"
        itable.add_row(key, str(counts.get(key, 0)), source)
    console.print(itable)
    console.print(
        f"[dim]{len(curated)} curated skills available. Install:[/] "
        "sovereign skills install --target all"
    )
    console.print("[dim]Run one prompt skill: sovereign skill <name> --prompt '…'[/]")
    return 0


def _skill(
    settings: Settings, name: str | None, prompt: str | None, model: str, tokens: int
) -> int:
    if not name:
        return _skills()
    template = read_skill(name)
    if template is None:
        console.print(f"[red]Unknown skill[/] {name}. Run: sovereign skills")
        return 1
    if not prompt:
        console.print(Panel(Text(template), title=name, border_style="dim"))
        console.print("[dim]Run it: sovereign skill " + name + " --prompt '…'[/]")
        return 0
    console.print(f"[dim]Running {name} via {model}…[/]")
    try:
        answer = complete(
            settings.gateway_url,
            model,
            [{"role": "user", "content": render_skill(name, prompt)}],
            max_tokens=tokens,
        )
    except SourceError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    console.print(Panel(Text(answer), title=name, border_style="cyan"))
    return 0


def _memory(action: str, text: str | None, project: str | None) -> int:
    cwd = Path(project).expanduser().resolve() if project else Path.cwd()
    if action == "add":
        if not text or not text.strip():
            console.print("[red]Usage:[/] sovereign memory add 'note about this project'")
            return 1
        path = add_memory(text, cwd)
        console.print(f"[green]Remembered[/] in {path}")
        return 0
    if action == "clear":
        path = clear_memory(cwd)
        console.print(f"[green]Cleared[/] {path}")
        return 0
    content = read_memory(cwd)
    console.print(Panel(Text(content), title=f"Project memory · {cwd.name}", border_style="dim"))
    return 0


def _clone(url: str, name: str | None) -> int:
    if not url or not re.match(r"^(https?://|git@|ssh://)", url):
        console.print("[red]Give a git URL[/] (https:// or git@).")
        return 1
    dest_root = Path.home() / "Documents" / "projects"
    dest_root.mkdir(parents=True, exist_ok=True)
    target = dest_root / (name or url.rstrip("/").split("/")[-1].replace(".git", ""))
    if target.exists():
        console.print(f"[yellow]{target} already exists.[/]")
        return 1
    console.print(f"[dim]Cloning {url} into {target}…[/]")
    result = subprocess.run(["git", "clone", url, str(target)], check=False)
    if result.returncode != 0:
        console.print("[red]git clone failed.[/]")
        return 1
    console.print(f"[green]Cloned[/] {target}")
    console.print(f"[dim]Index it for search:[/] sovereign index {target}")
    return 0


def _is_git_repo(target: Path) -> bool:
    return (target / ".git").exists()


def _project_changes(target: Path, limit: int = 8000) -> str:
    """The actual change set: git diff, else a git status listing, else ''."""
    try:
        diff = subprocess.run(
            ["git", "-C", str(target), "diff", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        status = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return ""
    parts = []
    if status.strip():
        parts.append("Changed files:\n" + status.strip())
    if diff.strip():
        parts.append("Diff:\n" + diff.strip())
    return ("\n\n".join(parts))[-limit:] if parts else ""


def _pipeline(
    settings: Settings,
    prompt: str,
    directory: str,
    plan_model: str,
    agent: str,
    review_model: str,
    yes: bool,
    no_review: bool,
    tokens: int,
    checks: str | None = None,
    no_verify: bool = False,
    max_fixes: int = 1,
    timeout: float = 900.0,
    review_tokens: int = 1600,
    agent_client: str = "qwen",
    agent_timeout: float = 900.0,
    dry_run: bool = False,
    mode: str = "auto",
    direct_tokens: int = 4000,
    fix_model: str | None = None,
) -> int:
    import httpx

    try:
        shared_client().get(
            settings.gateway_url.rstrip("/") + "/v1/models", timeout=3.0
        ).raise_for_status()
    except httpx.HTTPError:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway --restart")
        return 1
    target = Path(directory).expanduser().resolve()
    if not target.is_dir():
        console.print(f"[red]Not a directory:[/] {target}")
        return 1
    if agent_client not in AGENT_CLIENTS:
        console.print(f"[red]Unknown agent client:[/] {agent_client}")
        console.print(f"[dim]Choose one of: {', '.join(AGENT_CLIENTS)}[/]")
        return 1
    if not command_exists(AGENT_CLIENTS[agent_client]) and mode != "direct":
        console.print(f"[red]{agent_client} CLI is not installed.[/]")
        console.print("[dim]Direct mode needs only Ollama: rerun with --mode direct[/]")
        return 1

    # The pipeline cycles through several large models; start from a clean GPU
    # so a 19 GB planner and an 18 GB coder never fight for the wired budget.
    def clear_gpu(label: str = "") -> None:
        """Evict residents so the next model gets the whole wired budget.

        A 19 GB planner and an 18 GB coder cannot coexist; leaving the planner
        loaded made the implementer fail with provider retries.
        """
        snap = _snapshot(settings)
        if not snap.loaded:
            return
        if label:
            console.print(f"[dim]Unloading {len(snap.loaded)} model(s) before {label}[/]")

        async def _clear() -> None:
            client = OllamaClient(settings.ollama_url)
            for view in snap.loaded:
                try:
                    await client.unload(view.tag)
                except OllamaError:
                    pass

        asyncio.run(_clear())

    if not dry_run:
        clear_gpu("planning")

    # Verification is what makes the result trustworthy: the project's own
    # tests decide, not the models.
    if no_verify:
        check_commands: list[str] = []
    elif checks:
        check_commands = [part.strip() for part in checks.split(";") if part.strip()]
    else:
        check_commands = detect_checks(target)
    latest_check: dict[str, str] = {"log": ""}

    def plan_fn(text: str) -> str:
        return complete(
            settings.gateway_url,
            plan_model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a staff engineer. Write a concise, ordered implementation "
                        "plan: files to create or edit, key functions, and acceptance checks. "
                        "Be specific and minimal."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=tokens,
        )

    def _direct_implementation(
        prompt_text: str, plan_text: str, failure: str, model: str | None = None
    ) -> tuple[bool, str]:
        """One request, whole files, no agent loop (seconds instead of minutes)."""
        files = relevant_files(target, prompt_text)
        messages = build_messages(prompt_text, plan_text, files, failure)
        # Ollama can restart underneath us (app restart, memory pressure). A
        # transport blip should not throw away the run.
        last_error = ""
        raw = ""
        for attempt in range(2):
            try:
                raw = complete(
                    settings.ollama_url,
                    model or agent,
                    messages,
                    max_tokens=direct_tokens,
                    timeout=max(120.0, agent_timeout),
                )
                break
            except SourceError as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(2.0)
        if not raw:
            return False, f"direct request failed: {last_error}"
        writes = parse_blocks(raw)
        if not writes:
            return False, raw[-2000:] or "model returned no file blocks"
        written, rejected = apply_writes(target, writes)
        lines = [f"wrote {len(written)} file(s): " + ", ".join(written)]
        if rejected:
            lines.append("rejected (unsafe path or too large): " + ", ".join(rejected))
        return bool(written), "\n".join(lines)

    def _agent_implementation(prompt_text: str, plan_text: str, failure: str) -> tuple[bool, str]:
        context = project_context(target)
        combined = (
            f"{prompt_text}\n\nImplementation plan:\n{plan_text}\n\n"
            "Implement it now: create or edit the files."
        )
        if failure:
            combined += (
                "\n\nThe project's checks failed after your last attempt. Fix the code so they "
                f"pass.\n\nCheck output:\n{failure}"
            )
        if context:
            combined = context + "\n\n" + combined

        try:
            plan = build_headless(
                agent_client,
                "local",
                target,
                combined,
                settings,
                agent,
                unattended=yes,
                wall_time=max(30, int(agent_timeout) - 20),
                max_tool_calls=12,
            )
        except ValueError as exc:
            return False, str(exc)
        ok, output = run_headless(plan, timeout=agent_timeout)
        stopped_early = "timed out" in output or "[exit 55]" in output
        if not ok and stopped_early:
            # Local agent CLIs sometimes finish the edits and then hang. If the
            # tree actually changed, let the checks decide instead of throwing
            # the work away.
            changes = _project_changes(target)
            if changes:
                ok = True
                output += (
                    "\n\nAgent hit its time limit after making changes; "
                    "handing the result to verification."
                )
        return ok, output

    def implement_fn(prompt_text: str, plan_text: str, failure: str = "") -> tuple[bool, str]:
        clear_gpu("implementation")

        # Load the coder before either path starts: an 18 GB cold load inside the
        # first provider call looks like a provider failure and triggers retries.
        async def _preload() -> None:
            client = OllamaClient(settings.ollama_url)
            try:
                await client.preload(agent, 16384)
            except OllamaError:
                pass

        asyncio.run(_preload())

        if mode in ("direct", "auto"):
            ok, output = _direct_implementation(prompt_text, plan_text, failure)
            if ok or mode == "direct":
                return ok, output
            note = "Direct mode produced no file blocks; falling back to the agent.\n\n"
            ok, agent_output = _agent_implementation(prompt_text, plan_text, failure)
            return ok, note + agent_output
        return _agent_implementation(prompt_text, plan_text, failure)

    def review_fn(plan_text: str, implementation: str) -> str:
        clear_gpu("review")
        changes = _project_changes(target)
        return complete(
            settings.gateway_url,
            review_model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a strict reviewer. Given the plan and the implementation "
                        "log, list concrete problems, risks, and follow-ups. Be specific."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Plan:\n{plan_text}\n\nImplementation log:\n{implementation}\n\n"
                        f"Project checks:\n{latest_check['log'][-2000:] or 'not run'}\n\n"
                        f"Actual changes:\n{changes or 'no git repository'}"
                    ),
                },
            ],
            # Reasoning models (gpt-oss in particular) spend tokens on hidden
            # reasoning before answering; too small a budget returns "".
            max_tokens=max(review_tokens, 600),
        )

    def verify_fn() -> tuple[bool, str]:
        # An agent can report success while changing nothing; running the checks
        # then fails on a missing module and hides the real problem.
        if _is_git_repo(target) and not _project_changes(target):
            log = "No files were changed by the implementer."
            latest_check["log"] = log
            return False, log
        outcome = run_checks(target, check_commands, timeout=timeout)
        latest_check["log"] = outcome.log
        return outcome.ok, outcome.log

    def fix_fn(prompt_text: str, plan_text: str, failure: str) -> tuple[bool, str]:
        """Repair with the small model first; a narrow fix should be cheap.

        A failed check usually means a typo, an import, or one wrong branch —
        work a 4B model does well and much faster than reloading the 18 GB
        planner. If the small model cannot produce a file block, the regular
        implementer still gets the round.
        """
        if fix_model and mode in ("direct", "auto"):
            clear_gpu("repair")
            ok, output = _direct_implementation(prompt_text, plan_text, failure, model=fix_model)
            if ok:
                return ok, output
            if mode == "direct":
                return ok, output
            return implement_fn(prompt_text, plan_text, failure)
        return implement_fn(prompt_text, plan_text, failure)

    timings: dict[str, float] = {}
    stage_info = {
        "plan": ("plan", plan_model),
        "implement": ("edit", agent),
        "verify": ("checks", ""),
        "fix": ("fix", fix_model or agent),
        "review": ("review", review_model),
    }

    def timed(label: str, fn):
        """Record wall time per stage so the summary explains where it went."""

        def wrapper(*args, **kwargs):
            started = time.monotonic()
            role, model = stage_info.get(label, ("", ""))
            recorder.stage_start(label, role=role, model=model)
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - started
                timings[label] = round(timings.get(label, 0.0) + elapsed, 1)

        return wrapper

    shown = ", ".join(check_commands) if check_commands else "none"
    if dry_run:
        console.print(
            f"[bold]Dry run[/] · dir={target} · plan={plan_model} · "
            f"implement={agent_client}({agent}, {mode}) · review={review_model} · "
            f"fix={fix_model or agent}"
        )
        console.print(f"checks: {shown}")
        console.print(
            f"fix rounds: {max_fixes} · agent timeout: {agent_timeout:.0f}s · "
            f"check timeout: {timeout:.0f}s"
        )
        console.print("[dim]Nothing was run.[/]")
        return 0
    console.print(
        f"[bold]Pipeline[/] · plan={plan_model} · implement={agent_client}({agent}) · "
        f"review={review_model} · checks={shown}"
    )
    if fix_model:
        console.print(f"[dim]Small repair model:[/] {fix_model}")
    from .harness import RunRecorder

    recorder = RunRecorder(prompt, str(target))
    recorder.start()

    def on_stage(stage) -> None:
        """Print and publish each result the moment it exists."""
        key = stage.name.split()[0]
        role, model = stage_info.get(key, ("", ""))
        recorder.stage_end(
            stage.name,
            role=role,
            model=model,
            ok=stage.ok,
            ms=timings.get(key, 0.0) * 1000,
            output=stage.output,
        )
        border = "green" if stage.ok else "red"
        console.print(Panel(Text(stage.output), title=stage.name, border_style=border))

    try:
        result = run_pipeline(
            prompt,
            timed("plan", plan_fn),
            timed("implement", implement_fn),
            None if no_review else timed("review", review_fn),
            verify=None if not check_commands else timed("verify", verify_fn),
            fix=timed("fix", fix_fn) if max_fixes > 0 else None,
            max_fixes=max(0, max_fixes),
            on_stage=on_stage,
        )
    except SourceError as exc:
        recorder.finish(False, None, str(exc))
        console.print(f"[red]{exc}[/]")
        return 1

    # Keep an auditable record of what the models did and what proved it.
    from datetime import datetime

    run_dir = LOCAL_AI_ROOT / "data" / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}"
    suffix = 1
    while run_dir.exists():
        # Two runs in the same second must not overwrite each other.
        suffix += 1
        run_dir = LOCAL_AI_ROOT / "data" / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)
    for stage in result.stages:
        (run_dir / f"{stage.name.replace(' ', '-')}.md").write_text(stage.output, encoding="utf-8")
    verified = {True: "passed", False: "failed", None: "not run"}[result.verified]
    summary = [
        f"prompt: {prompt}",
        f"directory: {target}",
        f"plan={plan_model} implement={agent_client}({agent}) review={review_model}",
        f"checks: {shown}",
        f"verification: {verified}",
        f"outcome: {'complete' if result.succeeded else 'incomplete'}",
        f"stages: {', '.join(stage.name for stage in result.stages)}",
        "timings: " + " · ".join(f"{name} {secs:.1f}s" for name, secs in timings.items()),
    ]
    (run_dir / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")

    state = "complete" if result.succeeded else "incomplete"
    style = "green" if result.succeeded else "red"
    recorder.finish(result.succeeded, result.verified, f"{state} · verification {verified}")
    console.print(
        f"[{style}]{state}[/] · verification {verified} · "
        f"{len(result.stages)} stages · [dim]{run_dir}[/]"
    )
    return 0 if result.succeeded else 1


def _harness(settings: Settings) -> int:
    """Show which model serves which job, plus live downloads and runs."""
    from .harness import plan_roles, recent_downloads, recent_runs

    snap = _snapshot(settings)
    roles = plan_roles(snap.views, snap.potential_free_gb, settings.max_context)
    title = Text("Sovereign runtime harness", style="bold")
    title.append(f"  ·  {LOCAL_AI_ROOT}", style="dim")
    console.print(Panel(title, border_style="#b794f4"))

    table = Table(header_style="bold #b794f4", expand=True)
    table.add_column("Job", style="bold")
    table.add_column("Tier")
    table.add_column("Model", style="cyan")
    table.add_column("Context", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Why")
    for role in roles:
        table.add_row(
            role.label,
            role.tier,
            role.tag,
            str(role.context or "—"),
            f"{role.size_gb:.1f}G" if role.size_gb else "—",
            role.reason,
        )
    console.print(table)

    if snap.loaded:
        loaded = ", ".join(f"{view.tag} ({view.context or '?'} ctx)" for view in snap.loaded)
        console.print(f"[green]Resident[/] {loaded}")
    else:
        console.print("[dim]No model resident — RAM is free.[/]")

    downloads = recent_downloads(4)
    if downloads:
        console.print("[bold]Downloads[/]")
        for item in downloads:
            console.print(f"  {item.tag:<28} {item.source:<10} {item.state}")

    runs = recent_runs(5)
    if runs:
        console.print("[bold]Recent orchestrations[/]")
        run_table = Table(header_style="bold #b794f4")
        run_table.add_column("When")
        run_table.add_column("Status")
        run_table.add_column("Stage")
        run_table.add_column("Model", style="cyan")
        run_table.add_column("Work")
        for run in runs:
            style = (
                "green"
                if run.status == "complete"
                else ("red" if run.status == "failed" else "yellow")
            )
            run_table.add_row(
                run.age,
                Text(run.status, style=style),
                run.stage or "—",
                run.model or "—",
                run.label,
            )
        console.print(run_table)
    else:
        console.print(
            '[dim]No orchestration runs yet — try:[/] sovereign orchestrate "fix the failing test"'
        )

    if not any(role.model for role in roles):
        console.print("[yellow]No models installed.[/] Run: sovereign setup")
    return 0


def _orchestrate(settings: Settings, args) -> int:
    """Route a coding task across a small repair model and larger workers."""
    from .harness import plan_roles

    snap = _snapshot(settings)
    roles = {
        role.key: role
        for role in plan_roles(snap.views, snap.potential_free_gb, settings.max_context)
    }
    edit, plan, review, fix = roles["edit"], roles["plan"], roles["review"], roles["fix"]
    if not edit.model and not args.agent:
        console.print("[red]No local coding model is installed.[/]")
        console.print("[dim]Run:[/] sovereign setup --yes --models recommended")
        return 1

    plan_model = str(args.plan_model or plan.model or edit.model)
    agent = str(args.agent or edit.model)
    review_model = str(args.review_model or review.model or edit.model)
    fix_model = args.fix_model or fix.model or agent

    console.print(
        f"[bold]Orchestrator[/] plan=[cyan]{plan_model}[/] · "
        f"implement=[cyan]{agent}[/] · fix=[cyan]{fix_model}[/] · "
        f"review=[cyan]{review_model}[/]"
    )
    return _pipeline(
        settings,
        args.prompt,
        args.dir,
        plan_model,
        agent,
        review_model,
        args.yes,
        args.no_review,
        args.tokens,
        checks=args.checks,
        no_verify=args.no_verify,
        max_fixes=args.max_fixes,
        timeout=args.timeout,
        review_tokens=args.review_tokens,
        agent_client=args.agent_client,
        agent_timeout=args.agent_timeout,
        dry_run=args.dry_run,
        mode=args.mode,
        direct_tokens=args.direct_tokens,
        fix_model=fix_model,
    )


def _install_clients() -> int:
    from .client_setup import install_all
    from .clients import write_codex_profile
    from .skills_install import install as install_skills

    profile = write_codex_profile()
    console.print(f"[green]Codex profile[/] {profile}")
    for path in install_client_wrappers():
        console.print(f"[green]Wrapper      [/] {path}")

    from .tier_gateway import ensure_running as ensure_tier

    router_ok = ensure_tier()
    console.print(
        f"[{'green' if router_ok else 'yellow'}]{'Tier gateway started' if router_ok else 'Tier gateway not running'}[/] "
        "[dim](http://127.0.0.1:4010/v1 · auto/fast/balanced/deep)[/]"
    )
    rows = install_all()
    table = Table(title="Client integrations", header_style="bold #b794f4")
    table.add_column("Component", style="bold")
    table.add_column("Result", overflow="fold")
    for label, result in rows:
        table.add_row(label, result)
    console.print(table)

    try:
        installed = install_skills(targets="all")
    except OSError as exc:
        console.print(f"[yellow]Skills install skipped:[/] {exc}")
        installed = {}
    console.print(
        "[green]Skills[/] " + ", ".join(f"{key}={len(paths)}" for key, paths in installed.items())
    )
    console.print(
        "[dim]Launch: sovereign launch codex|claude|opencode|qwen|codium [path]. "
        "Restart Claude Desktop and ChatGPT to pick up the MCP server.[/]"
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
    resolved = resolve_client_models(snap.views, snap.potential_free_gb, snap.settings.max_context)
    _chat_alias, chat_tag = resolved["chatgpt"]
    code_alias, _code_tag = resolved["codex"]
    fallback_tag = snap.chat_selection.tag if snap.chat_selection else "qwen3.5:4b"
    lines = [
        f'export OLLAMA_HOST="{settings.ollama_host}"',
        f'export SOVEREIGN_OLLAMA_HOST="{settings.ollama_host}"',
        f'export SOVEREIGN_MODEL="{chat_tag or fallback_tag}"',
        # OpenAI-compatible — tier gateway chooses fast/balanced/deep per request
        f'export SOVEREIGN_ROUTER_URL="{settings.router_url}"',
        f'export OPENAI_BASE_URL="{settings.router_url}/v1"',
        'export OPENAI_API_KEY="local"',
        'export OPENAI_MODEL="best"',
        f'export SOVEREIGN_CODE_MODEL="{code_alias}"',  # explicit strong alias
        # Anthropic-compatible — Claude Code through the sovereign bridge
        'export ANTHROPIC_BASE_URL="http://127.0.0.1:4001"',
        'export ANTHROPIC_AUTH_TOKEN="local"',
        'export ANTHROPIC_API_KEY="local"',
        'export ANTHROPIC_MODEL="local-claude"',
        'export ANTHROPIC_SMALL_FAST_MODEL="local-claude"',
        'export ANTHROPIC_DEFAULT_SONNET_MODEL="local-claude"',
        'export ANTHROPIC_DEFAULT_OPUS_MODEL="local-claude"',
        'export ANTHROPIC_DEFAULT_HAIKU_MODEL="local-claude"',
        'export CLAUDE_CODE_MAX_CONTEXT_TOKENS="65536"',
        'export CLAUDE_CODE_MAX_OUTPUT_TOKENS="8192"',
        'export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1"',
        'export CLAUDE_CODE_DISABLE_BACKGROUND_TASKS="1"',
        'export DISABLE_AUTO_COMPACT="1"',
        'export DISABLE_TELEMETRY="1"',
    ]
    print("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sovereign",
        description="Terminal-first local AI coding console.",
    )
    parser.add_argument("--version", action="version", version=f"sovereign {__version__}")
    sub = parser.add_subparsers(dest="command")

    dashboard = sub.add_parser(
        "dashboard",
        help="open the live read-only monitor (default): banks, projects, system",
    )
    dashboard.add_argument("--json", action="store_true", help="print one report as JSON")
    dashboard.add_argument("--demo", action="store_true", help="render the demo report")
    monitor = sub.add_parser(
        "monitor",
        help="alias for dashboard: skill/prompt banks, live projects, system activity",
    )
    monitor.add_argument("--json", action="store_true", help="print one report as JSON")
    monitor.add_argument("--demo", action="store_true", help="render the demo report")
    status = sub.add_parser("status", help="one-shot system status")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    models = sub.add_parser("models", help="list installed and recommended models")
    models.add_argument("--remote", action="store_true", help="list downloadable models")
    models.add_argument("query", nargs="?", default=None, help="filter by name")
    cloud = sub.add_parser(
        "cloud", help="use Ollama Cloud models (Kimi K3, DeepSeek V4, GLM 5.3, Qwen 3.8)"
    )
    cloud.add_argument("--enable", action="store_true", help="enable Ollama Cloud and restart it")
    cloud.add_argument("--disable", action="store_true", help="disable Ollama Cloud (local-only)")
    cloud.add_argument(
        "--install-aliases",
        action="store_true",
        help="write cloud-* aliases into the LiteLLM gateway config",
    )
    cloud.add_argument(
        "--pull",
        action="store_true",
        help="register every cloud model with Ollama (no weights downloaded)",
    )
    cloud.add_argument("--probe", action="store_true", help="check login/readiness with one model")
    cloud.add_argument(
        "--install-opencode",
        action="store_true",
        help="add the OpenRouter provider and remote models to OpenCode (opt-in)",
    )
    cloud.add_argument("--timeout", type=float, default=12.0, help="probe timeout in seconds")
    cloud.add_argument(
        "--set-key",
        choices=sorted(PROVIDERS),
        default=None,
        metavar="PROVIDER",
        help="store an OpenRouter/DeepSeek/Z.ai/Moonshot/Alibaba key in cloud.env",
    )
    cloud.add_argument(
        "--key",
        default=None,
        help="API key value (omit it to be prompted without shell history)",
    )
    cloud.add_argument(
        "--route",
        choices=("auto", "ollama", *PROVIDERS),
        default="auto",
        help="route written by --install-aliases (default: first configured key, else Ollama)",
    )
    tune = sub.add_parser("tune", help="apply/verify Ollama context, flash attention and q8 KV")
    tune.add_argument("--context", type=int, default=DEFAULT_CONTEXT)
    tune.add_argument("--dry-run", action="store_true", help="show changes without applying")
    doctor = sub.add_parser("doctor", help="check the local stack and print fixes")
    doctor.add_argument("--fix", action="store_true", help="apply the safe fixes automatically")
    verify = sub.add_parser("verify", help="send a test completion through the gateway aliases")
    verify.add_argument("--all", action="store_true", help="test all nine aliases")
    verify.add_argument("--embedding", action="store_true", help="also check the embedding model")
    verify.add_argument("--timeout", type=float, default=120.0, help="per-alias timeout in seconds")
    gateway = sub.add_parser("gateway", help="show gateway status, paths, and restart command")
    gateway.add_argument(
        "--restart", action="store_true", help="restart the supervisor and wait for health"
    )
    bridge = sub.add_parser(
        "bridge", help="Anthropic Messages bridge so Claude Code can execute local tools"
    )
    bridge.add_argument("--host", default="127.0.0.1")
    bridge.add_argument("--port", type=int, default=4001)
    bridge.add_argument("--gateway", default="http://127.0.0.1:4010")
    bridge.add_argument("--model", default="local-agent", help="default gateway alias")
    bridge.add_argument("--start", action="store_true", help="start in the background")
    bridge.add_argument("--stop", action="store_true", help="stop the background bridge")
    bridge.add_argument("--status", action="store_true", help="show whether it is running")
    router = sub.add_parser(
        "router",
        help="latency-aware tier gateway: fast model for small tasks, big model for hard ones",
    )
    router.add_argument("--host", default="127.0.0.1")
    router.add_argument("--port", type=int, default=4010)
    router.add_argument("--ollama", default="http://127.0.0.1:11434")
    router.add_argument("--upstream", default="http://127.0.0.1:4000")
    router.add_argument("--start", action="store_true", help="start in the background")
    router.add_argument("--restart", action="store_true", help="restart the background gateway")
    router.add_argument("--stop", action="store_true", help="stop the background gateway")
    router.add_argument("--status", action="store_true", help="show tiers and whether it is up")
    router.add_argument("--stats", action="store_true", help="show recent latency by tier")
    local = sub.add_parser("local", help="audit every local agent path")
    local.add_argument("--fix", action="store_true", help="rewrite local settings/MCP")
    local.add_argument("--strict", action="store_true", help="exit non-zero if not local")
    local.add_argument("--json", action="store_true", help="machine-readable output")
    claude = sub.add_parser("claude", help="check/restart local Claude Code settings")
    claude.add_argument("--restart", action="store_true", help="restart the Claude app")
    claude.add_argument("--fix", action="store_true", help="rewrite local Claude settings/MCP")
    claude.add_argument(
        "--local",
        action="store_true",
        help="point Claude Code/Cowork at the local bridge and restart",
    )
    claude.add_argument(
        "--cloud", action="store_true", help="restore the saved cloud settings and restart"
    )
    chatgpt = sub.add_parser("chatgpt", help="check/restart the ChatGPT desktop app")
    chatgpt.add_argument("--restart", action="store_true", help="restart the ChatGPT app")
    chatgpt.add_argument("--fix", action="store_true", help="rewrite the MCP manifests")
    chatgpt.add_argument(
        "--local",
        action="store_true",
        help="force the app onto the local tier gateway (no sign-in) and restart",
    )
    chatgpt.add_argument(
        "--cloud", action="store_true", help="restore the cloud config and restart"
    )
    chatgpt.add_argument(
        "--verify",
        action="store_true",
        help="prove the app runs locally and needs no OpenAI sign-in",
    )
    chatgpt.add_argument(
        "--repair",
        action="store_true",
        help="rewrite the local app config if it drifted back to the cloud",
    )
    sub.add_parser(
        "mcp",
        help="serve MCP over stdio (models, skills, memory, checks) for desktop clients",
    )
    sub.add_parser("env", help="print shell exports for local OpenAI-compatible clients")
    sub.add_parser("clients", help="show local coding clients and their capabilities")
    sub.add_parser("backends", help="show which local inference servers are reachable")
    sub.add_parser("install-clients", help="write the local Codex profile and client wrappers")
    sub.add_parser("free", help="unload all resident models")
    sub.add_parser("best", help="show the strongest model each connected tool uses")
    dog = sub.add_parser("watchdog", help="recover a wedged Ollama without killing a busy one")
    dog.add_argument("--no-restart", action="store_true", help="report only")
    dog.add_argument("--interval", type=float, default=8.0, help="seconds between samples")
    guard = sub.add_parser("guardian", help="check/restore the gateway and bridge (no 24/7 loop)")
    guard.add_argument("--status", action="store_true", help="report only, start nothing")
    guard.add_argument("--watch", action="store_true", help="keep checking until interrupted")
    guard.add_argument("--interval", type=float, default=30.0, help="seconds between checks")
    guard.add_argument("--json", action="store_true", help="print machine readable output")
    auto = sub.add_parser(
        "autostart",
        help="start the gateway tier and bridge at login and survive a reboot",
    )
    auto.add_argument("--install", action="store_true", help="install and load the services")
    auto.add_argument("--uninstall", action="store_true", help="remove the services")
    auto.add_argument("--repair", action="store_true", help="rewrite the plists and reload")
    auto.add_argument("--restart", action="store_true", help="restart every service")
    auto.add_argument("--json", action="store_true", help="print machine readable output")
    prune = sub.add_parser("prune", help="list installed models nothing references")
    prune.add_argument("--apply", action="store_true", help="remove them (default: dry run)")
    warm = sub.add_parser("warm", help="preload a model so the first prompt is fast")
    warm.add_argument("--model", default=None, help="tag to warm (default: best for --task)")
    warm.add_argument("--task", default="code", choices=("code", "chat", "agent"))

    browse = sub.add_parser("browse", help="drive a visible browser with the local model")
    browse.add_argument("url", nargs="?", default=None, help="starting URL")
    browse.add_argument("--task", default=None, help="what to do on the page")
    browse.add_argument("--model", default="local-agent", help="gateway alias for planning")
    browse.add_argument("--max-steps", type=int, default=15)
    browse.add_argument("--headless", action="store_true", help="run without a visible window")
    browse.add_argument("--allow-local", action="store_true", help="allow localhost/private IPs")
    browse.add_argument(
        "--allow-domain", action="append", default=[], help="restrict navigation to a domain"
    )
    browse.add_argument("--yes", action="store_true", help="skip destructive-action confirmations")
    browse.add_argument("--dry-run", action="store_true", help="show the first planned action only")
    browse.add_argument(
        "--screenshots", action="store_true", help="save a PNG at each terminal state"
    )

    bench = sub.add_parser("bench", help="measure generation speed for chosen aliases")
    bench.add_argument("--models", default=None, help="comma-separated aliases")
    bench.add_argument("--tokens", type=int, default=64, help="output tokens per alias")
    bench.add_argument("--prompt", default=None, help="prompt to benchmark")

    backup = sub.add_parser("backup", help="archive configs and chat data to a local tarball")
    backup.add_argument("--keep", type=int, default=None, help="retain only the newest N backups")

    index = sub.add_parser("index", help="embed a directory for local semantic search")
    index.add_argument("path", nargs="?", default=".")
    index.add_argument("--model", default=DEFAULT_EMBED)
    index.add_argument("--limit", type=int, default=None, help="max files to index")

    search = sub.add_parser("search", help="semantic search over an indexed directory")
    search.add_argument("query")
    search.add_argument("--path", default=".")
    search.add_argument("--model", default=DEFAULT_EMBED)
    search.add_argument("--top", type=int, default=5)

    summary = sub.add_parser("summarize", help="summarize a local file or URL")
    summary.add_argument("path", nargs="?", default=None)
    summary.add_argument("--url", default=None)
    summary.add_argument("--model", default="local-chat")
    summary.add_argument("--max-chars", type=int, default=24000)
    summary.add_argument("--max-tokens", type=int, default=512)

    logs = sub.add_parser("logs", help="show the last lines of a local log")
    logs.add_argument("target", nargs="?", default="gateway", choices=TARGETS)
    logs.add_argument("-n", "--lines", type=int, default=40)
    logs.add_argument("-f", "--follow", action="store_true", help="keep following (Ctrl+C to stop)")

    sessions = sub.add_parser("sessions", help="list or prune stored chat sessions")
    sessions.add_argument("--prune", action="store_true", help="delete old sessions")
    sessions.add_argument("--days", type=float, default=30.0, help="retention in days (default 30)")
    sessions.add_argument("--keep", type=int, default=50, help="always keep the newest N")
    sessions.add_argument("--dry-run", action="store_true", help="show what --prune would delete")
    sessions.add_argument("--limit", type=int, default=20, help="rows to list")
    sessions.add_argument("--search", default=None, metavar="TEXT", help="search chat history")
    sessions.add_argument(
        "--export", default=None, metavar="PATH", help="export all sessions to JSONL"
    )

    undo = sub.add_parser("undo", help="restore the files changed by the last pipeline/code pass")
    undo.add_argument("--path", default=None, help="project root (default: current directory)")

    pipeline = sub.add_parser("pipeline", help="plan -> implement -> review across models")
    pipeline.add_argument("prompt")
    pipeline.add_argument("--dir", default=".")
    pipeline.add_argument("--plan-model", default="local-glm", help="strongest reasoner")
    pipeline.add_argument("--agent", default="qwen3-coder:30b", help="strongest coder")
    pipeline.add_argument(
        "--review-model", default="local-review", help="independent reviewer (different family)"
    )
    pipeline.add_argument("--yes", action="store_true", help="yolo-approve agent tool calls")
    pipeline.add_argument("--no-review", action="store_true")
    pipeline.add_argument("--tokens", type=int, default=700)
    pipeline.add_argument(
        "--checks",
        default=None,
        help="semicolon-separated check commands (default: auto-detect from the project)",
    )
    pipeline.add_argument("--no-verify", action="store_true", help="skip project checks")
    pipeline.add_argument(
        "--fix", dest="max_fixes", type=int, default=1, help="repair rounds after a failed check"
    )
    pipeline.add_argument("--timeout", type=float, default=900.0, help="per-check timeout")
    pipeline.add_argument(
        "--dry-run", action="store_true", help="show the resolved models and checks only"
    )
    pipeline.add_argument(
        "--mode",
        choices=("auto", "direct", "agent"),
        default="auto",
        help="direct = one request writes whole files; agent = CLI loop; auto = direct then agent",
    )
    pipeline.add_argument(
        "--direct-tokens", type=int, default=4000, help="output budget for direct mode"
    )
    pipeline.add_argument(
        "--review-tokens",
        type=int,
        default=1600,
        help="budget for the reviewer (reasoning models need headroom)",
    )
    pipeline.add_argument(
        "--agent-client",
        default="qwen",
        choices=sorted(AGENT_CLIENTS),
        help="which local coding client writes the code",
    )
    pipeline.add_argument(
        "--agent-timeout",
        type=float,
        default=900.0,
        help="timeout for one agent run, in seconds",
    )

    config = sub.add_parser("config", help="view or edit sovereign config")
    config.add_argument("--set", dest="set_value", default=None, metavar="KEY=VALUE")
    config.add_argument("--get", dest="get_key", default=None, metavar="KEY")

    sub.add_parser("stats", help="show disk usage across the local AI stack")

    pull = sub.add_parser("pull", help="pull one or more Ollama models by tag")
    pull.add_argument("model", nargs="+", help="one or more Ollama model tags")

    pull_stack = sub.add_parser(
        "pull-stack", help="pull every model in an offline stack (lean/balanced/capable/max)"
    )
    pull_stack.add_argument("name", choices=sorted(MODEL_STACKS))
    pull_stack.add_argument("--yes", action="store_true", help="skip confirmation prompt")

    setup_stack = sub.add_parser(
        "setup-stack", help="pull a stack then verify gateway aliases route to installed models"
    )
    setup_stack.add_argument("name", choices=sorted(MODEL_STACKS))
    setup_stack.add_argument("--yes", action="store_true", help="skip confirmation prompt")

    setup = sub.add_parser(
        "setup", help="one-command self-contained setup of the whole local stack"
    )
    setup.add_argument(
        "--models", default="recommended", help="model set: recommended, a stack name, or none"
    )
    setup.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    setup.add_argument("--no-clients", action="store_true", help="skip client integration")
    setup.add_argument("--no-services", action="store_true", help="skip launchd services")
    setup.add_argument("--no-login", action="store_true", help="skip login agent")
    setup.add_argument("--no-migrate", action="store_true", help="skip legacy migration")
    setup.add_argument("--dry-run", action="store_true", help="show what would happen")
    setup.add_argument("--open", action="store_true", help="open the live monitor when ready")
    sub.add_parser(
        "harness", help="show which model serves which job, plus live downloads and runs"
    )
    orchestrate = sub.add_parser(
        "orchestrate", help="hand a coding task to a small fixer and larger workers"
    )
    orchestrate.add_argument("prompt")
    orchestrate.add_argument("--dir", default=".")
    orchestrate.add_argument("--plan-model", default=None, help="override the planner")
    orchestrate.add_argument("--agent", default=None, help="override the implementer")
    orchestrate.add_argument("--review-model", default=None, help="override the reviewer")
    orchestrate.add_argument("--fix-model", default=None, help="override the small repair model")
    orchestrate.add_argument("--yes", action="store_true", help="yolo-approve agent tool calls")
    orchestrate.add_argument("--no-review", action="store_true")
    orchestrate.add_argument("--tokens", type=int, default=700)
    orchestrate.add_argument(
        "--checks",
        default=None,
        help="semicolon-separated check commands (default: auto-detect from the project)",
    )
    orchestrate.add_argument("--no-verify", action="store_true", help="skip project checks")
    orchestrate.add_argument(
        "--max-fixes", type=int, default=1, help="repair rounds after a failed check"
    )
    orchestrate.add_argument("--timeout", type=float, default=900.0, help="per-check timeout")
    orchestrate.add_argument(
        "--dry-run", action="store_true", help="show the resolved models and checks only"
    )
    orchestrate.add_argument(
        "--mode",
        choices=("auto", "direct", "agent"),
        default="auto",
        help="direct = one request writes whole files; agent = CLI loop; auto = direct then agent",
    )
    orchestrate.add_argument(
        "--direct-tokens", type=int, default=4000, help="output budget for direct mode"
    )
    orchestrate.add_argument(
        "--review-tokens", type=int, default=1600, help="budget for the reviewer"
    )
    orchestrate.add_argument(
        "--agent-client",
        default="qwen",
        choices=sorted(AGENT_CLIENTS),
        help="which local coding client writes the code",
    )
    orchestrate.add_argument(
        "--agent-timeout", type=float, default=900.0, help="timeout for one agent run"
    )
    sub.add_parser("gateway-aliases", help="show which gateway aliases route to installed models")

    rm = sub.add_parser("rm", help="remove an installed model")
    rm.add_argument("model")

    run = sub.add_parser("run", help="download (if needed) and run any model on a prompt")
    run.add_argument("model")
    run.add_argument("prompt", nargs="?", default=None)
    run.add_argument("--context", type=int, default=16384)
    run.add_argument("--temperature", type=float, default=0.25)
    run.add_argument("--system", default=None)
    run.add_argument("--no-pull", action="store_true", help="fail instead of auto-pulling")
    run.add_argument("--keep-alive", default="15m", help="how long Ollama keeps the model resident")
    run.add_argument(
        "--think",
        action="store_true",
        default=None,
        help="force thinking mode on (use with --no-think to force off)",
    )
    run.add_argument(
        "--no-think",
        action="store_false",
        dest="think",
        default=None,
        help="force thinking mode off",
    )

    model_info = sub.add_parser("model-info", help="inspect a model before pulling it")
    model_info.add_argument("model")

    consult = sub.add_parser("consult", help="run one prompt through several models")
    consult.add_argument("prompt")
    consult.add_argument("--models", default=None, help="comma-separated aliases")
    consult.add_argument("--tokens", type=int, default=400)
    consult.add_argument(
        "--domain",
        default=None,
        help="force a specialist domain (default: detect it from the prompt)",
    )

    domains = sub.add_parser("domains", help="list the specialist domains and their aliases")
    domains.add_argument(
        "--detect",
        default=None,
        metavar="PROMPT",
        help="show which domain a prompt would be routed to",
    )

    pack = sub.add_parser("pack", help="task packs: skills, guardrails, model sources, playbook")
    pack.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=("list", "show", "models", "brief"),
        help="default: list",
    )
    pack.add_argument("key", nargs="?", default=None, help="pack key (pentest, vulnerability, …)")
    pack.add_argument(
        "--path",
        default="AGENTS.md",
        metavar="FILE",
        help="brief: write the managed block into this project file (default: AGENTS.md)",
    )
    pack.add_argument(
        "--limit",
        type=int,
        default=5,
        help="models: HF candidate hits per query (max 20)",
    )

    hf = sub.add_parser("hf", help="Hugging Face Hub: login, search, inspect, download, import")
    hf.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=(
            "status",
            "login",
            "logout",
            "search",
            "info",
            "download",
            "list",
            "import",
            "remove",
        ),
        help="default: status",
    )
    hf.add_argument("target", nargs="?", default=None, help="search query or repository id")
    hf.add_argument(
        "--token-stdin",
        action="store_true",
        help="read the token from stdin instead of a hidden prompt",
    )
    hf.add_argument("--browser", action="store_true", help="use `hf auth login` browser flow")
    hf.add_argument("--no-verify", action="store_true", help="skip the whoami token check")
    hf.add_argument(
        "--dataset",
        action="store_true",
        help="operate on a dataset repository instead of a model",
    )
    hf.add_argument("--gguf", action="store_true", help="only show GGUF repositories")
    hf.add_argument("--author", default=None, help="filter by organization or user")
    hf.add_argument(
        "--filter",
        action="append",
        default=[],
        help="extra Hub tag filter, repeatable (e.g. license:mit)",
    )
    hf.add_argument("--license", default=None, help="license filter (e.g. mit, apache-2.0)")
    hf.add_argument("--language", default=None, help="language filter (e.g. en, fr)")
    hf.add_argument("--format", default=None, help="format filter (e.g. parquet, gguf)")
    hf.add_argument("--pipeline", default=None, help="model pipeline tag (e.g. text-generation)")
    hf.add_argument(
        "--sort",
        default="downloads",
        choices=("downloads", "likes", "last_modified", "created_at", "trending_score"),
    )
    hf.add_argument("--limit", type=int, default=20, help="search results (max 100)")
    hf.add_argument("--include", action="append", default=[], help="file glob to download")
    hf.add_argument("--exclude", action="append", default=[], help="file glob to skip")
    hf.add_argument(
        "--all",
        dest="download_all",
        action="store_true",
        help="download every file in the repository",
    )
    hf.add_argument("--revision", default=None, help="branch, tag, or commit")
    hf.add_argument("--local-dir", default=None, help="destination (default: local-ai/models)")
    hf.add_argument("--cache-dir", default=None, help="override the Hub cache")
    hf.add_argument("--max-workers", type=int, default=None, help="parallel download workers")
    hf.add_argument("--dry-run", action="store_true", help="show the download command only")
    hf.add_argument("--files", action="store_true", help="info: list every file")
    hf.add_argument("--readme", action="store_true", help="info: show the repository README")
    hf.add_argument("--name", default=None, help="import: Ollama model name")
    hf.add_argument("--context", type=int, default=None, help="import: num_ctx override")
    hf.add_argument("--yes", action="store_true", help="skip confirmations")
    hf.add_argument("--json", action="store_true")

    skills = sub.add_parser("skills", help="list or install the curated skill library")
    skills.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=("list", "install", "search"),
        help="default: list",
    )
    skills.add_argument("query", nargs="?", default=None, help="words to search for")
    skills.add_argument(
        "--target",
        default="all",
        help="all, or claude,codex,qwen,opencode,continue",
    )
    skills.add_argument("--project", default=None, help="also install project-level skills here")
    skills.add_argument(
        "--all", dest="include_all", action="store_true", help="install the entire library"
    )
    skills.add_argument("--name", action="append", default=[], help="install only these names")
    skills.add_argument("--dry-run", action="store_true")
    skills.add_argument("--limit", type=int, default=30)

    skill = sub.add_parser("skill", help="show or run a saved skill prompt")
    skill.add_argument("name", nargs="?", default=None)
    skill.add_argument("--prompt", default=None)
    skill.add_argument("--model", default="local-chat")
    skill.add_argument("--tokens", type=int, default=800)

    memory = sub.add_parser("memory", help="per-project memory injected into chat")
    memory.add_argument("action", nargs="?", choices=("show", "add", "clear"), default="show")
    memory.add_argument("text", nargs="?", default=None)
    memory.add_argument("--project", default=None)

    clone = sub.add_parser("clone", help="clone a GitHub repo into ~/Documents/projects")
    clone.add_argument("url")
    clone.add_argument("--name", default=None)

    launch = sub.add_parser("launch", help="launch a local coding client in a project")
    launch.add_argument("client", choices=("qwen", "codex", "claude", "opencode", "codium"))
    launch.add_argument("path", nargs="?", default=".")
    launch.add_argument("--yolo", action="store_true", help="auto-approve Qwen Code tool calls")
    launch.add_argument(
        "--model",
        default=None,
        help="Ollama tag or gateway alias (default: the router's best agent model)",
    )
    launch.add_argument(
        "--dry-run",
        action="store_true",
        help="show the model, eviction and command without launching",
    )
    launch.add_argument(
        "--cloud",
        action="store_true",
        help="codex or claude: use the real subscription (prompts leave this Mac)",
    )
    sub.add_parser("pull-recommended", help="pull qwen2.5-coder:14b")
    sub.add_parser("init", help="create config/data directories and default config")

    localbar = sub.add_parser("local-bar", help="macOS menu bar controller for the local stack")
    localbar.add_argument("--install", action="store_true", help="compile/install the app")
    localbar.add_argument("--open", action="store_true", help="open the menu bar app")
    localbar.add_argument("--status", action="store_true", help="show whether it is running")
    chat_web = sub.add_parser("chat-web", help="fully local ChatGPT-style web client (127.0.0.1)")
    chat_web.add_argument("--port", type=int, default=4020)
    chat_web.add_argument("--start", action="store_true", help="start in the background")
    chat_web.add_argument("--stop", action="store_true", help="stop the background server")
    chat_web.add_argument("--status", action="store_true", help="show the URL/status")
    chat_web.add_argument("--open", action="store_true", help="open in the browser")
    chat_web.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    chat_web.add_argument(
        "--install-app", action="store_true", help="create ~/Applications/ChatGPT Local.app"
    )
    chat = sub.add_parser("chat", help="open the interactive chat dashboard (opt-in)")
    chat.add_argument("--model", default=None)

    code = sub.add_parser("code", help="launch Qwen Code in a project with the best local model")
    code.add_argument("path", nargs="?", default=".")
    code.add_argument("--yolo", action="store_true", help="auto-approve tool calls (use with care)")
    code.add_argument("-p", "--prompt", default=None, help="run one prompt headlessly, then exit")

    login = sub.add_parser("install-login", help="open the dashboard in Terminal at login")
    login.add_argument("--start-now", action="store_true")
    sub.add_parser("uninstall-login", help="remove the login terminal agent")

    # --- agents -----------------------------------------------------------
    agents = sub.add_parser("agents", help="detect coding agents and list gateway targets")
    agents.add_argument("--json", action="store_true", help="machine-readable JSON output")
    agents.add_argument("--tsv", action="store_true", help="tab-separated output for shell scripts")

    # --- prompts ----------------------------------------------------------
    prompts = sub.add_parser("prompts", help="prompt database: versioned, categorized, searchable")
    prompts.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=("list", "add", "get", "render", "delete", "search", "count", "touch"),
    )
    prompts.add_argument("name", nargs="?", default=None, help="prompt name")
    prompts.add_argument("--content", default=None, help="prompt content (for add)")
    prompts.add_argument("--category", default=None, help="category filter (default: no filter)")
    prompts.add_argument("--tags", default="", help="comma-separated tags")
    prompts.add_argument(
        "--version", type=int, default=None, help="specific version (get/delete/render)"
    )
    prompts.add_argument("--search", default=None, help="full-text search query (list/search)")
    prompts.add_argument("--replace", action="store_true", help="replace existing prompt (add)")
    prompts.add_argument("--var", action="append", default=[], help="VAR=value for render")
    prompts.add_argument("--limit", type=int, default=100, help="max rows to list")

    # --- skill-db ---------------------------------------------------------
    skilldb = sub.add_parser(
        "skill-db", help="skill database: index, search, rate, install/uninstall"
    )
    skilldb.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=(
            "list",
            "add",
            "get",
            "delete",
            "search",
            "count",
            "sync",
            "rate",
            "touch",
            "export",
            "import",
        ),
    )
    skilldb.add_argument("name", nargs="?", default=None, help="skill name")
    skilldb.add_argument("--content", default=None, help="skill content (for add)")
    skilldb.add_argument("--category", default=None, help="category filter (default: no filter)")
    skilldb.add_argument("--tags", default="", help="comma-separated tags")
    skilldb.add_argument("--description", default="", help="one-line description")
    skilldb.add_argument("--rating", type=float, default=0.0, help="rating 0-5")
    skilldb.add_argument("--search", default=None, help="full-text search query (list/search)")
    skilldb.add_argument("--installed-only", action="store_true", help="only show installed skills")
    skilldb.add_argument("--limit", type=int, default=200, help="max rows to list")

    # --- gateway-config ---------------------------------------------------
    gwcfg = sub.add_parser(
        "gateway-config", help="generate the LiteLLM model_list.yaml for all code agents"
    )
    gwcfg.add_argument("--write", action="store_true", help="write model_list.yaml to disk")
    gwcfg.add_argument(
        "--path",
        default=None,
        help="output path (default: ~/Documents/local-ai/gateway/model_list.yaml)",
    )
    gwcfg.add_argument(
        "--show", action="store_true", help="print the YAML to stdout instead of writing"
    )

    # --- connect ----------------------------------------------------------
    connect = sub.add_parser("connect", help="run the one-command agent connect (like curl | sh)")
    connect.add_argument(
        "--script",
        default=None,
        help="path to agent-connect.sh (default: scripts/agent-connect.sh)",
    )

    # --- cache ------------------------------------------------------------
    cache = sub.add_parser("cache", help="response cache: stats, clear, warm")
    cache.add_argument("action", nargs="?", default="stats", choices=("stats", "clear"))
    cache.add_argument(
        "--older-than", type=float, default=None, help="clear entries older than seconds"
    )

    # --- warm pool --------------------------------------------------------
    warm_pool = sub.add_parser(
        "warm-pool", help="model warm pool: status, load, touch, start, stop"
    )
    warm_pool.add_argument(
        "action", nargs="?", default="status", choices=("status", "load", "touch", "start", "stop")
    )
    warm_pool.add_argument("model", nargs="?", default=None, help="model tag to load/touch")

    # --- knowledge --------------------------------------------------------
    knowledge = sub.add_parser("knowledge", help=".md knowledge base: index, search, roots")
    knowledge.add_argument(
        "action", nargs="?", default="roots", choices=("roots", "index", "search")
    )
    knowledge.add_argument(
        "query", nargs="?", default=None, help="search words (for search) or root path (for index)"
    )
    knowledge.add_argument("--root", default=None, help="directory to index (for index)")
    knowledge.add_argument("--model", default="nomic-embed-text", help="embedding model")
    knowledge.add_argument("--top", type=int, default=10, help="top results (for search)")

    return parser


# --------------------------------------------------------------------- agents


def _agents(as_json: bool, as_tsv: bool) -> int:
    reports = detect_all()
    if as_json:
        import json as _json

        print(_json.dumps([r.to_dict() for r in reports], indent=2))
        return 0
    if as_tsv:
        for r in reports:
            print(
                f"{r.key}\t{r.name}\t{'true' if r.installed else 'false'}\t"
                f"{r.command or ''}\t{r.config_dir or ''}\t{r.app_bundle or ''}"
            )
        return 0
    console.print(agent_summary())
    installed = installed_agents()
    if installed:
        console.print("\n[bold]Gateway targets (sovereign local-first):[/]")
        targets = gateway_targets()
        table = Table(box=None, padding=(0, 1))
        table.add_column("Agent", style="bold")
        table.add_column("Points at")
        for r in installed:
            table.add_row(r.name, targets.get(r.key, "http://127.0.0.1:4010/v1"))
        console.print(table)
    else:
        console.print(
            "[dim]None found. Install one, then re-run `sovereign agents`, or run "
            "`sovereign connect` to set everything up.[/]"
        )
    return 0


# --------------------------------------------------------------------- prompts


def _prompts(args) -> int:
    db = PromptDB()
    try:
        action = args.action or "list"
        if action == "list":
            rows = db.list_all(
                category=args.category,
                tag=None,
                search=args.search,
                limit=args.limit,
            )
            if not rows:
                console.print("[dim]No prompts yet. Add one with:[/]")
                console.print(
                    "  sovereign prompts add <name> --content '…' --category code --tags coding,review"
                )
                return 0
            table = Table(title="Prompts", header_style="bold #b794f4")
            table.add_column("Name", style="bold")
            table.add_column("Category")
            table.add_column("Tags")
            table.add_column("Version", justify="right")
            table.add_column("Uses", justify="right")
            table.add_column("Updated", overflow="fold")
            for p in rows:
                updated = (p.updated_at or "")[:16].replace("T", " ")
                table.add_row(
                    p.name,
                    p.category,
                    ", ".join(p.tags),
                    str(p.version),
                    str(p.usage_count),
                    updated,
                )
            console.print(table)
            console.print(f"[dim]{db.count()} prompt(s)[/]")
            return 0

        if action == "add":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign prompts add <name> --content '…'")
                return 1
            if not args.content:
                console.print("[red]Give content:[/] --content '…'")
                return 1
            variables = _parse_vars(args.var)
            if variables:
                console.print("[dim]Note: {{variables}} are applied at render time, not stored.[/]")
            try:
                p = db.add(
                    args.name,
                    args.content,
                    category=args.category or "general",
                    tags=args.tags,
                    replace=args.replace,
                )
            except ValueError as exc:
                console.print(f"[red]{exc}[/]")
                console.print("[dim]Use --replace to overwrite, or pick a different name.[/]")
                return 1
            console.print(
                f"[green]Added[/] {p.name} (v{p.version}) · vars: {', '.join(p.variables) or 'none'}"
            )
            return 0

        if action == "get":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign prompts get <name>")
                return 1
            p = cast(
                Any,
                (
                    db.get_version(args.name, args.version)
                    if args.version is not None
                    else db.get(args.name)
                ),
            )
            if p is None:
                console.print(f"[red]No such prompt:[/] {args.name}")
                return 1
            console.print(
                Panel(Text(p.content), title=f"prompt · {p.name} v{p.version}", border_style="cyan")
            )
            console.print(
                f"[dim]category={p.category} tags={', '.join(p.tags) or 'none'} vars={', '.join(p.variables) or 'none'}[/]"
            )
            return 0

        if action == "render":
            if not args.name:
                console.print(
                    "[red]Give a name:[/] sovereign prompts render <name> --var VAR=value"
                )
                return 1
            variables = _parse_vars(args.var)
            try:
                text = db.render(args.name, version=args.version, **variables)
            except KeyError as exc:
                console.print(f"[red]{exc}[/]")
                return 1
            console.print(Text(text))
            return 0

        if action == "delete":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign prompts delete <name> [--version N]")
                return 1
            ok = db.delete(args.name, version=args.version)
            if not ok:
                console.print(f"[red]No such prompt:[/] {args.name}")
                return 1
            what = f"v{args.version} of" if args.version is not None else "all versions of"
            console.print(f"[green]Deleted[/] {what} {args.name}")
            return 0

        if action == "search":
            query = args.search or args.name or ""
            if not query:
                console.print("[red]Give a query:[/] sovereign prompts search <words>")
                return 1
            rows = db.list_all(search=query, limit=args.limit)
            if not rows:
                console.print(f"[dim]No prompts match '{query}'.[/]")
                return 0
            table = Table(title=f"Prompt search · {query}", header_style="bold #b794f4")
            table.add_column("Name", style="bold")
            table.add_column("Category")
            table.add_column("Version", justify="right")
            table.add_column("Uses", justify="right")
            for p in rows:
                table.add_row(p.name, p.category, str(p.version), str(p.usage_count))
            console.print(table)
            return 0

        if action == "count":
            console.print(f"{db.count()}")
            return 0

        if action == "touch":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign prompts touch <name>")
                return 1
            row = db._conn.execute(
                "SELECT id FROM prompts WHERE name = ? ORDER BY version DESC LIMIT 1", (args.name,)
            ).fetchone()
            if row is None:
                console.print(f"[red]No such prompt:[/] {args.name}")
                return 1
            db.touch(args.name)
            console.print(f"[green]Touched[/] {args.name}")
            return 0

        console.print(f"[red]Unknown action:[/] {action}")
        return 1
    finally:
        db.close()


# --------------------------------------------------------------------- skill-db


def _skill_db(args) -> int:
    db = SkillDB()
    try:
        action = args.action or "list"
        if action == "list":
            rows = db.list_all(
                category=args.category,
                tag=None,
                search=args.search,
                installed_only=args.installed_only,
                limit=args.limit,
            )
            if not rows:
                console.print("[dim]No skills indexed yet.[/]")
                console.print("[dim]Run: sovereign skill-db sync[/]")
                return 0
            table = Table(title="Skills", header_style="bold #b794f4")
            table.add_column("Name", style="bold")
            table.add_column("Category")
            table.add_column("Tags")
            table.add_column("Rating", justify="right")
            table.add_column("Uses", justify="right")
            table.add_column("Installed", justify="center")
            for s in rows:
                mark = "[green]yes[/]" if s.installed else "[dim]no[/]"
                table.add_row(
                    s.name,
                    s.category,
                    ", ".join(s.tags),
                    f"{s.rating:.1f}",
                    str(s.usage_count),
                    mark,
                )
            console.print(table)
            console.print(f"[dim]{db.count()} skill(s)[/]")
            return 0

        if action == "sync":
            stats = db.sync_repo()
            console.print(
                f"[green]Synced[/] · added {stats['added']} · updated {stats['updated']} · "
                f"unchanged {stats['unchanged']} · disabled {stats['disabled']}"
            )
            return 0

        if action == "add":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign skill-db add <name> --content '…'")
                return 1
            if not args.content:
                console.print("[red]Give content:[/] --content '…'")
                return 1
            try:
                s = db.add(
                    args.name,
                    args.content,
                    category=args.category or "general",
                    tags=args.tags,
                    description=args.description,
                    rating=args.rating,
                )
            except ValueError as exc:
                console.print(f"[red]{exc}[/]")
                console.print("[dim]Use a different name.[/]")
                return 1
            console.print(f"[green]Added[/] {s.name} (category={s.category})")
            return 0

        if action == "get":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign skill-db get <name>")
                return 1
            s = cast(Any, db.get(args.name))
            if s is None:
                console.print(f"[red]No such skill:[/] {args.name}")
                return 1
            console.print(
                Panel(Text(s.content), title=f"skill · {s.name} v{s.version}", border_style="cyan")
            )
            console.print(
                f"[dim]category={s.category} tags={', '.join(s.tags) or 'none'} "
                f"rating={s.rating:.1f} installed={s.installed}[/]"
            )
            return 0

        if action == "delete":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign skill-db delete <name>")
                return 1
            ok = db.delete(args.name)
            if not ok:
                console.print(f"[red]No such skill:[/] {args.name}")
                return 1
            console.print(f"[green]Deleted[/] {args.name}")
            return 0

        if action == "search":
            query = args.search or args.name or ""
            if not query:
                console.print("[red]Give a query:[/] sovereign skill-db search <words>")
                return 1
            rows = db.list_all(search=query, limit=args.limit)
            if not rows:
                console.print(f"[dim]No skills match '{query}'.[/]")
                return 0
            table = Table(title=f"Skill search · {query}", header_style="bold #b794f4")
            table.add_column("Name", style="bold")
            table.add_column("Category")
            table.add_column("Rating", justify="right")
            for s in rows:
                table.add_row(s.name, s.category, f"{s.rating:.1f}")
            console.print(table)
            return 0

        if action == "count":
            console.print(f"{db.count()}")
            return 0

        if action == "rate":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign skill-db rate <name> --rating 0-5")
                return 1
            ok = db.rate(args.name, args.rating)
            if not ok:
                console.print(f"[red]No such skill:[/] {args.name}")
                return 1
            console.print(f"[green]Rated[/] {args.name} → {args.rating}")
            return 0

        if action == "touch":
            if not args.name:
                console.print("[red]Give a name:[/] sovereign skill-db touch <name>")
                return 1
            db.touch(args.name)
            console.print(f"[green]Touched[/] {args.name}")
            return 0

        if action == "export":
            import json as _json

            path = Path(args.name or Path.home() / "skills_export.json")
            path.write_text(_json.dumps(db.export_json(), indent=2) + "\n", encoding="utf-8")
            console.print(f"[green]Exported[/] {db.count()} skill(s) to {path}")
            return 0

        if action == "import":
            import json as _json

            path = Path(args.name)
            if not path.is_file():
                console.print(f"[red]Not a file:[/] {path}")
                return 1
            rows = _json.loads(path.read_text(encoding="utf-8"))
            written = db.import_json(rows)
            console.print(f"[green]Imported[/] {written} skill(s)")
            return 0

        console.print(f"[red]Unknown action:[/] {action}")
        return 1
    finally:
        db.close()


# --------------------------------------------------------------------- gateway-config


def _gateway_config(args) -> int:
    if args.show or args.write is False:
        print(render_gateway_config())
        return 0
    path = Path(args.path) if args.path else gateway_config_path()
    written = write_gateway_config(path=path)
    console.print(f"[green]Wrote[/] {written}")
    console.print(
        "[dim]Restart the LiteLLM gateway so it picks up the new model list: "
        "sovereign gateway --restart[/]"
    )
    return 0


# --------------------------------------------------------------------- connect


def _connect(script: str | None) -> int:
    root = Path(__file__).resolve().parents[2]
    sh = script or str(root / "scripts" / "agent-connect.sh")
    path = Path(sh)
    if not path.is_file():
        console.print(f"[red]Connect script not found:[/] {path}")
        return 1
    path.chmod(0o755)
    console.print(f"[dim]Running {path}[/]")
    try:
        subprocess.run(["bash", str(path)], check=True)
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Connect script exited {exc.returncode}[/]")
        return exc.returncode
    return 0


def _parse_vars(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        out[key.strip()] = value.strip()
    return out


# --------------------------------------------------------------------- cache


def _cache(args) -> int:
    from .tier_gateway import CACHE

    if args.action == "stats":
        mem = CACHE.memory.stats()
        disk = CACHE.disk.stats()
        table = Table(title="Response Cache", header_style="bold #b794f4")
        table.add_column("Layer", style="bold")
        table.add_column("Entries", justify="right")
        table.add_column("Hits", justify="right")
        table.add_column("Misses", justify="right")
        table.add_column("Hit rate", justify="right")
        table.add_row(
            "memory",
            str(mem["entries"]),
            str(mem["hits"]),
            str(mem["misses"]),
            f"{mem['hit_rate']}%",
        )
        table.add_row(
            "disk",
            str(disk["entries"]),
            str(disk.get("disk_hits", 0)),
            str(disk.get("memory_misses", 0)),
            f"{disk.get('hit_rate', 0)}%",
        )
        console.print(table)
        return 0
    if args.action == "clear":
        removed = CACHE.disk.clear(older_than=args.older_than)
        CACHE.memory.clear()
        if args.older_than is not None:
            console.print(
                f"[green]Cleared[/] {removed} cache entr{'y' if removed == 1 else 'ies'} "
                f"older than {args.older_than}s"
            )
        else:
            console.print(f"[green]Cleared[/] {removed} cache entr{'y' if removed == 1 else 'ies'}")
        return 0
    console.print(f"[red]Unknown action:[/] {args.action}")
    return 1


# --------------------------------------------------------------------- warm


def _warm_pool(args) -> int:
    from .warm import pool as warm_pool

    p = warm_pool()
    if args.action == "status":
        console.print(p.summary())
        return 0
    if args.action == "load":
        tags = [args.model] if args.model else None
        results = p.warm(tags)
        for tag, seconds in results.items():
            console.print(f"[green]{tag}[/] loaded in {seconds}s")
        p.save_state()
        return 0
    if args.action == "touch":
        tags = [args.model] if args.model else None
        p.touch(tags)
        console.print("[green]Touched[/]" + (f" {args.model}" if args.model else ""))
        return 0
    if args.action == "start":
        p.start()
        console.print("[green]Warm pool keep-alive started.[/]")
        return 0
    if args.action == "stop":
        p.stop()
        console.print("[green]Warm pool keep-alive stopped.[/]")
        return 0
    console.print(f"[red]Unknown action:[/] {args.action}")
    return 1


# --------------------------------------------------------------------- knowledge


def _knowledge(args) -> int:
    from .knowledge import KnowledgeBase

    kb = KnowledgeBase()
    try:
        if args.action == "roots":
            rows = kb.list_roots()
            if not rows:
                console.print("[dim]No knowledge roots indexed yet.[/]")
                console.print("[dim]Run: sovereign knowledge index /path/to/docs[/]")
                return 0
            table = Table(title="Knowledge Roots", header_style="bold #b794f4")
            table.add_column("Root", style="bold")
            table.add_column("Files", justify="right")
            table.add_column("Chunks", justify="right")
            table.add_column("Indexed", overflow="fold")
            table.add_column("Embed model")
            for row in rows:
                indexed = (row["indexed_at"] or "")[:16].replace("T", " ")
                table.add_row(
                    row["root"],
                    str(row["file_count"]),
                    str(row["chunk_count"]),
                    indexed,
                    row["embed_model"],
                )
            console.print(table)
            return 0
        if args.action == "index":
            root = args.root or args.query
            if not root:
                console.print("[red]Give a directory:[/] sovereign knowledge index /path/to/docs")
                return 1
            stats = kb.index_root(root, embed_model=args.model)
            console.print(
                f"[green]Indexed[/] {root}: {stats['files']} files · {stats['chunks']} chunks"
            )
            return 0
        if args.action == "search":
            query = args.query
            if not query:
                console.print("[red]Give a query:[/] sovereign knowledge search <words>")
                return 1
            hits = kb.search(query, top=args.top)
            if not hits:
                console.print(f"[dim]No matches for '{query}'.[/]")
                return 0
            table = Table(title=f"Knowledge search · {query}", header_style="bold #b794f4")
            table.add_column("Score", justify="right")
            table.add_column("File", style="bold")
            table.add_column("Snippet", overflow="fold")
            for h in hits:
                table.add_row(f"{h.score:.2f}", h.name, h.snippet)
            console.print(table)
            return 0
        console.print(f"[red]Unknown action:[/] {args.action}")
        return 1
    finally:
        kb.close()


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
    if command in {"dashboard", "monitor"}:
        from .monitor import collect_live
        from .tui.monitor import MonitorApp

        if getattr(args, "demo", False):
            MonitorApp(settings=settings, demo=True).run()
            return 0
        if getattr(args, "json", False):
            snapshot = asyncio.run(collect(settings))
            report = collect_live(settings, snapshot)
            print(json.dumps(report.to_dict(), indent=2, default=str))
            return 0
        MonitorApp(settings=settings).run()
        return 0
    if command == "local-bar":
        from . import localbar

        if args.status:
            console.print(
                f"Sovereign Local {'[green]running[/]' if localbar.running() else '[dim]stopped[/]'}"
            )
            return 0 if localbar.running() else 1
        if args.install:
            console.print(f"[green]Installed[/] {localbar.install()}")
        if args.open or not args.install:
            localbar.open_app()
            console.print(f"[green]Sovereign Local[/] {localbar.app_path()}")
        return 0
    if command == "chat-web":
        from . import webchat

        if args.stop:
            return 0 if webchat.stop(args.port) else 1
        if args.status:
            up = webchat.port_open("127.0.0.1", args.port)
            console.print(
                f"ChatGPT Local  {'[green]running[/]' if up else '[dim]stopped[/]'}  "
                f"http://127.0.0.1:{args.port}"
            )
            return 0 if up else 1
        if args.serve:
            webchat.serve(args.port, settings.router_url)
            return 0
        if args.install_app:
            app = webchat.install_app(args.port)
            console.print(f"[green]Installed[/] {app}")
        ok = webchat.ensure_running(args.port, settings.router_url)
        if not ok:
            console.print("[red]ChatGPT Local did not start.[/] See: sovereign logs webchat")
            return 1
        console.print(f"[green]ChatGPT Local[/] http://127.0.0.1:{args.port}")
        if args.open or not args.start:
            webchat.open_browser(args.port)
        return 0
    if command == "chat":
        from .tui.app import SovereignApp

        if getattr(args, "model", None):
            settings.default_model = args.model
        SovereignApp(settings=settings, mode="chat").run()
        return 0
    if command == "status":
        snapshot = _snapshot(settings)
        if args.json:
            return _status_json(snapshot)
        _status(snapshot)
        return 0
    if command == "models":
        snap = _snapshot(settings)
        if args.remote:
            return _models_remote(snap, args.query)
        _models(snap)
        return 0
    if command == "cloud":
        return _cloud(
            settings,
            enable=args.enable,
            disable=args.disable,
            install_aliases=args.install_aliases,
            pull=args.pull,
            probe=args.probe,
            timeout=args.timeout,
            set_key=args.set_key,
            key=args.key,
            prefer=args.route,
            install_opencode=args.install_opencode,
        )
    if command == "tune":
        return _tune(args.context, dry_run=args.dry_run)
    if command == "doctor":
        snap = _snapshot(settings)
        if args.fix:
            return _doctor_fix(settings, snap)
        return _doctor(snap)
    if command == "verify":
        return _verify(
            _snapshot(settings),
            all_aliases=args.all,
            timeout=args.timeout,
            embedding=args.embedding,
        )
    if command == "gateway":
        if args.restart:
            return _gateway_restart(settings)
        return _gateway(_snapshot(settings))
    if command == "bridge":
        return _bridge(
            args.host,
            args.port,
            args.gateway,
            args.model,
            start=args.start,
            stop=args.stop,
            status=args.status,
        )
    if command == "router":
        return _router(
            args.host,
            args.port,
            args.ollama,
            args.upstream,
            start=args.start,
            stop=args.stop,
            status=args.status,
            stats=args.stats,
            restart=args.restart,
        )
    if command == "local":
        return _local(fix=args.fix, strict=args.strict, as_json=args.json)
    if command == "claude":
        return _claude(restart=args.restart, fix=args.fix, local=args.local, cloud=args.cloud)
    if command == "chatgpt":
        if args.verify:
            return _chatgpt_verify()
        return _chatgpt(
            restart=args.restart,
            fix=args.fix,
            local=args.local,
            cloud=args.cloud,
            repair=args.repair,
        )
    if command == "mcp":
        from .mcp import serve

        serve()
        return 0
    if command == "env":
        _env(settings)
        return 0
    if command == "clients":
        _clients(_snapshot(settings))
        return 0
    if command == "backends":
        return _backends(settings)
    if command == "install-clients":
        return _install_clients()
    if command == "launch":
        return _launch(
            args.client,
            args.path,
            yolo=args.yolo,
            dry_run=args.dry_run,
            model=args.model,
            cloud=getattr(args, "cloud", False),
        )
    if command == "best":
        return _best(_snapshot(settings))
    if command == "watchdog":
        return _watchdog(settings, restart=not args.no_restart, interval=args.interval)
    if command == "guardian":
        return _guardian(
            settings,
            status_only=args.status,
            watch=args.watch,
            interval=args.interval,
            as_json=args.json,
        )
    if command == "autostart":
        return _autostart(
            settings,
            install=args.install,
            uninstall=args.uninstall,
            repair=args.repair,
            restart=args.restart,
            as_json=args.json,
        )
    if command == "prune":
        return _prune(_snapshot(settings), apply=args.apply)
    if command == "warm":
        return _warm_model(settings, args.model, args.task)
    if command == "free":
        return _free(settings)
    if command == "logs":
        return _logs(args.target, lines=args.lines, follow=args.follow)
    if command == "browse":
        return _browse(args, settings)
    if command == "bench":
        models = (
            [name.strip() for name in args.models.split(",") if name.strip()]
            if args.models
            else list(DEFAULT_MODELS)
        )
        return _bench(settings, models, args.tokens, args.prompt or DEFAULT_PROMPT)
    if command == "backup":
        return _backup(keep=args.keep)
    if command == "undo":
        return _undo(path=args.path)
    if command == "index":
        return _index(settings, args.path, args.model, args.limit)
    if command == "search":
        return _search(settings, args.query, args.path, args.model, args.top)
    if command == "summarize":
        return _summarize(
            settings,
            args.path,
            args.url,
            args.model,
            args.max_chars,
            args.max_tokens,
        )
    if command == "sessions":
        return _sessions(
            days=args.days,
            keep=args.keep,
            prune=args.prune,
            dry_run=args.dry_run,
            limit=args.limit,
            search=args.search,
            export=args.export,
        )
    if command == "config":
        return _config(settings, get_key=args.get_key, set_value=args.set_value)
    if command == "stats":
        return _stats()
    if command == "pull":
        for tag in args.model:
            if _pull(settings, tag) != 0:
                return 1
        return 0
    if command == "pull-stack":
        return _pull_stack(settings, args.name, yes=args.yes)
    if command == "setup-stack":
        return _setup_stack(settings, args.name, yes=args.yes)
    if command == "setup":
        return _setup(
            settings,
            models=args.models,
            yes=args.yes,
            clients=not args.no_clients,
            services=not args.no_services,
            login=not args.no_login,
            migrate=not args.no_migrate,
            dry_run=args.dry_run,
            open_monitor=args.open,
        )
    if command == "harness":
        return _harness(settings)
    if command == "orchestrate":
        return _orchestrate(settings, args)
    if command == "gateway-aliases":
        return _gateway_aliases(_snapshot(settings))
    if command == "rm":
        return _rm(args.model)
    if command == "run":
        return _run(
            settings,
            args.model,
            args.prompt,
            args.context,
            args.temperature,
            args.system,
            args.no_pull,
            args.keep_alive,
            args.think,
        )
    if command == "model-info":
        return _model_info(settings, args.model)
    if command == "consult":
        models = (
            [name.strip() for name in args.models.split(",") if name.strip()] if args.models else []
        )
        return _consult(settings, args.prompt, models, args.tokens, args.domain)
    if command == "domains":
        return _domains(args.detect)
    if command == "pack":
        return _pack(args)
    if command == "hf":
        return _hf(args)
    if command == "skills":
        return _skills(
            action=args.action,
            target=args.target,
            project=args.project,
            include_all=args.include_all,
            names=args.name,
            dry_run=args.dry_run,
            query=args.query,
            limit=args.limit,
        )
    if command == "skill":
        return _skill(settings, args.name, args.prompt, args.model, args.tokens)
    if command == "memory":
        return _memory(args.action, args.text, args.project)
    if command == "clone":
        return _clone(args.url, args.name)
    if command == "pipeline":
        return _pipeline(
            settings,
            args.prompt,
            args.dir,
            args.plan_model,
            args.agent,
            args.review_model,
            args.yes,
            args.no_review,
            args.tokens,
            checks=args.checks,
            no_verify=args.no_verify,
            max_fixes=args.max_fixes,
            timeout=args.timeout,
            review_tokens=args.review_tokens,
            agent_client=args.agent_client,
            agent_timeout=args.agent_timeout,
            dry_run=args.dry_run,
            mode=args.mode,
            direct_tokens=args.direct_tokens,
        )
    if command == "pull-recommended":
        return _pull_recommended(settings)
    if command == "install-login":
        return _install_login(start_now=args.start_now)
    if command == "uninstall-login":
        return _uninstall_login()
    if command == "code":
        return _code(args.path, yolo=args.yolo, prompt=args.prompt)
    if command == "agents":
        return _agents(args.json, args.tsv)
    if command == "prompts":
        return _prompts(args)
    if command == "skill-db":
        return _skill_db(args)
    if command == "gateway-config":
        return _gateway_config(args)
    if command == "connect":
        return _connect(args.script)
    if command == "cache":
        return _cache(args)
    if command == "warm-pool":
        return _warm_pool(args)
    if command == "knowledge":
        return _knowledge(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
