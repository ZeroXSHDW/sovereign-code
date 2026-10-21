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


REMOTE_CATALOG: dict[str, tuple[str, float]] = {
    # coding specialists
    "qwen2.5-coder:1.5b": ("tiny coder; fast, low RAM", 0.9),
    "qwen2.5-coder:3b": ("small coder; quick edits and iteration", 1.9),
    "qwen2.5-coder:7b": ("solid coder", 4.7),
    "qwen2.5-coder:14b": ("best coder that fits 24 GB", 9.0),
    "qwen2.5-coder:32b": ("stronger coder; tight on 24 GB", 20.0),
    "deepseek-coder-v2:16b": ("strong coding model", 9.0),
    "deepseek-coder-v2:236b": ("max-capability coder; needs far more than 24 GB", 134.0),
    # reasoning / chain-of-thought
    "deepseek-r1:1.5b": ("tiny reasoning model", 0.9),
    "deepseek-r1:7b": ("reasoning model with visible chain-of-thought", 4.4),
    "deepseek-r1:8b": ("reasoning model with visible chain-of-thought", 4.7),
    "deepseek-r1:14b": ("reasoning model with visible chain-of-thought", 9.0),
    "deepseek-r1:32b": ("strong reasoning model; tight on 24 GB", 20.0),
    # general / chat
    "qwen2.5:0.5b": ("tiny general model", 0.4),
    "qwen2.5:3b": ("fast general model", 1.9),
    "qwen2.5:7b": ("general model", 4.4),
    "qwen2.5:32b": ("large general model; too big for 24 GB", 20.0),
    "qwen3:0.6b": ("tiny current-gen model", 0.4),
    "qwen3:4b": ("current-gen general model", 2.3),
    "qwen3:8b": ("current-gen general model with reasoning", 4.9),
    "qwen3:14b": ("current-gen general model with reasoning", 9.0),
    "qwen3:32b": ("large reasoning model; too big for 24 GB", 20.0),
    "llama3.2:1b": ("smallest general model", 0.8),
    "llama3.2:3b": ("tiny fast general model", 2.0),
    "llama3.1:8b": ("reasoning fallback with long context", 4.9),
    "gemma3:1b": ("compact general model", 0.8),
    "gemma3:4b": ("compact general model", 2.7),
    "gemma3:12b": ("general model with strong reasoning", 7.7),
    "gemma3:27b": ("large general model; too big for 24 GB", 17.0),
    "phi4:14b": ("small reasoning model", 9.0),
    "mistral-small:24b": ("mid-size general model; tight on 24 GB", 15.0),
    "codestral:22b": ("Mistral coding model; tight on 24 GB", 13.0),
    # vision / embeddings
    "llava:13b": ("vision model", 8.0),
    "qwen2.5-vl:7b": ("vision-language model", 4.4),
    "mxbai-embed-large": ("embedding model (1024-dim)", 0.7),
    "snowflake-arctic-embed": ("small embedding model", 0.2),
}

# Honest offline model stacks for a 24 GB Mac. Models run one or two at a time
# (Ollama swaps automatically); the numbers are rough installed-size totals.
MODEL_STACKS: dict[str, dict[str, object]] = {
    "lean": {
        "models": ("qwen2.5-coder:3b", "qwen2.5:0.5b", "nomic-embed-text"),
        "approx_gb": 4,
        "note": "Fast edits + tiny chat + embeddings; leaves most RAM free.",
    },
    "balanced": {
        "models": ("qwen2.5-coder:7b", "qwen3:4b", "deepseek-r1:8b", "nomic-embed-text"),
        "approx_gb": 14,
        "note": "Solid coder + current-gen chat + reasoning; comfortable on 24 GB.",
    },
    "capable": {
        "models": ("qwen2.5-coder:14b", "gemma4:12b", "deepseek-r1:14b", "nomic-embed-text"),
        "approx_gb": 29,
        "note": "Best local coder + deep reasoning + strong CoT; tight on 24 GB — "
        "swap models with `sovereign free` between turns.",
    },
    "max": {
        "models": ("qwen2.5-coder:32b", "deepseek-r1:32b", "codestral:22b"),
        "approx_gb": 53,
        "note": "Maximum capability but will not fit comfortably on 24 GB; only pull "
        "what you need, one at a time.",
    },
}

# Models asked about by name that are NOT published on Ollama's library as far as
# this project can verify. We deliberately do not add them as one-click downloads.
NOT_ON_OLLAMA = ("GLM", "deepseek-v4.1-flash", "kimi k3", "kimi-k3")
