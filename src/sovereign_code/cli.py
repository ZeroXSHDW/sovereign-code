"""Command-line entry point for Sovereign Code."""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import fields as dc_fields
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from . import __version__
from .backup import create_backup
from .bench import DEFAULT_MODELS, DEFAULT_PROMPT, bench_alias
from .browser.executor import chromium_path
from .clients import (
    codex_profile_path,
    install_client_wrappers,
    local_clients,
    plan_launch,
    resolve_client_models,
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
from .logs import TARGETS, log_path, tail_lines
from .memory import add_memory, clear_memory, project_context, read_memory
from .models import MODEL_STACKS, TASK_PREFERENCE
from .ollama import OllamaClient, OllamaError
from .pipeline import run_pipeline
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
from .skills import list_skills, read_skill, render_skill
from .stats import collect_stats, human_size
from .status import Snapshot, collect
from .summarize import SourceError, complete, read_text_source, summarize_text
from .system import (
    command_exists,
    login_agent_installed,
    models_to_evict,
    ollama_runner_models,
    port_open,
    qwen_memory_path,
    swap_usage_gb,
    wired_limit_gb,
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
    table.add_row("Memory", snap.memory.label)
    table.add_row("GPU budget", f"{wired_limit_gb(snap.memory.total_gb):.1f} GB wired")
    table.add_row("Disk free", f"{snap.disk_free_gb:.0f} GB")
    table.add_row("Loopback", "yes" if snap.loopback else "[red]NO[/]")
    table.add_row("Login terminal", "installed" if snap.login_installed else "not installed")
    table.add_row("Models", f"{len(snap.installed)} installed · {len(snap.loaded)} loaded")
    console.print(table)

    if snap.loaded:
        console.print("\n[bold]Loaded[/]")
        for view in snap.loaded:
            engine = f" · [cyan]{view.runner}[/]" if view.runner else ""
            console.print(
                f"  [green]{view.tag}[/]  ctx {view.context or '?'} · "
                f"{view.size_gb:.1f} GB{engine}"
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


def _models_remote(snap: Snapshot, query: str | None = None) -> int:
    from .models import REMOTE_CATALOG

    installed = {view.tag for view in snap.installed}
    rows = [
        (tag, "[green]installed[/]" if tag in installed else "[dim]pull[/]", desc)
        for tag, (desc, _size_gb) in sorted(REMOTE_CATALOG.items())
        if not query or query.lower() in tag.lower()
    ]
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

    if not asyncio.run(installed()):
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


def _rm(settings: Settings, model: str) -> int:
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


def _gateway_aliases(settings: Settings, snap: Snapshot) -> int:
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
        clean_tag = tag.strip('"\'')
        if clean_tag.startswith("openai/"):
            table.add_row(alias, "OpenAI cloud passthrough", "[dim]passthrough[/]", "-")
            continue
        view = snap.views.get(clean_tag) or (
            snap.views.get(f"{clean_tag}:latest")
            if ":" not in clean_tag
            else snap.views.get(clean_tag.removesuffix(":latest"))
        )
        if view and view.installed:
            inst = "[green]yes[/]"
            size = f"{view.size_gb:.1f} GB"
        else:
            inst = "[yellow]no[/]"
            size = "-"
            missing.append((alias, clean_tag))
        table.add_row(alias, clean_tag, inst, size)
    console.print(table)
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
    models = stack["models"]
    snap = _snapshot(settings)
    installed = {view.tag for view in snap.installed}
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
    return _gateway_aliases(settings, snap)


def _models(snap: Snapshot) -> None:
    table = Table(title="Local models", header_style="bold #b794f4")
    table.add_column("", width=2)
    table.add_column("Model", style="bold")
    table.add_column("Role")
    table.add_column("Size", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("Status")
    table.add_column("Notes", overflow="fold")
    for view in snap.all_models:
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
        httpx.get(f"{base}/v1/models", timeout=3.0).raise_for_status()
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
    path = log_path(target)
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


def _stats(settings: Settings) -> int:
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
        probe = httpx.get(f"{settings.gateway_url.rstrip('/')}/v1/models", timeout=3.0)
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

    # A hung Ollama answers /api/version, so check that it actually serves and
    # recover it here rather than making the user work out why nothing replies.
    has_embed = any("embed" in view.tag for view in snap.installed)
    if snap.ollama_up and has_embed:
        live = probe_liveness(snap.settings.ollama_url)
        if not live.ok:
            from .tune import current_server_env, restart_ollama

            def _restart() -> str:
                restart_ollama()
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


def _backup(settings: Settings, keep: int | None = None) -> int:
    include = [LOCAL_AI_ROOT / "config" / "sovereign", LOCAL_AI_ROOT / "data"]
    exclude = {LOCAL_AI_ROOT / "data": ("browser", "index")}
    extra = {
        LOCAL_AI_ROOT / "config" / "codex" / "local.config.toml": "config/codex/local.config.toml"
    }
    try:
        path = create_backup(
            include,
            LOCAL_AI_ROOT / "backups",
            exclude=exclude,
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
    restart_ollama()
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
    add(snap.loopback, "Loopback only", "Ollama and gateway are on 127.0.0.1", "never bind 0.0.0.0")
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
            if not fits
            else ""
        ),
        warn=True,
    )

    swap_used, swap_total = swap_usage_gb()
    # macOS swaps routinely; only flag real thrash, not a 1 GB baseline.
    swapping = swap_used >= 4.0 or (
        swap_total >= 4.0 and swap_used / swap_total >= 0.85
    )
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
    add(
        snap.gateway.up,
        "LiteLLM gateway",
        f"{len(snap.gateway.models)} models",
        "launchctl kickstart -k gui/$(id -u)/com.user.ailocalgateway",
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
    add(
        GATEWAY_WATCHDOG.is_file(),
        "Gateway watchdog",
        "5-minute health check" if GATEWAY_WATCHDOG.is_file() else "not installed",
        "install local-ai/launchd/com.user.ailocalgateway.watchdog.plist",
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
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?", tag):
        console.print(f"[red]Invalid model tag:[/] {tag}")
        return 1
    snap = _snapshot(settings)
    if snap.views.get(tag) and snap.views[tag].installed:
        console.print(f"[green]{tag} is already installed.[/]")
        return 0
    from .models import REMOTE_CATALOG

    estimated_gb = REMOTE_CATALOG.get(tag, ("", 0.0))[1]
    size_text = f" (~{estimated_gb:.0f} GB)" if estimated_gb else ""
    if estimated_gb and snap.disk_free_gb < max(2.0, estimated_gb + 2.0):
        console.print(
            f"[yellow]Warning:[/] only {snap.disk_free_gb:.0f} GB free; {tag} is "
            f"~{estimated_gb:.0f} GB. You may run out of disk — free space or "
            "remove a model first (`sovereign rm <tag>`)."
        )
    console.print(f"Pulling [bold]{tag}[/]{size_text}" + (f" — {note}" if note else ""))
    client = OllamaClient(settings.ollama_url)

    async def run() -> None:
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
                    if progress.tasks[task].total != float(total):
                        progress.update(task, total=float(total))
                    progress.update(task, completed=float(completed))
                status = event.get("status")
                if status:
                    progress.update(task, description=f"{tag}: {status}")
            progress.update(task, description=f"{tag}: done")

    asyncio.run(run())
    console.print(f"[green]{tag} installed.[/] Run: sovereign models")
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
    table.add_row(
        state, "Gateway", f"{snap.settings.gateway_url} · {len(snap.gateway.models)} aliases"
    )
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
    table.add_row("", "Restart", "sovereign gateway --restart")
    console.print(table)
    return 0 if snap.gateway.up else 1


def _gateway_restart(settings: Settings) -> int:
    import httpx

    base = settings.gateway_url.rstrip("/")

    def up() -> bool:
        try:
            return httpx.get(f"{base}/health/liveliness", timeout=1.5).status_code == 200
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
            return _gateway(_snapshot(settings))
        time.sleep(1)

    console.print("[red]Gateway did not come back.[/] Check: sovereign logs gateway -n 80")
    return 1


def _clients(snap: Snapshot) -> None:
    resolved = resolve_client_models(snap.views, snap.potential_free_gb, snap.settings.max_context)
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
    chat = (
        snap.chat_selection.tag
        if snap.chat_selection and snap.chat_selection.model
        else "-"
    )
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
    """Recover a wedged Ollama, but never interrupt one that is merely busy."""
    from .tune import restart_ollama
    from .watchdog import STUCK, classify, sample

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
    restart_ollama()
    for _ in range(30):
        if probe_liveness(base, timeout=8.0).ok:
            console.print("[green]recovered[/]")
            return 0
        time.sleep(1)
    console.print("[red]Still not serving after restart.[/]")
    return 1


def _prune(snap: Snapshot, apply: bool = False) -> int:
    """Report installed models that no alias, stack or task preference uses."""
    from .prune import parse_alias_targets, prune_candidates, referenced_tags

    config_path = LOCAL_AI_ROOT / "gateway" / "config.yaml"
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError:
        config_text = ""

    refs = referenced_tags(
        parse_alias_targets(config_text), MODEL_STACKS, TASK_PREFERENCE
    )
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
        result = subprocess.run(
            ["ollama", "rm", tag], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            removed.append(tag)
        else:
            console.print(f"[red]Could not remove {tag}:[/] {result.stderr.strip()[:120]}")
    if removed:
        console.print(f"[green]Removed[/] {', '.join(removed)} · {total:.1f} GB freed")
    return 0 if len(removed) == len(candidates) else 1


def _warm(settings: Settings, model: str | None, task: str) -> int:
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
        context = (view.context if view and view.context else settings.max_context)
    else:
        selection = choose(want, snap.views, snap.potential_free_gb, max_context=settings.max_context)
        if not selection.model:
            console.print("[yellow]No installed model to warm.[/]")
            return 1
        tag, context = selection.tag, selection.context

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


def _launch(client: str, path: str, yolo: bool = False, dry_run: bool = False) -> int:
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

    _make_room(snap, agent_model, dry_run)

    try:
        plan = plan_launch(client, target, snap.settings, agent_model, yolo=yolo)
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
        os.execvpe(plan.argv[0], plan.argv, plan.env)
    except OSError as exc:
        console.print(f"[red]Could not launch {info.name}:[/] {exc}")
        return 1
    return 0


def _consult(settings: Settings, prompt: str, models: list[str], tokens: int) -> int:
    import httpx

    try:
        httpx.get(settings.gateway_url.rstrip("/") + "/v1/models", timeout=3.0).raise_for_status()
    except httpx.HTTPError:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway --restart")
        return 1
    for model in models:
        console.print(f"[dim]Consulting {model}…[/]")
        try:
            answer = complete(
                settings.gateway_url,
                model,
                [{"role": "user", "content": prompt}],
                max_tokens=tokens,
            )
        except SourceError as exc:
            console.print(f"[red]{model}: {exc}[/]")
            continue
        console.print(Panel(Text(answer), title=model, border_style="cyan"))
    return 0


def _skills(settings: Settings) -> int:
    rows = list_skills()
    if not rows:
        console.print(
            "[yellow]No skills yet.[/] Add Markdown files to ~/Documents/local-ai/config/skills/"
        )
        return 0
    table = Table(title="Skills", header_style="bold #b794f4")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    for name, description in rows:
        table.add_row(name, description)
    console.print(table)
    console.print("[dim]Run one: sovereign skill <name> --prompt '…'[/]")
    return 0


def _skill(
    settings: Settings, name: str | None, prompt: str | None, model: str, tokens: int
) -> int:
    if not name:
        return _skills(settings)
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


def _memory(settings: Settings, action: str, text: str | None, project: str | None) -> int:
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


def _clone(settings: Settings, url: str, name: str | None) -> int:
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
) -> int:
    import httpx

    try:
        httpx.get(settings.gateway_url.rstrip("/") + "/v1/models", timeout=3.0).raise_for_status()
    except httpx.HTTPError:
        console.print("[red]Gateway is offline.[/] Start it with: sovereign gateway --restart")
        return 1
    target = Path(directory).expanduser().resolve()
    if not target.is_dir():
        console.print(f"[red]Not a directory:[/] {target}")
        return 1
    if not command_exists("qwen"):
        console.print("[red]Qwen Code CLI is not installed.[/]")
        console.print("[dim]npm i -g @qwen-code/qwen-code (then sovereign install-clients)[/]")
        return 1

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

    def implement_fn(prompt_text: str, plan_text: str) -> tuple[bool, str]:
        context = project_context(target)
        combined = (
            f"{prompt_text}\n\nImplementation plan:\n{plan_text}\n\n"
            "Implement it now: create or edit the files."
        )
        if context:
            combined = context + "\n\n" + combined
        env = os.environ.copy()
        env["QWEN_HOME"] = str(LOCAL_AI_ROOT / "qwen")
        command = [
            "qwen",
            "--model",
            agent,
            "--approval-mode",
            "yolo" if yes else "default",
            "-p",
            combined,
        ]
        process = subprocess.run(
            command, cwd=str(target), env=env, capture_output=True, text=True, check=False
        )
        output = (process.stdout or "") + (process.stderr or "")
        return process.returncode == 0, output[-4000:]

    def review_fn(plan_text: str, implementation: str) -> str:
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
                    "content": f"Plan:\n{plan_text}\n\nImplementation log:\n{implementation}",
                },
            ],
            max_tokens=tokens,
        )

    console.print(
        f"[bold]Pipeline[/] · plan={plan_model} · implement={agent} · review={review_model}"
    )
    try:
        result = run_pipeline(prompt, plan_fn, implement_fn, None if no_review else review_fn)
    except SourceError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    for stage in result.stages:
        border = "green" if stage.ok else "red"
        console.print(Panel(Text(stage.output), title=stage.name, border_style=border))
    return 0 if result.succeeded else 1


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
    resolved = resolve_client_models(snap.views, snap.potential_free_gb, snap.settings.max_context)
    chat_alias, chat_tag = resolved["chatgpt"]
    code_alias, _code_tag = resolved["codex"]
    claude_alias, _claude_tag = resolved["claude"]
    fallback_tag = snap.chat_selection.tag if snap.chat_selection else "qwen3.5:4b"
    lines = [
        f'export OLLAMA_HOST="{settings.ollama_host}"',
        f'export SOVEREIGN_OLLAMA_HOST="{settings.ollama_host}"',
        f'export SOVEREIGN_MODEL="{chat_tag or fallback_tag}"',
        # OpenAI-compatible — ChatGPT / Codex CLI / any OpenAI SDK
        f'export OPENAI_BASE_URL="{settings.gateway_url}/v1"',
        'export OPENAI_API_KEY="local"',
        f'export OPENAI_MODEL="{chat_alias}"',
        f'export SOVEREIGN_CODE_MODEL="{code_alias}"',  # best local coder alias
        # Anthropic-compatible — Claude Code
        f'export ANTHROPIC_BASE_URL="{settings.gateway_url}"',
        'export ANTHROPIC_AUTH_TOKEN="local"',
        'export ANTHROPIC_API_KEY="local"',
        f'export ANTHROPIC_MODEL="{claude_alias}"',
        f'export ANTHROPIC_SMALL_FAST_MODEL="{chat_alias}"',
        f'export ANTHROPIC_DEFAULT_SONNET_MODEL="{claude_alias}"',
        f'export ANTHROPIC_DEFAULT_HAIKU_MODEL="{chat_alias}"',
        'export CLAUDE_CODE_MAX_CONTEXT_TOKENS="65536"',
        'export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1"',
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

    sub.add_parser("dashboard", help="open the live terminal dashboard (default)")
    sub.add_parser("status", help="one-shot system status")
    models = sub.add_parser("models", help="list installed and recommended models")
    models.add_argument("--remote", action="store_true", help="list downloadable models")
    models.add_argument("query", nargs="?", default=None, help="filter by name")
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
    sub.add_parser("env", help="print shell exports for local OpenAI-compatible clients")
    sub.add_parser("clients", help="show local coding clients and their capabilities")
    sub.add_parser("install-clients", help="write the local Codex profile and client wrappers")
    sub.add_parser("free", help="unload all resident models")
    sub.add_parser("best", help="show the strongest model each connected tool uses")
    dog = sub.add_parser("watchdog", help="recover a wedged Ollama without killing a busy one")
    dog.add_argument("--no-restart", action="store_true", help="report only")
    dog.add_argument("--interval", type=float, default=8.0, help="seconds between samples")
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

    pipeline = sub.add_parser("pipeline", help="plan -> implement -> review across models")
    pipeline.add_argument("prompt")
    pipeline.add_argument("--dir", default=".")
    pipeline.add_argument("--plan-model", default="local-reasoning")
    pipeline.add_argument("--agent", default="gemma4:12b")
    pipeline.add_argument("--review-model", default="local-agent")
    pipeline.add_argument("--yes", action="store_true", help="yolo-approve agent tool calls")
    pipeline.add_argument("--no-review", action="store_true")
    pipeline.add_argument("--tokens", type=int, default=700)

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

    sub.add_parser("skills", help="list saved skill prompts")

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
    launch.add_argument("client", choices=("qwen", "codex", "claude", "opencode"))
    launch.add_argument("path", nargs="?", default=".")
    launch.add_argument("--yolo", action="store_true", help="auto-approve Qwen Code tool calls")
    launch.add_argument(
        "--dry-run",
        action="store_true",
        help="show the model, eviction and command without launching",
    )
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
        snap = _snapshot(settings)
        if args.remote:
            return _models_remote(snap, args.query)
        _models(snap)
        return 0
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
    if command == "env":
        _env(settings)
        return 0
    if command == "clients":
        _clients(_snapshot(settings))
        return 0
    if command == "install-clients":
        return _install_clients()
    if command == "launch":
        return _launch(args.client, args.path, yolo=args.yolo, dry_run=args.dry_run)
    if command == "best":
        return _best(_snapshot(settings))
    if command == "watchdog":
        return _watchdog(settings, restart=not args.no_restart, interval=args.interval)
    if command == "prune":
        return _prune(_snapshot(settings), apply=args.apply)
    if command == "warm":
        return _warm(settings, args.model, args.task)
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
        return _backup(settings, keep=args.keep)
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
        return _stats(settings)
    if command == "pull":
        for tag in args.model:
            if _pull(settings, tag) != 0:
                return 1
        return 0
    if command == "pull-stack":
        return _pull_stack(settings, args.name, yes=args.yes)
    if command == "setup-stack":
        return _setup_stack(settings, args.name, yes=args.yes)
    if command == "gateway-aliases":
        return _gateway_aliases(settings, _snapshot(settings))
    if command == "rm":
        return _rm(settings, args.model)
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
            [name.strip() for name in args.models.split(",") if name.strip()]
            if args.models
            else ["local-chat", "local-reasoning"]
        )
        return _consult(settings, args.prompt, models, args.tokens)
    if command == "skills":
        return _skills(settings)
    if command == "skill":
        return _skill(settings, args.name, args.prompt, args.model, args.tokens)
    if command == "memory":
        return _memory(settings, args.action, args.text, args.project)
    if command == "clone":
        return _clone(settings, args.url, args.name)
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
        )
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
