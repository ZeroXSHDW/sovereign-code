"""One snapshot of the local AI stack, shared by CLI and TUI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .cloud import cloud_enabled
from .config import Settings
from .gateway import GatewayStatus
from .gateway import check as check_gateway
from .models import ModelView, build_views, recommended_tag, sort_views
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
    # Ollama Cloud readiness is a machine setting, not a network probe; the
    # dashboard stays fast and `sovereign cloud --probe` does the live check.
    cloud_enabled: bool = False
    router_up: bool = False
    code_selection: Selection | None = None
    chat_selection: Selection | None = None
    error: str = ""

    def _unique(self, predicate: Any) -> list[ModelView]:
        """Views matching `predicate`, de-duplicated by object identity.

        build_views registers both `foo` and `foo:latest` as aliases for the
        *same* ModelView, so a naive `views.values()` yields every aliased model
        twice — which double-counted resident memory and duplicated dashboard
        rows.
        """
        seen: set[int] = set()
        found: list[ModelView] = []
        for view in self.views.values():
            if not predicate(view) or id(view) in seen:
                continue
            seen.add(id(view))
            found.append(view)
        return found

    @property
    def loaded(self) -> list[ModelView]:
        return self._unique(lambda view: view.loaded)

    @property
    def installed(self) -> list[ModelView]:
        return self._unique(lambda view: view.installed)

    @property
    def sorted_models(self) -> list[ModelView]:
        return sort_views(self.installed)

    @property
    def all_models(self) -> list[ModelView]:
        """Every known model (installed, loaded or missing), de-aliased."""
        return sort_views(self._unique(lambda view: True))

    @property
    def potential_free_gb(self) -> float | None:
        """Free RAM after evicting current residents (the one-model policy).

        `None` means the memory counters could not be read. That is not the
        same as "0 GB free": the router treats a real zero as a signal to
        shrink the context window to its floor, so an unreadable counter must
        not be allowed to shrink every model to 2k.
        """
        if not self.memory.known:
            return None
        resident_gb = sum(view.vram_gb or view.size_gb for view in self.loaded)
        return round(self.memory.free_gb + resident_gb, 1)

    @property
    def best_coder(self) -> ModelView | None:
        return self.code_selection.model if self.code_selection else None

    @property
    def recommended_coder(self) -> ModelView | None:
        """The coder to download, i.e. the catalog's recommended model.

        Not the router's strongest pick: the router ranks by capability, while
        this is the model that fits a 24 GB Mac with room to spare, which is
        what "pull the recommended coder" means.
        """
        return self.views.get(recommended_tag())

    def model(self, tag: str | None) -> ModelView | None:
        return self.views.get(tag) if tag else None


async def _safe(coro: Any) -> Any:
    try:
        return await coro
    except Exception as exc:  # network/model errors must never kill the dashboard
        return exc


def _host_port(url: str, default_port: int) -> tuple[str, int]:
    """Split a service URL into (host, port).

    The probes used to hardcode 11434 and 4000, so a user who moved Ollama to
    another port was told the stack was down.
    """
    text = url if "://" in url else f"http://{url}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return ("127.0.0.1", default_port)
    return (parts.hostname or "127.0.0.1", parts.port or default_port)


async def collect(settings: Settings) -> Snapshot:
    client = OllamaClient(settings.ollama_url)
    snapshot = Snapshot(settings=settings)
    snapshot.memory = read_memory()
    snapshot.disk_free_gb = disk_free_gb()
    snapshot.login_installed = login_agent_installed()
    snapshot.login_loaded = login_agent_loaded()
    snapshot.cloud_enabled = cloud_enabled()
    snapshot.ollama_port = port_open(*_host_port(settings.ollama_url, 11434))
    snapshot.gateway_port = port_open(*_host_port(settings.gateway_url, 4000))
    snapshot.router_up = port_open(*_host_port(settings.router_url, 4010))
    snapshot.loopback = is_loopback(settings.ollama_url) and is_loopback(settings.gateway_url)

    version, tags, ps, gateway = await asyncio.gather(
        _safe(client.version()),
        _safe(client.tags()),
        _safe(client.ps()),
        _safe(check_gateway(settings.gateway_url)),
    )
    problems: list[str] = []
    if isinstance(version, Exception):
        problems.append(f"ollama: {version}")
    else:
        snapshot.version = str(version)
        snapshot.ollama_up = True
    if isinstance(tags, Exception):
        problems.append(f"model list: {tags}")
        tags = None
    if isinstance(ps, Exception):
        problems.append(f"resident models: {ps}")
        ps = None
    if isinstance(gateway, GatewayStatus):
        snapshot.gateway = gateway
    else:
        problems.append(f"gateway: {gateway}")
    snapshot.error = "; ".join(problems)

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
