"""LiteLLM gateway probe (OpenAI-compatible, loopback)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from .http import async_client

_ALIAS_ENTRY = re.compile(
    r"^[ \t]*-[ \t]*model_name:[ \t]*[\"']?([^\"'\s#]+)[\"']?[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
_OLLAMA_TARGET = re.compile(
    r"^[ \t]*(?:-[ \t]*)?model:[ \t]*[\"']?ollama/([^\"'\s#]+)", re.MULTILINE
)


@dataclass(frozen=True)
class AliasEntry:
    """One `model_list` entry: the alias clients ask for and the model behind it."""

    alias: str
    target: str


def parse_aliases(text: str) -> list[AliasEntry]:
    """Parse a LiteLLM `model_list` into alias/target pairs, in file order.

    One parser for the whole project. Three modules used to read the same
    file with three different regexes, so an edit to the gateway config could
    be accepted by one and silently ignored by another — the symptom was
    `sovereign verify` reporting an alias that `sovereign gateway-aliases`
    did not know about.
    """
    entries: list[AliasEntry] = []
    matches = list(_ALIAS_ENTRY.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        target = _OLLAMA_TARGET.search(body)
        entries.append(AliasEntry(match.group(1), target.group(1) if target else ""))
    return entries


def alias_names(text: str) -> tuple[str, ...]:
    """Alias names declared in the config, in file order."""
    return tuple(entry.alias for entry in parse_aliases(text))


def alias_targets(text: str) -> dict[str, str]:
    """alias -> ollama tag, for the aliases that point at a local model."""
    return {entry.alias: entry.target for entry in parse_aliases(text) if entry.target}


@dataclass
class GatewayStatus:
    up: bool = False
    models: list[str] = field(default_factory=list)
    detail: str = ""


async def check(url: str = "http://127.0.0.1:4000", timeout: float = 3.0) -> GatewayStatus:
    base = url.rstrip("/")
    try:
        client = async_client(f"gateway:{base}", timeout=timeout, connect=1.5)
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
