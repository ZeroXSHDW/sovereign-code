"""Tests for model selection, context budgeting, and the gateway alias parser."""

from __future__ import annotations

from sovereign_code.gateway import alias_names, alias_targets, parse_aliases
from sovereign_code.models import CATALOG, build_views
from sovereign_code.router import Task, choose, context_for, preferred_tags, recommend_pull


def _views(*tags: str) -> dict:
    payload = {"models": [{"name": tag, "size": (4 * 1024**3), "details": {}} for tag in tags]}
    return build_views(payload, None)


def test_a_preferred_model_wins_when_installed():
    views = _views("qwen3-coder:30b", "qwen2.5-coder:14b")
    selection = choose(Task.CODE, views, free_gb=8.0)
    assert selection.model is not None
    assert selection.model.tag == "qwen3-coder:30b"


def test_an_explicit_preference_overrides_the_task():
    views = _views("qwen3-coder:30b", "qwen2.5-coder:14b")
    selection = choose(Task.CODE, views, free_gb=8.0, preferred="qwen2.5-coder:14b")
    assert selection.model.tag == "qwen2.5-coder:14b"


def test_a_preferred_model_that_is_not_installed_is_ignored():
    views = _views("qwen2.5-coder:14b")
    selection = choose(Task.CODE, views, free_gb=8.0, preferred="nope:1b")
    assert selection.model.tag in preferred_tags(Task.CODE.value)


def test_the_router_falls_back_to_an_installed_model():
    """A task whose preferred tags are all missing still has to return a model."""
    views = _views("phi:latest")
    selection = choose(Task.REASON, views, free_gb=8.0)
    assert selection.model is not None
    assert selection.model.tag == "phi:latest"
    assert selection.context >= 2048
    assert selection.needs_pull is None


def test_the_router_reports_what_to_pull_when_nothing_is_installed():
    selection = choose(Task.CODE, _views(), free_gb=8.0)
    assert selection.model is None
    assert selection.needs_pull == recommend_pull(Task.CODE)
    assert selection.needs_pull in CATALOG


def test_unknown_free_memory_keeps_a_usable_context():
    """`free_gb=None` means "unknown", not "no memory at all"."""
    view = _views("qwen3-coder:30b")["qwen3-coder:30b"]
    context = context_for(view, None, max_context=32768)
    assert context >= 4096


def test_context_shrinks_when_memory_is_tight():
    views = _views("qwen3-coder:30b")
    view = views["qwen3-coder:30b"]
    roomy = context_for(view, 32.0)
    tight = context_for(view, 0.5)
    assert tight < roomy
    assert tight >= 2048


def test_context_never_exceeds_the_model_limit():
    views = _views("qwen2.5-coder:14b")
    view = views["qwen2.5-coder:14b"]
    assert context_for(view, 64.0, max_context=32768) <= min(
        CATALOG[view.tag].max_context, 32768
    )


def test_preferred_tags_exist_in_the_catalog():
    for task in ("code", "chat", "reason", "vision", "fast", "agent", "general"):
        for tag in preferred_tags(task):
            assert tag in CATALOG, f"{task} -> {tag}"


# ------------------------------------------------------------------- gateway

LITELLM_CONFIG = """
model_list:
  - model_name: "local-chat"
    litellm_params:
      model: "ollama/qwen3.5:4b"
  - model_name: local-code
    litellm_params:
      model: ollama/qwen3-coder:30b
  - model_name: "local-vision"
    litellm_params:
      model: "ollama/qwen2.5vl:7b"
"""


def test_alias_parser_reads_the_litellm_model_list():
    entries = parse_aliases(LITELLM_CONFIG)
    targets = {entry.alias: entry.target for entry in entries}
    assert targets["local-chat"] == "qwen3.5:4b"
    assert targets["local-code"] == "qwen3-coder:30b"
    assert targets["local-vision"] == "qwen2.5vl:7b"


def test_alias_parser_keeps_the_file_order():
    entries = parse_aliases(LITELLM_CONFIG)
    assert [entry.alias for entry in entries] == ["local-chat", "local-code", "local-vision"]


def test_alias_parser_ignores_comments_and_blank_lines():
    text = """
    # a comment
    model_list:
      - model_name: "local-chat"   # trailing comment
        litellm_params:
          model: "ollama/qwen3.5:4b"

    """
    entries = parse_aliases(text)
    assert [entry.alias for entry in entries] == ["local-chat"]


def test_alias_parser_reports_an_alias_without_a_target():
    text = """
    model_list:
      - model_name: "local-chat"
        litellm_params:
          model: "openai/gpt-4o"
    """
    entries = parse_aliases(text)
    assert entries[0].alias == "local-chat"
    assert entries[0].target == ""


def test_alias_parser_handles_an_empty_config():
    assert parse_aliases("") == []


def test_alias_names_and_targets_line_up():
    names = alias_names(LITELLM_CONFIG)
    targets = alias_targets(LITELLM_CONFIG)
    assert len(names) == 3
    assert set(targets) <= set(names)
    assert targets["local-code"] == "qwen3-coder:30b"
