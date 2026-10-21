"""Tests for the hardware-aware router."""

from sovereign_code.models import CATALOG, CODING, ModelSpec, ModelView, build_views
from sovereign_code.router import Task, choose, context_for, estimated_total_gb

GIB = 1024**3


def _bare_view(tag: str, size_gb: float, max_context: int = 32768) -> ModelView:
    spec = ModelSpec(
        tag=tag, role=CODING, params_b=0.0, size_gb=size_gb, max_context=max_context
    )
    return ModelView(spec=spec, installed=True, size_gb=size_gb)


def views(*names, loaded=None):
    tags = {
        "models": [
            {"name": name, "size": int(CATALOG[name].size_gb * GIB), "details": {}}
            for name in names
        ]
    }
    ps = {
        "models": [
            {"name": name, "size": int(CATALOG[name].size_gb * GIB), "context_length": 16384}
            for name in (loaded or [])
        ]
    }
    return build_views(tags, ps)


def test_code_prefers_14b_when_present():
    selection = choose(Task.CODE, views("qwen2.5-coder:14b", "qwen3.5:4b"), free_gb=20)
    assert selection.tag == "qwen2.5-coder:14b"
    assert selection.context == 32768


def test_code_falls_back_to_7b():
    selection = choose(Task.CODE, views("qwen2.5-coder:7b", "qwen3.5:4b"), free_gb=20)
    assert selection.tag == "qwen2.5-coder:7b"


def test_context_shrinks_under_pressure():
    all_views = views("qwen2.5-coder:14b")
    roomy = choose(Task.CODE, all_views, free_gb=30)
    tight = choose(Task.CODE, all_views, free_gb=12)
    assert roomy.context == 32768
    assert tight.context <= 16384
    assert estimated_total_gb(all_views["qwen2.5-coder:14b"], tight.context) <= 12


def test_chat_prefers_qwen35():
    selection = choose(Task.CHAT, views("qwen3.5:4b", "llama3.1:8b"), free_gb=20)
    assert selection.tag == "qwen3.5:4b"


def test_preferred_override_wins():
    all_views = views("qwen3.5:4b", "llama3.1:8b")
    selection = choose(Task.CODE, all_views, free_gb=20, preferred="llama3.1:8b")
    assert selection.tag == "llama3.1:8b"


def test_empty_machine_requests_pull():
    selection = choose(Task.CODE, build_views({"models": []}, None), free_gb=20)
    assert selection.model is None
    assert selection.needs_pull == "qwen3-coder:30b"


def test_context_respects_model_ceiling():
    all_views = views("phi:latest")
    assert context_for(all_views["phi:latest"], free_gb=20) == 2048


def test_agent_prefers_the_agentic_coder():
    selection = choose(
        Task.AGENT, views("gemma4:12b", "qwen3.5:4b", "qwen3-coder:30b"), free_gb=20
    )
    assert selection.tag == "qwen3-coder:30b"


def test_agent_falls_back_to_gemma_without_the_coder():
    # qwen3-coder/gpt-oss absent: gemma4:12b is the next tool-capable choice and
    # outranks the older dense coder in the measured ranking.
    selection = choose(Task.AGENT, views("gemma4:12b", "qwen2.5-coder:14b"), free_gb=20)
    assert selection.tag == "gemma4:12b"


def test_loaded_model_keeps_its_context():
    all_views = views("qwen3.5:4b", loaded=["qwen3.5:4b"])
    assert context_for(all_views["qwen3.5:4b"], free_gb=1) == 16384


def test_reason_prefers_deepseek_when_gemma_missing():
    selection = choose(Task.REASON, views("deepseek-r1:8b", "llama3.1:8b"), free_gb=20)
    assert selection.tag == "deepseek-r1:8b"


def test_fast_prefers_gemma3_4b():
    selection = choose(Task.FAST, views("gemma3:4b", "phi:latest"), free_gb=20)
    assert selection.tag == "gemma3:4b"


def test_large_model_keeps_a_usable_context():
    # 19 GB of weights against 17 GB of free RAM: the weights alone exceed the
    # budget, but the model still runs on this Mac, so the router must not
    # collapse it to 2048 and make it useless for coding.
    assert context_for(_bare_view("big", 19.0), free_gb=17.0) == 16384


def test_impossible_model_falls_back_to_minimum():
    # Far beyond what the machine can hold: no point reserving a context.
    assert context_for(_bare_view("huge", 43.0), free_gb=17.0) == 2048
