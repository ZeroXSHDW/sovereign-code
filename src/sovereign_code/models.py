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
    "glm4": ModelSpec(
        tag="glm4",
        role=AGENT,
        params_b=9.0,
        size_gb=5.5,
        max_context=32768,
        strengths=("agent", "code", "tools", "reason"),
        summary="GLM-4 9B: fast agentic tool use, multilingual coding & reasoning.",
    ),
    "deepseek-coder:6.7b": ModelSpec(
        tag="deepseek-coder:6.7b",
        role=CODING,
        params_b=6.7,
        size_gb=3.8,
        max_context=16384,
        strengths=("code", "tools", "refactor"),
        summary="DeepSeek Coder 6.7B: dedicated fast coding model.",
    ),
    "qwen3-coder:30b": ModelSpec(
        tag="qwen3-coder:30b",
        role=CODING,
        params_b=30.5,
        size_gb=19.0,
        # 256k native; 32k is the comfortable ceiling on 24 GB with q8 KV.
        max_context=32768,
        strengths=("code", "refactor", "tools", "agent"),
        summary="Agentic coder (MoE); larger download for 24 GB.",
        recommended=False,
    ),
    "glm-4.7-flash": ModelSpec(
        tag="glm-4.7-flash",
        role=AGENT,
        params_b=30.5,
        size_gb=19.0,
        max_context=32768,
        strengths=("agent", "code", "tools", "thinking"),
        summary="GLM Flash: strong agentic tool use and reasoning.",
    ),
    "gpt-oss:20b": ModelSpec(
        tag="gpt-oss:20b",
        role=CODING,
        params_b=20.9,
        size_gb=14.0,
        max_context=32768,
        strengths=("code", "reason", "tools", "agent"),
        summary="Fast tool-caller; low memory, quick first token.",
    ),
    "qwen3.5:9b": ModelSpec(
        tag="qwen3.5:9b",
        role=CHAT,
        params_b=9.0,
        size_gb=6.6,
        max_context=65536,
        strengths=("chat", "reason", "vision", "tools"),
        summary="Fast current-gen general model; chat alternative.",
    ),
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
    "deepseek-r1:8b": ModelSpec(
        tag="deepseek-r1:8b",
        role=REASON,
        params_b=8.2,
        size_gb=5.2,
        max_context=32768,
        strengths=("reason", "thinking"),
        summary="Reasoning model with visible chain-of-thought.",
    ),
    "qwen3:8b": ModelSpec(
        tag="qwen3:8b",
        role=REASON,
        params_b=8.2,
        size_gb=5.2,
        max_context=32768,
        strengths=("reason", "chat", "tools", "thinking"),
        summary="Current-gen general model with reasoning and tool use.",
    ),
    "gemma3:4b": ModelSpec(
        tag="gemma3:4b",
        role=FAST,
        params_b=3.9,
        size_gb=3.4,
        max_context=32768,
        strengths=("fast", "chat"),
        summary="Compact, fast general model.",
    ),
}

TASK_PREFERENCE: dict[str, tuple[str, ...]] = {
    # Curated to the strongest models measured on this M5 Pro / 24 GB
    # (2026-10-21), strongest first. Weaker/superseded models are pruned so a
    # task never silently falls back to something like phi or gemma3:4b.
    CODING: (
        "qwen3-coder:30b",
        "gpt-oss:20b",
        "qwen2.5-coder:14b",
        "glm-4.7-flash",
        "qwen2.5-coder:7b",
    ),
    CHAT: (
        "qwen3.5:9b",
        "gemma4:12b",
        "qwen3.5:4b",
        "glm-4.7-flash",
        "gpt-oss:20b",
    ),
    REASON: (
        "glm-4.7-flash",
        "deepseek-r1:8b",
        "gpt-oss:20b",
        "gemma4:12b",
        "qwen3.5:9b",
    ),
    VISION: (
        "qwen3.5:9b",
        "gemma4:12b",
    ),
    FAST: (
        "qwen3.5:4b",
        "qwen3.5:9b",
        "qwen2.5-coder:7b",
    ),
    GENERAL: (
        "qwen3.5:9b",
        "qwen3.5:4b",
        "gemma4:12b",
        "glm-4.7-flash",
    ),
    # Agentic coding needs reliable tool calls, not just code knowledge.
    AGENT: (
        "qwen3-coder:30b",
        "gpt-oss:20b",
        "gemma4:12b",
        "qwen2.5-coder:14b",
        "glm-4.7-flash",
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
    # "mlx" or "llamacpp" as reported by /api/ps. MLX models run substantially
    # faster on Apple silicon, so this is worth showing.
    runner: str = ""

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
        spec = (
            CATALOG.get(tag)
            or CATALOG.get(tag.removesuffix(":latest"))
            or _dynamic_spec(tag, size_gb, params, details.get("family", ""))
        )
        view = ModelView(
            spec=spec,
            installed=True,
            size_gb=size_gb or spec.size_gb,
            capabilities=tuple(item.get("capabilities") or ()),
        )
        views[tag] = view
        if tag.endswith(":latest"):
            views.setdefault(tag.removesuffix(":latest"), view)
        elif ":" not in tag:
            views.setdefault(f"{tag}:latest", view)

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
        view.runner = str(item.get("runner") or "")

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
    # fast agentic MoE models (best speed/capability on 24 GB)
    "glm4": ("GLM-4 9B; fast multilingual coding, agentic tool use & reasoning", 5.5),
    "qwen3-coder:30b": ("best agentic coder; 30B MoE, ~3B active — fast", 19.0),
    "glm-4.7-flash": ("GLM Flash; agentic tool use + reasoning, 198k ctx", 19.0),
    "gpt-oss:20b": ("fastest reliable tool-caller; low memory", 14.0),
    "qwen3.5:9b": ("fast current-gen general/chat model", 6.6),
    "qwen3.5:4b": ("smallest current-gen model; fastest", 3.3),
    # coding specialists
    "qwen2.5-coder:1.5b": ("tiny coder; fast, low RAM", 0.9),
    "qwen2.5-coder:3b": ("small coder; quick edits and iteration", 1.9),
    "qwen2.5-coder:7b": ("solid coder", 4.7),
    "qwen2.5-coder:14b": ("best coder that fits 24 GB", 9.0),
    "qwen2.5-coder:32b": ("stronger coder; tight on 24 GB", 20.0),
    "deepseek-coder:6.7b": ("dedicated fast coding model", 3.8),
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

# Honest offline model stacks for a 24 GB Mac. Only one ~18 GB model fits at a
# time; the numbers are rough installed-size totals.
MODEL_STACKS: dict[str, dict[str, object]] = {
    "lean": {
        "models": ("qwen3.5:4b", "qwen2.5-coder:7b", "nomic-embed-text"),
        "approx_gb": 8,
        "note": "Fast chat + a FIM coder + embeddings; leaves most RAM free.",
    },
    "balanced": {
        "models": ("gpt-oss:20b", "qwen3.5:9b", "nomic-embed-text"),
        "approx_gb": 21,
        "note": "Strong tool-caller + fast chat; still fits beside the OS.",
    },
    "capable": {
        "models": ("qwen3-coder:30b", "qwen3.5:9b", "qwen3.5:4b", "nomic-embed-text"),
        "approx_gb": 33,
        "note": "The daily stack: best coder, fast chat, tiny helper. The 30B wants "
        "the machine to itself, so swap with `sovereign free`.",
    },
    "max": {
        "models": ("qwen3-coder:30b", "glm-4.7-flash", "gpt-oss:20b", "deepseek-r1:8b"),
        "approx_gb": 51,
        "note": "Every model worth keeping; the 18-19 GB ones run strictly one at a time.",
    },
}

# Models that exist on Ollama only as CLOUD (routed) entries — verified
# 2026-10-21. They cannot be pulled and run locally, so they are deliberately
# not offered as one-click downloads. GLM itself *is* local: see glm-4.7-flash.
NOT_ON_OLLAMA = (
    "glm-5.3",
    "glm-5.3-flash",
    "deepseek-v4.1-flash",
    "deepseek-v4-pro",
    "kimi-k2.7-code",
    "kimi k3",
    "kimi-k3",
)
