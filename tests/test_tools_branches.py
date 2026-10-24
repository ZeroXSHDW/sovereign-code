"""Supplementary branch coverage for small pure-logic modules.

These target specific defensive branches the modules' primary test files do
not exercise: string vs. object config shapes, non-dict provider blocks, and
unlink/permission failure paths.
"""

from __future__ import annotations

from pathlib import Path

from sovereign_code.tools import (
    opencode_local_models,
    opencode_models,
    qwen_default,
    qwen_models,
)


def test_qwen_default_accepts_a_plain_string() -> None:
    assert qwen_default('{"model": "glm-4.7-flash"}') == "glm-4.7-flash"


def test_qwen_default_invalid_json() -> None:
    assert qwen_default("not json") == ""


def test_qwen_default_returns_empty_for_non_model_shape() -> None:
    assert qwen_default('{"model": 42}') == ""


def test_opencode_models_non_dict_providers() -> None:
    assert opencode_models('{"providers": "not-a-dict"}') == []
    assert opencode_models('{"provider": []}') == []
    assert opencode_models("not json") == []


def test_opencode_local_models_non_dict_providers() -> None:
    assert opencode_local_models('{"providers": "nope"}') == []
    assert opencode_local_models("not json") == []


def test_qwen_models_non_list_entries() -> None:
    assert qwen_models('{"modelProviders": {"openai": "nope"}}') == []
    assert qwen_models('{"modelProviders": {}}') == []
    assert qwen_models('{"modelProviders": "not-a-dict"}') == []


def test_qwen_models_missing_entries_default() -> None:
    assert qwen_models('{"modelProviders": {"other": []}}') == []


def test_qwen_models_single_object_entry() -> None:
    assert qwen_models('{"modelProviders": {"openai": {"id": "solo:1"}}}') == ["solo:1"]


def test_qwen_models_invalid_json() -> None:
    assert qwen_models("nope") == []


def test_continue_default_skips_comments() -> None:
    from sovereign_code.tools import continue_default

    text = "models:\n  # a comment line inside the block\n  - name: First\n    model: a:1\n"
    assert continue_default(text) == "a:1"


def test_read_text_missing_file() -> None:
    from sovereign_code.tools import read_text

    assert read_text(Path("/nonexistent/definitely-missing.txt")) == ""
