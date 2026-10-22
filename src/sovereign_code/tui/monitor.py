"""The live, read-only dashboard.

This is what opens at login and what ``sovereign`` runs by default. Unlike the
old chat dashboard it never sends a prompt, never keeps a model resident, and
never restarts services in the background. It only reports:

* the total skill bank and prompt bank,
* which projects are using a model now or used one recently,
* which models are resident and what the stack is doing.

Chat is an explicit opt-in: ``sovereign chat`` or ``sovereign code``.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Static

from ..clients import local_clients, plan_launch
from ..config import Settings
from ..monitor import LiveReport, collect_live, demo_report, format_age
from ..ollama import OllamaClient
from ..router import Task, choose
from ..status import Snapshot, collect
from ..system import wired_limit_gb

REFRESH_SECONDS = 5.0

HELP_TEXT = """\
Live monitor keys

F5 / r    refresh now
F9 / f    unload every resident model (free RAM)
F2        open Qwen Code in the workspace
F4        open the local Codex / ChatGPT profile
F6        open Claude Code against the local gateway
Ctrl+Q    quit

This dashboard is read-only. It does not chat, does not load a model, and does
not keep any service alive in the background. For a chat turn, run
`sovereign chat`; for coding, press F2 or run `sovereign code`.
"""


class MonitorApp(App[None]):
    CSS_PATH = Path(__file__).with_name("app.tcss")
    TITLE = "Sovereign Code · live monitor"
    SUB_TITLE = "skill bank · prompt bank · live model use"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f2", "launch_code", "Qwen"),
        Binding("f4", "launch_codex", "Codex"),
        Binding("f5", "refresh", "Refresh"),
        Binding("f6", "launch_claude", "Claude"),
        Binding("f9", "free", "Free RAM"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("f", "free", "Free RAM", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]

    def __init__(self, settings: Settings | None = None, demo: bool = False) -> None:
        super().__init__()
        self.settings = settings or Settings.load()
        self.demo = demo
        self.snapshot: Snapshot | None = None
        self.report: LiveReport | None = None
        self._busy = False
        self._notice = ""
        self.ollama = OllamaClient(self.settings.ollama_url)

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("SYSTEM", classes="section-title")
                yield Static("", id="system-panel", classes="panel")
                yield Static("SERVICES", classes="section-title")
                yield Static("", id="service-panel", classes="panel")
                yield Static("RESIDENT MODELS", classes="section-title")
                yield Static("", id="loaded-panel", classes="panel")
            with VerticalScroll(id="main"):
                with Horizontal(id="bank-row"):
                    with Vertical(id="skill-box"):
                        yield Static("SKILL BANK", classes="section-title")
                        yield Static("", id="skill-panel", classes="card")
                    with Vertical(id="prompt-box"):
                        yield Static("PROMPT BANK", classes="section-title")
                        yield Static("", id="prompt-panel", classes="card")
                yield Static("LIVE PROJECTS", classes="section-title")
                yield Static("", id="project-panel", classes="card")
                yield Static("LIVE ACTIVITY · RECENT GATEWAY REQUESTS", classes="section-title")
                yield Static("", id="activity-panel", classes="card")
                yield Static(HELP_TEXT, id="help-panel", classes="hint")
        yield Static("starting…", id="statusbar")
        yield Footer()

    async def on_mount(self) -> None:
        if self.demo:
            self.report = demo_report()
            self._render_report()
            self._render_status()
            self.set_interval(REFRESH_SECONDS, self.tick)
            return
        await self.refresh_all()
        self.set_interval(REFRESH_SECONDS, self.tick)

    # ---------------------------------------------------------------- update
    async def tick(self) -> None:
        if self.demo:
            return
        await self.refresh_all()

    async def refresh_all(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.snapshot = await collect(self.settings)
            self.report = await asyncio.to_thread(collect_live, self.settings, self.snapshot)
            self._render_status()
            self._render_report()
        finally:
            self._busy = False

    def _render_status(self) -> None:
        snap = self.snapshot
        report = self.report
        text = Text()
        if report is None:
            text.append("starting…", style="dim")
            self.query_one("#statusbar", Static).update(text)
            return
        if snap is not None:
            text.append("OLLAMA ", style="bold")
            text.append(
                "● online" if snap.ollama_up else "○ offline",
                style="green" if snap.ollama_up else "red",
            )
            text.append("   GATEWAY ", style="bold")
            text.append(
                "● online" if snap.gateway.up else "○ offline",
                style="green" if snap.gateway.up else "yellow",
            )
        else:
            text.append("DEMO", style="bold yellow")
        text.append("   RAM ", style="bold")
        free = report.memory.free_gb
        style = "cyan" if free > 4 else "yellow"
        text.append(f"{free:.0f}G free", style=style)
        text.append("   LOAD ", style="bold")
        text.append(f"{report.load[0]:.1f}", style="dim")
        text.append("   MODELS ", style="bold")
        text.append(f"{len(report.loaded)} resident", style="dim")
        text.append("   READ-ONLY", style="dim italic")
        if self._notice:
            text.append(f"   {self._notice}", style="bold green")
        self.query_one("#statusbar", Static).update(text)

    def _render_report(self) -> None:
        report = self.report
        if report is None:
            return
        self._render_system(report)
        self._render_services(report)
        self._render_loaded(report)
        self._render_banks(report)
        self._render_projects(report)
        self._render_activity(report)

    def _render_system(self, report: LiveReport) -> None:
        text = Text()
        mem = report.memory
        text.append(f"MEM  {mem.free_gb:.1f}G free / {mem.total_gb:.0f}G", style="bold cyan")
        text.append(f"  ({mem.free_pct:.0f}%)\n")
        text.append(f"SWAP {report.swap_used_gb:.1f}G / {report.swap_total_gb:.1f}G\n", style="dim")
        text.append(f"DISK {report.disk_free_gb:.0f}G free\n", style="dim")
        text.append(
            f"LOAD {report.load[0]:.2f} {report.load[1]:.2f} {report.load[2]:.2f}"
            f"  ·  {report.cpu_count} cores\n",
            style="dim",
        )
        text.append(f"GPU  {wired_limit_gb(mem.total_gb):.0f}G wired ceiling\n", style="dim")
        text.append(f"REQ  {report.gateway_requests} in recent log\n", style="dim")
        if report.errors:
            text.append("ERR  " + "; ".join(report.errors[:2]), style="red")
        self.query_one("#system-panel", Static).update(text)

    def _render_services(self, report: LiveReport) -> None:
        text = Text()
        for service in report.services:
            text.append("● " if service.up else "○ ", style="green" if service.up else "red")
            text.append(f"{service.name}", style="bold" if service.up else "dim")
            text.append(f"  :{service.port}\n", style="dim")
        self.query_one("#service-panel", Static).update(text)

    def _render_loaded(self, report: LiveReport) -> None:
        text = Text()
        if not report.loaded:
            text.append("none — RAM is free\n", style="green")
        for tag, size_gb, context, runner in report.loaded:
            text.append(f"{tag}\n", style="green")
            engine = f" · {runner}" if runner else ""
            text.append(f"  {size_gb:.1f}G · {context or '?'} ctx{engine}\n", style="dim")
        self.query_one("#loaded-panel", Static).update(text)

    def _render_banks(self, report: LiveReport) -> None:
        skills = report.skills
        skill_text = Text()
        skill_text.append(f"{skills.total:,} skills\n", style="bold")
        skill_text.append(f"{skills.size_mb:.1f} MB · {skills.detail}\n", style="dim")
        skill_text.append(f"{skills.category_line}\n", style="dim")
        skill_text.append(f"top: {skills.top_line}\n", style="dim italic")
        self.query_one("#skill-panel", Static).update(skill_text)

        prompts = report.prompts
        prompt_text = Text()
        prompt_text.append(f"{prompts.total:,} prompts\n", style="bold")
        prompt_text.append(f"{prompts.size_mb:.1f} MB · {prompts.detail}\n", style="dim")
        prompt_text.append(f"{prompts.category_line}\n", style="dim")
        prompt_text.append(f"top: {prompts.top_line}\n", style="dim italic")
        self.query_one("#prompt-panel", Static).update(prompt_text)

    def _render_projects(self, report: LiveReport) -> None:
        text = Text()
        if not report.projects:
            text.append("No project has used a model recently.\n", style="dim")
        for project in report.projects:
            dot = "● " if project.active else "○ "
            text.append(dot, style="green" if project.active else "dim")
            text.append(f"{project.name:<24}", style="bold" if project.active else "")
            model = project.model or "no model recorded"
            text.append(f"  {model:<18}", style="cyan" if project.active else "dim")
            text.append(f"  {project.age:>4}", style="dim")
            if project.pid:
                text.append(f"  pid {project.pid}", style="dim")
            text.append("\n")
            text.append(f"  {project.path}\n", style="dim")
        self.query_one("#project-panel", Static).update(text)

    def _render_activity(self, report: LiveReport) -> None:
        text = Text()
        if not report.activity:
            text.append("No gateway requests logged yet.\n", style="dim")
        for event in report.activity:
            text.append(f"{format_age(event.at)}  ", style="dim")
            text.append(f"{event.tier:<9}", style="bold cyan")
            text.append(f"{event.model:<18} ", style="bold")
            tools = " tools" if event.tools else ""
            label = f"{event.ms:>6}ms  {event.tokens:>4} tok{tools}  {event.age}\n"
            text.append(label, style="dim")
        self.query_one("#activity-panel", Static).update(text)

    # ---------------------------------------------------------------- actions
    async def action_refresh(self) -> None:
        await self.refresh_all()

    async def action_help(self) -> None:
        self._notice = "see the read-only help panel below"
        self._render_status()

    async def action_free(self) -> None:
        tags: list[str] = []
        if self.snapshot is not None:
            tags = [view.tag for view in self.snapshot.loaded]
        if not tags:
            self._notice = "no model resident — nothing to unload"
            self._render_status()
            return
        for tag in tags:
            try:
                await self.ollama.unload(tag)
            except Exception:
                continue
        self._notice = f"unloaded {', '.join(tags)}"
        await self.refresh_all()

    async def _launch(self, client: str) -> None:
        info = {item.key: item for item in local_clients()}.get(client)
        if info is None or not info.installed:
            self._notice = f"{client} is not installed"
            self._render_status()
            return
        target = Path(self.settings.workspace).expanduser().resolve()
        if not target.is_dir():
            target = Path.cwd()
        if self.snapshot is None:
            await self.refresh_all()
        selection = choose(
            Task.AGENT,
            self.snapshot.views if self.snapshot else {},
            self.snapshot.potential_free_gb if self.snapshot else None,
            max_context=self.settings.max_context,
        )
        try:
            plan = plan_launch(
                client,
                target,
                self.settings,
                agent_model=selection.tag or "gemma4:12b",
            )
        except ValueError as exc:
            self._notice = f"could not launch {info.name}: {exc}"
            self._render_status()
            return
        if selection.tag and self.snapshot is not None:
            for view in self.snapshot.loaded:
                if view.tag != selection.tag:
                    try:
                        await self.ollama.unload(view.tag)
                    except Exception:
                        pass
        self._notice = f"opening {info.name} with {plan.model}"
        self._render_status()
        try:
            with self.suspend():
                subprocess.call(plan.argv, cwd=str(plan.cwd), env=plan.env)
        finally:
            await self.refresh_all()

    async def action_launch_code(self) -> None:
        await self._launch("qwen")

    async def action_launch_codex(self) -> None:
        await self._launch("codex")

    async def action_launch_claude(self) -> None:
        await self._launch("claude")


__all__ = ["REFRESH_SECONDS", "MonitorApp"]
