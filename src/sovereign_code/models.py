"""Known local models and runtime model views."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

CODING = "code"
CHAT = "chat"
REASON = "reason"
VISION = "vision"
FAST = "fast"
GENERAL = "general"
AGENT = "agent"


@dataclass(frozen=True)
class ModelSpec:
    tag: str
    role: str
    params_b: float
    size_gb: float
    max_context: int
    strengths: tuple[str, ...] = ()
    summary: str = ""
    recommended: bool = False

    @property
    def thinking(self) -> bool:
        return "thinking" in self.strengths


CATALOG: dict[str, ModelSpec] = {
    "qwen2.5-coder:14b": ModelSpec(
        tag="qwen2.5-coder:14b",
        role=CODING,
        params_b=14.7,
        size_gb=9.0,
        # 32k verified with OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0
        # (set by com.user.ollama.env). Without them the ceiling is 20,480.
        max_context=32768,
        strengths=("code", "refactor", "tools"),
        summary="Best coding model that fits 24 GB; verified at 32k with q8 KV.",
        recommended=True,
    ),
    "qwen2.5-coder:7b": ModelSpec(
        tag="qwen2.5-coder:7b",
        role=CODING,
        params_b=7.6,
        size_gb=4.7,
        max_context=32768,
        strengths=("code", "tools", "insert"),
        summary="Fast coder fallback; lower quality than 14B.",
    ),
    "qwen3.5:4b": ModelSpec(
        tag="qwen3.5:4b",
        role=CHAT,
        params_b=4.5,
        size_gb=4.0,
        max_context=65536,
        strengths=("chat", "vision", "tools", "thinking"),
        summary="Default fast chat/agent model with vision and tool use.",
    ),
    "gemma4:12b": ModelSpec(
        tag="gemma4:12b",
        role=REASON,
        params_b=12.4,
        size_gb=7.7,
        max_context=65536,
        strengths=("reason", "vision", "audio", "tools", "thinking"),
        summary="Stronger deep reasoning and vision; heavier memory use.",
    ),
    "llama3.1:8b": ModelSpec(
        tag="llama3.1:8b",
        role=REASON,
        params_b=8.0,
        size_gb=4.9,
        max_context=131072,
        strengths=("reason", "tools"),
        summary="Reliable reasoning fallback with a long context.",
    ),
    "mistral:latest": ModelSpec(
        tag="mistral:latest",
        role=GENERAL,
        params_b=7.2,
        size_gb=4.4,
        max_context=32768,
        strengths=("general", "tools"),
        summary="General-purpose 7B fallback.",
    ),
    "phi:latest": ModelSpec(
        tag="phi:latest",
        role=FAST,
        params_b=3.0,
        size_gb=1.6,
        max_context=2048,
        strengths=("fast",),
        summary="Tiny smoke-test model; not for real coding.",
    ),
}

TASK_PREFERENCE: dict[str, tuple[str, ...]] = {
    CODING: (
        "qwen2.5-coder:14b",
        "qwen2.5-coder:7b",
        "qwen3.5:4b",
        "llama3.1:8b",
    ),
    CHAT: (
        "qwen3.5:4b",
        "gemma4:12b",
        "llama3.1:8b",
        "mistral:latest",
    ),
    REASON: (
        "gemma4:12b",
        "llama3.1:8b",
        "qwen3.5:4b",
        "qwen2.5-coder:14b",
    ),
    VISION: (
        "gemma4:12b",
        "qwen3.5:4b",
    ),
    FAST: (
        "phi:latest",
        "qwen3.5:4b",
        "mistral:latest",
    ),
    GENERAL: (
        "qwen3.5:4b",
        "llama3.1:8b",
        "mistral:latest",
    ),
    # Agentic coding needs reliable tool calls, not just code knowledge.
    AGENT: (
        "gemma4:12b",
        "qwen3.5:4b",
        "llama3.1:8b",
        "qwen2.5-coder:14b",
        "qwen2.5-coder:7b",
    ),
}


@dataclass
class ModelView:
    spec: ModelSpec
    installed: bool = False
    loaded: bool = False
    size_gb: float = 0.0
    context: int | None = None
    vram_gb: float | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tag(self) -> str:
        return self.spec.tag

    @property
    def label(self) -> str:
        marker = "▶" if self.loaded else ("●" if self.installed else "↓")
        return f"{marker} {self.tag}"

    @property
    def status(self) -> str:
        if self.loaded:
            return f"loaded · {self.context or '?'} ctx"
        if self.installed:
            return f"installed · {self.size_gb:.1f} GB"
        return "not installed"


def parse_size_gb(value: Any) -> float:
    try:
        return round(float(value) / (1024**3), 2)
    except (TypeError, ValueError):
        return 0.0


def parse_params_b(value: Any) -> float | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    try:
        if text.endswith("B"):
            return float(text[:-1])
        if text.endswith("M"):
            return round(float(text[:-1]) / 1000, 2)
    except ValueError:
        return None
    return None


def _dynamic_spec(tag: str, size_gb: float, params: float | None, family: str) -> ModelSpec:
    return ModelSpec(
        tag=tag,
        role=GENERAL,
        params_b=params or 0.0,
        size_gb=size_gb,
        max_context=8192,
        strengths=(family.lower(),) if family else (),
        summary=f"Installed model ({family or 'unknown family'}).",
    )


def build_views(
    tags_payload: dict[str, Any] | None,
    ps_payload: dict[str, Any] | None,
    include_missing: bool = True,
) -> dict[str, ModelView]:
    """Merge /api/tags and /api/ps into a stable, display-ready mapping."""
    views: dict[str, ModelView] = {}
    for item in (tags_payload or {}).get("models", []):
        tag = item.get("name") or item.get("model")
        if not tag:
            continue
        size_gb = parse_size_gb(item.get("size"))
        details = item.get("details") or {}
        params = parse_params_b(details.get("parameter_size"))
        spec = CATALOG.get(tag) or _dynamic_spec(tag, size_gb, params, details.get("family", ""))
        views[tag] = ModelView(
            spec=spec,
            installed=True,
            size_gb=size_gb or spec.size_gb,
            capabilities=tuple(item.get("capabilities") or ()),
        )

    for item in (ps_payload or {}).get("models", []):
        tag = item.get("name") or item.get("model")
        if not tag:
            continue
        view = views.get(tag)
        if view is None:
            spec = CATALOG.get(tag) or _dynamic_spec(tag, parse_size_gb(item.get("size")), None, "")
            view = ModelView(spec=spec, installed=True, size_gb=parse_size_gb(item.get("size")))
            views[tag] = view
        view.loaded = True
        view.context = item.get("context_length")
        view.vram_gb = parse_size_gb(item.get("size_vram")) or None

    if include_missing:
        for tag, spec in CATALOG.items():
            if tag not in views:
                views[tag] = ModelView(spec=spec, installed=False, size_gb=spec.size_gb)

    return views


def installed_views(views: dict[str, ModelView]) -> list[ModelView]:
    return [v for v in views.values() if v.installed]


def sort_views(views: Iterable[ModelView]) -> list[ModelView]:
    def key(view: ModelView) -> tuple[int, int, int, str]:
        return (
            0 if view.loaded else 1,
            0 if view.installed else 1,
            0 if view.spec.recommended else 1,
            view.tag,
        )

    return sorted(views, key=key)


def preferred_tags(task: str) -> tuple[str, ...]:
    return TASK_PREFERENCE.get(task, TASK_PREFERENCE[GENERAL])
