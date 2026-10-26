"""Debug overlay for the live monitor."""

from __future__ import annotations

import json
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from ..debug import recent_debug_records, recent_logs, recent_swallowed


class DebugOverlay(ModalScreen[None]):
    """A read-only overlay showing recent logs, tracebacks and debug traces."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape,q", "dismiss", "Close"),
        Binding("ctrl+q", "dismiss", "Close"),
        Binding("l", "logs", "Logs"),
        Binding("s", "swallowed", "Swallowed"),
        Binding("d", "debug", "Debug"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="debug-dialog"):
            yield Static(
                "DEBUG OVERLAY  ·  l logs · s swallowed · d debug traces · q close",
                id="debug-title",
            )
            with VerticalScroll(id="debug-body"):
                yield Static("", id="debug-content")
        yield Footer()

    def on_mount(self) -> None:
        self._show_swallowed()

    def action_logs(self) -> None:
        self._show_logs()

    def action_swallowed(self) -> None:
        self._show_swallowed()

    def action_debug(self) -> None:
        self._show_debug()

    def _show_logs(self) -> None:
        lines = recent_logs("tier", count=80) or ["No tier-gateway log found."]
        self._update("TIER GATEWAY LOG", "\n".join(lines))

    def _show_swallowed(self) -> None:
        lines = recent_swallowed(count=80) or ["No swallowed exceptions recorded."]
        self._update("SWALLOWED EXCEPTIONS", "\n".join(lines))

    def _show_debug(self) -> None:
        records = recent_debug_records(count=40)
        if not records:
            self._update("DEBUG TRACES", "No debug traces recorded.")
            return
        parts: list[str] = []
        for record in records:
            kind = record.get("kind", "unknown")
            ts = record.get("ts", 0)
            stamp = ""
            if ts:
                from datetime import datetime

                stamp = datetime.fromtimestamp(ts).strftime("%H:%M:%S ")
            if "raw" in record:
                parts.append(f"{stamp}{record['raw']}")
                continue
            body = {k: v for k, v in record.items() if k not in {"ts", "kind"}}
            parts.append(f"{stamp}[{kind}]\n{json.dumps(body, indent=2, default=str)}")
        self._update("DEBUG TRACES", "\n\n".join(parts))

    def _update(self, title: str, content: str) -> None:
        title_widget = self.query_one("#debug-title", Static)
        title_widget.update(Text(title, style="bold cyan"))
        self.query_one("#debug-content", Static).update(content)
