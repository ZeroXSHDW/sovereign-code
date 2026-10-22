"""Anthropic Messages bridge for local and gateway models.

Claude Code speaks the Anthropic Messages API and streams tool calls as
``tool_use`` content blocks. LiteLLM's streamed Ollama translation emits the
tool call as plain text, so Claude Code prints JSON instead of editing files.
This bridge accepts Anthropic requests, asks the gateway for a **non-streaming**
OpenAI completion (where LiteLLM's tool-call translation is correct), then
re-emits the result as Anthropic JSON or SSE.

It works for every gateway alias: local Ollama models, Ollama Cloud, and
provider routes. No cloud key is needed for local work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .tier_gateway import CLAUDE_MODEL_ROUTES

DEFAULT_PORT = 4001
DEFAULT_GATEWAY = "http://127.0.0.1:4010"
DEFAULT_ALIAS = "local-agent"

# Claude Code sends a real Claude model id unless it is told otherwise. Map the
# ids it knows onto the local routes so a plain `claude` still works, and so
# every name in the map is a name the tier gateway can route.
MODEL_MAP: dict[str, str] = dict(CLAUDE_MODEL_ROUTES)


def resolve_model(model: str | None, default: str = DEFAULT_ALIAS) -> str:
    name = (model or "").strip()
    if not name:
        return default
    if name in MODEL_MAP:
        return MODEL_MAP[name]
    if name.startswith("claude-"):
        return default
    return name


def local_models() -> list[dict[str, Any]]:
    """The local models in the shape Anthropic's model list uses.

    The list comes from the tier gateway's catalog, so Claude Code and ChatGPT
    see the same local models, and every name in it can actually be routed.
    """
    from .tier_gateway import catalog_models, installed_models

    return [
        {
            "type": "model",
            "id": str(entry["id"]),
            "display_name": str(entry["id"]),
            "created_at": "2026-01-01T00:00:00Z",
        }
        for entry in catalog_models(installed_models())
    ]


def _text_of(content: Any) -> str:
    """Flatten a string or a list of Anthropic text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part)
    return ""


def _image_block(block: dict[str, Any]) -> dict[str, Any] | None:
    source = block.get("source") or {}
    if source.get("type") != "base64" or not source.get("data"):
        return None
    media = source.get("media_type") or "image/png"
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media};base64,{source['data']}"},
    }


def convert_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Anthropic messages -> OpenAI chat messages, including tool results."""
    messages: list[dict[str, Any]] = []
    system = payload.get("system")
    if system:
        messages.append({"role": "system", "content": _text_of(system)})

    tool_names: dict[str, str] = {}
    for message in payload.get("messages") or []:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        blocks = content if isinstance(content, list) else []
        if role == "assistant":
            text: list[str] = []
            calls: list[dict[str, Any]] = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text.append(str(block.get("text") or ""))
                elif block.get("type") == "tool_use":
                    tool_id = str(block.get("id") or f"toolu_{uuid.uuid4().hex[:24]}")
                    name = str(block.get("name") or "tool")
                    tool_names[tool_id] = name
                    calls.append(
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(block.get("input") or {}),
                            },
                        }
                    )
            converted: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(part for part in text if part) or None,
            }
            if calls:
                converted["tool_calls"] = calls
            messages.append(converted)
            continue

        # A user turn can mix text, images, and tool results. OpenAI wants the
        # tool messages first, then the ordinary user content.
        user_text: list[str] = []
        parts: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                user_text.append(str(block.get("text") or ""))
            elif kind == "image":
                image = _image_block(block)
                if image:
                    parts.append(image)
            elif kind == "tool_result":
                result = block.get("content")
                result_text = result if isinstance(result, str) else _text_of(result)
                if not result_text and isinstance(result, list):
                    # Tool results may contain text blocks rather than text.
                    result_text = json.dumps(result)[:4000]
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(block.get("tool_use_id") or ""),
                        "content": result_text or "(no output)",
                    }
                )
        messages.extend(tool_messages)
        if user_text or parts:
            if parts:
                messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "\n".join(user_text)}, *parts],
                    }
                )
            else:
                messages.append({"role": "user", "content": "\n".join(user_text)})
    return messages


def convert_tools(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    tools = []
    for tool in payload.get("tools") or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": str(tool.get("description") or ""),
                    "parameters": tool.get("input_schema") or {"type": "object"},
                },
            }
        )
    choice = payload.get("tool_choice")
    if not isinstance(choice, dict):
        return tools, None
    kind = choice.get("type")
    if kind == "auto":
        return tools, "auto"
    if kind == "any":
        return tools, "required"
    if kind == "none":
        return tools, "none"
    if kind == "tool" and choice.get("name"):
        return tools, {"type": "function", "function": {"name": choice["name"]}}
    return tools, None


def to_openai_request(
    payload: dict[str, Any], default_model: str = DEFAULT_ALIAS
) -> dict[str, Any]:
    """The non-streaming gateway request that corresponds to an Anthropic call."""
    model = resolve_model(payload.get("model"), default_model)
    request: dict[str, Any] = {
        "model": model,
        "messages": convert_messages(payload),
        "max_tokens": int(payload.get("max_tokens") or 4096),
        "temperature": float(payload.get("temperature", 0.2)),
        "stream": False,
    }
    tools, choice = convert_tools(payload)
    if tools:
        request["tools"] = tools
        if choice is not None:
            request["tool_choice"] = choice
    stop = payload.get("stop_sequences")
    if stop:
        request["stop"] = stop
    return request


def to_anthropic_response(data: dict[str, Any], model: str) -> dict[str, Any]:
    """OpenAI chat completion -> Anthropic Messages response."""
    choices = data.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    content: list[dict[str, Any]] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        content.append({"type": "text", "text": text})
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except (TypeError, ValueError):
            parsed = {"raw": arguments}
        content.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}"),
                "name": str(function.get("name") or "tool"),
                "input": parsed if isinstance(parsed, dict) else {"value": parsed},
            }
        )
    if not content:
        content.append({"type": "text", "text": ""})

    finish = str(choice.get("finish_reason") or "")
    if message.get("tool_calls"):
        stop_reason = "tool_use"
    elif finish == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "end_turn"
    usage = data.get("usage") or {}
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


def _event(name: str, data: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def message_start_event(message: dict[str, Any]) -> bytes:
    usage = message.get("usage") or {}
    return _event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message["id"],
                "type": "message",
                "role": "assistant",
                "model": message["model"],
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": 0},
            },
        },
    )


def sse_events(message: dict[str, Any], include_start: bool = True) -> Iterable[bytes]:
    """Render one Anthropic message as the SSE stream Claude Code expects."""
    usage = message.get("usage") or {}
    if include_start:
        yield message_start_event(message)
    for index, block in enumerate(message.get("content") or []):
        if block.get("type") == "text":
            yield _event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "text", "text": ""},
                },
            )
            text = str(block.get("text") or "")
            if text:
                yield _event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )
        elif block.get("type") == "tool_use":
            yield _event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {
                        "type": "tool_use",
                        "id": block["id"],
                        "name": block["name"],
                        "input": {},
                    },
                },
            )
            yield _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(block.get("input") or {}),
                    },
                },
            )
        yield _event(
            "content_block_stop",
            {"type": "content_block_stop", "index": index},
        )
    yield _event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": message.get("stop_reason"),
                "stop_sequence": None,
            },
            "usage": {"output_tokens": usage.get("output_tokens", 0)},
        },
    )
    yield _event("message_stop", {"type": "message_stop"})


def completion(gateway_url: str, payload: dict[str, Any], timeout: float = 600.0) -> dict[str, Any]:
    """Ask the gateway for a non-streaming chat completion."""
    request = to_openai_request(payload)
    base = gateway_url.rstrip("/")
    try:
        response = httpx.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": "Bearer local"},
            json=request,
            timeout=httpx.Timeout(timeout, connect=5.0),
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"gateway unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200:
        detail = response.text.replace("\n", " ")[:400]
        raise RuntimeError(f"gateway HTTP {response.status_code}: {detail}")
    return response.json()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SovereignBridge/1.0"

    # Injected by make_server.
    gateway_url = DEFAULT_GATEWAY
    default_model = DEFAULT_ALIAS

    def log_message(self, *args: Any) -> None:  # keep Claude's stderr clean
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in ("/health", "/"):
            self._json(200, {"ok": True, "gateway": self.gateway_url})
            return
        if path == "/v1/models":
            self._json(200, {"data": local_models()})
            return
        self._json(404, {"type": "error", "error": {"type": "not_found_error"}})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            payload = self._read()
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"type": "error", "error": {"type": "invalid_request_error"}})
            return
        if path == "/v1/messages/count_tokens":
            estimate = max(1, len(json.dumps(payload)) // 4)
            self._json(200, {"input_tokens": estimate})
            return
        if path != "/v1/messages":
            self._json(404, {"type": "error", "error": {"type": "not_found_error"}})
            return
        model = resolve_model(payload.get("model"), self.default_model)
        if payload.get("stream"):
            # Headers and message_start go out before the model runs. Claude
            # closes a connection that has not produced a byte within its
            # first-response timeout, and a local 34k-token prompt can take
            # minutes to prefill.
            message_id = f"msg_{uuid.uuid4().hex[:24]}"
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.close_connection = True
                self.end_headers()
                estimate = max(1, len(json.dumps(payload)) // 4)
                self.wfile.write(
                    message_start_event(
                        {
                            "id": message_id,
                            "model": model,
                            "usage": {"input_tokens": estimate},
                        }
                    )
                )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            try:
                data = completion(self.gateway_url, payload)
                message = to_anthropic_response(data, model)
                message["id"] = message_id
                for chunk in sse_events(message, include_start=False):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            except (RuntimeError, ValueError) as exc:
                try:
                    self.wfile.write(
                        _event(
                            "error",
                            {
                                "type": "error",
                                "error": {"type": "api_error", "message": str(exc)[:400]},
                            },
                        )
                    )
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            return
        try:
            data = completion(self.gateway_url, payload)
        except (RuntimeError, ValueError) as exc:
            self._json(
                502,
                {
                    "type": "error",
                    "error": {"type": "api_error", "message": str(exc)},
                },
            )
            return
        self._json(200, to_anthropic_response(data, model))


def make_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    gateway_url: str = DEFAULT_GATEWAY,
    default_model: str = DEFAULT_ALIAS,
) -> ThreadingHTTPServer:
    handler = type(
        "SovereignBridgeHandler",
        (_Handler,),
        {"gateway_url": gateway_url, "default_model": default_model},
    )
    return ThreadingHTTPServer((host, port), handler)


def pid_path() -> Path:
    from .config import LOCAL_AI_ROOT

    return LOCAL_AI_ROOT / "data" / "bridge.pid"


def log_path() -> Path:
    from .config import LOCAL_AI_ROOT

    return LOCAL_AI_ROOT / "data" / "logs" / "bridge.log"


def port_open(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_running(
    gateway_url: str = DEFAULT_GATEWAY,
    port: int = DEFAULT_PORT,
    wait: float = 12.0,
) -> bool:
    """Start the bridge in the background if it is not already listening."""
    if port_open(port=port):
        return True
    # The bridge talks to the tier gateway by default; start it first.
    if gateway_url.rstrip("/").endswith(":4010"):
        try:
            from .tier_gateway import ensure_running as ensure_tier

            ensure_tier()
        except Exception:
            pass
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "sovereign_code",
        "bridge",
        "--port",
        str(port),
        "--gateway",
        gateway_url,
    ]
    try:
        with log.open("ab") as handle:
            process = subprocess.Popen(
                cmd,
                stdout=handle,
                stderr=handle,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
    except OSError:
        return False
    pid_path().parent.mkdir(parents=True, exist_ok=True)
    pid_path().write_text(str(process.pid), encoding="utf-8")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if port_open(port=port):
            return True
        time.sleep(0.2)
    return False


def stop() -> bool:
    try:
        pid = int(pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 15)
    except OSError:
        return False
    try:
        pid_path().unlink()
    except OSError:
        pass
    return True


def serve(host: str, port: int, gateway_url: str, default_model: str) -> None:
    if port_open(port=port):
        # Another instance owns the port. Exiting cleanly keeps launchd from
        # restarting this one into a fight with the server that is up.
        print(f"bridge already serving on {port}", flush=True)
        return
    pid_path().parent.mkdir(parents=True, exist_ok=True)
    pid_path().write_text(str(os.getpid()), encoding="utf-8")
    server = make_server(host, port, gateway_url, default_model)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            pid_path().unlink()
        except OSError:
            pass
