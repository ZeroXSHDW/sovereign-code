"""Local inference backends: Ollama, the LiteLLM gateway, Jan, LM Studio, llama.cpp, MLX.

MLX is Apple's framework for running models on Apple Silicon. An
``mlx-lm`` server (``pip install mlx mlx-lm``) serves an OpenAI-compatible
``/v1`` API on loopback, so it plugs into the same probe path as every other
backend.

All of them speak the OpenAI-compatible ``/v1`` API, so any can serve a
specialist request. This module only probes and lists; routing stays in
``domains`` and ``summarize.complete``.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

from .config import Settings
from .http import shared_client


def _mlx_url() -> str:
    return os.environ.get("SOVEREIGN_MLX_URL", "http://127.0.0.1:8081").rstrip("/")


@dataclass(frozen=True)
class Backend:
    key: str
    name: str
    url: str


@dataclass(frozen=True)
class BackendStatus:
    backend: Backend
    online: bool
    models: tuple[str, ...]


def known_backends(settings: Settings) -> list[Backend]:
    return [
        Backend("gateway", "LiteLLM gateway", settings.gateway_url.rstrip("/")),
        Backend("ollama", "Ollama", settings.ollama_url.rstrip("/")),
        Backend("jan", "Jan", "http://127.0.0.1:1337"),
        Backend("lmstudio", "LM Studio", "http://127.0.0.1:1234"),
        Backend("llamacpp", "llama.cpp server", "http://127.0.0.1:8080"),
        Backend("mlx", "MLX", _mlx_url()),
    ]


def probe(backend: Backend, timeout: float = 1.5) -> BackendStatus:
    """List models via the OpenAI-compatible endpoint (Ollama also supports it)."""
    try:
        response = shared_client().get(
            f"{backend.url}/v1/models",
            headers={"Authorization": "Bearer local"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json().get("data") or []
    except httpx.HTTPError:
        return BackendStatus(backend, False, ())
    except (ValueError, AttributeError):
        # The server answered, but not with a model list. It is up, but it is
        # not an OpenAI-compatible backend.
        return BackendStatus(backend, False, ())
    names = tuple(str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id"))
    return BackendStatus(backend, True, names)


def probe_all(settings: Settings, timeout: float = 1.5) -> list[BackendStatus]:
    return [probe(backend, timeout) for backend in known_backends(settings)]


def resolve(settings: Settings, key: str) -> Backend | None:
    return next((b for b in known_backends(settings) if b.key == key), None)


def wait_online(backend: Backend, *, timeout: float = 30.0, interval: float = 1.0) -> BackendStatus:
    """Poll ``/v1/models`` until the backend answers or the timeout elapses.

    Returns the first online status, or the last offline status on timeout.
    Useful after launching ``mlx-lm`` so a `sovereign run` doesn't race a
    server that is still loading weights.
    """
    deadline = time.monotonic() + max(1.0, timeout)
    last = BackendStatus(backend, False, ())
    while time.monotonic() < deadline:
        last = probe(backend)
        if last.online:
            return last
        time.sleep(interval)
    return last
