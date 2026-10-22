"""A small MCP server exposing Sovereign Code to desktop AI clients.

ChatGPT's desktop app, Claude Desktop, Claude Code, Codex, and OpenCode all
speak the Model Context Protocol. This server gives them the parts that are
otherwise stuck behind the CLI: the live model catalog, the strongest model for
a task, the curated skills, project memory, gateway completions, and the
project's own checks.

Transport is stdio with newline-delimited JSON-RPC 2.0 (the MCP stdio spec).
Nothing is written to stdout except protocol messages.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
from pathlib import Path
from typing import Any

from . import __version__

PROTOCOL_VERSION = "2024-11-05"


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "list_models",
        "List installed local models, cloud models, and every name a client may ask for.",
        {},
    ),
    _tool(
        "best_model",
        "Return the strongest installed model and context window for a task.",
        {
            "task": {
                "type": "string",
                "enum": ["code", "chat", "reason", "vision", "fast", "agent"],
                "default": "code",
            }
        },
    ),
    _tool(
        "list_skills",
        "List curated skills, or search all 22k library skills with a query.",
        {"query": {"type": "string"}},
    ),
    _tool(
        "get_skill",
        "Return one skill's full Markdown body.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _tool(
        "hf_status",
        "Report whether Hugging Face is authenticated (never the token), where the "
        "token, Hub cache, and downloads live, and whether the hf CLI is installed.",
        {},
    ),
    _tool(
        "search_hf_models",
        "Search Hugging Face Hub models. Public search works without a token; a token "
        "adds private and gated results. Use hf_model_info before downloading.",
        {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
            "gguf_only": {"type": "boolean", "default": False},
            "author": {"type": "string"},
            "sort": {
                "type": "string",
                "enum": ["downloads", "likes", "last_modified", "created_at", "trending_score"],
                "default": "downloads",
            },
        },
        ["query"],
    ),
    _tool(
        "hf_model_info",
        "Inspect one Hugging Face model: gated status, storage, GGUF metadata, and "
        "files. Set files=true to list every file.",
        {
            "repo_id": {"type": "string"},
            "files": {"type": "boolean", "default": False},
        },
        ["repo_id"],
    ),
    _tool(
        "search_hf_datasets",
        "Search Hugging Face Hub datasets. Results include licence, languages, "
        "formats, task, and size metadata. A token adds private and gated datasets.",
        {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
            "author": {"type": "string"},
            "sort": {
                "type": "string",
                "enum": ["downloads", "likes", "last_modified", "created_at", "trending_score"],
                "default": "downloads",
            },
        },
        ["query"],
    ),
    _tool(
        "hf_dataset_info",
        "Inspect one Hugging Face dataset: gated status, storage, licence, "
        "languages, formats, and files. Set files=true to list every file.",
        {
            "repo_id": {"type": "string"},
            "files": {"type": "boolean", "default": False},
        },
        ["repo_id"],
    ),
    _tool(
        "list_hf_local",
        "List Hugging Face repositories already on this Mac: downloaded models, "
        "downloaded datasets, and the shared Hub cache, with sizes and paths.",
        {
            "repo_type": {
                "type": "string",
                "enum": ["all", "model", "dataset"],
                "default": "all",
            }
        },
    ),
    _tool(
        "project_context",
        "Return the saved project memory and a short file index for a directory.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    _tool(
        "local_status",
        "Report whether this machine is running the local stack only: the tier "
        "gateway, the Anthropic bridge, Ollama Cloud, and whether the ChatGPT "
        "and Claude desktop apps are pointed at the local path without a sign-in.",
        {},
    ),
    _tool(
        "ask",
        "Run a prompt through the local gateway using a model alias (local or cloud).",
        {
            "prompt": {"type": "string"},
            "model": {"type": "string", "default": "best"},
            "max_tokens": {"type": "integer", "default": 512},
        },
        ["prompt"],
    ),
    _tool(
        "run_checks",
        "Detect and run a project's tests, returning the pass/fail log. The commands "
        "are always detected from the project; a client cannot choose what runs.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    _tool(
        "delegate",
        "Run a local coding agent on a project. Read-only by default; set write=true "
        "to allow edits. The agent still asks before acting, and this tool can never "
        "disable its approval prompts. Returns the agent's output and success flag.",
        {
            "prompt": {"type": "string"},
            "path": {"type": "string"},
            "client": {
                "type": "string",
                "enum": ["codex", "claude"],
                "default": "codex",
            },
            "write": {
                "type": "boolean",
                "default": False,
                "description": "Allow file edits; false runs read-only/plan mode",
            },
            "timeout": {"type": "integer", "default": 240},
        },
        ["prompt", "path"],
    ),
    _tool(
        "browser_open",
        "Open a visible local Chromium session at a URL and return the page state.",
        {
            "url": {"type": "string"},
            "allow_local": {"type": "boolean", "default": False},
            "headless": {"type": "boolean", "default": False},
        },
        ["url"],
    ),
    _tool(
        "browser_observe",
        "Return the current browser URL, visible text, and numbered interactive elements.",
        {},
    ),
    _tool(
        "browser_act",
        "Perform one browser action: navigate, click, fill, select, press, scroll, "
        "extract, handoff, or done. Destructive actions require confirm=true.",
        {
            "action": {
                "type": "string",
                "enum": [
                    "navigate",
                    "click",
                    "fill",
                    "select",
                    "press",
                    "scroll",
                    "extract",
                    "handoff",
                    "done",
                ],
            },
            "url": {"type": "string"},
            "id": {"type": "integer"},
            "text": {"type": "string"},
            "key": {"type": "string"},
            "value": {"type": "string"},
            "direction": {"type": "string", "enum": ["up", "down", "top", "bottom"]},
            "amount": {"type": "integer"},
            "confirm": {"type": "boolean", "default": False},
        },
        ["action"],
    ),
    _tool(
        "browser_screenshot",
        "Save a screenshot of the visible browser page; returns its path and PNG image content.",
        {},
    ),
    _tool("browser_close", "Close the local browser session.", {}),
]


def list_skills_payload(query: str = "") -> list[dict[str, str]]:
    from .skills import search_skills
    from .skills_install import load_curated

    needle = query.strip()
    if needle:
        return [
            {"name": name, "description": description}
            for name, description in search_skills(needle, limit=50)
        ]
    rows = []
    for skill in load_curated():
        rows.append({"name": skill.name, "description": skill.description})
    return rows


def _hf_status_payload() -> dict[str, Any]:
    from . import hf

    status = hf.token_status(verify=False)
    token_mode = ""
    if status.present:
        try:
            token_mode = oct(status.path.stat().st_mode & 0o777)
        except OSError:
            token_mode = ""
    return {
        "token": status.to_dict(),
        "token_mode": token_mode,
        "cli": {"path": hf.hf_cli_path() or "", "version": hf.hf_cli_version()},
        "cache_dir": str(hf.hub_cache_dir()),
        "download_dir": str(hf.DOWNLOAD_ROOT),
        "dataset_dir": str(hf.DATASET_DOWNLOAD_ROOT),
    }


def _hf_search_payload(
    query: str,
    limit: int,
    gguf_only: bool,
    author: str | None,
    sort: str,
    repo_type: str = "model",
) -> list[dict[str, Any]]:
    from . import hf

    rows = hf.search_models(
        query,
        limit=limit,
        gguf_only=gguf_only,
        author=author,
        sort=sort,
        token=hf.resolve_token()[0] or None,
        repo_type=repo_type,
    )
    return [row.to_dict() for row in rows]


def _hf_info_payload(
    repo_id: str,
    include_files: bool,
    repo_type: str = "model",
) -> dict[str, Any]:
    from . import hf

    info = hf.info_model(
        repo_id,
        token=hf.resolve_token()[0] or None,
        repo_type=repo_type,
    )
    return info.to_dict(include_files=include_files)


def _hf_local_payload(repo_type: str = "all") -> list[dict[str, Any]]:
    from . import hf

    kind = None if repo_type in {"", "all"} else repo_type
    return [row.to_dict() for row in hf.local_repos(kind)]


def _models_payload() -> dict[str, Any]:
    import asyncio

    from .config import Settings
    from .status import collect

    settings = Settings.load()
    snap = asyncio.run(collect(settings))
    local = [
        {"tag": view.tag, "role": view.spec.role, "context": view.spec.max_context}
        for view in snap.installed
        if not view.spec.cloud
    ]
    cloud = [
        {"tag": view.tag, "role": view.spec.role, "context": view.spec.max_context}
        for view in snap.installed
        if view.spec.cloud
    ]
    from .tier_gateway import catalog_models, installed_models

    # The names a client may ask for: the tiers, the quality routes, the local
    # aliases and the installed models, with the model behind each one.
    routes = [
        {
            "id": entry["id"],
            "tier": entry["tier"],
            "model": entry["model"],
            "context": entry["context"],
        }
        for entry in catalog_models(installed_models())
    ]
    return {
        "local": local,
        "cloud": cloud,
        "routes": routes,
        "gateway": snap.settings.gateway_url,
        "router": snap.settings.router_url,
        "cloud_enabled": snap.cloud_enabled,
    }


def _best_model(task: str) -> dict[str, Any]:
    import asyncio

    from .config import Settings
    from .router import Task, choose
    from .status import collect

    settings = Settings.load()
    snap = asyncio.run(collect(settings))
    selection = choose(
        Task(task),
        snap.views,
        snap.potential_free_gb,
        max_context=settings.max_context,
    )
    return {
        "task": task,
        "model": selection.tag,
        "context": selection.context,
        "reason": selection.reason,
    }


def _project_context(path: str) -> str:
    from .memory import project_context

    target = Path(path).expanduser().resolve()
    memory = project_context(target)
    files: list[str] = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            files.append(entry.name + ("/" if entry.is_dir() else ""))
            if len(files) >= 60:
                break
    except OSError:
        pass
    parts = [f"# Project {target}", "Files: " + ", ".join(files)]
    if memory:
        parts += ["", memory]
    return "\n".join(parts)


def _ask(prompt: str, model: str, max_tokens: int) -> str:
    from .config import Settings
    from .summarize import complete

    settings = Settings.load()
    return complete(
        settings.router_url,
        model,
        [{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )


_BROWSER_LOCK = threading.Lock()
_BROWSER: Any = None
_BROWSER_MODE: tuple[bool, bool] | None = None


def _browser_policy(allow_local: bool):
    from .browser.actions import BrowserPolicy

    return BrowserPolicy(allow_local=allow_local)


def _browser_open(url: str, allow_local: bool = False, headless: bool = False) -> dict:
    global _BROWSER, _BROWSER_MODE
    from .browser.actions import check_url
    from .browser.executor import BrowserSession
    from .config import LOCAL_AI_ROOT

    with _BROWSER_LOCK:
        mode = (allow_local, headless)
        if _BROWSER is not None and mode != _BROWSER_MODE:
            _BROWSER.close()
            _BROWSER = None
        policy = _browser_policy(allow_local)
        target = check_url(url, policy)
        if _BROWSER is None:
            _BROWSER = BrowserSession(
                profile_dir=LOCAL_AI_ROOT / "data" / "browser" / "profile",
                policy=policy,
                headless=headless,
                timeout_ms=15000,
            )
            _BROWSER.start(target)
            _BROWSER_MODE = mode
        else:
            _BROWSER.goto(target)
        return _browser_observation(_BROWSER.observe())


def _browser_observation(observation: dict) -> dict:
    return {
        "url": observation.get("url"),
        "title": observation.get("title"),
        "captcha": observation.get("captcha"),
        "text": str(observation.get("text") or "")[:4000],
        "elements": observation.get("elements") or [],
    }


def _browser_observe() -> dict:
    global _BROWSER
    with _BROWSER_LOCK:
        if _BROWSER is None:
            raise ValueError("browser is not open; call browser_open first")
        return _browser_observation(_BROWSER.observe())


def _browser_act(arguments: dict[str, Any]) -> dict:
    global _BROWSER
    from .browser.actions import parse_action

    with _BROWSER_LOCK:
        if _BROWSER is None:
            raise ValueError("browser is not open; call browser_open first")
        payload = {
            key: value
            for key, value in arguments.items()
            if key in {"action", "url", "id", "text", "key", "value", "direction", "amount"}
        }
        action = parse_action(payload)
        confirm = bool(arguments.get("confirm", False))
        result = _BROWSER.perform(action, confirm=lambda _message: confirm)
        return {
            "result": result,
            "page": _browser_observation(_BROWSER.observe())
            if action.kind not in {"done", "handoff"}
            else None,
        }


def _browser_screenshot() -> list[dict[str, Any]]:
    global _BROWSER
    from .config import LOCAL_AI_ROOT

    with _BROWSER_LOCK:
        if _BROWSER is None:
            raise ValueError("browser is not open; call browser_open first")
        folder = LOCAL_AI_ROOT / "data" / "browser" / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"mcp-{int(__import__('time').time())}.png"
        shot = _BROWSER.screenshot(path)
        if shot is None:
            raise ValueError("screenshot failed")
        content: list[dict[str, Any]] = [{"type": "text", "text": str(shot)}]
        try:
            data = shot.read_bytes()
            if len(data) <= 2_000_000:
                content.append(
                    {
                        "type": "image",
                        "data": base64.b64encode(data).decode(),
                        "mimeType": "image/png",
                    }
                )
        except OSError:
            pass
        return content


def _browser_close() -> dict:
    global _BROWSER, _BROWSER_MODE
    with _BROWSER_LOCK:
        if _BROWSER is not None:
            _BROWSER.close()
        _BROWSER = None
        _BROWSER_MODE = None
        return {"ok": True}


def _delegate(
    prompt: str,
    path: str,
    client: str = "codex",
    write: bool = False,
    timeout: int = 240,
) -> dict[str, Any]:
    from .agents import build_headless, run_headless
    from .config import Settings

    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"not a directory: {target}")
    if client not in {"codex", "claude"}:
        raise ValueError("delegate supports codex or claude")
    seconds = max(30, min(int(timeout or 240), 600))
    plan = build_headless(
        client,
        "local",
        target,
        prompt,
        Settings.load(),
        "auto",
        # The MCP path never turns the agent's approval prompts off: a
        # connected client must not be able to run an agent unattended.
        # `write` still allows edits, but the agent keeps asking the human.
        unattended=False,
        write=write,
        wall_time=seconds,
    )
    ok, output = run_headless(plan, timeout=float(seconds))
    return {
        "ok": ok,
        "client": client,
        "write": write,
        "seconds": seconds,
        "output": output,
    }


def _checks(path: str, commands: list[str] | None = None) -> dict[str, Any]:
    """Run the project's own checks.

    `commands` is for internal callers only: the MCP tool schema does not
    offer it, and an explicit command still has to be an allow-listed test
    or lint runner.
    """
    from .checks import allowed_commands, detect_checks, run_allowed_checks, run_checks

    target = Path(path).expanduser().resolve()
    if commands:
        chosen = allowed_commands(commands)
        result = run_allowed_checks(target, chosen, timeout=900.0)
    else:
        chosen = detect_checks(target)
        result = run_checks(target, chosen, timeout=900.0)
    return {"ok": result.ok, "commands": chosen, "log": result.log[-6000:]}


def _local_status() -> dict[str, Any]:
    """Whether this machine is running the local stack only.

    The desktop apps can answer this over their own MCP connection, which is
    the one place a "no sign-in" claim can be checked from inside the app.
    """
    from . import bridge as bridge_mod
    from .client_setup import claude_forced_local, codex_forced_local, codex_needs_openai_signin
    from .cloud import env_cloud_disabled
    from .config import Settings

    settings = Settings.load()
    gateway: dict[str, Any] = {"up": False, "local_only": False, "tiers": {}}
    try:
        import httpx

        health = httpx.get(f"{settings.router_url.rstrip('/')}/health", timeout=3.0).json()
        gateway = {
            "up": True,
            "local_only": bool(health.get("local_only")),
            "tiers": health.get("tiers") or {},
        }
    except Exception:
        pass
    return {
        "local_only": bool(gateway["up"] and gateway["local_only"] and env_cloud_disabled()),
        "gateway": gateway,
        "bridge_up": bridge_mod.port_open(port=4001),
        "ollama_cloud": "disabled" if env_cloud_disabled() else "enabled",
        "apps": {
            "chatgpt": {
                "local": codex_forced_local(),
                "signin_required": codex_needs_openai_signin(),
            },
            "claude": {"local": claude_forced_local()},
        },
    }


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> str | list[dict[str, Any]]:
    args = arguments or {}
    if name == "list_models":
        return _text(_models_payload())
    if name == "best_model":
        return _text(_best_model(str(args.get("task") or "code")))
    if name == "list_skills":
        return _text(list_skills_payload(str(args.get("query") or "")))
    if name == "get_skill":
        from .skills_install import get_skill

        wanted = str(args.get("name") or "")
        skill = get_skill(wanted)
        if skill is None:
            raise ValueError(f"unknown skill: {wanted}")
        return skill.body
    if name == "hf_status":
        return _text(_hf_status_payload())
    if name == "search_hf_models":
        return _text(
            _hf_search_payload(
                str(args.get("query") or ""),
                int(args.get("limit") or 20),
                bool(args.get("gguf_only", False)),
                str(args.get("author") or "") or None,
                str(args.get("sort") or "downloads"),
            )
        )
    if name == "hf_model_info":
        return _text(
            _hf_info_payload(
                str(args.get("repo_id") or ""),
                bool(args.get("files", False)),
            )
        )
    if name == "search_hf_datasets":
        return _text(
            _hf_search_payload(
                str(args.get("query") or ""),
                int(args.get("limit") or 20),
                False,
                str(args.get("author") or "") or None,
                str(args.get("sort") or "downloads"),
                "dataset",
            )
        )
    if name == "hf_dataset_info":
        return _text(
            _hf_info_payload(
                str(args.get("repo_id") or ""),
                bool(args.get("files", False)),
                "dataset",
            )
        )
    if name == "list_hf_local":
        return _text(_hf_local_payload(str(args.get("repo_type") or "all")))
    if name == "project_context":
        return _project_context(str(args.get("path") or "."))
    if name == "local_status":
        return _text(_local_status())
    if name == "ask":
        return _ask(
            str(args.get("prompt") or ""),
            str(args.get("model") or "best"),
            int(args.get("max_tokens") or 512),
        )
    if name == "run_checks":
        # The tool schema has no "commands" parameter: the client never picks
        # what runs on this Mac, only where the project is.
        target = str(args.get("path") or ".")
        return _text(_checks(target))
    if name == "browser_open":
        return _text(
            _browser_open(
                str(args.get("url") or ""),
                bool(args.get("allow_local", False)),
                bool(args.get("headless", False)),
            )
        )
    if name == "browser_observe":
        return _text(_browser_observe())
    if name == "browser_act":
        return _text(_browser_act(args))
    if name == "browser_screenshot":
        return _browser_screenshot()
    if name == "browser_close":
        return _text(_browser_close())
    if name == "delegate":
        return _text(
            _delegate(
                str(args.get("prompt") or ""),
                str(args.get("path") or "."),
                str(args.get("client") or "codex"),
                bool(args.get("write", False)),
                int(args.get("timeout") or 240),
            )
        )
    raise ValueError(f"unknown tool: {name}")


def resources() -> list[dict[str, Any]]:
    from .skills_install import load_curated

    rows = [
        {
            "uri": f"sovereign://skills/{skill.name}",
            "name": skill.name,
            "description": skill.description,
            "mimeType": "text/markdown",
        }
        for skill in load_curated()
    ]
    rows.append(
        {
            "uri": "sovereign://models",
            "name": "models",
            "description": "Installed local and cloud models",
            "mimeType": "application/json",
        }
    )
    return rows


def read_resource(uri: str) -> str:
    if uri == "sovereign://models":
        return _text(_models_payload())
    if uri.startswith("sovereign://skills/"):
        from .skills_install import load_curated

        name = uri.rsplit("/", 1)[-1]
        for skill in load_curated():
            if skill.name == name:
                return skill.body
    raise ValueError(f"unknown resource: {uri}")


def prompts() -> list[dict[str, Any]]:
    from .skills_install import load_curated

    return [
        {
            "name": skill.name,
            "description": skill.description,
            "arguments": [
                {"name": "context", "description": "Code or task context", "required": False}
            ],
        }
        for skill in load_curated()
    ]


def get_prompt(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from .skills_install import load_curated

    for skill in load_curated():
        if skill.name == name:
            context = str((arguments or {}).get("context") or "")
            text = skill.body
            if context:
                text += "\n\n## Context\n\n" + context
            return {
                "description": skill.description,
                "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
            }
    raise ValueError(f"unknown prompt: {name}")


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method.startswith("notifications/"):
        return None
    try:
        if method == "initialize":
            result: Any = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "sovereign-code", "version": __version__},
                "instructions": (
                    "Sovereign Code exposes this Mac's local models, skills, project "
                    "memory, and checks. Use list_models for availability, ask with "
                    "model=fast for quick work or model=deep for code/reasoning, "
                    "list_skills/get_skill for workflows, run_checks to verify, and "
                    "delegate to run a real local Codex/Claude agent on a project "
                    "(read-only unless write=true; it never skips the human's "
                    "approvals). Browser control is available via "
                    "browser_open/observe/act/screenshot/close. Use hf_status, "
                    "search_hf_models/hf_model_info, and search_hf_datasets/"
                    "hf_dataset_info to discover Hugging Face repositories; use "
                    "list_hf_local to see what is already cached. Downloads are an "
                    "explicit CLI action (`sovereign hf download`). "
                    "Do not claim a local model ran if ask fails."
                ),
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = str(params.get("name") or "")
            output = call_tool(name, params.get("arguments") or {})
            content = output if isinstance(output, list) else [{"type": "text", "text": output}]
            result = {"content": content, "isError": False}
        elif method == "resources/list":
            result = {"resources": resources()}
        elif method == "resources/read":
            result = {
                "contents": [
                    {
                        "uri": params.get("uri"),
                        "mimeType": "text/markdown",
                        "text": read_resource(str(params.get("uri") or "")),
                    }
                ]
            }
        elif method == "prompts/list":
            result = {"prompts": prompts()}
        elif method == "prompts/get":
            result = get_prompt(str(params.get("name") or ""), params.get("arguments"))
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
    except Exception as exc:  # MCP turns tool failures into error results
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)[:500]},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve() -> None:
    """Read newline-delimited JSON-RPC from stdin, write to stdout."""
    try:
        from .config import Settings
        from .tier_gateway import ensure_running as ensure_tier

        settings = Settings.load()
        ensure_tier(upstream=settings.gateway_url, ollama=settings.ollama_url)
    except Exception:
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict):
            continue
        response = handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
