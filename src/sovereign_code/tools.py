"""Read what each connected tool will actually use.

"Strongest first" only means something if it can be checked. These parsers read
the live configs (gateway, OpenCode, Qwen Code, Continue) so `sovereign best`
reports the effective model instead of what we hoped was configured.
"""

from __future__ import annotations

import json
from pathlib import Path

from .gateway import alias_targets


def gateway_models(text: str) -> dict[str, str]:
    """alias -> ollama tag, from a LiteLLM model_list."""
    return alias_targets(text)


def opencode_default(text: str) -> str:
    """The model OpenCode opens with, without the provider prefix."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    model = str(data.get("model") or "")
    return model.split("/", 1)[1] if "/" in model else model


def qwen_default(text: str) -> str:
    """The model Qwen Code opens with.

    Qwen writes the default either as an object (`{"model": {"name": ...}}`)
    or as a plain string, and only the object form used to be read.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    model = data.get("model")
    if isinstance(model, dict):
        return str(model.get("name") or "")
    if isinstance(model, str):
        return model
    return ""


def _continue_models(text: str) -> list[str]:
    """Model ids listed under Continue's `models:` block.

    A `context:` key belongs to the model that precedes it, so it ends that
    entry — it does not end the block. Stopping there dropped every model
    after the first one.
    """
    found: list[str] = []
    in_models = False
    base_indent = 0
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if not in_models:
            if stripped.startswith("models:"):
                in_models = True
                base_indent = indent
            continue
        if indent <= base_indent:
            break  # a new top-level key ends the models block
        entry = stripped.lstrip("-").strip()
        if entry.startswith("model:"):
            found.append(entry.split(":", 1)[1].strip().strip("\"'"))
    return found


def continue_default(text: str) -> str:
    """First `model:` under `models:` — Continue uses the first chat model."""
    models = _continue_models(text)
    return models[0] if models else ""


def opencode_models(text: str) -> list[str]:
    """Model ids declared by any OpenCode provider.

    The old parser only read the built-in `ollama` provider; OpenCode's native
    Ollama integration streams tool calls as text, so the working config uses a
    custom OpenAI-compatible provider named `local`. Reading every provider also
    keeps cloud/provider blocks visible to `doctor` and `prune`.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return []
    found: list[str] = []
    providers = data.get("provider") or {}
    for key in ("local", "ollama", "sovereign"):
        provider = providers.get(key)
        if not isinstance(provider, dict):
            continue
        found.extend(str(name) for name in (provider.get("models") or {}))
    return found


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
    return _continue_models(text)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def codex_logged_in(home: Path | None = None) -> bool:
    return ((home or Path.home()) / ".codex" / "auth.json").is_file()
