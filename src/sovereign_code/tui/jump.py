"""Unified fuzzy jump palette for the terminal views.

Ctrl+P already lists the app's actions. This provider adds the things the
stack actually knows about: installed models, saved chats, and the skill bank
(22k Markdown skills). Selecting a hit runs the matching app hook.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.command import DiscoveryHit, Hit, Provider

from ..config import SESSIONS_DIR
from ..sessions import scan_sessions, search_sessions
from ..skills import search_skills


@dataclass(frozen=True)
class _Jump:
    label: str
    category: str
    help: str
    command: Callable[[], Any]


class JumpProvider(Provider):
    """Search models, saved chats, and the skill bank from the command palette."""

    def __init__(self, screen: Any, match_style: Any = None) -> None:
        super().__init__(screen, match_style)
        self._cache: list[_Jump] | None = None
        self._session_paths: set[Path] = set()

    def _items(self) -> list[_Jump]:
        if self._cache is not None:
            return self._cache
        items: list[_Jump] = []
        snapshot = getattr(self.app, "snapshot", None)
        if snapshot is not None:
            for view in getattr(snapshot, "sorted_models", []):
                if not view.installed:
                    continue
                items.append(
                    _Jump(
                        label=f"model  {view.tag}",
                        category="model",
                        help=f"use {view.tag} · {view.spec.role} · {view.size_gb:.1f}G",
                        command=self._call("jump_select_model", view.tag),
                    )
                )
        if hasattr(self.app, "resume_session"):
            for info in scan_sessions()[:8]:
                self._session_paths.add(info.path)
                items.append(
                    _Jump(
                        label=f"chat  {info.path.stem}",
                        category="chat",
                        help=f"resume {info.model} · {info.messages} messages",
                        command=self._call("jump_resume_session", info.path),
                    )
                )
        self._cache = items
        return items

    def _call(self, name: str, *args: Any) -> Callable[[], Any]:
        def command() -> Any:
            method = getattr(self.app, name, None)
            if method is None:
                self.app.notify("That jump is not available in this view", timeout=2)
                return None
            return method(*args)

        return command

    def _display(self, category: str, label: str) -> Text:
        text = Text()
        text.append(category, style="bold cyan")
        text.append("  ")
        text.append(label)
        return text

    async def discover(self) -> AsyncIterator[DiscoveryHit]:
        for item in self._items()[:12]:
            yield DiscoveryHit(
                self._display(item.category, item.label.split("  ", 1)[-1]),
                item.command,
                text=item.label,
                help=item.help,
            )

    async def search(self, query: str) -> AsyncIterator[Hit]:
        matcher = self.matcher(query)
        for item in self._items():
            score = matcher.match(item.label)
            if score:
                yield Hit(
                    score,
                    self._display(item.category, item.label.split("  ", 1)[-1]),
                    item.command,
                    text=item.label,
                    help=item.help,
                )
        terms = query.strip()
        if len(terms) < 2:
            return
        try:
            results = await asyncio.to_thread(search_skills, terms, 10)
        except Exception:  # a missing or unreadable bank must not break the palette
            results = []
        for name, description in results:
            yield Hit(
                0.6,
                self._display("skill", name),
                self._call("jump_skill", name),
                text=f"skill {name}",
                help=description or "run this skill",
            )
        if len(terms) < 3 or not hasattr(self.app, "resume_session"):
            return
        try:
            matches = await asyncio.to_thread(search_sessions, terms)
        except Exception:  # a missing sessions folder must not break the palette
            matches = []
        shown = 0
        for match in matches:
            path = SESSIONS_DIR / str(match.get("path") or "")
            if not path.name or path in self._session_paths:
                continue
            snippet = " ".join(str(match.get("snippet") or "").split())[:110]
            if not snippet:
                continue
            yield Hit(
                0.5,
                self._display("match", snippet),
                self._call("jump_resume_session", path),
                text=f"chat match {snippet}",
                help=f"{match.get('role') or 'message'} · {path.name}",
            )
            shown += 1
            if shown >= 8:
                break


__all__ = ["JumpProvider"]
