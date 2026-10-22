"""A latency-aware OpenAI-compatible gateway in front of LiteLLM/Ollama.

Small models should answer small work in a second or two; big models should be
reserved for the requests that need them. This server classifies each request,
picks a tier, and talks to Ollama natively (so streamed tool calls are correct,
unlike LiteLLM's Ollama translation). Named aliases and cloud/provider models
are proxied to the existing LiteLLM gateway unchanged.

Endpoints:
  GET  /health
  GET  /v1/models
  GET  /metrics
  POST /v1/chat/completions   (stream and non-stream)
  POST /v1/responses          (Responses API for Codex, stream and non-stream)
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4010
DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_UPSTREAM = "http://127.0.0.1:4000"

# A wedged model used to hold the single-resident lock for ten minutes. These
# bounds turn "looks hung" into either a fallback model or an explicit error.
DEFAULT_REQUEST_TIMEOUT = 300.0
DEFAULT_STREAM_IDLE_TIMEOUT = 180.0


def _seconds(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def request_timeout() -> float:
    """Total time one non-streaming model may take before the next is tried."""
    return _seconds("SOVEREIGN_REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT)


def stream_idle_timeout() -> float:
    """How long a stream may produce no bytes before it is treated as stuck."""
    return _seconds("SOVEREIGN_STREAM_IDLE_TIMEOUT", DEFAULT_STREAM_IDLE_TIMEOUT)


def local_only() -> bool:
    """Local-only is the default; set SOVEREIGN_LOCAL_ONLY=0 to allow cloud."""
    return os.environ.get("SOVEREIGN_LOCAL_ONLY", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _event(name: str, data: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


FAST, BALANCED, DEEP, ULTRA = "fast", "balanced", "deep", "ultra"
TIERS = (FAST, BALANCED, DEEP, ULTRA)

# tier -> (model, context, think)
TIER_MODELS: dict[str, tuple[str, int, bool | None]] = {
    FAST: ("qwen3.5:4b", 8192, False),
    BALANCED: ("qwen3.5:9b", 65536, False),
    # Deep coding uses the 30B MoE: measured 12.7 s vs 45.1 s for the dense
    # 27B on the same coding prompt. `ultra` keeps the 27B for the hardest
    # reasoning, where its quality is worth the latency.
    DEEP: ("qwen3-coder:30b", 32768, False),
    ULTRA: ("qwen3.8:27b", 16384, False),
}

MODEL_CONTEXT: dict[str, tuple[int, bool | None]] = {
    "qwen3.5:4b": (8192, False),
    "qwen3.5:9b": (65536, False),
    "qwen3-coder:30b": (32768, False),
    "glm-4.7-flash": (32768, False),
    "qwen3.8:27b": (16384, False),
}

FALLBACKS: dict[str, tuple[str, ...]] = {
    FAST: ("qwen3.5:4b", "qwen3.5:9b"),
    BALANCED: ("qwen3.5:9b", "qwen3.5:4b"),
    DEEP: ("qwen3-coder:30b", "glm-4.7-flash", "qwen3.8:27b", "qwen3.5:9b"),
    ULTRA: ("qwen3.8:27b", "qwen3-coder:30b", "glm-4.7-flash"),
}

# Names a client may put in `model` to ask for a tier.
TIER_ALIASES: dict[str, str | None] = {
    "auto": None,
    "sovereign": None,
    "sovereign-auto": None,
    "local-auto": None,
    "fast": FAST,
    "sovereign-fast": FAST,
    "local-fast": FAST,
    "balanced": BALANCED,
    "sovereign-balanced": BALANCED,
    "local-chat": BALANCED,
    "deep": DEEP,
    "sovereign-deep": DEEP,
    "local-code": DEEP,
    "local-agent": DEEP,
    "local-reasoning": DEEP,
    "local-thinking": DEEP,
    "ultra": ULTRA,
    "sovereign-ultra": ULTRA,
    "local-ultra": ULTRA,
}

# Local aliases with a fixed model/context that do not fit the three tiers.
EXPLICIT_LOCAL: dict[str, tuple[str, int, bool | None]] = {
    "local-claude": ("qwen3.5:9b", 65536, False),
    "local-vision": ("qwen3.8:27b", 16384, False),
    "local-vision-deep": ("qwen3.8:27b", 16384, False),
    "local-review": ("gemma4:12b", 16384, False),
    "local-glm": ("glm-4.7-flash", 32768, False),
    "local-gptoss": ("gpt-oss:20b", 16384, False),
    "local-browser-nav": ("qwen3.8:27b", 16384, False),
    "local-code-dense": ("qwen2.5-coder:14b", 32768, False),
}

_CODE_SIGNALS = (
    "```",
    "def ",
    "class ",
    "function ",
    "traceback",
    "stack trace",
    "exception",
    "compile",
    "refactor",
    "implement",
    "debug",
    "unit test",
    "pytest",
    "bug",
    "fix ",
    "python",
    "typescript",
    "javascript",
    "sql",
    "regex",
    "api endpoint",
    "architecture",
    "migration",
    "security",
    "performance",
    "optimize",
    "docker",
    "kubernetes",
)
_REASON_SIGNALS = (
    "prove",
    "analyze",
    "analyse",
    "compare",
    "trade-off",
    "tradeoff",
    "design",
    "explain why",
    "step by step",
    "root cause",
    "plan",
    "reason",
    "evaluate",
    "critique",
    "strategy",
)
_SIMPLE_SIGNALS = (
    "say ",
    "reply",
    "respond",
    "thanks",
    "what is",
    "who is",
    "translate",
    "capital of",
    "define ",
    "how do you spell",
)

FAST_TOKENS = 240
BALANCED_TOKENS = 1200


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    text = json.dumps(messages, default=str)
    return max(1, len(text) // 4)


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in ("text", "input_text")
        )
    return ""


def has_signal(text: str, signals: tuple[str, ...]) -> bool:
    import re

    return any(
        re.search(rf"(?<!\w){re.escape(signal.strip())}(?!\w)", text)
        for signal in signals
        if signal.strip()
    )


def clean_user_text(text: str) -> str:
    """Drop Claude Code's inline <system-reminder> blocks before classification."""
    import re

    return re.sub(r"<system-reminder>.*?</system-reminder>", " ", text, flags=re.S).strip()


def classify(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    forced: str | None = None,
) -> tuple[str, str]:
    """Return (tier, short reason). Deterministic and cheap."""
    if forced in TIERS:
        return forced, "forced by tier header"
    # System prompts in coding agents contain words like "implement" and code
    # fences; classifying on them sent every short Qwen request to the 27B.
    user_messages = [
        message
        for message in messages
        if isinstance(message, dict) and message.get("role") != "system"
    ]
    tokens = estimate_tokens(user_messages)
    total_tokens = estimate_tokens(messages)
    text = clean_user_text(" ".join(_text_of(message) for message in user_messages)).lower()
    has_tools = bool(tools)
    code = any(signal in text for signal in _CODE_SIGNALS)
    reason = any(signal in text for signal in _REASON_SIGNALS)
    simple = has_signal(text, _SIMPLE_SIGNALS)
    turns = len(messages)

    # Agent clients (Qwen, Codex, Claude, OpenCode) send tools on every turn
    # and their prompt contains code by definition. Sending all of that to the
    # 27B made every "hi" a 30-second, memory-hungry request. Tools mostly need
    # a reliable 9B; the 27B is for genuinely large tool tasks.
    if has_tools:
        if tokens > 15000:
            return DEEP, "large tool task"
        return BALANCED, "tool use"
    if turns >= 8:
        return DEEP, "long conversation"
    if total_tokens > 28000:
        return DEEP, "large context"
    if tokens > BALANCED_TOKENS or code or reason:
        return DEEP, "complex/code/reasoning prompt"
    if turns >= 4:
        return BALANCED, "multi-turn"
    if tokens <= FAST_TOKENS and simple:
        return FAST, "simple short prompt"
    if tokens <= FAST_TOKENS:
        if total_tokens > 7000:
            return BALANCED, "short prompt but large system context"
        return FAST, "short prompt"
    return BALANCED, "medium prompt"


def _model_available(model: str, installed: set[str]) -> bool:
    if not installed:
        return True
    return model in installed or f"{model}:latest" in installed


QUALITY_ALIASES = {
    "best",
    "quality",
    "sovereign-best",
    "sovereign-quality",
    "local-best",
    "local-quality",
}

# Claude Code's own model ids and the local route each one uses. The bridge
# maps what Claude sends onto these routes, and the client setup writes the
# ids into Claude's settings, so the two cannot drift apart.
CLAUDE_MODEL_ROUTES: dict[str, str] = {
    "claude-sonnet-4-5": "deep",
    "claude-sonnet-4-5-20250929": "deep",
    "claude-opus-4-1": "ultra",
    "claude-opus-4-1-20250805": "ultra",
    "claude-3-7-sonnet-latest": "deep",
    "claude-3-5-haiku-latest": "fast",
    "claude-haiku-4-5": "fast",
}

# The Claude slots, and the model id and local route behind each of them.
CLAUDE_SLOT_MODELS: dict[str, tuple[str, str]] = {
    "ANTHROPIC_DEFAULT_SONNET_MODEL": ("claude-sonnet-4-5", "deep"),
    "ANTHROPIC_DEFAULT_OPUS_MODEL": ("claude-opus-4-1", "ultra"),
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": ("claude-haiku-4-5", "fast"),
    "ANTHROPIC_SMALL_FAST_MODEL": ("claude-haiku-4-5", "fast"),
}


ALIAS_INTENT: dict[str, str] = {
    "local-code": "code",
    "local-agent": "code",
    "local-reasoning": "reason",
    "local-thinking": "reason",
}


def task_user_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Claude Code appends a large skill/context user turn after the real prompt."""
    users = [
        message
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    for message in reversed(users):
        if len(_text_of(message)) <= 4000:
            return message
    return users[-1] if users else None


def is_simple_request(messages: list[dict[str, Any]]) -> bool:
    message = task_user_message(messages)
    if message is None:
        return False
    text = clean_user_text(_text_of(message)).lower()
    return estimate_tokens([{"role": "user", "content": text}]) <= 30 and has_signal(
        text, _SIMPLE_SIGNALS
    )


def detect_intent(messages: list[dict[str, Any]], tools: bool = False) -> str:
    message = task_user_message(messages)
    text = clean_user_text(_text_of(message)).lower() if message else ""
    if tools or any(signal in text for signal in _CODE_SIGNALS):
        return "code"
    if any(signal in text for signal in _REASON_SIGNALS):
        return "reason"
    return "general"


def choose_model(
    tier: str, installed: set[str], intent: str = "code"
) -> tuple[str, int, bool | None]:
    order = FALLBACKS[tier]
    if tier == DEEP and intent == "reason":
        order = ("glm-4.7-flash", "qwen3.8:27b", "qwen3-coder:30b", "qwen3.5:9b")
    for model in order:
        if _model_available(model, installed):
            context, think = MODEL_CONTEXT.get(model, (TIER_MODELS[tier][1], TIER_MODELS[tier][2]))
            return model, context, think
    context, think = MODEL_CONTEXT.get(
        TIER_MODELS[tier][0], (TIER_MODELS[tier][1], TIER_MODELS[tier][2])
    )
    return TIER_MODELS[tier][0], context, think


# The only local model that holds a Claude Code sized prompt on this Mac.
LONG_CONTEXT_MODEL = "qwen3.5:9b"
LONG_CONTEXT_TOKENS = 65536


def fit_to_context(model: str, context: int, needed: int, installed: set[str]) -> tuple[str, int]:
    """Serve a request that does not fit the chosen model with a bigger one.

    A 16k model cannot hold a 30k Claude Code prompt, and the client that sent
    it has no way to know which model will answer. The 9B takes 64k, so the
    request is answered instead of truncated.
    """
    if needed <= context:
        return model, context
    if needed > LONG_CONTEXT_TOKENS:
        return model, context
    if not _model_available(LONG_CONTEXT_MODEL, installed):
        return model, context
    return LONG_CONTEXT_MODEL, LONG_CONTEXT_TOKENS


def catalog_models(installed: set[str] | None = None) -> list[dict[str, Any]]:
    """Every model name a client can ask for, and the model behind it.

    Both gateways serve this list, so ChatGPT and Claude see exactly the
    local models the router accepts. A name that is missing here is a name no
    client can use, and a name in here is always routable.
    """
    installed = installed if installed is not None else set()
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        model_id: str,
        owned_by: str,
        tier: str = "",
        model: str = "",
        context: int = 0,
    ) -> None:
        if model_id in seen:
            return
        seen.add(model_id)
        target = model or model_id
        entries.append(
            {
                "id": model_id,
                "object": "model",
                "owned_by": owned_by,
                "tier": tier,
                "model": target,
                "context": context,
                "installed": not installed or _model_available(target, installed),
            }
        )

    # The tiers: the names every client config uses.
    for tier in TIERS:
        model, context, _think = TIER_MODELS[tier]
        add(tier, "sovereign", tier=tier, model=model, context=context)

    # The quality route: "best" and "auto" pick a tier per request.
    for alias in ("auto", "best", "quality"):
        add(alias, "sovereign", tier="auto")

    # The aliases that name a model directly.
    for alias, (model, context, _think) in EXPLICIT_LOCAL.items():
        add(alias, "sovereign", model=model, context=context)

    # The remaining route names: the tier aliases and the quality variants.
    for alias, tier in TIER_ALIASES.items():
        if alias in seen:
            continue
        if tier is None:
            add(alias, "sovereign", tier="auto")
            continue
        model, context, _think = TIER_MODELS[tier]
        add(alias, "sovereign", tier=tier, model=model, context=context)
    for alias in QUALITY_ALIASES:
        add(alias, "sovereign", tier="auto")

    # The models Ollama has installed, so a client can name one directly.
    for tag in sorted(installed):
        if "embed" in tag.lower() or tag.endswith(":cloud"):
            # An embedding model cannot answer a chat turn, and a cloud model
            # is not a local one: the local-only gateway refuses it.
            continue
        name = tag.removesuffix(":latest") if tag.endswith(":latest") else tag
        if name in seen:
            continue
        context, _think = MODEL_CONTEXT.get(name, (0, False))
        add(name, "ollama", model=name, context=context)

    return entries


def catalog_ids(installed: set[str] | None = None) -> set[str]:
    """The names in the catalog: every model a client may ask for."""
    return {str(entry["id"]) for entry in catalog_models(installed)}


_MODEL_LOCK = threading.Lock()
_SIZE_CACHE: tuple[float, dict[str, float]] | None = None


def _model_sizes(ollama: str) -> dict[str, float]:
    """name -> GB from /api/tags, cached briefly."""
    global _SIZE_CACHE
    now = time.monotonic()
    if _SIZE_CACHE and now - _SIZE_CACHE[0] < 20:
        return _SIZE_CACHE[1]
    sizes: dict[str, float] = {}
    try:
        response = httpx.get(f"{ollama.rstrip('/')}/api/tags", timeout=3.0)
        for item in response.json().get("models") or []:
            name = str(item.get("name") or "")
            if name:
                sizes[name] = round(float(item.get("size") or 0) / (1024**3), 2)
    except (httpx.HTTPError, ValueError):
        pass
    _SIZE_CACHE = (now, sizes)
    return sizes


def _loaded_models(ollama: str) -> list[tuple[str, float, int]]:
    try:
        response = httpx.get(f"{ollama.rstrip('/')}/api/ps", timeout=3.0)
        return [
            (
                str(item.get("name") or ""),
                round(float(item.get("size") or 0) / (1024**3), 2),
                int(item.get("context_length") or 0),
            )
            for item in response.json().get("models") or []
            if item.get("name")
        ]
    except (httpx.HTTPError, ValueError):
        return []


def ensure_model_room(model: str, ollama: str, context: int = 0) -> None:
    """Keep one model resident, so a 4B and an 18B never fight for 24 GB.

    Ollama reports an MLX/Metal out-of-memory panic when it tries to hold two
    large models. Evicting the other residents before a local call is slower
    than a cache hit but far faster than a failed request.
    """
    loaded = _loaded_models(ollama)
    for name, _size, loaded_ctx in loaded:
        same = name == model or name.removesuffix(":latest") == model.removesuffix(":latest")
        if same and (not context or not loaded_ctx or loaded_ctx >= context):
            continue
        try:
            httpx.post(
                f"{ollama.rstrip('/')}/api/generate",
                json={"model": name, "prompt": "", "stream": False, "keep_alive": 0},
                timeout=15.0,
            )
        except httpx.HTTPError:
            pass


def context_for_request(base: int, messages: list[dict[str, Any]], max_tokens: int = 0) -> int:
    """Use the smallest context that fits this request, not the tier maximum.

    A 65k KV allocation for a 9k prompt wastes memory and slows the first
    prefill. The tier maximum remains the ceiling.
    """
    needed = estimate_tokens(messages) + int(max_tokens or 0) + 512
    for size in (8192, 16384, 32768, 65536):
        if size >= needed:
            return min(base, size)
    return base


def _responses_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("input_text", "output_text", "text"):
                parts.append(str(part.get("text") or ""))
        return "\n".join(parts)
    return ""


def iter_chat_stream(response: httpx.Response) -> Iterable[dict[str, Any]]:
    """Parse an OpenAI-compatible SSE response into chunk objects."""
    for line in response.iter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if not isinstance(chunk, dict):
            continue
        if chunk.get("error"):
            error = chunk["error"]
            detail = error.get("message") if isinstance(error, dict) else error
            raise RuntimeError(f"upstream stream error: {str(detail)[:400]}")
        yield chunk


def _tier_headers(result: httpx.Response) -> dict[str, str]:
    """Carry the routing headers from the chat call to the Responses reply."""
    headers: dict[str, str] = {}
    for key in (
        "x-sovereign-tier",
        "x-sovereign-model",
        "x-sovereign-reason",
        "x-sovereign-fallback",
    ):
        value = result.headers.get(key)
        if value:
            headers[key] = value
    return headers


def responses_to_chat(payload: dict[str, Any], default_model: str = "auto") -> dict[str, Any]:
    """Translate an OpenAI Responses request into a chat-completions request."""
    messages: list[dict[str, Any]] = []
    instructions = payload.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": _responses_text(instructions)})
    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        for item in raw_input:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "function_call_output":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(item.get("call_id") or item.get("id") or ""),
                        "content": _responses_text(item.get("output")) or "(no output)",
                    }
                )
            elif kind == "function_call":
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": str(item.get("call_id") or item.get("id") or ""),
                                "type": "function",
                                "function": {
                                    "name": str(item.get("name") or "tool"),
                                    "arguments": item.get("arguments") or "{}",
                                },
                            }
                        ],
                    }
                )
            elif kind in ("message", "input_text", "output_text") or "role" in item:
                role = str(item.get("role") or "user")
                if kind == "input_text":
                    messages.append({"role": "user", "content": _responses_text(item)})
                else:
                    messages.append({"role": role, "content": _responses_text(item.get("content"))})
            elif "content" in item:
                messages.append(
                    {
                        "role": str(item.get("role") or "user"),
                        "content": _responses_text(item["content"]),
                    }
                )
    tools = []
    for tool in payload.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and tool.get("name"):
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": str(tool.get("description") or ""),
                        "parameters": tool.get("parameters") or {"type": "object"},
                    },
                }
            )
        elif tool.get("type") == "function" and (tool.get("function") or {}).get("name"):
            tools.append(tool)
    request: dict[str, Any] = {
        "model": str(payload.get("model") or default_model),
        "messages": messages,
        "max_tokens": int(payload.get("max_output_tokens") or 4096),
        "temperature": payload.get("temperature", 0.2),
        "stream": False,
    }
    if tools:
        request["tools"] = tools
        if payload.get("tool_choice") is not None:
            request["tool_choice"] = payload["tool_choice"]
    return request


def chat_to_responses(completion: dict[str, Any]) -> dict[str, Any]:
    """OpenAI chat completion -> Responses API object."""
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    output: list[dict[str, Any]] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        output.append(
            {
                "id": f"msg_{uuid.uuid4().hex[:20]}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content, "annotations": []}],
            }
        )
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        output.append(
            {
                "id": f"fc_{uuid.uuid4().hex[:20]}",
                "type": "function_call",
                "status": "completed",
                "call_id": str(call.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                "name": str(function.get("name") or "tool"),
                "arguments": arguments,
            }
        )
    if not output:
        output.append(
            {
                "id": f"msg_{uuid.uuid4().hex[:20]}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "", "annotations": []}],
            }
        )
    usage = completion.get("usage") or {}
    return {
        "id": f"resp_{uuid.uuid4().hex[:24]}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": str(completion.get("model") or ""),
        "output": output,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


def _response_item(
    item: dict[str, Any], status: str = "completed", blank: bool = False
) -> dict[str, Any]:
    clone = copy.deepcopy(item)
    clone["status"] = status
    if blank:
        if clone.get("type") == "message" and clone.get("content"):
            clone["content"][0]["text"] = ""
        if clone.get("type") == "function_call":
            clone["arguments"] = ""
    return clone


def responses_sse(
    response: dict[str, Any], include_start: bool = True, start_seq: int = 0
) -> Iterable[bytes]:
    """Render a Responses object as the SSE event sequence Codex expects."""
    seq = start_seq

    def event(name: str, data: dict[str, Any]) -> bytes:
        nonlocal seq
        data["sequence_number"] = seq
        seq += 1
        return _event(name, data)

    if include_start:
        yield event(
            "response.created",
            {
                "type": "response.created",
                "response": _response_item(response, "in_progress", blank=True),
            },
        )
        yield event(
            "response.in_progress",
            {
                "type": "response.in_progress",
                "response": _response_item(response, "in_progress", blank=True),
            },
        )
    for index, item in enumerate(response.get("output") or []):
        kind = item.get("type")
        blank = _response_item(item, "in_progress", blank=True)
        yield event(
            "response.output_item.added",
            {"type": "response.output_item.added", "output_index": index, "item": blank},
        )
        if kind == "message":
            text = str(((item.get("content") or [{}])[0]).get("text") or "")
            yield event(
                "response.content_part.added",
                {
                    "type": "response.content_part.added",
                    "item_id": item["id"],
                    "output_index": index,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
            )
            if text:
                yield event(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": item["id"],
                        "output_index": index,
                        "content_index": 0,
                        "delta": text,
                    },
                )
            yield event(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "item_id": item["id"],
                    "output_index": index,
                    "content_index": 0,
                    "text": text,
                },
            )
            yield event(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "item_id": item["id"],
                    "output_index": index,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": text, "annotations": []},
                },
            )
        elif kind == "function_call":
            arguments = str(item.get("arguments") or "")
            if arguments:
                yield event(
                    "response.function_call_arguments.delta",
                    {
                        "type": "response.function_call_arguments.delta",
                        "item_id": item["id"],
                        "output_index": index,
                        "delta": arguments,
                    },
                )
            yield event(
                "response.function_call_arguments.done",
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": item["id"],
                    "output_index": index,
                    "arguments": arguments,
                },
            )
        yield event(
            "response.output_item.done",
            {"type": "response.output_item.done", "output_index": index, "item": item},
        )
    yield event("response.completed", {"type": "response.completed", "response": response})


def responses_stream(
    chunks: Iterable[dict[str, Any]],
    response_id: str,
    model: str,
    start_seq: int = 0,
    include_start: bool = True,
) -> Iterable[bytes]:
    """Translate streaming chat chunks into Responses API SSE events.

    Text is emitted as ``response.output_text.delta`` while the model runs.
    Tool calls are buffered until the turn ends, because a Responses
    ``function_call`` carries one complete argument object.
    """
    seq = start_seq
    created_at = int(time.time())

    def event(name: str, data: dict[str, Any]) -> bytes:
        nonlocal seq
        data["sequence_number"] = seq
        seq += 1
        return _event(name, data)

    def response_object(status: str, output: list[dict[str, Any]], usage: dict[str, int]) -> dict:
        return {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "status": status,
            "model": model,
            "output": output,
            "usage": usage,
        }

    empty = response_object("in_progress", [], {})
    if include_start:
        yield event(
            "response.created",
            {"type": "response.created", "response": empty},
        )
        yield event(
            "response.in_progress",
            {"type": "response.in_progress", "response": empty},
        )

    text_open = False
    text_id = f"msg_{uuid.uuid4().hex[:20]}"
    text_index = 0
    next_index = 0
    text_parts: list[str] = []
    tools: dict[int, dict[str, str]] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    for chunk in chunks:
        if chunk.get("model"):
            model = str(chunk["model"])
        raw_usage = chunk.get("usage") or {}
        if raw_usage:
            usage = {
                "input_tokens": int(raw_usage.get("prompt_tokens") or usage["input_tokens"]),
                "output_tokens": int(raw_usage.get("completion_tokens") or usage["output_tokens"]),
                "total_tokens": int(raw_usage.get("total_tokens") or usage["total_tokens"]),
            }
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                if not text_open:
                    text_open = True
                    text_index = next_index
                    next_index += 1
                    yield event(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": text_index,
                            "item": {
                                "id": text_id,
                                "type": "message",
                                "status": "in_progress",
                                "role": "assistant",
                                "content": [],
                            },
                        },
                    )
                    yield event(
                        "response.content_part.added",
                        {
                            "type": "response.content_part.added",
                            "item_id": text_id,
                            "output_index": text_index,
                            "content_index": 0,
                            "part": {"type": "output_text", "text": "", "annotations": []},
                        },
                    )
                text_parts.append(text)
                yield event(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": text_id,
                        "output_index": text_index,
                        "content_index": 0,
                        "delta": text,
                    },
                )
            for call in delta.get("tool_calls") or []:
                try:
                    call_index = int(call.get("index") or 0)
                except (TypeError, ValueError):
                    call_index = 0
                slot = tools.setdefault(call_index, {"id": "", "name": "", "arguments": ""})
                if call.get("id"):
                    slot["id"] = str(call["id"])
                function = call.get("function") or {}
                if function.get("name"):
                    slot["name"] = str(function["name"])
                arguments = function.get("arguments")
                if isinstance(arguments, dict):
                    slot["arguments"] += json.dumps(arguments)
                elif isinstance(arguments, str):
                    slot["arguments"] += arguments
            # Some providers put tool calls on the message, not the delta.
            message = choice.get("message") or {}
            for call in message.get("tool_calls") or []:
                slot = tools.setdefault(
                    len(tools),
                    {"id": "", "name": "", "arguments": ""},
                )
                if call.get("id"):
                    slot["id"] = str(call["id"])
                function = call.get("function") or {}
                if function.get("name"):
                    slot["name"] = str(function["name"])
                arguments = function.get("arguments")
                if isinstance(arguments, dict):
                    slot["arguments"] += json.dumps(arguments)
                elif isinstance(arguments, str):
                    slot["arguments"] += arguments

    output: list[dict[str, Any]] = []
    text = "".join(text_parts)
    if text_open:
        part = {"type": "output_text", "text": text, "annotations": []}
        yield event(
            "response.output_text.done",
            {
                "type": "response.output_text.done",
                "item_id": text_id,
                "output_index": text_index,
                "content_index": 0,
                "text": text,
            },
        )
        yield event(
            "response.content_part.done",
            {
                "type": "response.content_part.done",
                "item_id": text_id,
                "output_index": text_index,
                "content_index": 0,
                "part": part,
            },
        )
        item = {
            "id": text_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [part],
        }
        yield event(
            "response.output_item.done",
            {"type": "response.output_item.done", "output_index": text_index, "item": item},
        )
        output.append(item)

    for call_index in sorted(tools):
        slot = tools[call_index]
        index = next_index
        next_index += 1
        raw_arguments = slot["arguments"].strip() or "{}"
        try:
            parsed = json.loads(raw_arguments)
        except ValueError:
            parsed = {"raw": raw_arguments}
        arguments = json.dumps(parsed)
        item_id = f"fc_{uuid.uuid4().hex[:20]}"
        call_id = slot["id"] or f"call_{uuid.uuid4().hex[:12]}"
        yield event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": index,
                "item": {
                    "id": item_id,
                    "type": "function_call",
                    "status": "in_progress",
                    "call_id": call_id,
                    "name": slot["name"] or "tool",
                    "arguments": "",
                },
            },
        )
        yield event(
            "response.function_call_arguments.delta",
            {
                "type": "response.function_call_arguments.delta",
                "item_id": item_id,
                "output_index": index,
                "delta": arguments,
            },
        )
        yield event(
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "item_id": item_id,
                "output_index": index,
                "arguments": arguments,
            },
        )
        item = {
            "id": item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": call_id,
            "name": slot["name"] or "tool",
            "arguments": arguments,
        }
        yield event(
            "response.output_item.done",
            {"type": "response.output_item.done", "output_index": index, "item": item},
        )
        output.append(item)

    if not output:
        empty_item = {
            "id": f"msg_{uuid.uuid4().hex[:20]}",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "", "annotations": []}],
        }
        yield event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**empty_item, "status": "in_progress", "content": []},
            },
        )
        yield event(
            "response.output_item.done",
            {"type": "response.output_item.done", "output_index": 0, "item": empty_item},
        )
        output.append(empty_item)

    if usage["total_tokens"] == 0:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    yield event(
        "response.completed",
        {
            "type": "response.completed",
            "response": response_object("completed", output, usage),
        },
    )


class ResponseCache:
    """Small LRU for non-streaming, tool-free, low-temperature responses."""

    def __init__(self, max_entries: int = 256, ttl: float = 600.0):
        self.max_entries = max_entries
        self.ttl = ttl
        self._data: dict[str, tuple[float, dict[str, Any]]] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    @staticmethod
    def key(request: dict[str, Any], tier: str, model: str) -> str:
        payload = {
            "tier": tier,
            "model": model,
            "messages": request.get("messages"),
            "temperature": request.get("temperature"),
            "max_tokens": request.get("max_tokens"),
            "stop": request.get("stop"),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if expires < time.monotonic():
                self._data.pop(key, None)
                return None
            return copy.deepcopy(value)

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, copy.deepcopy(value))
            self._order.append(key)
            while len(self._data) > self.max_entries:
                oldest = self._order.pop(0)
                self._data.pop(oldest, None)


CACHE = ResponseCache()
_METRICS_LOCK = threading.Lock()


def metrics_path() -> Path:
    from .config import LOCAL_AI_ROOT

    return LOCAL_AI_ROOT / "data" / "logs" / "tiers.jsonl"


def log_metric(event: dict[str, Any]) -> None:
    path = metrics_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > 5 * 1024 * 1024:
            path.replace(path.with_suffix(".jsonl.1"))
        with _METRICS_LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
    except OSError:
        pass


def metrics_summary(limit: int = 500) -> dict[str, Any]:
    path = metrics_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return {"requests": 0}
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    if not events:
        return {"requests": 0}
    by_tier: dict[str, dict[str, Any]] = {}
    for event in events:
        tier = str(event.get("tier") or "?")
        bucket = by_tier.setdefault(tier, {"count": 0, "ms": 0.0, "times": []})
        bucket["count"] += 1
        bucket["ms"] += float(event.get("ms") or 0)
        bucket["times"].append(float(event.get("ms") or 0))
    for bucket in by_tier.values():
        times = sorted(bucket.pop("times"))
        count = max(1, bucket["count"])
        bucket["avg_ms"] = round(bucket["ms"] / count)
        bucket["p50_ms"] = round(times[len(times) // 2]) if times else 0
        bucket["p95_ms"] = round(times[min(len(times) - 1, int(len(times) * 0.95))]) if times else 0
    return {"requests": len(events), "by_tier": by_tier}


def _convert_tool_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI history -> Ollama history (tool arguments are objects there)."""
    names: dict[str, str] = {}
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            calls = []
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {"raw": arguments}
                call_id = str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}")
                name = str(function.get("name") or "tool")
                names[call_id] = name
                calls.append({"id": call_id, "function": {"name": name, "arguments": arguments}})
            item: dict[str, Any] = {"role": "assistant", "content": _text_of(message)}
            if calls:
                item["tool_calls"] = calls
            converted.append(item)
            continue
        if role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "content": _text_of(message),
                    "tool_name": names.get(str(message.get("tool_call_id") or ""), "tool"),
                }
            )
            continue
        # Multimodal: keep text, lift data-URL images into Ollama's `images`.
        content = message.get("content")
        if isinstance(content, list):
            texts: list[str] = []
            images: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in ("text", "input_text"):
                    texts.append(str(part.get("text") or ""))
                elif part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url") or ""
                    if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                        images.append(url.split(";base64,", 1)[1])
            item = {"role": role, "content": "\n".join(texts)}
            if images:
                item["images"] = images
            converted.append(item)
            continue
        converted.append({"role": role, "content": _text_of(message)})
    return converted


def _openai_tool_calls(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for index, call in enumerate(raw):
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        calls.append(
            {
                "index": int(function.get("index", index) or 0),
                "id": str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                "type": "function",
                "function": {"name": str(function.get("name") or "tool"), "arguments": arguments},
            }
        )
    return calls


def repeated_tool_call(messages: list[dict[str, Any]]) -> bool:
    """Detect the same tool call repeating three times in the recent history."""
    signatures: list[tuple[tuple[str, str], ...]] = []
    for message in messages[-12:]:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            calls.append((str(function.get("name") or ""), str(function.get("arguments") or "")))
        if calls:
            signatures.append(tuple(calls))
    return len(signatures) >= 3 and len(set(signatures[-3:])) == 1


def truncate_tool_outputs(
    messages: list[dict[str, Any]], limit: int = 4000
) -> list[dict[str, Any]]:
    """Keep long tool results from consuming the whole context on long runs."""
    result = []
    for message in messages:
        if not isinstance(message, dict):
            result.append(message)
            continue
        if message.get("role") == "tool" and isinstance(message.get("content"), str):
            content = message["content"]
            if len(content) > limit:
                message = {
                    **message,
                    "content": content[:limit] + "\n[tool output truncated by Sovereign]",
                }
        result.append(message)
    return result


def compact_messages(messages: list[dict[str, Any]], context: int) -> list[dict[str, Any]]:
    """Keep the task anchor and recent turns when a long session exceeds context."""
    budget = max(1024, int(context * 0.72))
    if estimate_tokens(messages) <= budget:
        return messages
    system = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
    anchor = next(
        (m for m in messages if isinstance(m, dict) and m.get("role") == "user"),
        None,
    )
    tail: list[dict[str, Any]] = []
    for message in reversed(messages):
        if message is anchor or message in system:
            continue
        candidate = system + ([anchor] if anchor else []) + list(reversed([*tail, message]))
        if estimate_tokens(candidate) > budget and tail:
            break
        tail.append(message)
    kept = system + ([anchor] if anchor else []) + list(reversed(tail))
    # A tool result without its assistant tool_call is invalid for Ollama.
    valid_ids: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for message in kept:
        role = message.get("role") if isinstance(message, dict) else None
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                if call.get("id"):
                    valid_ids.add(str(call["id"]))
        elif role == "tool" and str(message.get("tool_call_id") or "") not in valid_ids:
            continue
        cleaned.append(message)
    kept = cleaned
    note = {
        "role": "system",
        "content": (
            "Earlier conversation was compacted to fit the model context. "
            "Keep working from the task anchor and the most recent turns."
        ),
    }
    return [note, *kept]


def _ollama_payload(
    request: dict[str, Any],
    model: str,
    context: int,
    think: bool | None,
    stream: bool,
) -> dict[str, Any]:
    options: dict[str, Any] = {"num_ctx": int(context)}
    if request.get("temperature") is not None:
        options["temperature"] = float(request["temperature"])
    if request.get("top_p") is not None:
        options["top_p"] = float(request["top_p"])
    if request.get("max_tokens") is not None:
        options["num_predict"] = int(request["max_tokens"])
    if request.get("stop"):
        options["stop"] = request["stop"]
    messages = compact_messages(
        truncate_tool_outputs(_convert_tool_history(request.get("messages") or [])),
        context,
    )
    loop = repeated_tool_call(request.get("messages") or [])
    if loop:
        messages.append(
            {
                "role": "system",
                "content": (
                    "The same tool call has repeated three times. Stop calling tools "
                    "and answer with what you have, or explain what is blocking you."
                ),
            }
        )
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": bool(stream),
        "options": options,
        "keep_alive": request.get("keep_alive") or "15m",
    }
    if request.get("tools") and not loop:
        payload["tools"] = request["tools"]
        if request.get("tool_choice") is not None:
            payload["tool_choice"] = request["tool_choice"]
    if think is not None:
        payload["think"] = bool(think)
    return payload


def _completion(
    model: str,
    content: str,
    thinking: str,
    raw_calls: list[dict[str, Any]],
    usage: dict[str, int],
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    calls = _openai_tool_calls(raw_calls)
    if calls:
        message["tool_calls"] = calls
    if thinking:
        message["reasoning_content"] = thinking
    finish = "tool_calls" if calls else "stop"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        },
    }


def _chunk(model: str, delta: dict[str, Any], finish: str | None = None, cid: str = "") -> bytes:
    payload = {
        "id": cid or f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def _usage_chunk(model: str, usage: dict[str, int], cid: str = "") -> bytes:
    payload = {
        "id": cid or f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        },
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def _installed(ollama: str) -> set[str]:
    global _INSTALLED_CACHE
    now = time.monotonic()
    if _INSTALLED_CACHE and now - _INSTALLED_CACHE[0] < 20:
        return _INSTALLED_CACHE[1]
    try:
        response = httpx.get(f"{ollama.rstrip('/')}/api/tags", timeout=3.0)
        models = {
            str(item.get("name") or "")
            for item in response.json().get("models") or []
            if item.get("name")
        }
    except (httpx.HTTPError, ValueError):
        models = set()
    _INSTALLED_CACHE = (now, models)
    return models


_INSTALLED_CACHE: tuple[float, set[str]] | None = None


def installed_models(ollama: str = DEFAULT_OLLAMA) -> set[str]:
    """The Ollama tags this Mac has installed."""
    return _installed(ollama)


@dataclass(frozen=True)
class Route:
    kind: str  # "local" or "proxy"
    model: str
    tier: str
    context: int = 0
    think: bool | None = None
    reason: str = ""


def resolve_route(
    request: dict[str, Any],
    forced_tier: str | None = None,
    installed: set[str] | None = None,
) -> Route:
    model = str(request.get("model") or "auto")
    installed = installed if installed is not None else set()
    if forced_tier in TIERS:
        model = forced_tier
    needed = (
        estimate_tokens(request.get("messages") or []) + int(request.get("max_tokens") or 0) + 512
    )
    if model == "local-claude":
        # Quality-first for normal Claude turns; fall back to the 65k 9B only
        # when the prompt genuinely needs the larger context.
        simple = is_simple_request(request.get("messages") or [])
        if needed <= 30000 and not simple and _model_available("glm-4.7-flash", installed):
            context = context_for_request(
                32768, request.get("messages") or [], int(request.get("max_tokens") or 0)
            )
            return Route(
                "local",
                "glm-4.7-flash",
                DEEP,
                context,
                False,
                "claude quality/glm",
            )
        target, context, think = EXPLICIT_LOCAL["local-claude"]
        context = context_for_request(
            context, request.get("messages") or [], int(request.get("max_tokens") or 0)
        )
        return Route(
            "local",
            target,
            BALANCED,
            context,
            think,
            "claude simple" if simple else "claude long context",
        )
    if model in EXPLICIT_LOCAL:
        target, context, think = EXPLICIT_LOCAL[model]
        if not _model_available(target, installed):
            target, context, think = choose_model(BALANCED, installed)
        tier = BALANCED
        context = context_for_request(
            context, request.get("messages") or [], int(request.get("max_tokens") or 0)
        )
        target, context = fit_to_context(target, context, needed, installed)
        return Route("local", target, tier, context, think, f"explicit {model}")
    if model in QUALITY_ALIASES:
        intent = detect_intent(request.get("messages") or [], bool(request.get("tools")))
        if is_simple_request(request.get("messages") or []) or needed > 30000:
            tier = BALANCED
        elif intent == "reason" and not request.get("tools") and needed <= 16000:
            tier = ULTRA
        else:
            tier = DEEP
        target, context, think = choose_model(tier, installed, intent)
        context = context_for_request(
            context, request.get("messages") or [], int(request.get("max_tokens") or 0)
        )
        target, context = fit_to_context(target, context, needed, installed)
        return Route("local", target, tier, context, think, f"quality {intent}/{tier}")
    if model in TIER_ALIASES:
        tier = TIER_ALIASES[model]
        if tier is None:
            tier, reason = classify(
                request.get("messages") or [], request.get("tools"), forced_tier
            )
        else:
            reason = f"alias {model}"
        intent = ALIAS_INTENT.get(model) or detect_intent(
            request.get("messages") or [], bool(request.get("tools"))
        )
        target, context, think = choose_model(tier, installed, intent)
        context = context_for_request(
            context, request.get("messages") or [], int(request.get("max_tokens") or 0)
        )
        target, context = fit_to_context(target, context, needed, installed)
        if tier in (DEEP, ULTRA):
            reason = f"{reason}/{intent}"
        return Route("local", target, tier, context, think, reason)
    if installed and not model.endswith(":cloud") and _model_available(model, installed):
        # A model name rather than a route: serve exactly that model, with the
        # context the catalog gives it. A client that names a model it can see
        # in the list must get that model.
        context, think = MODEL_CONTEXT.get(model, (32768, False))
        context = context_for_request(
            context, request.get("messages") or [], int(request.get("max_tokens") or 0)
        )
        target, context = fit_to_context(model, context, needed, installed)
        return Route("local", target, "", context, think, f"explicit model {model}")
    return Route("proxy", model, "", 0, None, "explicit upstream alias")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SovereignTierGateway/1.0"
    ollama = DEFAULT_OLLAMA
    upstream = DEFAULT_UPSTREAM

    def log_message(self, *args: Any) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(
        self,
        status: int,
        payload: dict[str, Any],
        extra: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        return data if isinstance(data, dict) else {}

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in ("/health", "/"):
            installed = _installed(self.ollama)
            self._json(
                200,
                {
                    "ok": True,
                    "upstream": self.upstream,
                    "ollama": self.ollama,
                    "tiers": {tier: choose_model(tier, installed, "code")[0] for tier in TIERS},
                    "local_only": local_only(),
                    "installed": sorted(installed),
                    "metrics": metrics_summary(),
                },
            )
            return
        if path == "/v1/models":
            installed = _installed(self.ollama)
            # The full catalog, so a client that asks for the model list sees
            # every name the router accepts instead of four tiers.
            self._json(200, {"object": "list", "data": catalog_models(installed)})
            return
        if path == "/metrics":
            self._json(200, metrics_summary())
            return
        self._json(404, {"error": {"message": "not found", "type": "not_found_error"}})

    def _stream_local(self, request: dict[str, Any], route: Route) -> None:
        _MODEL_LOCK.acquire()
        try:
            ensure_model_room(route.model, self.ollama, route.context)
        except Exception:
            pass
        payload = _ollama_payload(request, route.model, route.context, route.think, True)
        started = time.monotonic()
        cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        content: list[str] = []
        thinking: list[str] = []
        calls: list[dict[str, Any]] = []
        usage: dict[str, int] = {}
        finish = "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("x-sovereign-tier", route.tier)
        self.send_header("x-sovereign-model", route.model)
        self.send_header("x-sovereign-reason", route.reason)
        self._cors()
        self.close_connection = True
        self.end_headers()
        try:
            self.wfile.write(b": sovereign\n\n")
            self.wfile.write(_chunk(route.model, {"role": "assistant", "content": ""}, cid=cid))
            self.wfile.flush()
            with httpx.Client(timeout=httpx.Timeout(stream_idle_timeout(), connect=5)) as client:
                with client.stream(
                    "POST", f"{self.ollama.rstrip('/')}/api/chat", json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", "replace")[:400]
                        error = {"error": {"message": body, "type": "upstream_error"}}
                        self.wfile.write(f"data: {json.dumps(error)}\n\n".encode())
                        self.wfile.write(b"data: [DONE]\n\n")
                        return
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            continue
                        message = data.get("message") or {}
                        text = message.get("content") or ""
                        think = message.get("thinking") or ""
                        if think:
                            thinking.append(think)
                            self.wfile.write(
                                _chunk(route.model, {"reasoning_content": think}, cid=cid)
                            )
                        if text:
                            content.append(text)
                            self.wfile.write(_chunk(route.model, {"content": text}, cid=cid))
                        raw_calls = message.get("tool_calls") or []
                        if raw_calls:
                            converted = _openai_tool_calls(raw_calls)
                            calls.extend(converted)
                            self.wfile.write(
                                _chunk(
                                    route.model,
                                    {
                                        "tool_calls": [
                                            {
                                                "index": call["index"],
                                                "id": call["id"],
                                                "type": "function",
                                                "function": call["function"],
                                            }
                                            for call in converted
                                        ]
                                    },
                                    cid=cid,
                                )
                            )
                        if data.get("done"):
                            usage = {
                                "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                                "completion_tokens": int(data.get("eval_count") or 0),
                            }
                            if calls:
                                finish = "tool_calls"
                            elif data.get("done_reason") == "length":
                                finish = "length"
                            else:
                                finish = "stop"
                            break
                        self.wfile.flush()
            self.wfile.write(_chunk(route.model, {}, finish, cid=cid))
            self.wfile.write(_usage_chunk(route.model, usage, cid=cid))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except httpx.HTTPError as exc:
            # The read timeout is per byte, so this is a stalled model rather
            # than a slow prefill: say so and release the model lock instead of
            # leaving the client and every queued request waiting.
            message = (
                f"model stalled with no output for {stream_idle_timeout():.0f}s "
                f"({type(exc).__name__})"
            )
            try:
                error = {"error": {"message": message, "type": "upstream_timeout"}}
                self.wfile.write(f"data: {json.dumps(error)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            _MODEL_LOCK.release()
            log_metric(
                {
                    "ts": time.time(),
                    "tier": route.tier,
                    "model": route.model,
                    "ms": round((time.monotonic() - started) * 1000),
                    "stream": True,
                    "tools": bool(request.get("tools")),
                    "reason": route.reason,
                    "tokens": estimate_tokens(request.get("messages") or []),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                }
            )

    def _local(self, request: dict[str, Any], route: Route, cache_key: str = "") -> None:
        if request.get("stream"):
            self._stream_local(request, route)
            return
        original = route.model
        candidates = [route.model]
        if not route.reason.startswith("explicit"):
            candidates += [m for m in FALLBACKS.get(route.tier, ()) if m != route.model]
        started = time.monotonic()
        data: dict[str, Any] | None = None
        last_error = ""
        needed = estimate_tokens(request.get("messages") or []) + int(
            request.get("max_tokens") or 0
        )
        for candidate in candidates:
            context, think = MODEL_CONTEXT.get(candidate, (route.context, route.think))
            if candidate != route.model and context and context < needed:
                continue
            payload = _ollama_payload(request, candidate, context, think, False)
            _MODEL_LOCK.acquire()
            try:
                ensure_model_room(candidate, self.ollama, context)
            except Exception:
                pass
            try:
                response = httpx.post(
                    f"{self.ollama.rstrip('/')}/api/chat",
                    json=payload,
                    timeout=httpx.Timeout(request_timeout(), connect=5),
                )
                if response.status_code >= 400:
                    last_error = response.text[:500]
                    continue
                data = response.json()
                route = Route("local", candidate, route.tier, context, think, route.reason)
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = str(exc)
                continue
            finally:
                _MODEL_LOCK.release()
        if data is None:
            self._json(
                502,
                {
                    "error": {
                        "message": last_error or "local model failed",
                        "type": "upstream_error",
                    }
                },
            )
            return
        message = data.get("message") or {}
        raw_calls = message.get("tool_calls") or []
        calls = _openai_tool_calls(raw_calls)
        result = _completion(
            route.model,
            str(message.get("content") or ""),
            str(message.get("thinking") or ""),
            raw_calls,
            {
                "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                "completion_tokens": int(data.get("eval_count") or 0),
            },
        )
        if calls:
            result["choices"][0]["finish_reason"] = "tool_calls"
        if data.get("done_reason") == "length":
            result["choices"][0]["finish_reason"] = "length"
        log_metric(
            {
                "ts": time.time(),
                "tier": route.tier,
                "model": route.model,
                "ms": round((time.monotonic() - started) * 1000),
                "stream": False,
                "tools": bool(request.get("tools")),
                "reason": route.reason,
                "tokens": estimate_tokens(request.get("messages") or []),
                "prompt_tokens": result["usage"]["prompt_tokens"],
                "completion_tokens": result["usage"]["completion_tokens"],
            }
        )
        if cache_key:
            CACHE.put(cache_key, result)
        headers = {
            "x-sovereign-tier": route.tier,
            "x-sovereign-model": route.model,
            "x-sovereign-reason": route.reason,
        }
        if route.model != original:
            headers["x-sovereign-fallback"] = f"{original}->{route.model}"
        self._json(200, result, headers)

    def _proxy(self, request: dict[str, Any], route: Route) -> None:
        """Forward an explicit alias to LiteLLM, including its own streaming."""
        if local_only():
            self._json(
                403,
                {
                    "error": {
                        "message": (
                            f"{route.model} is a cloud route and this gateway is "
                            "local-only. Restart with SOVEREIGN_LOCAL_ONLY=0 to "
                            "allow cloud calls."
                        ),
                        "type": "local_only",
                    }
                },
                {"x-sovereign-local-only": "1"},
            )
            return
        stream = bool(request.get("stream"))
        headers = {"Authorization": "Bearer local", "Content-Type": "application/json"}
        try:
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("x-sovereign-tier", "upstream")
                self.send_header("x-sovereign-model", route.model)
                self._cors()
                self.close_connection = True
                self.end_headers()
                with httpx.Client(
                    timeout=httpx.Timeout(stream_idle_timeout(), connect=5)
                ) as client:
                    with client.stream(
                        "POST",
                        f"{self.upstream.rstrip('/')}/v1/chat/completions",
                        headers=headers,
                        json=request,
                    ) as response:
                        if response.status_code >= 400:
                            self.wfile.write(response.read())
                            return
                        for chunk in response.iter_bytes():
                            self.wfile.write(chunk)
                            self.wfile.flush()
            else:
                response = httpx.post(
                    f"{self.upstream.rstrip('/')}/v1/chat/completions",
                    headers=headers,
                    json=request,
                    timeout=httpx.Timeout(request_timeout(), connect=5),
                )
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.content)))
                self.send_header("x-sovereign-tier", "upstream")
                self.send_header("x-sovereign-model", route.model)
                self._cors()
                self.end_headers()
                self.wfile.write(response.content)
        except (httpx.HTTPError, BrokenPipeError, ConnectionResetError) as exc:
            try:
                self._json(502, {"error": {"message": str(exc), "type": "upstream_error"}})
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _responses(self, payload: dict[str, Any]) -> None:
        """Responses API adapter so Codex can use the tier gateway."""
        chat = responses_to_chat(payload)
        port = self.server.server_address[1]
        target = f"http://127.0.0.1:{port}/v1/chat/completions"
        stream = bool(payload.get("stream"))
        response_id = f"resp_{uuid.uuid4().hex[:24]}"
        model = str(payload.get("model") or "auto")
        if stream:
            chat["stream"] = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("x-sovereign-model", model)
            self._cors()
            self.close_connection = True
            self.end_headers()
            placeholder = {
                "id": response_id,
                "object": "response",
                "created_at": int(time.time()),
                "status": "in_progress",
                "model": model,
                "output": [],
                "usage": {},
            }
            try:
                self.wfile.write(b": sovereign\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(stream_idle_timeout(), connect=5)
                ) as client:
                    with client.stream("POST", target, json=chat) as result:
                        if result.status_code != 200:
                            body = result.read().decode("utf-8", "replace")[:400]
                            raise RuntimeError(body)
                        for chunk in responses_stream(
                            iter_chat_stream(result),
                            response_id,
                            model,
                            start_seq=2,
                        ):
                            self.wfile.write(chunk)
                            self.wfile.flush()
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                try:
                    self.wfile.write(
                        _event(
                            "response.failed",
                            {
                                "type": "response.failed",
                                "response": {
                                    **placeholder,
                                    "status": "failed",
                                    "error": {
                                        "code": "upstream_error",
                                        "message": str(exc)[:400],
                                    },
                                },
                            },
                        )
                    )
                except (BrokenPipeError, ConnectionResetError):
                    pass
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        try:
            with httpx.Client(timeout=httpx.Timeout(request_timeout(), connect=5)) as client:
                result = client.post(target, json=chat)
            if result.status_code != 200:
                raise RuntimeError(result.text[:400])
            response = chat_to_responses(result.json())
            response["id"] = response_id
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            self._json(
                502,
                {"error": {"message": str(exc)[:400], "type": "upstream_error"}},
            )
            return
        # The routing headers say which tier and model actually served the
        # request, so a client can tell "auto" apart from a fixed model.
        self._json(200, response, _tier_headers(result))

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in ("/v1/chat/completions", "/v1/responses"):
            self._json(404, {"error": {"message": "not found", "type": "not_found_error"}})
            return
        try:
            request = self._read()
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": {"message": "invalid JSON", "type": "invalid_request"}})
            return
        if path == "/v1/responses":
            self._responses(request)
            return
        forced = self.headers.get("x-sovereign-tier")
        installed = _installed(self.ollama)
        route = resolve_route(request, forced, installed)
        if route.kind == "proxy":
            self._proxy(request, route)
            return

        # Cache only simple, deterministic, tool-free calls.
        cacheable = (
            not request.get("stream")
            and not request.get("tools")
            and float(request.get("temperature") or 0.2) <= 0.3
            and int(request.get("max_tokens") or 0) <= 2048
            and self.headers.get("x-sovereign-cache", "").lower() != "off"
        )
        key = ResponseCache.key(request, route.tier, route.model) if cacheable else ""
        if cacheable:
            cached = CACHE.get(key)
            if cached is not None:
                log_metric(
                    {
                        "ts": time.time(),
                        "tier": route.tier,
                        "model": route.model,
                        "ms": 0,
                        "cached": True,
                        "stream": False,
                        "tools": False,
                    }
                )
                self._json(
                    200,
                    cached,
                    {
                        "x-sovereign-tier": route.tier,
                        "x-sovereign-model": route.model,
                        "x-sovereign-cached": "1",
                        "x-sovereign-reason": route.reason,
                    },
                )
                return
        # _local writes the response itself; capture it for the cache via a
        # second call is not worth it, so cache only on the non-stream path.
        self._local(request, route, key if cacheable else "")


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    ollama: str = DEFAULT_OLLAMA,
    upstream: str = DEFAULT_UPSTREAM,
) -> ThreadingHTTPServer:
    handler = type(
        "SovereignTierHandler",
        (_Handler,),
        {"ollama": ollama, "upstream": upstream},
    )
    return ThreadingHTTPServer((host, port), handler)


def pid_path() -> Path:
    from .config import LOCAL_AI_ROOT

    return LOCAL_AI_ROOT / "data" / "tier-gateway.pid"


def log_path() -> Path:
    from .config import LOCAL_AI_ROOT

    return LOCAL_AI_ROOT / "data" / "logs" / "tier-gateway.log"


def port_open(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_running(
    upstream: str = DEFAULT_UPSTREAM,
    ollama: str = DEFAULT_OLLAMA,
    port: int = DEFAULT_PORT,
    wait: float = 10.0,
) -> bool:
    if port_open(port=port):
        return True
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "sovereign_code",
        "router",
        "--port",
        str(port),
        "--upstream",
        upstream,
        "--ollama",
        ollama,
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


def warm_fast(ollama: str) -> None:
    """Load the 4B tier once so the first small request is not a cold start."""
    model, context, _think = TIER_MODELS[FAST]
    if not _model_available(model, _installed(ollama)):
        return
    _MODEL_LOCK.acquire()
    try:
        ensure_model_room(model, ollama, context)
        httpx.post(
            f"{ollama.rstrip('/')}/api/generate",
            json={
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": "15m",
                "options": {"num_ctx": context},
            },
            timeout=httpx.Timeout(120, connect=5),
        )
    except httpx.HTTPError:
        pass
    except Exception:  # a failed warm-up must never take the gateway down
        pass
    finally:
        _MODEL_LOCK.release()


def serve(host: str, port: int, ollama: str, upstream: str) -> None:
    if port_open(port=port):
        # Another instance owns the port. Exiting cleanly keeps launchd from
        # restarting this one into a fight with the server that is up.
        print(f"tier gateway already serving on {port}", flush=True)
        return
    pid_path().parent.mkdir(parents=True, exist_ok=True)
    pid_path().write_text(str(os.getpid()), encoding="utf-8")
    server = make_server(host, port, ollama, upstream)
    # Listen first, warm second: a restart used to refuse connections for as
    # long as the 4B model took to load. Requests that arrive during the warm-up
    # wait on the model lock; they are not rejected by a closed port.
    threading.Thread(
        target=warm_fast,
        args=(ollama,),
        name="sovereign-warm-fast",
        daemon=True,
    ).start()
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
