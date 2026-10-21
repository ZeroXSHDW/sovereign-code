"""Tests for reading each tool's effective model."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.tools import (
    codex_logged_in,
    continue_default,
    gateway_models,
    opencode_default,
    qwen_default,
)

GATEWAY = """
model_list:
  - model_name: local-code
    litellm_params:
      model: ollama/qwen3-coder:30b
  - model_name: "openai/*"
    litellm_params:
      model: "openai/*"
  - model_name: local-glm
    litellm_params:
      model: ollama/glm-4.7-flash
      think: false
"""


def test_gateway_models_maps_alias_to_local_tag() -> None:
    mapping = gateway_models(GATEWAY)
    assert mapping == {"local-code": "qwen3-coder:30b", "local-glm": "glm-4.7-flash"}


def test_opencode_default_strips_the_provider() -> None:
    assert opencode_default('{"model": "ollama/qwen3-coder:30b"}') == "qwen3-coder:30b"
    assert opencode_default("not json") == ""


def test_qwen_default_reads_the_model_name() -> None:
    assert qwen_default('{"model": {"name": "glm-4.7-flash"}}') == "glm-4.7-flash"
    assert qwen_default('{"model": {}}') == ""


def test_continue_default_is_the_first_model() -> None:
    text = (
        "name: x\n"
        "models:\n"
        "  - name: Best\n"
        "    provider: ollama\n"
        "    model: qwen3-coder:30b\n"
        "  - name: Second\n"
        "    model: qwen3.5:9b\n"
        "context:\n"
        "  - provider: code\n"
    )
    assert continue_default(text) == "qwen3-coder:30b"


def test_codex_login_detection(tmp_path: Path) -> None:
    assert codex_logged_in(tmp_path) is False
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    assert codex_logged_in(tmp_path) is True
