"""Tests for finding installed models nothing references."""

from __future__ import annotations

from sovereign_code.prune import (
    base_tag,
    parse_alias_targets,
    prune_candidates,
    referenced_tags,
)

CONFIG = """
model_list:
  - model_name: local-code
    litellm_params:
      model: ollama/qwen3-coder:30b
      api_base: http://127.0.0.1:11434
  - model_name: "openai/*"
    litellm_params:
      model: "openai/*"
"""


def test_alias_targets_strip_the_provider_prefix() -> None:
    assert parse_alias_targets(CONFIG) == {"qwen3-coder:30b"}


def test_referenced_tags_include_stacks_and_preferences() -> None:
    refs = referenced_tags(
        {"qwen3-coder:30b"},
        {"lean": {"models": ("qwen3.5:4b", "nomic-embed-text")}},
        {"code": ("qwen3-coder:30b", "gpt-oss:20b")},
    )
    assert refs == {"qwen3-coder:30b", "qwen3.5:4b", "nomic-embed-text", "gpt-oss:20b"}


def test_candidates_ignore_latest_suffix_and_sort_by_size() -> None:
    installed = [
        ("llama3.1:8b", 4.6),
        ("nomic-embed-text:latest", 0.3),
        ("phi:latest", 1.6),
    ]
    candidates = prune_candidates(installed, {"nomic-embed-text", "phi"})
    assert candidates == [("llama3.1:8b", 4.6)]
    assert base_tag("phi:latest") == "phi"


def test_nothing_is_pruned_when_everything_is_referenced() -> None:
    # Only the :latest suffix is normalised — "qwen3-coder" is a different tag
    # from "qwen3-coder:30b", so the exact referenced name must match.
    assert prune_candidates([("qwen3-coder:30b", 18.0)], {"qwen3-coder:30b"}) == []


def test_referenced_tags_skips_non_sequence_models() -> None:
    stacks = {"bad": {"models": "not-a-sequence"}}
    assert referenced_tags(set(), stacks, {}) == set()
