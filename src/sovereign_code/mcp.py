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

import json
import sys
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
        "List installed local models, cloud models, and the gateway route each alias uses.",
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
        "List the curated skills available to the coding clients, optionally filtered.",
        {"query": {"type": "string"}},
    ),
    _tool(
        "get_skill",
        "Return one skill's full Markdown body.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _tool(
        "project_context",
        "Return the saved project memory and a short file index for a directory.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    _tool(
        "ask",
        "Run a prompt through the local gateway using a model alias (local or cloud).",
        {
            "prompt": {"type": "string"},
            "model": {"type": "string", "default": "local-chat"},
            "max_tokens": {"type": "integer", "default": 512},
        },
        ["prompt"],
    ),
    _tool(
        "run_checks",
        "Detect and run a project's tests, returning the pass/fail log.",
        {
            "path": {"type": "string"},
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit commands; omit to auto-detect",
            },
        },
        ["path"],
    ),
]


def list_skills_payload(query: str = "") -> list[dict[str, str]]:
    from .skills_install import load_curated

    needle = query.strip().lower()
    rows = []
    for skill in load_curated():
        haystack = f"{skill.name} {skill.description}".lower()
        if needle and needle not in haystack:
            continue
        rows.append({"name": skill.name, "description": skill.description})
    return rows


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
    return {
        "local": local,
        "cloud": cloud,
        "gateway": snap.settings.gateway_url,
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
        settings.gateway_url,
        model,
        [{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )


def _checks(path: str, commands: list[str] | None) -> dict[str, Any]:
    from .checks import detect_checks, run_checks

    target = Path(path).expanduser().resolve()
    chosen = commands or detect_checks(target)
    result = run_checks(target, chosen, timeout=900.0)
    return {"ok": result.ok, "commands": chosen, "log": result.log[-6000:]}


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    if name == "list_models":
        return _text(_models_payload())
    if name == "best_model":
        return _text(_best_model(str(args.get("task") or "code")))
    if name == "list_skills":
        return _text(list_skills_payload(str(args.get("query") or "")))
    if name == "get_skill":
        from .skills_install import load_curated

        wanted = str(args.get("name") or "")
        for skill in load_curated():
            if skill.name == wanted:
                return skill.body
        raise ValueError(f"unknown skill: {wanted}")
    if name == "project_context":
        return _project_context(str(args.get("path") or "."))
    if name == "ask":
        return _ask(
            str(args.get("prompt") or ""),
            str(args.get("model") or "local-chat"),
            int(args.get("max_tokens") or 512),
        )
    if name == "run_checks":
        commands = args.get("commands")
        target = str(args.get("path") or ".")
        return _text(
            _checks(target, commands if isinstance(commands, list) else None)
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
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = str(params.get("name") or "")
            output = call_tool(name, params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": output}], "isError": False}
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
