"""Review and apply the file writes a model proposed.

The single-shot editing path (`direct.py`) writes blocks immediately. In the
interactive console the writes are staged here first: the user sees a unified
diff per file, and nothing touches disk until they press *apply*. Existing
files are copied into a timestamped backup folder before they are replaced.
"""

from __future__ import annotations

import difflib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from ..config import DATA_DIR
from ..direct import FileWrite, apply_writes, resolve_target


class PatchReview(ModalScreen[dict[str, Any] | None]):
    """A diff of each proposed file, with apply and cancel actions."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("a", "apply", "Apply"),
        Binding("r,escape", "cancel", "Cancel"),
    ]

    def __init__(self, root: Path, writes: list[FileWrite]) -> None:
        super().__init__()
        self.root = root.resolve()
        self.writes = writes
        self.valid_writes: list[FileWrite] = []
        self.rejected: list[str] = []
        self._diffs: list[list[str]] = []
        for write in writes:
            target = resolve_target(self.root, write.path)
            if target is None:
                self.rejected.append(write.path)
                continue
            old = ""
            if target.is_file():
                try:
                    old = target.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    old = ""
            diff = list(
                difflib.unified_diff(
                    old.splitlines(),
                    write.content.splitlines(),
                    fromfile=f"a/{write.path}",
                    tofile=f"b/{write.path}",
                    lineterm="",
                )
            )
            self.valid_writes.append(write)
            self._diffs.append(diff)

    def compose(self) -> ComposeResult:
        with Vertical(id="patch-dialog"):
            yield Static("PROPOSED CHANGES", classes="section-title")
            yield Static("", id="patch-summary")
            yield DataTable(id="patch-table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="patch-preview"):
                yield Static("", id="patch-body")
            yield Static("a apply · r / esc cancel", id="patch-hint", classes="hint")

    def on_mount(self) -> None:
        added = sum(self._counts(index)[0] for index in range(len(self._diffs)))
        removed = sum(self._counts(index)[1] for index in range(len(self._diffs)))
        summary = f"{len(self.valid_writes)} file(s) · +{added} / -{removed}"
        if self.rejected:
            summary += f" · {len(self.rejected)} refused (outside the project)"
        self.query_one("#patch-summary", Static).update(summary)

        table = self.query_one("#patch-table", DataTable)
        table.add_column("FILE", width=28)
        table.add_column("+", width=4)
        table.add_column("-", width=4)
        for index, write in enumerate(self.valid_writes):
            add, remove = self._counts(index)
            table.add_row(write.path, str(add), str(remove))
        if self.valid_writes:
            table.focus()
            table.move_cursor(row=0)
            self._show_preview(0)
        else:
            self._set_body(Text("No applicable changes.\n", style="dim"))

    def _counts(self, index: int) -> tuple[int, int]:
        added = removed = 0
        for line in self._diffs[index]:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return added, removed

    def _set_body(self, content: Text) -> None:
        self.query_one("#patch-body", Static).update(content)

    def _show_preview(self, index: int) -> None:
        text = Text()
        for line in self._diffs[index]:
            if line.startswith("+") and not line.startswith("+++"):
                style = "green"
            elif line.startswith("-") and not line.startswith("---"):
                style = "red"
            elif line.startswith("@@"):
                style = "cyan"
            else:
                style = "dim"
            text.append(line + "\n", style=style)
        self._set_body(text if text.plain else Text("(new empty file)", style="dim"))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._show_preview(event.cursor_row)

    def _backup(self) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = DATA_DIR / "backups" / "patches" / stamp
        copied = False
        for write in self.valid_writes:
            target = resolve_target(self.root, write.path)
            if target is None or not target.is_file():
                continue
            try:
                relative = target.relative_to(self.root)
            except ValueError:
                continue
            backup = destination / relative
            try:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            except OSError:
                continue
            copied = True
        return destination if copied else None

    def action_apply(self) -> None:
        if not self.valid_writes:
            self.dismiss(None)
            return
        backup = self._backup()
        written, rejected = apply_writes(self.root, self.valid_writes)
        self.dismiss(
            {
                "written": written,
                "rejected": rejected,
                "backup": str(backup) if backup else None,
                "discarded": [write.path for write in self.valid_writes if write.path in rejected],
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["PatchReview"]
