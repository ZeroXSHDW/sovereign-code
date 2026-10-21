"""Async Ollama API client (loopback only)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


class OllamaError(RuntimeError):
    pass


PRELOAD_TIMEOUT = 900.0
"""Budget for a cold model load, in seconds."""


@dataclass
class ChatChunk:
    content: str = ""
    thinking: str = ""
    done: bool = False
    model: str = ""
    eval_count: int = 0
    prompt_eval_count: int = 0
    total_duration_ns: int = 0


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 180.0,
        connect_timeout: float = 3.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.connect_timeout = connect_timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> dict:
        """Send one request and return the decoded body.

        `timeout` defaults to the client timeout. The connect phase is kept
        short so a dead Ollama is reported quickly, but the read phase must
        honour the full budget: loading a 19 GB model from disk takes far
        longer than a health probe and would otherwise be cut off mid-load.
        """
        budget = self.timeout if timeout is None else timeout
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(budget, connect=self.connect_timeout),
                transport=transport,
            ) as client:
                response = await client.request(method, self._url(path), json=payload)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama unreachable at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            from .cloud import ollama_error_hint

            raise OllamaError(
                ollama_error_hint(
                    f"Ollama {path} returned {response.status_code}: {response.text[:300]}"
                )
            )
        try:
            return response.json()
        except ValueError as exc:
            raise OllamaError(f"Ollama returned invalid JSON for {path}") from exc

    async def version(self) -> str:
        data = await self._request("GET", "/api/version")
        return str(data.get("version", "unknown"))

    async def tags(self) -> dict[str, Any]:
        return await self._request("GET", "/api/tags")

    async def ps(self) -> dict[str, Any]:
        return await self._request("GET", "/api/ps")

    async def show(self, model: str) -> dict[str, Any]:
        return await self._request("POST", "/api/show", {"model": model})

    async def preload(
        self,
        model: str,
        context: int = 16384,
        keep_alive: str = "15m",
        transport: httpx.BaseTransport | None = None,
    ) -> dict[str, Any]:
        """Load a model into memory without asking it to do anything.

        The first request after 15 minutes idle pays a multi-second cold load,
        which users read as "slow". Warming it up front moves that cost out of
        the way of the first real prompt.

        A cold load reads the whole weight file from disk, so this call gets a
        generous budget of its own; cutting it short would abort the load
        server-side while the client reports failure.
        """
        return await self._request(
            "POST",
            "/api/generate",
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"num_ctx": int(context)},
            },
            timeout=max(self.timeout, PRELOAD_TIMEOUT),
            transport=transport,
        )

    async def unload(self, model: str) -> None:
        """Ask the server to evict a resident model immediately."""
        await self._request(
            "POST",
            "/api/generate",
            {"model": model, "prompt": "", "stream": False, "keep_alive": 0},
        )

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        context: int = 16384,
        temperature: float = 0.25,
        think: bool | None = None,
        keep_alive: str = "15m",
        transport: httpx.BaseTransport | None = None,
    ) -> AsyncIterator[ChatChunk]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": keep_alive,
            "options": {
                "num_ctx": int(context),
                "temperature": float(temperature),
            },
        }
        if think is not None:
            payload["think"] = bool(think)

        timeout = httpx.Timeout(self.timeout, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                async with client.stream("POST", self._url("/api/chat"), json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        from .cloud import ollama_error_hint

                        raise OllamaError(
                            ollama_error_hint(
                                f"Ollama chat returned {response.status_code}: {body[:300]}"
                            )
                        )
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if "error" in data:
                            raise OllamaError(str(data["error"]))
                        message = data.get("message") or {}
                        yield ChatChunk(
                            content=message.get("content") or "",
                            thinking=message.get("thinking") or "",
                            done=bool(data.get("done")),
                            model=data.get("model", model),
                            eval_count=int(data.get("eval_count") or 0),
                            prompt_eval_count=int(data.get("prompt_eval_count") or 0),
                            total_duration_ns=int(data.get("total_duration") or 0),
                        )
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama stream failed: {exc}") from exc

    async def pull(
        self, model: str, transport: httpx.BaseTransport | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a model download.

        Ollama answers `/api/pull` with HTTP 200 and then reports failures as
        an `error` object inside the stream, so the error has to be read out of
        the events: without that a refused or full disk is indistinguishable
        from a finished download.
        """
        payload = {"model": model, "stream": True}
        timeout = httpx.Timeout(None, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                async with client.stream("POST", self._url("/api/pull"), json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        from .cloud import ollama_error_hint

                        raise OllamaError(
                            ollama_error_hint(
                                f"pull failed ({response.status_code}): {body[:300]}"
                            )
                        )
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if "error" in data:
                            raise OllamaError(str(data["error"]))
                        yield data
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama pull failed: {exc}") from exc
