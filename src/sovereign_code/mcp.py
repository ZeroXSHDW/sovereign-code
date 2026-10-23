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
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import __version__
from .diagnostics import note

PROTOCOL_VERSION = "2024-11-05"

# A single skill can be a full workflow document. Bulk loading is capped so a
# broad query cannot return tens of megabytes to a client in one tool result.
MAX_BULK_SKILLS = 50
MAX_SKILL_BODY_CHARS = 20_000


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


_COMPUTER_LOCK = threading.Lock()

_MAX_OUTPUT = 100_000

# Commands that can destroy the machine or lock the user out. The MCP server is
# deliberately powerful, so the few irreversible operations are fenced off.
_DENY_COMMAND = re.compile(
    r"rm\s+(-[a-z]*[rf][a-z]*\s+)+(/|/\*|~|\$HOME)(\s|$)|"
    r"mkfs(\.|\s)|"
    r"diskutil\s+(erase|partition|reformat)|"
    r"(shutdown|reboot|halt)\s|"
    r"dd\s+.*of=/dev/|"
    r":\(\)\s*\{|"
    r">\s*/dev/(disk|sd|nvme)",
    re.IGNORECASE,
)


def _computer_enabled() -> bool:
    value = os.environ.get("SOVEREIGN_MCP_COMPUTER", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _ensure_computer() -> None:
    if not _computer_enabled():
        raise ValueError("computer control is disabled; set SOVEREIGN_MCP_COMPUTER=1 to enable it")


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text) - limit} more bytes)"


_SENSITIVE_NAMES = frozenset(
    {"cloud.env", "auth.json", ".env", ".netrc", ".npmrc", ".pypirc", "credentials"}
)
_SENSITIVE_NAME_PREFIXES = (".env.", "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa")
_SENSITIVE_DIRS = frozenset({".ssh", ".gnupg", ".aws", ".codex", ".claude", "Keychains"})


def _refuse_sensitive(path: str | Path) -> Path:
    """Resolve the path (following symlinks) and refuse credential files."""
    resolved = Path(path).expanduser().resolve()
    name = resolved.name
    if (
        name in _SENSITIVE_NAMES
        or name.startswith(_SENSITIVE_NAME_PREFIXES)
        or _SENSITIVE_DIRS.intersection(resolved.parts)
    ):
        raise ValueError(f"refused: {resolved} can hold credentials")
    return resolved


def _workspace_path(value: str) -> Path:
    """Resolve a path that must live under an allowed workspace root."""
    from .config import Settings

    target = Path(value or ".").expanduser().resolve()
    roots = [Path.cwd().resolve()]
    env_root = os.environ.get("SOVEREIGN_WORKSPACE")
    if env_root:
        roots.append(Path(env_root).expanduser().resolve())
    try:
        roots.append(Path(Settings.load().workspace).expanduser().resolve())
    except Exception as exc:
        note("workspace-root", exc)
    if not any(target == root or root in target.parents for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise ValueError(f"refused: {target} is outside the workspace ({allowed})")
    _refuse_sensitive(target)
    return target


def _audit(kind: str, **data: Any) -> None:
    """Append one local, private record of a computer action."""
    from .config import LOCAL_AI_ROOT
    from .safefile import ensure_private_dir, open_private

    folder = LOCAL_AI_ROOT / "data" / "computer"
    ensure_private_dir(folder)
    path = folder / "audit.jsonl"
    record = {"ts": time.time(), "kind": kind, **data}
    with _COMPUTER_LOCK:
        with open_private(path, "a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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
        "skills_for_task",
        "Rank skills for a task and return compact cards (name, category, tokens, "
        "risk) plus a suggested playbook. Does not load skill bodies.",
        {
            "task": {"type": "string"},
            "limit": {"type": "integer", "default": 8},
            "max_tokens": {"type": "integer", "default": 3000},
        },
        ["task"],
    ),
    _tool(
        "get_skill",
        "Return one skill's full Markdown body.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _tool(
        "load_skills",
        "Load several skill bodies in one call, by name and/or search query. "
        "Enforces a token budget so several large skills cannot swallow the "
        "context window.",
        {
            "names": {"type": "array", "items": {"type": "string"}},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
            "max_tokens": {"type": "integer", "default": 8000},
        },
    ),
    _tool(
        "repo_map",
        "Outline a project: languages, every source file, and its classes and "
        "functions with line numbers. Call this first when working in an unfamiliar "
        "repository; it is far cheaper than listing directories.",
        {
            "path": {"type": "string", "default": "."},
            "max_files": {"type": "integer", "default": 600},
            "max_tokens": {"type": "integer", "default": 2400},
        },
    ),
    _tool(
        "repo_search",
        "Search every source file for a term or regular expression and return "
        "path:line matches. Use it to find a symbol, an error message or a config key "
        "without reading whole files.",
        {
            "path": {"type": "string", "default": "."},
            "query": {"type": "string"},
            "regex": {"type": "boolean", "default": False},
            "glob": {"type": "string"},
            "limit": {"type": "integer", "default": 100},
            "code_only": {"type": "boolean", "default": True},
        },
        ["query"],
    ),
    _tool(
        "repo_read",
        "Read numbered lines from one file. Use the line numbers from repo_search or "
        "repo_map to read only the region you need.",
        {
            "path": {"type": "string"},
            "start": {"type": "integer", "default": 1},
            "end": {"type": "integer", "default": 300},
        },
        ["path"],
    ),
    _tool(
        "repo_write",
        "Create or replace one file inside the workspace, atomically. Refuses to "
        "overwrite an existing file unless overwrite=true or expected_sha256 matches, "
        "so a stale model cannot clobber a newer edit.",
        {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean", "default": False},
            "expected_sha256": {"type": "string"},
        },
        ["path", "content"],
    ),
    _tool(
        "repo_edit",
        "Replace one exact string in a file. Refuses an ambiguous match unless "
        "replace_all=true. Set dry_run=true to see the unified diff first.",
        {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
            "replace_all": {"type": "boolean", "default": False},
            "dry_run": {"type": "boolean", "default": False},
        },
        ["path", "old", "new"],
    ),
    _tool(
        "repo_patch",
        "Apply a unified diff to one file inside the workspace. Every hunk must match "
        "or nothing is written.",
        {"path": {"type": "string"}, "patch": {"type": "string"}},
        ["path", "patch"],
    ),
    _tool(
        "list_packs",
        "List task packs (pentest, vulnerability, risk, vendor, legal, compliance, "
        "forensics, finance) with their key, label, domain and summary.",
        {},
    ),
    _tool(
        "pack_profile",
        "Return one task pack's full profile: guardrails, steps, deliverables, "
        "model queries, and suggested skills.",
        {"key": {"type": "string"}},
        ["key"],
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
            "limit": {"type": "integer", "default": 30},
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
            "limit": {"type": "integer", "default": 30},
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
            "max_tokens": {"type": "integer", "default": 1024},
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
    _tool(
        "run_command",
        "Run a shell command on this Mac and return its output. This is full local "
        "computer control: use it for builds, tests, git, package managers, ssh, "
        "adb and any CLI. A leading sudo uses the macOS authorization dialog. "
        "Destructive commands are refused unless SOVEREIGN_MCP_UNRESTRICTED=1. "
        "Output is truncated.",
        {
            "command": {"type": "string"},
            "cwd": {"type": "string", "description": "Working directory; defaults to $HOME"},
            "timeout": {"type": "integer", "default": 300},
        },
        ["command"],
    ),
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


def load_skills_payload(
    names: list[str] | None = None,
    query: str = "",
    limit: int = 10,
    max_tokens: int = 6000,
) -> dict[str, Any]:
    from .skills import search_skills
    from .skills_install import get_skill, load_curated
    from .skills_safety import scan

    wanted = [str(name).strip() for name in (names or []) if str(name).strip()]
    wanted = list(dict.fromkeys(wanted))
    cap = max(1, min(int(limit or 10), MAX_BULK_SKILLS))
    selected: dict[str, Any] = {}
    missing: list[str] = []

    for name in wanted:
        skill = get_skill(name)
        if skill is None:
            missing.append(name)
        elif skill.name not in selected:
            selected[skill.name] = skill

    needle = query.strip()
    if needle:
        for name, _description in search_skills(needle, limit=cap):
            if len(selected) >= cap:
                break
            if name in selected:
                continue
            skill = get_skill(name)
            if skill is not None:
                selected[skill.name] = skill

    if not wanted and not needle:
        for skill in load_curated()[:cap]:
            selected[skill.name] = skill

    budget = max(200, min(80_000, max_tokens)) * 4
    used = 0
    rows: list[dict[str, Any]] = []
    omitted: list[str] = []
    for skill in list(selected.values())[:cap]:
        body = skill.body
        room = budget - used
        if room < 400:
            omitted.append(skill.name)
            continue
        text = body[: min(len(body), MAX_SKILL_BODY_CHARS, room)]
        truncated = len(text) < len(body)
        used += len(text)
        found = scan(body)
        rows.append(
            {
                "name": skill.name,
                "description": skill.description,
                "body": text,
                "truncated": truncated,
                "tokens": max(1, len(text) // 4),
                "risk": found.risk,
                "warnings": [found.warning()] if found.warning() else [],
            }
        )
    return {
        "skills": rows,
        "missing": missing,
        "omitted": omitted,
        "tokens_used": used // 4,
        "budget_tokens": budget // 4,
    }


def _list_packs_payload() -> list[dict[str, str]]:
    from . import packs

    return [
        {
            "key": key,
            "label": pack.label,
            "domain": pack.domain,
            "task": str(pack.task),
            "summary": pack.summary,
        }
        for key, pack in sorted(packs.PACKS.items())
    ]


def _pack_profile_payload(key: str) -> dict[str, Any]:
    from . import packs

    pack = packs.get_pack(key)
    if pack is None:
        raise ValueError(f"unknown pack: {key}")
    skills = packs.pack_skills(pack, limit=6)
    return {
        "key": pack.key,
        "label": pack.label,
        "domain": pack.domain,
        "task": str(pack.task),
        "summary": pack.summary,
        "guardrails": list(pack.guardrails),
        "steps": list(pack.steps),
        "deliverables": list(pack.deliverables),
        "model_queries": list(pack.model_queries),
        "suggested_skills": [
            {"name": name, "description": packs._first(desc)} for name, desc in skills
        ],
    }


def _repo_map(path: str, max_files: int, max_tokens: int) -> str:
    from .repomap import repo_map

    root = _workspace_path(path)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    limited_files = max(1, min(5_000, max_files))
    limited_tokens = max(200, min(20_000, max_tokens))
    return repo_map(root, max_files=limited_files, max_tokens=limited_tokens)


def _repo_search(
    path: str,
    query: str,
    regex: bool,
    glob: str | None,
    limit: int,
    code_only: bool = True,
) -> list[str]:
    from .repomap import search_repo

    root = _workspace_path(path)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    hits = search_repo(
        root,
        query,
        regex=regex,
        glob=glob,
        limit=max(1, min(200, limit)),
        code_only=code_only,
    )
    return [hit.as_line() for hit in hits] or ["no matches"]


def _repo_write(
    path: str,
    content: str,
    overwrite: bool,
    expected_sha256: str | None,
) -> dict[str, Any]:
    from .repoedit import write_text

    target = _workspace_path(path)
    if target.exists() and not overwrite and not expected_sha256:
        raise ValueError(f"{target} exists; pass overwrite=true or expected_sha256 to replace it")
    result = write_text(target, content, expected_sha256=expected_sha256)
    _audit("repo_write", path=str(target), bytes=result.bytes, created=result.created)
    return {
        "path": result.path,
        "bytes": result.bytes,
        "created": result.created,
        "sha256": result.sha256,
    }


def _repo_edit(
    path: str,
    old: str,
    new: str,
    replace_all: bool,
    dry_run: bool,
) -> dict[str, Any]:
    from .repoedit import edit_text, preview

    target = _workspace_path(path)
    if dry_run:
        return {"path": str(target), "diff": preview(target, old, new), "dry_run": True}
    result = edit_text(target, old, new, replace_all=replace_all)
    _audit("repo_edit", path=str(target), replacements=result.replacements)
    return {
        "path": result.path,
        "replacements": result.replacements,
        "first_line": result.first_line,
        "sha256": result.sha256,
    }


def _repo_patch(root: str, patch: str) -> dict[str, Any]:
    from .repoedit import apply_patch

    base = _workspace_path(root)
    result = apply_patch(base, patch)
    _audit("repo_patch", path=result.path, changed=result.replacements)
    return {"path": result.path, "changed": result.replacements, "sha256": result.sha256}


def _repo_read(path: str, start: int, end: int) -> dict[str, Any]:
    from .repomap import read_slice

    target = _workspace_path(path)
    return read_slice(target, start=start, end=end)


def _run_command(command: str, cwd: str = "", timeout: int = 120) -> dict[str, Any]:
    _ensure_computer()
    text = command.strip()
    if not text:
        raise ValueError("command is empty")
    if _DENY_COMMAND.search(text):
        raise ValueError("refused: this command could destroy the machine or its data")
    workdir = Path(cwd).expanduser() if cwd else Path.home()
    if not workdir.is_dir():
        raise ValueError(f"not a directory: {workdir}")
    budget = max(1, min(3600, int(timeout or 120)))
    _audit("run_command", command=text, cwd=str(workdir), timeout=budget)
    from .terminal import run_shell

    result = run_shell(text, cwd=workdir, timeout=budget)
    return {
        "ok": result["ok"],
        "returncode": result["returncode"],
        "stdout": _truncate(result["stdout"]),
        "stderr": _truncate(result["stderr"]),
        "cwd": result["cwd"],
        "privileged": result.get("privileged", False),
    }


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
                timeout_ms=60000,
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
        "text": str(observation.get("text") or "")[:6000],
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
            if len(data) <= 5_000_000:
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
    seconds = max(30, min(int(timeout or 240), 3600))
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
        result = run_allowed_checks(target, chosen, timeout=1800.0)
    else:
        chosen = detect_checks(target)
        result = run_checks(target, chosen, timeout=1800.0)
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
        from .http import shared_client

        url = f"{settings.router_url.rstrip('/')}/health"
        health = shared_client(timeout=3.0, connect=3.0).get(url).json()
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
    if name == "skills_for_task":
        from .skillrouter import playbook, route

        cards, note = route(
            str(args.get("task") or ""),
            limit=max(1, min(20, int(args.get("limit") or 8))),
            max_tokens=max(200, min(8000, int(args.get("max_tokens") or 3000))),
        )
        return _text(
            {
                "skills": [card.as_dict() for card in cards],
                "playbook": playbook(str(args.get("task") or "")),
                "note": note,
            }
        )
    if name == "get_skill":
        from .skills_install import get_skill

        wanted = str(args.get("name") or "")
        skill = get_skill(wanted)
        if skill is None:
            raise ValueError(f"unknown skill: {wanted}")
        return skill.body
    if name == "load_skills":
        names = args.get("names")
        if isinstance(names, str):
            names = [names]
        return _text(
            load_skills_payload(
                names=names,
                query=str(args.get("query") or ""),
                limit=int(args.get("limit") or 10),
                max_tokens=int(args.get("max_tokens") or 8000),
            )
        )
    if name == "list_packs":
        return _text(_list_packs_payload())
    if name == "pack_profile":
        return _text(_pack_profile_payload(str(args.get("key") or "")))
    if name == "repo_map":
        return _text(
            _repo_map(
                str(args.get("path") or "."),
                int(args.get("max_files") or 600),
                int(args.get("max_tokens") or 2400),
            )
        )
    if name == "repo_search":
        return _text(
            _repo_search(
                str(args.get("path") or "."),
                str(args.get("query") or ""),
                bool(args.get("regex", False)),
                str(args.get("glob") or "") or None,
                int(args.get("limit") or 100),
                bool(args.get("code_only", True)),
            )
        )
    if name == "repo_read":
        return _text(
            _repo_read(
                str(args.get("path") or ""),
                int(args.get("start") or 1),
                int(args.get("end") or 300),
            )
        )
    if name == "repo_write":
        return _text(
            _repo_write(
                str(args.get("path") or ""),
                str(args.get("content") or ""),
                bool(args.get("overwrite", False)),
                str(args.get("expected_sha256") or "") or None,
            )
        )
    if name == "repo_edit":
        return _text(
            _repo_edit(
                str(args.get("path") or ""),
                str(args.get("old") or ""),
                str(args.get("new") or ""),
                bool(args.get("replace_all", False)),
                bool(args.get("dry_run", False)),
            )
        )
    if name == "repo_patch":
        return _text(
            _repo_patch(
                str(args.get("path") or "."),
                str(args.get("patch") or ""),
            )
        )
    if name == "run_command":
        return _text(
            _run_command(
                str(args.get("command") or ""),
                str(args.get("cwd") or ""),
                int(args.get("timeout") or 120),
            )
        )
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
            int(args.get("max_tokens") or 1024),
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
                    "list_skills/get_skill/load_skills for workflows, run_checks to "
                    "verify, and delegate to run a real local Codex/Claude agent on "
                    "a project (read-only unless write=true; it never skips the "
                    "human's approvals). Navigate code with repo_map/repo_search/"
                    "repo_read and edit with repo_write/repo_edit/repo_patch. "
                    "Task packs (pentest, legal, forensics, ...) via list_packs/"
                    "pack_profile. Browser control via browser_open/observe/act/"
                    "screenshot/close. Hugging Face: hf_status, search_hf_models/"
                    "hf_model_info, search_hf_datasets/hf_dataset_info, "
                    "list_hf_local. Downloads are an explicit CLI action "
                    "(`sovereign hf download`). Run shell commands via "
                    "run_command (requires SOVEREIGN_MCP_COMPUTER=1). "
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
