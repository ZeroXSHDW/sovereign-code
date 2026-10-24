"""Select and wire a model into the local coding clients.

``sovereign model use <tag>`` makes an installed model the current one for
OpenCode, Codex (ChatGPT), and Claude Code by writing each client's own model
field. This is the glue that turns "pulled a specialist model" into "it is
what the client actually uses" without hand-editing configs.

The clients already route by model name through the tier gateway (any installed
tag is served exactly), so this module only writes the client-side selection —
it never changes routing, cloud behaviour, or the local-only default.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .clients import codex_home_path, write_codex_catalog
from .config import Settings
from .tier_gateway import installed_models

CLIENTS = ("opencode", "codex", "claude")


def opencode_model_path() -> Path:
    """The OpenCode config whose ``model`` field selects the default."""
    return Path.home() / ".config" / "opencode" / "opencode.json"


def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def set_opencode_model(tag: str, path: Path | None = None) -> Path:
    """Point OpenCode's default model at ``tag`` via the right provider.

    A real model tag is served by Ollama (`local/<tag>`); a domain key such as
    ``legal`` is only understood by the tier gateway (`sovereign/<key>`), which
    routes it to that specialist's model.
    """
    from .domains import DOMAINS

    provider = "sovereign" if tag in DOMAINS else "local"
    target = path or opencode_model_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["model"] = f"{provider}/{tag}"
    return _write_json(target, data)


def set_codex_model(tag: str, settings: Settings | None = None) -> Path:
    """Point Codex's local profile at ``tag`` with the catalog's context window."""
    from .client_setup import CODEX_LOCAL_PROVIDER_ID
    from .models import CATALOG

    context = 32768
    spec = CATALOG.get(tag)
    if spec is not None and spec.max_context:
        context = spec.max_context
    # Regenerate the catalog so the profile's catalog file is fresh, then write
    # the profile with this model and its context window.
    catalog = write_codex_catalog()
    url = (settings or Settings.load()).router_url.rstrip("/")
    profile = (
        f'model = "{tag}"\n'
        f'model_provider = "{CODEX_LOCAL_PROVIDER_ID}"\n'
        f"model_context_window = {context}\n"
        f'model_catalog_json = "{catalog}"\n\n'
        f"[model_providers.{CODEX_LOCAL_PROVIDER_ID}]\n"
        f'name = "Sovereign tier gateway"\n'
        f'base_url = "{url}/v1"\n'
        'wire_api = "responses"\n'
        "supports_websockets = false\n\n"
        f"[model_providers.{CODEX_LOCAL_PROVIDER_ID}.auth]\n"
        'command = "/bin/echo"\n'
        'args = ["local"]\n'
    )
    home = codex_home_path()
    home.mkdir(parents=True, exist_ok=True)
    config = home / "config.toml"
    config.write_text(profile, encoding="utf-8")
    return config


def set_claude_model(tag: str, path: Path | None = None) -> Path:
    """Point Claude Code at ``tag`` through the bridge.

    The bridge passes an unrecognised name straight to the tier gateway, which
    serves any installed tag exactly, so setting ``ANTHROPIC_MODEL`` to the tag
    is enough — no new alias is required.
    """
    target = path or claude_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    env = data.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    env["ANTHROPIC_MODEL"] = tag
    # The picker slots default to Claude ids; point the default turn at the tag
    # without rewriting the fixed slots the bridge already maps.
    env["ANTHROPIC_SMALL_FAST_MODEL"] = tag
    return _write_json(target, data)


def model_use(tag: str, client: str, settings: Settings | None = None) -> dict[str, str]:
    """Wire ``tag`` into ``client`` (opencode/codex/claude/all).

    Returns ``{client: written-path}``. Raises ``ValueError`` for an unknown
    client. The caller is responsible for verifying the tag is installed first.
    """
    targets = CLIENTS if client == "all" else [client]
    if not all(name in CLIENTS for name in targets):
        raise ValueError(f"unknown client: {client}")
    done: dict[str, str] = {}
    for name in targets:
        if name == "opencode":
            done[name] = str(set_opencode_model(tag))
        elif name == "codex":
            done[name] = str(set_codex_model(tag, settings))
        elif name == "claude":
            done[name] = str(set_claude_model(tag))
    return done


def current_models() -> dict[str, str]:
    """Read back the model each client is currently pointed at (best effort)."""
    out: dict[str, str] = {}
    # OpenCode: model is "local/<tag>".
    try:
        data = json.loads(opencode_model_path().read_text(encoding="utf-8"))
        model = str(data.get("model") or "")
        out["opencode"] = model.removeprefix("local/") if model.startswith("local/") else model
    except (OSError, ValueError, AttributeError):
        out["opencode"] = ""
    # Codex: model is a bare tag in the local profile.
    try:
        data = tomllib.loads((codex_home_path() / "config.toml").read_text(encoding="utf-8"))
        out["codex"] = str(data.get("model") or "")
    except (OSError, ValueError):
        out["codex"] = ""
    # Claude: model is ANTHROPIC_MODEL in settings.json env.
    try:
        data = json.loads(claude_settings_path().read_text(encoding="utf-8"))
        env = data.get("env") if isinstance(data, dict) else {}
        out["claude"] = str((env or {}).get("ANTHROPIC_MODEL") or "")
    except (OSError, ValueError, AttributeError):
        out["claude"] = ""
    return out


def is_installed(tag: str) -> bool:
    """Whether Ollama already has the tag (or its :latest form) locally."""
    return tag in installed_models()


def resolve_domain(domain_key: str) -> str:
    """Validate a domain key and return the model id to wire into a client.

    The tier gateway accepts a domain key directly (`legal`, `forensics`, …)
    and routes it to that specialist's model, so selecting a domain is just
    writing its key as the client model — no tag resolution needed.
    """
    from .domains import DOMAINS

    if domain_key not in DOMAINS:
        raise ValueError(f"unknown domain: {domain_key}")
    return domain_key
