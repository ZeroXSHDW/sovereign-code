"""Sovereign Code live terminal dashboard."""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Markdown, Static

from ..clients import local_clients, plan_launch, resolve_client_models
from ..config import Settings
from ..memory import project_context
from ..models import ModelView
from ..ollama import OllamaClient
from ..router import Task, choose, mode_label, system_prompt, task_from_name
from ..sessions import SessionWriter, prune_sessions, scan_sessions, select_prunable
from ..status import Snapshot, collect
from ..system import Memory, wired_limit_gb
from ..verify import CORE_ALIASES, AliasResult, probe_aliases

HELP_TEXT = """\
**Commands**

- `/model <tag>` — switch model
- `/models` — list installed models
- `/chat`, `/code`, `/reason`, `/vision`, `/fast` — switch mode
- `/status` — refresh system state
- `/open [path]`, `/qwen [path]` — Qwen Code local agent
- `/codex [path]`, `/claude [path]` — local chat clients
- `/clients` — show installed clients and capabilities
- `/verify` — send a tiny test through the four core gateway aliases
- `/browse <url> [task]` — drive a visible Chromium with the local model
- `/search <query>` — semantic search over the indexed workspace
- `/index [path]` — embed a directory for search
- `/summarize <file|url>` — local-model summary
- `/backup` — archive configs and chat data
- `/run <command>` — run a shell command locally and show output
- `/terminal [path]` — open a real Terminal window
- `/skills`, `/skill <name>` — saved prompt templates
- `/memory add <note>` — remember a project note (injected into chat)
- `/free` — unload other models and free memory
- `/clear` — new conversation
- `/help` — this help
- `/pwd` — show the working directory
- `/quit` — exit

**Keys:** `F2` Qwen Code · `F4` Codex · `F6` Claude · `F3` model · `F5` refresh
· `F7` verify gateway · `F8` browse · `Ctrl+N` new chat · `Ctrl+Q` quit
"""


class ModelListItem(ListItem):
    def __init__(self, view: ModelView) -> None:
        self.view = view
        label = Text()
        label.append("▶ " if view.loaded else ("● " if view.installed else "↓ "), style="bold")
        label.append(view.tag, style="bold" if view.loaded else "")
        label.append(f"  {view.size_gb:.1f}G", style="dim")
        if view.context:
            label.append(f"  {view.context} ctx", style="dim")
        if view.spec.role:
            label.append(f"  {view.spec.role}", style="dim italic")
        if view.runner:
            label.append(f"  {view.runner}", style="dim italic")
        super().__init__(
            Label(label),
            id="model-" + view.tag.replace(":", "-").replace("/", "-").replace(".", "-"),
        )


class SovereignApp(App[None]):
    CSS_PATH = Path(__file__).with_name("app.tcss")
    TITLE = "Sovereign Code"
    SUB_TITLE = "local-first coding console"
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f2", "launch_code", "Qwen"),
        Binding("f3", "cycle_model", "Model"),
        Binding("f4", "launch_codex", "Codex"),
        Binding("f5", "refresh", "Refresh"),
        Binding("f6", "launch_claude", "Claude"),
        Binding("f7", "verify", "Verify"),
        Binding("f8", "browse", "Browse"),
        Binding("f9", "open_terminal", "Terminal"),
        Binding("ctrl+n", "clear_chat", "New"),
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        mode: str = "dashboard",
        demo: bool = False,
    ) -> None:
        super().__init__()
        self.settings = settings or Settings.load()
        self.mode = mode
        self.demo = demo
        self.ai_task = Task.CODE if mode == "code" else Task.CHAT
        self.selected_model: str | None = self.settings.default_model
        self.history: list[dict[str, str]] = []
        self.snapshot: Snapshot | None = None
        self.session: SessionWriter | None = None
        self._streaming = False
        self._assistant: Markdown | None = None
        self._refresh_busy = False
        self._verify_busy = False
        self.last_verify: list[AliasResult] = []
        self._model_signature: tuple = ()
        self.ollama = OllamaClient(self.settings.ollama_url)
        self._started_at = time.monotonic()

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("LOCAL MODELS", classes="section-title")
                yield ListView(id="model-list")
                yield Static("", id="system-panel", classes="panel")
            with Vertical(id="main"):
                yield VerticalScroll(id="chat-scroll")
                yield Static("", id="hint", classes="hint")
                yield Input(
                    placeholder="Ask the local model…   /help for commands",
                    id="prompt",
                )
        yield Static("starting…", id="statusbar")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        await self.add_message(
            "system",
            "**Sovereign Code** is running locally. No prompt leaves this Mac.\n\n"
            "Type a question, press `F9` for a real terminal, or `F2` for Qwen Code.\n"
            "Use `/help` for the full command list.",
        )
        if self.demo:
            self._apply_demo()
        else:
            await self.refresh_snapshot()
        self._prune_sessions()
        self.set_interval(2.5, self.refresh_tick)

    def _prune_sessions(self) -> None:
        days = self.settings.session_retention_days
        if days <= 0:
            return
        victims = select_prunable(scan_sessions(), days=days, keep=self.settings.session_keep)
        if victims:
            prune_sessions(victims)

    # ---------------------------------------------------------------- status
    async def refresh_tick(self) -> None:
        if self.demo:
            return
        await self.refresh_snapshot()

    async def refresh_snapshot(self) -> None:
        if self._refresh_busy or self.demo:
            return
        self._refresh_busy = True
        try:
            self.snapshot = await collect(self.settings)
            self._render_status()
            self._render_system()
            await self._render_models()
        finally:
            self._refresh_busy = False

    def _apply_demo(self) -> None:
        from ..models import CATALOG, ModelView

        views = {
            tag: ModelView(spec=spec, installed=tag != "qwen2.5-coder:14b", size_gb=spec.size_gb)
            for tag, spec in CATALOG.items()
        }
        self.snapshot = Snapshot(
            settings=self.settings,
            ollama_up=True,
            version="demo",
            views=views,
            memory=Memory(24.0, 16.0, 67.0),
        )
        self.selected_model = "qwen3.5:4b"
        self._render_status()
        self._render_system()
        self.run_worker(self._render_models())

    def _render_status(self) -> None:
        snap = self.snapshot
        text = Text()
        if not snap:
            text.append("starting…", style="dim")
            self.query_one("#statusbar", Static).update(text)
            return
        text.append("OLLAMA ", style="bold")
        text.append(
            "● online" if snap.ollama_up else "○ offline",
            style="green" if snap.ollama_up else "red",
        )
        text.append(f" {snap.version}", style="dim")
        text.append("   GATEWAY ", style="bold")
        text.append(
            "● online" if snap.gateway.up else "○ offline",
            style="green" if snap.gateway.up else "yellow",
        )
        text.append(f"   RAM {snap.memory.label}", style="dim")
        text.append(f"   MODE {mode_label(self.ai_task)}", style="bold cyan")
        current = self.selected_model or (snap.chat_selection.tag if snap.chat_selection else None)
        text.append(f"   MODEL {current or 'none'}", style="bold")
        if not snap.loopback:
            text.append("   LOOPBACK VIOLATION", style="bold red")
        self.query_one("#statusbar", Static).update(text)

    def _render_system(self) -> None:
        snap = self.snapshot
        text = Text()
        if not snap:
            text.append("waiting for Ollama…", style="dim")
        else:
            text.append("LOADED\n", style="bold")
            if snap.loaded:
                for view in snap.loaded:
                    engine = f" · {view.runner}" if view.runner else ""
                    text.append(f"{view.tag} · {view.context or '?'}{engine}\n", style="green")
            else:
                text.append("  none\n", style="dim")
            text.append("\nCODER\n", style="bold")
            coder = snap.recommended_coder or snap.best_coder
            if coder:
                style = "cyan" if coder.installed else "yellow"
                text.append(f"{coder.tag}\n", style=style)
                text.append(f"  {coder.status}\n", style="dim")
                if not coder.installed and snap.best_coder:
                    text.append(f"  fallback {snap.best_coder.tag}\n", style="dim")
            else:
                text.append("  none installed\n", style="yellow")
            wired = wired_limit_gb(snap.memory.total_gb)
            text.append(
                f"\nMEM {snap.memory.free_gb:.0f}G free / {snap.memory.total_gb:.0f}G"
                f" · GPU {wired:.0f}G wired\n",
                style="dim",
            )
            text.append(
                "LOGIN installed\n" if snap.login_installed else "LOGIN not installed\n",
                style="dim",
            )
            text.append(f"WS {self.settings.workspace}\n", style="dim")
        self.query_one("#system-panel", Static).update(text)

    async def _render_models(self) -> None:
        snap = self.snapshot
        if not snap:
            return
        signature = tuple((v.tag, v.installed, v.loaded, v.context) for v in snap.sorted_models)
        if signature == self._model_signature:
            return
        self._model_signature = signature
        list_view = self.query_one("#model-list", ListView)
        await list_view.clear()
        for view in snap.sorted_models:
            await list_view.append(ModelListItem(view))
        current = self.selected_model or (snap.chat_selection.tag if snap.chat_selection else None)
        if current:
            for index, view in enumerate(snap.sorted_models):
                if view.tag == current:
                    list_view.index = index
                    break
        else:
            installed = [v for v in snap.sorted_models if v.installed]
            if installed:
                self.selected_model = installed[0].tag
                list_view.index = snap.sorted_models.index(installed[0])

    # ---------------------------------------------------------------- events
    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ModelListItem):
            self.selected_model = item.view.tag
            self._render_status()
            self.query_one("#prompt", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if value.startswith("/"):
            await self.handle_command(value)
            return
        await self.send(value)

    # ---------------------------------------------------------------- chat
    def current_selection(self):
        if not self.snapshot:
            return None
        return choose(
            self.ai_task,
            self.snapshot.views,
            self.snapshot.potential_free_gb,
            preferred=self.selected_model,
            max_context=self.settings.max_context,
        )

    async def add_message(self, role: str, text: str) -> Markdown:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        widget = Markdown(text, classes=f"message {role}")
        await scroll.mount(widget)
        scroll.scroll_end(animate=False)
        return widget

    async def send(self, text: str) -> None:
        if self._streaming:
            await self.add_message("system", "_Still generating — wait for the current reply._")
            return
        if not self.snapshot:
            await self.add_message("system", "_Ollama is not reachable yet._")
            return
        selection = self.current_selection()
        if not selection or not selection.model:
            await self.add_message(
                "system",
                "_No local model is installed. Run `ollama pull qwen2.5-coder:14b`._",
            )
            return
        await self._make_room(selection.model.tag)
        selection = self.current_selection()
        if not selection or not selection.model:
            await self.add_message("system", "_No model available after eviction._")
            return
        self.history.append({"role": "user", "content": text})
        await self.add_message("you", text)
        self._assistant = await self.add_message("assistant", "…")
        self._streaming = True
        if self.session is None:
            self.session = SessionWriter.create(selection.model.tag)
        self.session.append("user", text)
        self.run_worker(self._stream_reply(selection), exclusive=True)

    async def _make_room(self, keep_tag: str) -> None:
        """Unload other resident models so the selected model can use a real context."""
        if not self.snapshot:
            return
        others = [v.tag for v in self.snapshot.loaded if v.tag != keep_tag]
        if not others:
            return
        for tag in others:
            try:
                await self.ollama.unload(tag)
            except Exception:
                pass
        await self.add_message("system", f"Unloaded {', '.join(others)} to free memory.")
        await self.refresh_snapshot()

    async def _stream_reply(self, selection) -> None:
        # The user turn is already in self.history, so this only has to
        # render the model's answer into the placeholder message.
        assistant = self._assistant
        if assistant is None:
            return
        system = system_prompt(self.ai_task)
        context = self._project_memory()
        if context:
            system += "\n\nProject context (follow these notes):\n" + context
        messages = [{"role": "system", "content": system}]
        messages.extend(self.history[-20:])
        chunks: list[str] = []
        stats = ""
        last_update = 0.0
        try:
            think = False if selection.model.spec.thinking else None
            async for chunk in self.ollama.chat_stream(
                selection.model.tag,
                messages,
                context=selection.context,
                temperature=self.settings.temperature,
                think=think,
            ):
                if chunk.content:
                    chunks.append(chunk.content)
                    now = time.monotonic()
                    if now - last_update > 0.06:
                        await assistant.update("".join(chunks))
                        last_update = now
                if chunk.done:
                    stats = (
                        f"\n\n`{selection.model.tag} · {selection.context} ctx · "
                        f"{chunk.eval_count} tok · {chunk.total_duration_ns / 1e9:.1f}s`"
                    )
            answer = "".join(chunks).strip()
            if not answer:
                raise RuntimeError("the model returned no content")
            await assistant.update(answer + stats)
            self.history.append({"role": "assistant", "content": answer})
            if self.session:
                self.session.append("assistant", answer, model=selection.model.tag)
        except Exception as exc:
            await assistant.update(f"**Local model error:** {exc}")
            if self.session:
                self.session.append("error", str(exc))
        finally:
            self._streaming = False
            self.query_one("#prompt", Input).focus()

    async def handle_command(self, value: str) -> None:
        parts = value.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if command in {"/help", "/commands", "/?"}:
            await self.add_message("system", HELP_TEXT)
        elif command == "/models":
            if not self.snapshot:
                return
            rows = "\n".join(f"- `{v.tag}` — {v.status}" for v in self.snapshot.sorted_models)
            await self.add_message("system", rows)
        elif command == "/model":
            if not self.snapshot or arg not in self.snapshot.views:
                await self.add_message("system", f"Unknown model `{arg}`. Try `/models`.")
                return
            if not self.snapshot.views[arg].installed:
                await self.add_message("system", f"`{arg}` is not installed yet.")
                return
            self.selected_model = arg
            self._render_status()
            await self.add_message("system", f"Model set to `{arg}`.")
        elif command in {"/chat", "/code", "/reason", "/vision", "/fast"}:
            self.ai_task = task_from_name(command[1:])
            selection = self.current_selection()
            if selection and selection.model:
                self.selected_model = selection.model.tag
            self._render_status()
            hint = " · press F2 to open Qwen Code" if self.ai_task is Task.CODE else ""
            await self.add_message(
                "system",
                f"Mode: **{mode_label(self.ai_task)}** · `{self.selected_model}`{hint}",
            )
        elif command in {"/open", "/qwen"}:
            await self.action_launch_code(arg or None)
        elif command in {"/terminal", "/term"}:
            from ..terminal import spawn_terminal

            target = arg or self.settings.workspace
            try:
                result = await asyncio.to_thread(
                    spawn_terminal, cwd=target, command="", dry_run=False
                )
            except Exception as exc:
                await self.add_message("system", f"Could not open a terminal: {exc}")
                return
            await self.add_message(
                "system",
                f"Opened a Terminal in `{result['cwd']}` ({result.get('method', '?')}).",
            )
        elif command in {"/run", "/shell", "/exec"}:
            if not arg:
                await self.add_message("system", "Usage: `/run <command>`")
                return
            from ..terminal import run_shell

            workspace = Path(self.settings.workspace).expanduser()
            if not workspace.is_dir():
                workspace = Path.cwd()
            await self.add_message("system", f"Running `{arg}`…")
            started = time.monotonic()
            try:
                result = await asyncio.to_thread(run_shell, arg, cwd=workspace, timeout=120)
            except Exception as exc:
                await self.add_message("system", f"Run failed: {exc}")
                return
            elapsed = time.monotonic() - started
            output = result.get("stdout", "")
            if result.get("stderr"):
                output += ("\n" if output else "") + result["stderr"]
            if len(output) > 4000:
                output = output[:2000] + "\n…[truncated]…\n" + output[-2000:]
            if not output:
                output = "(no output)"
            mark = "OK" if result.get("ok") else "FAIL"
            await self.add_message(
                "system",
                f"**{mark}** (exit {result.get('returncode')}, {elapsed:.1f}s)\n```\n{output}\n```",
            )
        elif command == "/codex":
            await self.action_launch_codex(arg or None)
        elif command == "/claude":
            await self.action_launch_claude(arg or None)
        elif command == "/clients":
            resolved = (
                resolve_client_models(
                    self.snapshot.views,
                    self.snapshot.potential_free_gb,
                    self.settings.max_context,
                )
                if self.snapshot
                else None
            )
            rows = "\n".join(
                f"- **{item.name}** — {item.capability} · `{item.model}` · "
                f"{'ready' if item.installed else 'missing'}\n  {item.detail}"
                for item in local_clients(resolved)
            )
            await self.add_message("system", rows)
        elif command in {"/status", "/reload"}:
            await self.refresh_snapshot()
            self._render_status()
            self._render_system()
            await self.add_message("system", "Status refreshed.")
        elif command == "/verify":
            await self.action_verify()
        elif command == "/browse":
            await self._launch_browse(arg)
        elif command == "/search":
            if not arg:
                await self.add_message("system", "Usage: `/search <query>`")
                return
            workspace = Path(self.settings.workspace).expanduser()
            if not workspace.is_dir():
                workspace = Path.cwd()
            await self._search_inline(arg, workspace)
        elif command == "/index":
            workspace = str(Path(self.settings.workspace).expanduser())
            await self._run_cli("index", arg or workspace)
        elif command == "/summarize":
            if not arg:
                await self.add_message("system", "Usage: `/summarize <file|url>`")
                return
            if arg.startswith(("http://", "https://")):
                await self._run_cli("summarize", "--url", arg)
            else:
                await self._run_cli("summarize", arg)
        elif command == "/backup":
            await self._run_cli("backup")
        elif command == "/hf":
            if not arg:
                await self.add_message("system", "Usage: `/hf search|info|download|import ...`")
                return
            await self._run_cli("hf", *arg.split())
        elif command == "/doctor":
            await self._run_cli("doctor")
        elif command == "/skills":
            await self._run_cli("skills")
        elif command == "/skill":
            await self._run_cli("skill", *shlex.split(arg))
        elif command == "/free":
            if self.snapshot:
                for view in self.snapshot.loaded:
                    try:
                        await self.ollama.unload(view.tag)
                    except Exception:
                        pass
                await self.refresh_snapshot()
            await self.add_message("system", "Resident models unloaded.")
        elif command == "/pwd":
            await self.add_message("system", f"`{self.settings.workspace}`")
        elif command == "/ping":
            await self.handle_command("/run ping -c 1 127.0.0.1")
        elif command == "/motd":
            import random

            tips = [
                "Press F9 to open a real terminal without leaving the dashboard.",
                "Use /run to execute shell commands and see their output inline.",
                "Try /calc for quick arithmetic without a model.",
                "Use /history to review recent turns.",
            ]
            await self.add_message("system", f"Tip: {random.choice(tips)}")  # noqa: S311  # noqa: S311
        elif command == "/banner":
            banner = (
                "```\n"
                " ____  ____  ____  ____  ____  ____  ____  ____\n"
                "||S ||||o ||||v ||||e ||||r ||||e ||||i ||||g ||\n"
                "||__||||__||||__||||__||||__||||__||||__||||__||\n"
                "|/  \\||/  \\||/  \\||/  \\||/  \\||/  \\||/  \\||/  \\|\n"
                "```\n"
                "Sovereign Code — local-first AI console"
            )
            await self.add_message("system", banner)
        elif command == "/whoami":
            import getpass
            import socket

            await self.add_message("system", f"{getpass.getuser()}@{socket.gethostname()}")
        elif command == "/env":
            import os as _os

            keys = ["PATH", "SHELL", "HOME", "PYTHONPATH"]
            lines = [f"- `{k}` = `{_os.environ.get(k, '')}`" for k in keys]
            await self.add_message("system", "\n".join(lines))
        elif command == "/calc":
            if not arg:
                await self.add_message("system", "Usage: `/calc <expression>`")
                return
            try:
                import ast as _ast
                import operator as _op

                _OPS = {
                    _ast.Add: _op.add,
                    _ast.Sub: _op.sub,
                    _ast.Mult: _op.mul,
                    _ast.Div: _op.truediv,
                    _ast.Pow: _op.pow,
                    _ast.Mod: _op.mod,
                }

                def _eval(node):
                    if isinstance(node, _ast.Expression):
                        return _eval(node.body)
                    if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
                        return node.value
                    if isinstance(node, _ast.BinOp) and type(node.op) in _OPS:
                        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
                    if isinstance(node, _ast.UnaryOp) and isinstance(node.op, _ast.USub):
                        return -_eval(node.operand)
                    raise ValueError("unsupported expression")

                value = _eval(_ast.parse(arg, mode="eval"))
                await self.add_message("system", f"`{arg}` = **{value}**")
            except Exception as exc:
                await self.add_message("system", f"Calc error: {exc}")
        elif command == "/echo":
            await self.add_message("system", arg or "")
        elif command == "/time":
            import datetime as _dt

            await self.add_message("system", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        elif command == "/uptime":
            elapsed = time.monotonic() - self._started_at
            mins, secs = divmod(int(elapsed), 60)
            hrs, mins = divmod(mins, 60)
            await self.add_message("system", f"Uptime: {hrs}h {mins}m {secs}s")
        elif command == "/version":
            from .. import __version__

            await self.add_message("system", f"Sovereign Code v{__version__}")
        elif command == "/history":
            if not self.history:
                await self.add_message("system", "_No conversation history yet._")
                return
            lines = []
            for item in self.history[-10:]:
                role = item.get("role", "?")
                content = " ".join(item.get("content", "").split())[:80]
                lines.append(f"- **{role}**: {content}")
            await self.add_message("system", "\n".join(lines))
        elif command in {"/clear", "/reset", "/cls"}:
            await self.clear_chat()
        elif command == "/quit":
            self.exit()
        else:
            await self.add_message("system", f"Unknown command `{command}`. Try `/help`.")

    async def clear_chat(self) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        await scroll.remove_children()
        self.history.clear()
        self.session = None
        await self.add_message("system", "_New conversation._")

    # ---------------------------------------------------------------- actions
    async def action_refresh(self) -> None:
        await self.refresh_snapshot()

    async def action_clear_chat(self) -> None:
        await self.clear_chat()

    async def action_browse(self) -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.value = "/browse "
        prompt.cursor_position = len(prompt.value)
        prompt.focus()

    async def action_open_terminal(self) -> None:
        await self.handle_command("/terminal")

    def _project_memory(self) -> str:
        cwd = Path(self.settings.workspace).expanduser() if self.settings.workspace else Path.cwd()
        if not cwd.is_dir():
            cwd = Path.cwd()
        return project_context(cwd)

    async def _search_inline(self, query: str, root: Path) -> None:
        from ..search import index_path_for, search_query

        db = index_path_for(root.resolve())
        if not db.is_file():
            await self.add_message("system", f"No index for {root}. Run `/index` first.")
            return
        try:
            results = await asyncio.to_thread(
                search_query, self.settings.ollama_url, db, query, "nomic-embed-text", 5
            )
        except Exception as exc:
            await self.add_message("system", f"Search failed: {exc}")
            return
        if not results:
            await self.add_message("system", "No matching chunks.")
            return
        lines = [f"**Search**: `{query}`"]
        for result in results:
            snippet = " ".join(result.text.split())[:120]
            lines.append(f"- `{result.path}:{result.line}` · {result.score:.2f}\n  {snippet}")
        await self.add_message("system", "\n".join(lines))

    async def _run_cli(self, *args: str) -> None:
        try:
            with self.suspend():
                await asyncio.to_thread(
                    subprocess.call, [sys.executable, "-m", "sovereign_code", *args]
                )
        finally:
            await self.refresh_snapshot()

    async def _launch_browse(self, arg: str) -> None:
        if not arg.strip():
            await self.add_message("system", "Usage: `/browse https://example.com what to find`")
            return
        parts = arg.split(maxsplit=1)
        url = parts[0].strip()
        task = parts[1].strip() if len(parts) > 1 else ""
        command = [sys.executable, "-m", "sovereign_code", "browse", url]
        if task:
            command += ["--task", task]
        await self.add_message(
            "system",
            f"Opening browser at `{url}`" + (f" — {task}" if task else ""),
        )
        try:
            with self.suspend():
                await asyncio.to_thread(subprocess.call, command)
        finally:
            await self.refresh_snapshot()

    async def action_verify(self) -> None:
        if self._verify_busy:
            return
        if not self.snapshot or not self.snapshot.gateway.up:
            await self.add_message(
                "system",
                "Gateway is offline. Restart it with `sovereign gateway --restart`.",
            )
            return
        self._verify_busy = True
        self.query_one("#statusbar", Static).update("verifying gateway aliases…")
        try:
            results = await asyncio.to_thread(
                probe_aliases, self.settings.gateway_url, CORE_ALIASES, 60.0
            )
            self.last_verify = results
        except Exception as exc:
            await self.add_message("system", f"Verify failed: {exc}")
            return
        finally:
            self._verify_busy = False
        passed = sum(1 for result in results if result.ok)
        lines = [f"**Gateway verify** — {passed}/{len(results)} passed"]
        for result in results:
            mark = "PASS" if result.ok else "FAIL"
            lines.append(
                f"- `{result.alias}` · **{mark}** · {result.seconds:.1f}s · {result.detail}"
            )
        await self.add_message("system", "\n".join(lines))
        await self.refresh_snapshot()

    async def action_cycle_model(self) -> None:
        if not self.snapshot:
            return
        installed = [v.tag for v in self.snapshot.sorted_models if v.installed]
        if not installed:
            return
        try:
            index = installed.index(self.selected_model or "")
        except ValueError:
            index = -1
        self.selected_model = installed[(index + 1) % len(installed)]
        self._render_status()
        await self.add_message("system", f"Model: `{self.selected_model}`")

    async def _launch_client(self, client: str, path: str | None = None) -> None:
        info = {item.key: item for item in local_clients()}.get(client)
        if info is None or not info.installed:
            name = info.name if info else client
            await self.add_message("system", f"`{name}` is not installed or not on PATH.")
            return
        target = (
            Path(path).expanduser().resolve()
            if path
            else Path(self.settings.workspace).expanduser().resolve()
        )
        if not target.is_dir():
            target = Path.cwd()
        if not target.is_dir():
            await self.add_message("system", f"Not a directory: `{target}`")
            return
        if not self.snapshot:
            await self.refresh_snapshot()
        selection = choose(
            Task.AGENT,
            self.snapshot.views if self.snapshot else {},
            # The same figure the CLI uses: free RAM *after* evicting the
            # current residents. Using the raw free-RAM number here picked a
            # smaller model and context than the CLI for the same machine.
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
            await self.add_message("system", f"Could not launch {info.name}: {exc}")
            return
        if selection.tag:
            # Free the GPU before the agent loads its model, exactly as the CLI
            # does; otherwise a resident model squeezes the agent's context.
            await self._make_room(selection.tag)
        note = f" — {plan.note}" if plan.note else ""
        await self.add_message(
            "system",
            f"Opening **{info.name}** with `{plan.model}` in `{target}`{note}…",
        )
        try:
            with self.suspend():
                await asyncio.to_thread(
                    subprocess.call,
                    plan.argv,
                    cwd=str(plan.cwd),
                    env=plan.env,
                )
        finally:
            await self.refresh_snapshot()

    async def action_launch_code(self, path: str | None = None) -> None:
        await self._launch_client("qwen", path)

    async def action_launch_codex(self, path: str | None = None) -> None:
        await self._launch_client("codex", path)

    async def action_launch_claude(self, path: str | None = None) -> None:
        await self._launch_client("claude", path)
