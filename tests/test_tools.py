"""Tests for reading each tool's effective model."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.tools import (
    codex_logged_in,
    continue_default,
    continue_models,
    gateway_models,
    opencode_default,
    opencode_local_models,
    opencode_models,
    qwen_default,
    qwen_models,
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


def test_opencode_and_qwen_models_are_listed() -> None:
    assert opencode_models('{"provider":{"ollama":{"models":{"a:1":{},"b:2":{}}}}}') == [
        "a:1",
        "b:2",
    ]
    assert opencode_models('{"providers":{"sovereign":{"models":{"auto":{}}}}}') == ["auto"]
    config = (
        '{"providers":{'
        '"local":{"models":{"local-a":{}}},'
        '"sovereign":{"models":{"auto":{}}},'
        '"remote":{"models":{"remote-b":{}}}}}'
    )
    assert opencode_local_models(config) == ["local-a", "auto"]
    assert qwen_models('{"modelProviders":{"openai":[{"id":"x"},{"id":"y"}]}}') == ["x", "y"]


def test_continue_models_returns_every_entry() -> None:
    text = "models:\n  - model: a:1\n  - model: b:2\ncontext:\n  - model: ignored\n"
    assert continue_models(text) == ["a:1", "b:2"]
