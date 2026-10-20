"""End-to-end checks against the local OpenAI-compatible gateway."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

CORE_ALIASES = ("local-chat", "local-code", "local-agent", "local-claude")

EXPECTED_ALIASES = (
    "local-chat",
    "local-thinking",
    "local-code",
    "local-claude",
    "local-agent",
    "local-browser-nav",
    "local-reasoning",
    "local-vision",
    "local-vision-deep",
)

PROMPT = "Reply with exactly: OK"

# Reasoning models spend the budget on hidden thinking before emitting content.
TOKEN_BUDGETS = {"local-thinking": 512}
DEFAULT_BUDGET = 8


@dataclass(frozen=True)
class AliasResult:
    alias: str
    ok: bool
    seconds: float
    detail: str


def probe_alias(
    base_url: str,
    alias: str,
    timeout: float = 120.0,
    transport: httpx.BaseTransport | None = None,
) -> AliasResult:
    """Send a tiny completion and require a non-empty reply."""
    base = base_url.rstrip("/")
    budget = TOKEN_BUDGETS.get(alias, DEFAULT_BUDGET)
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=3.0), transport=transport
        ) as client:
            response = client.post(
                f"{base}/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": alias,
                    "messages": [{"role": "user", "content": PROMPT}],
                    "max_tokens": budget,
                    "temperature": 0,
                    "stream": False,
                },
            )
        elapsed = time.monotonic() - started
        if response.status_code != 200:
            return AliasResult(alias, False, elapsed, f"HTTP {response.status_code}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            return AliasResult(alias, False, elapsed, "malformed response")
        text = content.strip()
        if not text:
            return AliasResult(alias, False, elapsed, "empty reply")
        return AliasResult(alias, True, elapsed, text[:40])
    except httpx.HTTPError as exc:
        return AliasResult(
            alias, False, time.monotonic() - started, f"{exc.__class__.__name__}"
        )


def probe_aliases(
    base_url: str,
    aliases: tuple[str, ...] = CORE_ALIASES,
    timeout: float = 120.0,
    transport: httpx.BaseTransport | None = None,
) -> list[AliasResult]:
    return [probe_alias(base_url, alias, timeout, transport) for alias in aliases]
