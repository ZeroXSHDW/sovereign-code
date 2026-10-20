"""LiteLLM gateway probe (OpenAI-compatible, loopback)."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx


@dataclass
class GatewayStatus:
    up: bool = False
    models: list[str] = field(default_factory=list)
    detail: str = ""


async def check(url: str = "http://127.0.0.1:4000", timeout: float = 3.0) -> GatewayStatus:
    base = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=1.5)) as client:
            response = await client.get(f"{base}/v1/models")
            if response.status_code == 200:
                try:
                    payload = response.json()
                    models = [str(item.get("id")) for item in payload.get("data", []) if item.get("id")]
                except ValueError:
                    models = []
                return GatewayStatus(True, models, "OpenAI-compatible endpoint is up")
            return GatewayStatus(False, [], f"HTTP {response.status_code}")
    except httpx.HTTPError as exc:
        return GatewayStatus(False, [], f"gateway unreachable: {exc.__class__.__name__}")
