"""Local inference backends: Ollama, the LiteLLM gateway, Jan, LM Studio, llama.cpp.

All of them speak the OpenAI-compatible ``/v1`` API, so any can serve a
specialist request. This module only probes and lists; routing stays in
``domains`` and ``summarize.complete``.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Settings


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
    ]


def probe(backend: Backend, timeout: float = 1.5) -> BackendStatus:
    """List models via the OpenAI-compatible endpoint (Ollama also supports it)."""
    try:
        response = httpx.get(
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
