"""Measure local-model throughput through the gateway."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .http import client_for

DEFAULT_MODELS = ("local-chat", "local-code", "local-agent")

DEFAULT_PROMPT = (
    "Explain in detail how a TCP connection is established and torn down, "
    "including the handshake flags and the purpose of each step."
)


@dataclass(frozen=True)
class BenchResult:
    alias: str
    ok: bool
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    detail: str = ""

    @property
    def tokens_per_second(self) -> float:
        return self.completion_tokens / self.seconds if self.seconds > 0 else 0.0


def bench_alias(
    base_url: str,
    alias: str,
    prompt: str,
    max_tokens: int = 64,
    timeout: float = 600.0,
    transport: httpx.BaseTransport | None = None,
) -> BenchResult:
    """Run one completion and report tokens and wall time (first call may include load)."""
    base = base_url.rstrip("/")
    started = time.monotonic()
    try:
        with client_for(timeout=timeout, connect=3.0, transport=transport) as client:
            response = client.post(
                f"{base}/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": alias,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0,
                    "stream": False,
                },
            )
        elapsed = time.monotonic() - started
        if response.status_code != 200:
            return BenchResult(alias, False, 0, 0, elapsed, f"HTTP {response.status_code}")
        usage = response.json().get("usage", {})
        return BenchResult(
            alias,
            True,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
            elapsed,
        )
    except httpx.HTTPError as exc:
        return BenchResult(alias, False, 0, 0, time.monotonic() - started, exc.__class__.__name__)
