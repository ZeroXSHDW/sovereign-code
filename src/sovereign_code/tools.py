"""Read what each connected tool will actually use.

"Strongest first" only means something if it can be checked. These parsers read
the live configs (gateway, OpenCode, Qwen Code, Continue) so `sovereign best`
reports the effective model instead of what we hoped was configured.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_BLOCK = re.compile(
    r"- model_name:\s*[\"']?([^\"'\s]+)[\"']?(.*?)(?=\n\s*-\s*model_name:|\Z)", re.S
)
_OLLAMA_TARGET = re.compile(r"model:\s*[\"']?ollama/([^\"'\s]+)")


def gateway_models(text: str) -> dict[str, str]:
    """alias -> ollama tag, from a LiteLLM model_list."""
    mapping: dict[str, str] = {}
    for match in _BLOCK.finditer(text):
        alias, body = match.group(1), match.group(2)
        target = _OLLAMA_TARGET.search(body)
        if target:
            mapping[alias] = target.group(1)
    return mapping


def opencode_default(text: str) -> str:
    """The model OpenCode opens with, without the provider prefix."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    model = str(data.get("model") or "")
    return model.split("/", 1)[1] if "/" in model else model


def qwen_default(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    model = data.get("model") or {}
    return str(model.get("name") or "") if isinstance(model, dict) else ""


def continue_default(text: str) -> str:
    """First `model:` under `models:` — Continue uses the first chat model."""
    in_models = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("models:"):
            in_models = True
            continue
        if in_models and line.startswith("context:"):
            break
        if in_models and line.startswith("model:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def opencode_models(text: str) -> list[str]:
    """Model ids declared in OpenCode's ollama provider."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    provider = (data.get("provider") or {}).get("ollama") or {}
    return [str(name) for name in (provider.get("models") or {})]


def qwen_models(text: str) -> list[str]:
    """Model ids registered in Qwen Code's settings."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    entries = (data.get("modelProviders") or {}).get("openai") or []
    return [str(entry.get("id")) for entry in entries if entry.get("id")]


def continue_models(text: str) -> list[str]:
    """Every `model:` listed under Continue's `models:` block."""
    found: list[str] = []
    in_models = False
    for raw in text.splitlines():
        # Handle both `    model: x` (provider entries) and `- model: x`.
        line = raw.strip().lstrip("-").strip()
        if line.startswith("models:"):
            in_models = True
            continue
        if in_models and line.startswith("context:"):
            break
        if in_models and line.startswith("model:"):
            found.append(line.split(":", 1)[1].strip().strip("\"'"))
    return found


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def codex_logged_in(home: Path | None = None) -> bool:
    return ((home or Path.home()) / ".codex" / "auth.json").is_file()
