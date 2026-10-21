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
    # True for Ollama Cloud tags (`:cloud`). They are served from ollama.com,
    # not from this Mac: no weights are downloaded and the prompt leaves the
    # machine. The local-first router never selects one unless it is named.
    cloud: bool = False

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
    # --- Frontier models served by Ollama Cloud -------------------------------
    # Verified on ollama.com/library (2026-10-21). Ollama Cloud is opt-in: the
    # server must run without OLLAMA_NO_CLOUD and the account must be signed in
    # (`ollama signin`). These entries carry no local size because nothing is
    # downloaded; `sovereign cloud` reports their readiness.
    "kimi-k3:cloud": ModelSpec(
        tag="kimi-k3:cloud",
        role=AGENT,
        params_b=2800.0,
        size_gb=0.0,
        max_context=1_048_576,
        strengths=("agent", "code", "reason", "vision", "tools", "thinking"),
        summary="Kimi K3 (Moonshot): 1M ctx, native multimodal agentic model.",
        cloud=True,
    ),
    "kimi-k2.6:cloud": ModelSpec(
        tag="kimi-k2.6:cloud",
        role=AGENT,
        params_b=1000.0,
        size_gb=0.0,
        max_context=262_144,
        strengths=("agent", "code", "vision", "tools"),
        summary="Kimi K2.6 (Moonshot): 256k ctx, long-horizon coding and agents.",
        cloud=True,
    ),
    "deepseek-v4.1-flash:cloud": ModelSpec(
        tag="deepseek-v4.1-flash:cloud",
        role=CODING,
        params_b=0.0,
        size_gb=0.0,
        max_context=1_048_576,
        strengths=("code", "reason", "agent", "tools", "thinking"),
        summary="DeepSeek V4.1 Flash: 1M ctx, fast high-throughput coding/reasoning.",
        cloud=True,
    ),
    "deepseek-v4-pro:cloud": ModelSpec(
        tag="deepseek-v4-pro:cloud",
        role=REASON,
        params_b=1600.0,
        size_gb=0.0,
        max_context=1_048_576,
        strengths=("reason", "code", "agent", "tools", "thinking"),
        summary="DeepSeek V4 Pro: 1.6T MoE, 1M ctx, frontier reasoning and agents.",
        cloud=True,
    ),
    "glm-5.3:cloud": ModelSpec(
        tag="glm-5.3:cloud",
        role=AGENT,
        params_b=0.0,
        size_gb=0.0,
        max_context=1_048_576,
        strengths=("agent", "code", "reason", "tools", "thinking"),
        summary="GLM-5.3 (Z.ai): 1M ctx, flagship long-horizon coding and agents.",
        cloud=True,
    ),
    "glm-5.3-flash:cloud": ModelSpec(
        tag="glm-5.3-flash:cloud",
        role=AGENT,
        params_b=320.0,
        size_gb=0.0,
        max_context=1_048_576,
        strengths=("agent", "code", "vision", "tools", "thinking"),
        summary="GLM-5.3 Flash (Z.ai): 320B MoE / 18B active, 1M ctx, multimodal.",
        cloud=True,
    ),
    "glm-5.2:cloud": ModelSpec(
        tag="glm-5.2:cloud",
        role=AGENT,
        params_b=0.0,
        size_gb=0.0,
        max_context=999_424,
        strengths=("agent", "code", "reason", "tools"),
        summary="GLM-5.2 (Z.ai): ~976k ctx, previous-gen long-horizon flagship.",
        cloud=True,
    ),
    # --- Current-gen local Qwen ------------------------------------------------
    # The big sibling, Qwen3.8-Flash-Next (125B-A6B, 256k ctx), is deliberately
    # NOT here: its smallest published artifact is 105 GB (nvfp4), which is more
    # than 4x this Mac's 24 GB of unified memory, and OCI pins it to
    # H100_X8/H200_X4. It cannot be pulled or served locally; do not add it.
    "qwen3.8:27b": ModelSpec(
        tag="qwen3.8:27b",
        role=CODING,
        params_b=27.0,
        size_gb=18.0,
        # 262k is the model family's native window. On 24 GB the router's own
        # ceiling applies (settings.max_context, 32k by default) because the KV
        # cache, not the weights, is what overflows first at this size.
        max_context=262_144,
        strengths=("code", "agent", "vision", "tools", "thinking"),
        summary="Qwen 3.8 27B: current-gen coder/agent + native vision; 18 GB, 256k ctx.",
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
    #
    # qwen3.8:27b leads code, agent and reason: it is the best current-gen model
    # that actually runs here. It is 18 GB of weights on 24 GB, so the router
    # pins it to a small window and it swaps against anything else resident —
    # that is why chat and fast stay on the 4-9 GB models.
    CODING: (
        "qwen3.8:27b",
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
        "qwen3.8:27b",
        "glm-4.7-flash",
        "deepseek-r1:8b",
        "gpt-oss:20b",
        "gemma4:12b",
        "qwen3.5:9b",
    ),
    VISION: (
        "qwen3.5:9b",
        "gemma4:12b",
        # Native vision-language, best accuracy per image; last because an 18 GB
        # load is a poor trade for a single screenshot.
        "qwen3.8:27b",
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
        "qwen3.8:27b",
    ),
    # Agentic coding needs reliable tool calls, not just code knowledge.
    AGENT: (
        "qwen3.8:27b",
        "qwen3-coder:30b",
        "gpt-oss:20b",
        "gemma4:12b",
        "qwen2.5-coder:14b",
        "glm-4.7-flash",
    ),
}

# Ollama Cloud tags, strongest first. Deliberately separate from
# TASK_PREFERENCE: the router must stay local-first, so a cloud model is only
# used when the user names it or asks the `cloud-*` aliases for it.
CLOUD_PREFERENCE: tuple[str, ...] = (
    "kimi-k3:cloud",
    "deepseek-v4-pro:cloud",
    "glm-5.3:cloud",
    "deepseek-v4.1-flash:cloud",
    "glm-5.3-flash:cloud",
    "kimi-k2.6:cloud",
    "glm-5.2:cloud",
)

CLOUD_TAGS: tuple[str, ...] = tuple(
    tag for tag, spec in CATALOG.items() if spec.cloud
)

# What the eight requested model names map to. Kept here (not only in the CLI)
# so the mapping is testable and `sovereign cloud` can show exactly where each
# familiar name goes. "DeepSeek V4 Flash" is the retired `deepseek-v4-flash`
# Ollama tag; providers still serve the exact model, and the alias uses it
# when a provider key exists, falling back to V4.1 over Ollama.
REQUESTED_CLOUD_MODELS: tuple[tuple[str, str, str], ...] = (
    ("Kimi K3", "kimi-k3:cloud", "1M ctx · multimodal agent · Moonshot"),
    (
        "DeepSeek Flash V4.1",
        "deepseek-v4.1-flash:cloud",
        "1M ctx · fast coding/reasoning · DeepSeek",
    ),
    (
        "DeepSeek Flash V4 Pro",
        "deepseek-v4-pro:cloud",
        "1M ctx · 1.6T MoE frontier reasoning · DeepSeek",
    ),
    (
        "DeepSeek V4 Flash",
        "deepseek-v4.1-flash:cloud",
        "exact V4 Flash via a provider key; V4.1 Flash over Ollama (tag retired 2026-08-27)",
    ),
    ("GLM 5.3 FL", "glm-5.3-flash:cloud", "1M ctx · 320B MoE / 18B active · Z.ai"),
    ("GLM 5.2", "glm-5.2:cloud", "~976k ctx · long-horizon flagship · Z.ai"),
    ("QWEN 3.8", "qwen3.8:27b", "local 18 GB · 256k ctx · runs on this Mac"),
    ("Kimi K2.6", "kimi-k2.6:cloud", "256k ctx · multimodal agent · Moonshot"),
)


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
    def cloud(self) -> bool:
        return self.spec.cloud

    @property
    def label(self) -> str:
        if self.cloud:
            marker = "☁" if self.installed else "↓☁"
        else:
            marker = "▶" if self.loaded else ("●" if self.installed else "↓")
        return f"{marker} {self.tag}"

    @property
    def status(self) -> str:
        if self.cloud:
            return "cloud · registered" if self.installed else "cloud · not registered"
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
            spec = (
                CATALOG.get(tag)
                or CATALOG.get(tag.removesuffix(":latest"))
                or _dynamic_spec(tag, parse_size_gb(item.get("size")), None, "")
            )
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


def recommended_tag() -> str:
    """The model to download when the user asks for a recommendation.

    This is the single source of truth for "recommended": the `recommended`
    flag on the catalog entry, which the doctor, the dashboard and
    `sovereign pull-recommended` all read. The router's own preference order
    is a different question — that one ranks by capability, not by fit.
    """
    for tag, spec in CATALOG.items():
        if spec.recommended:
            return tag
    return TASK_PREFERENCE[CODING][0]


REMOTE_CATALOG: dict[str, tuple[str, float]] = {
    # fast agentic MoE models (best speed/capability on 24 GB)
    "glm4": ("GLM-4 9B; fast multilingual coding, agentic tool use & reasoning", 5.5),
    "qwen3.8:27b": ("primary local coder/agent, native vision; 18 GB, 256k ctx", 18.0),
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
    # Ollama Cloud frontier models: no local download (0 GB). They are listed
    # here so `models --remote` and `sovereign cloud` use one catalog. Pulling
    # one still requires Ollama Cloud to be enabled and the account signed in.
    "kimi-k3:cloud": ("Kimi K3; 1M ctx, multimodal agent (cloud)", 0.0),
    "kimi-k2.6:cloud": ("Kimi K2.6; 256k ctx, long-horizon coding (cloud)", 0.0),
    "deepseek-v4.1-flash:cloud": ("DeepSeek V4.1 Flash; 1M ctx, fast coding (cloud)", 0.0),
    "deepseek-v4-pro:cloud": ("DeepSeek V4 Pro; 1.6T MoE, 1M ctx (cloud)", 0.0),
    "glm-5.3:cloud": ("GLM-5.3; 1M ctx flagship coding agent (cloud)", 0.0),
    "glm-5.3-flash:cloud": ("GLM-5.3 Flash; 320B MoE, 1M ctx, multimodal (cloud)", 0.0),
    "glm-5.2:cloud": ("GLM-5.2; ~976k ctx long-horizon agent (cloud)", 0.0),
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
    "cloud": {
        "models": CLOUD_PREFERENCE,
        "approx_gb": 0,
        "note": "Frontier models served by Ollama Cloud: no download, but prompts "
        "leave this Mac. Run `sovereign cloud --enable` and `ollama signin`; the "
        "frontier tags also need an Ollama Pro plan.",
    },
}

# These tags were once mistaken for local Ollama models. They now exist as
# Ollama Cloud entries only: no weights are downloaded, and the prompt is
# processed on ollama.com. `sovereign cloud` owns their setup.
CLOUD_ONLY = CLOUD_PREFERENCE

# Bare names people type for the cloud models, mapped to the real Ollama tag.
# The original DeepSeek V4 Flash tag was retired by Ollama on 2026-08-27, so
# its name resolves to the current Flash instead of failing with a bare 404.
CLOUD_TAG_ALIASES: dict[str, str] = {
    "deepseek-v4-flash:cloud": "deepseek-v4.1-flash:cloud",
    "deepseek-v4-flash": "deepseek-v4.1-flash:cloud",
    "glm-5.3-flash": "glm-5.3-flash:cloud",
    "deepseek-v4.1-flash": "deepseek-v4.1-flash:cloud",
    "deepseek-v4-pro": "deepseek-v4-pro:cloud",
    "kimi-k3": "kimi-k3:cloud",
    "kimi-k2.6": "kimi-k2.6:cloud",
    "glm-5.3": "glm-5.3:cloud",
    "glm-5.2": "glm-5.2:cloud",
}
