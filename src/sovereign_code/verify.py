"""End-to-end checks against the local OpenAI-compatible gateway."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .gateway import alias_names

CORE_ALIASES = ("local-chat", "local-code", "local-agent", "local-claude")


def configured_aliases(config_path: Path) -> tuple[str, ...]:
    """Alias names declared in a LiteLLM config, in file order.

    Reading the config beats a hard-coded list: aliases added by hand (or by
    another tool) stay verifiable, and removed ones stop being probed. The
    `openai/*` passthrough is skipped — it has no local model behind it.
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    return tuple(name for name in alias_names(text) if not name.startswith("openai/"))


EXPECTED_ALIASES = (
    "local-chat",
    "local-thinking",
    "local-code",
    "local-claude",
    "local-agent",
    "local-browser-nav",
    "local-reasoning",
    "local-reasoning-deep",
    "local-vision",
    "local-vision-deep",
)

PROMPT = "Reply with exactly: OK"

# Reasoning models spend the budget on hidden thinking before emitting content.
# Probing them with the default 8-token budget returned an empty body and
# reported a healthy alias as broken.
TOKEN_BUDGETS = {
    "local-thinking": 512,
    "local-reasoning": 512,
    "local-reasoning-deep": 512,
    "local-vision-deep": 256,
}
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
        return AliasResult(alias, False, time.monotonic() - started, f"{exc.__class__.__name__}")


def check_embedding(
    ollama_url: str,
    model: str = "nomic-embed-text",
    timeout: float = 60.0,
    transport: httpx.BaseTransport | None = None,
) -> tuple[bool, str]:
    """Confirm the embedding endpoint returns a real vector."""
    base = ollama_url.rstrip("/")
    if not base.startswith("http"):
        base = f"http://{base}"
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=3.0), transport=transport
        ) as client:
            response = client.post(f"{base}/api/embed", json={"model": model, "input": ["ok"]})
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"
        dimension = len(response.json()["embeddings"][0])
        return dimension > 0, f"{model} · {dimension}-dim"
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        return False, exc.__class__.__name__


def probe_aliases(
    base_url: str,
    aliases: tuple[str, ...] = CORE_ALIASES,
    timeout: float = 120.0,
    transport: httpx.BaseTransport | None = None,
) -> list[AliasResult]:
    return [probe_alias(base_url, alias, timeout, transport) for alias in aliases]


@dataclass
class LivenessResult:
    ok: bool
    detail: str


def probe_liveness(
    base_url: str,
    model: str = "nomic-embed-text",
    timeout: float = 5.0,
    transport: httpx.BaseTransport | None = None,
) -> LivenessResult:
    """Prove the server can actually *serve*, not just answer /api/version.

    When a model load cannot fit the GPU budget, Ollama stops progressing while
    /api/version and /api/ps still return 200. Every later request queues behind
    the stuck one, so the stack looks "up" but is unusable. A tiny embedding
    request exercises the scheduler and detects that state.
    """
    base = base_url.rstrip("/")
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=3.0), transport=transport
        ) as client:
            response = client.post(f"{base}/api/embed", json={"model": model, "input": "ping"})
    except httpx.HTTPError as exc:
        return LivenessResult(False, f"no response in {timeout:.0f}s ({type(exc).__name__})")
    elapsed = time.monotonic() - started
    if response.status_code >= 400:
        return LivenessResult(False, f"HTTP {response.status_code}")
    # A 200 that carries an error body is not a served request: a stuck load
    # answers with HTTP 200 and an error payload, which a status-only check
    # would have reported as a healthy stack.
    try:
        payload = response.json()
    except ValueError:
        return LivenessResult(False, "malformed response")
    if isinstance(payload, dict) and payload.get("error"):
        return LivenessResult(False, f"error: {str(payload['error'])[:120]}")
    return LivenessResult(True, f"served in {elapsed * 1000:.0f} ms")
