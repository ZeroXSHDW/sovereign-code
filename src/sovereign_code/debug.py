"""Debugger utilities for Sovereign Code.

Four faces:
1. Run a Python script under pdb.
2. Trace one HTTP request/response.
3. Run a debugging task through the local gateway.
4. Tail recent log lines and swallowed exceptions.
"""

from __future__ import annotations

import json
import os
import pdb
import runpy
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import httpx

from .config import LOCAL_AI_ROOT, Settings
from .logs import resolve_log_path, tail_lines
from .safefile import ensure_private_dir, open_private

DEBUG_LOG = LOCAL_AI_ROOT / "data" / "logs" / "debug.log"


def _debug_dir() -> Path:
    return ensure_private_dir(DEBUG_LOG.parent)


def _write_debug_record(kind: str, data: dict[str, Any]) -> None:
    """Append a structured line to the debug log."""
    try:
        _debug_dir()
        record = {"ts": time.time(), "kind": kind, **data}
        with open_private(DEBUG_LOG, "a") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


def run_under_pdb(script: Path, args: list[str], env: dict[str, str] | None = None) -> int:
    """Run ``script`` under the standard :mod:`pdb` debugger.

    The script's directory is added to ``sys.path`` so local imports work the
    same way they would if the script were run directly. Extra environment
    variables are merged into ``os.environ`` for the process.
    """
    target = Path(script).resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    if env:
        os.environ.update(env)
    sys.argv = [str(target), *args]
    directory = target.parent
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    _write_debug_record("pdb_start", {"script": str(target), "args": args})
    try:
        pdb.run(
            f"runpy.run_path({str(target)!r}, run_name='__main__')",
            globals={"runpy": runpy},
        )
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        _write_debug_record("pdb_exit", {"script": str(target), "code": code})
        return code
    except BaseException as exc:
        _write_debug_record(
            "pdb_exception",
            {"script": str(target), "type": type(exc).__name__, "message": str(exc)},
        )
        raise
    _write_debug_record("pdb_exit", {"script": str(target), "code": 0})
    return 0


def trace_http(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_data: dict[str, Any] | list[Any] | None = None,
    data: str | bytes | None = None,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Make one HTTP request and return a structured trace record.

    The record contains the request line, headers, body, response status,
    response headers and the first part of the response body. Nothing is
    streamed; this is for inspecting a single call, not for production traffic.
    """
    from .http import local_client

    request_headers = dict(headers) if headers else {}
    method = method.upper()
    client = local_client(timeout=timeout, transport=transport)
    started = time.time()
    try:
        response = client.request(
            method,
            url,
            headers=request_headers,
            json=json_data,
            content=data,
        )
    except httpx.HTTPError as exc:
        record = {
            "url": url,
            "method": method,
            "request_headers": request_headers,
            "duration_ms": round((time.time() - started) * 1000, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_debug_record("http_trace", record)
        raise
    text = response.text
    record = {
        "url": url,
        "method": method,
        "request_headers": request_headers,
        "status": response.status_code,
        "response_headers": dict(response.headers),
        "body_preview": text[:4000],
        "body_bytes": len(response.content),
        "duration_ms": round((time.time() - started) * 1000, 2),
    }
    _write_debug_record("http_trace", record)
    return record


def _load_debugging_skill(task: str) -> str:
    """Load a debugging skill body if one is available, otherwise return ''."""
    from .skills import read_skill, render_skill

    skill = read_skill("debugging-and-error-recovery")
    if skill is not None:
        return "\n\n" + render_skill(skill, task)
    return ""


def debug_task(task: str, model: str = "best", max_tokens: int = 2000) -> str:
    """Send ``task`` to the local gateway with the debugging skill loaded.

    The gateway is queried through the same path the MCP server uses, so this
    works whether the gateway is up or not and returns the model's answer.
    """
    from .summarize import complete

    settings = Settings.load()
    system = (
        "You are a debugging assistant. Help reproduce, isolate and fix the "
        "problem described by the user. Be concise and actionable."
    )
    system += _load_debugging_skill(task)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    _write_debug_record("debug_task", {"task": task, "model": model})
    return complete(settings.router_url, model, messages, max_tokens=max_tokens)


def recent_logs(target: str, count: int = 40) -> list[str]:
    """Return the last ``count`` lines of a named log target."""
    return tail_lines(resolve_log_path(target), count)


def recent_swallowed(count: int = 40) -> list[str]:
    """Return the last ``count`` lines from the swallowed-exception log."""
    from .diagnostics import LOG_NAME

    path = LOCAL_AI_ROOT / "data" / "logs" / LOG_NAME
    return tail_lines(path, count)


def recent_debug_records(count: int = 40) -> list[dict[str, Any]]:
    """Return parsed recent records from the debug log."""
    lines = tail_lines(DEBUG_LOG, count)
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except (ValueError, TypeError):
            records.append({"raw": line})
    return records


def format_trace_record(record: dict[str, Any]) -> str:
    """Pretty-print a trace record for terminal output."""
    lines: list[str] = []
    lines.append(f"> {record.get('method', 'GET')} {record.get('url', '')}")
    for key, value in record.get("request_headers", {}).items():
        lines.append(f"> {key}: {value}")
    if record.get("body_preview"):
        lines.append("")
        lines.append(record["body_preview"])
    lines.append("")
    status = record.get("status")
    if status is not None:
        lines.append(f"< HTTP {status}")
    else:
        lines.append(f"< ERROR {record.get('error', 'unknown')}")
    for key, value in record.get("response_headers", {}).items():
        lines.append(f"< {key}: {value}")
    duration = record.get("duration_ms")
    if duration is not None:
        lines.append(f"< duration: {duration} ms")
    return "\n".join(lines)


def current_traceback_text() -> str:
    """Return the current Python stack as a string."""
    return "".join(traceback.format_stack())
