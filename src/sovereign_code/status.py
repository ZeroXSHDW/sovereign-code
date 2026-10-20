"""One snapshot of the local AI stack, shared by CLI and TUI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .gateway import GatewayStatus
from .gateway import check as check_gateway
from .models import ModelView, build_views, sort_views
from .ollama import OllamaClient
from .router import Selection, Task, choose
from .system import (
    Memory,
    disk_free_gb,
    is_loopback,
    login_agent_installed,
    login_agent_loaded,
    port_open,
    read_memory,
)


@dataclass
class Snapshot:
    settings: Settings
    ollama_up: bool = False
    version: str = "offline"
    views: dict[str, ModelView] = field(default_factory=dict)
    gateway: GatewayStatus = field(default_factory=GatewayStatus)
    memory: Memory = field(default_factory=lambda: Memory(0.0, 0.0, 0.0))
    disk_free_gb: float = 0.0
    ollama_port: bool = False
    gateway_port: bool = False
    loopback: bool = True
    login_installed: bool = False
    login_loaded: bool = False
    code_selection: Selection | None = None
    chat_selection: Selection | None = None
    error: str = ""

    @property
    def loaded(self) -> list[ModelView]:
        return [v for v in self.views.values() if v.loaded]

    @property
    def installed(self) -> list[ModelView]:
        return [v for v in self.views.values() if v.installed]

    @property
    def sorted_models(self) -> list[ModelView]:
        return sort_views(self.views.values())

    @property
    def potential_free_gb(self) -> float:
        """Free RAM after evicting current residents (the one-model policy)."""
        return round(self.memory.free_gb + sum(v.size_gb for v in self.loaded), 1)

    @property
    def best_coder(self) -> ModelView | None:
        return self.code_selection.model if self.code_selection else None

    @property
    def recommended_coder(self) -> ModelView | None:
        return self.views.get("qwen2.5-coder:14b")

    def model(self, tag: str | None) -> ModelView | None:
        return self.views.get(tag) if tag else None


async def _safe(coro: Any) -> Any:
    try:
        return await coro
    except Exception as exc:  # network/model errors must never kill the dashboard
        return exc


async def collect(settings: Settings) -> Snapshot:
    client = OllamaClient(settings.ollama_url)
    snapshot = Snapshot(settings=settings)
    snapshot.memory = read_memory()
    snapshot.disk_free_gb = disk_free_gb()
    snapshot.login_installed = login_agent_installed()
    snapshot.login_loaded = login_agent_loaded()
    snapshot.ollama_port = port_open("127.0.0.1", 11434)
    snapshot.gateway_port = port_open("127.0.0.1", 4000)
    snapshot.loopback = is_loopback(settings.ollama_url) and is_loopback(settings.gateway_url)

    version, tags, ps, gateway = await asyncio.gather(
        _safe(client.version()),
        _safe(client.tags()),
        _safe(client.ps()),
        _safe(check_gateway(settings.gateway_url)),
    )
    if isinstance(version, Exception):
        snapshot.error = str(version)
    else:
        snapshot.version = str(version)
        snapshot.ollama_up = True
    if isinstance(tags, Exception):
        tags = None
    if isinstance(ps, Exception):
        ps = None
    if isinstance(gateway, GatewayStatus):
        snapshot.gateway = gateway

    snapshot.views = build_views(tags, ps, include_missing=True)
    snapshot.code_selection = choose(
        Task.CODE,
        snapshot.views,
        snapshot.potential_free_gb,
        max_context=settings.max_context,
    )
    snapshot.chat_selection = choose(
        Task.CHAT,
        snapshot.views,
        snapshot.potential_free_gb,
        max_context=settings.max_context,
    )
    return snapshot
