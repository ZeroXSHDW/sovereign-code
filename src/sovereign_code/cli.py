"""Command-line entry point for Sovereign Code."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, fields as dc_fields
import html
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.text import Text
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
from .backup import create_backup
from .bench import DEFAULT_MODELS, DEFAULT_PROMPT, bench_alias
from .browser.executor import chromium_path
from .logs import TARGETS, log_path, tail_lines
from .search import (
    DEFAULT_EMBED,
    EmbedError,
    IndexStore,
    build_index,
    embed,
    index_path_for,
)
from .stats import collect_stats, human_size
from .summarize import SourceError, read_text_source, summarize_text
from .models import build_views, sort_views
from .ollama import OllamaClient
from .router import Task, choose, mode_label
from .sessions import (
    prune_sessions,
    scan_sessions,
    search_sessions,
    select_prunable,
)
from .status import Snapshot, collect
from .system import command_exists, login_agent_installed, qwen_config_path, qwen_memory_path
from .verify import CORE_ALIASES, EXPECTED_ALIASES, probe_aliases

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
    console.print("[dim]First call per alias may include model load time; rerun for steady-state.[/]")
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
) -> int:
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
        console.print(
            f"[green]Removed {removed} sessions[/] · kept {len(infos) - removed}"
        )
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
    from .browser.executor import BrowserSession, BrowserError

    policy = BrowserPolicy(
        allow_local=args.allow_local,
        allowed_domains=tuple(args.allow_domain),
    )
    if not args.url:
        console.print("[red]Give a starting URL:[/] sovereign browse https://example.com --task '…'")
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
        console.print(
            "[bold]Browser open.[/] Use it normally; press Enter here to close."
        )
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
        except Exception as exc:  # noqa: BLE001 - surfaced in the table
            rows.append(("[red]FAILED[/]", label, str(exc)))

    run("config", lambda: write_default_config())
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
    store = IndexStore(db)
    try:
        vector = embed(settings.ollama_url, model, [query])[0]
        results = store.search(vector, top=top)
    except EmbedError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    finally:
        store.close()
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
    doctor = sub.add_parser("doctor", help="check the local stack and print fixes")
    doctor.add_argument("--fix", action="store_true", help="apply the safe fixes automatically")
    verify = sub.add_parser("verify", help="send a test completion through the gateway aliases")
    verify.add_argument("--all", action="store_true", help="test all nine aliases")
    verify.add_argument(
        "--timeout", type=float, default=120.0, help="per-alias timeout in seconds"
    )
    gateway = sub.add_parser("gateway", help="show gateway status, paths, and restart command")
    gateway.add_argument(
        "--restart", action="store_true", help="restart the supervisor and wait for health"
    )
    sub.add_parser("env", help="print shell exports for local OpenAI-compatible clients")
    sub.add_parser("clients", help="show local coding clients and their capabilities")
    sub.add_parser("install-clients", help="write the local Codex profile and client wrappers")
    sub.add_parser("free", help="unload all resident models")

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

    config = sub.add_parser("config", help="view or edit sovereign config")
    config.add_argument("--set", dest="set_value", default=None, metavar="KEY=VALUE")
    config.add_argument("--get", dest="get_key", default=None, metavar="KEY")

    sub.add_parser("stats", help="show disk usage across the local AI stack")

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
        snap = _snapshot(settings)
        if args.fix:
            return _doctor_fix(settings, snap)
        return _doctor(snap)
    if command == "verify":
        return _verify(_snapshot(settings), all_aliases=args.all, timeout=args.timeout)
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
        return _launch(args.client, args.path, yolo=args.yolo)
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
        )
    if command == "config":
        return _config(settings, get_key=args.get_key, set_value=args.set_value)
    if command == "stats":
        return _stats(settings)
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
