"""Tests for the LiteLLM model_list generator."""

from __future__ import annotations

from sovereign_code.gateway_config import (
    CLIENT_MODELS,
    ROLE_ALIASES,
    TIER_GATEWAY,
    default_path,
    render,
    write,
)


def test_render_contains_model_list_header():
    text = render()
    assert "model_list:" in text
    assert "sovereign model list" in text


def test_render_has_role_aliases():
    text = render()
    for alias in ("local-code", "local-chat", "local-agent", "local-auto", "local-fast"):
        assert f"model_name: {alias}" in text


def test_render_routes_tiers_to_gateway():
    text = render()
    assert TIER_GATEWAY in text


def test_render_has_direct_model_entries():
    text = render()
    assert "model_name: local-qwen3.8" in text
    assert "ollama/qwen3.8:27b" in text


def test_client_models_cover_installed_agents():
    for agent in ("opencode", "codex", "claude", "qwen", "cursor", "windsurf", "zed"):
        assert agent in CLIENT_MODELS
        assert isinstance(CLIENT_MODELS[agent], tuple)
        assert len(CLIENT_MODELS[agent]) > 0


def test_role_aliases_map_to_tiers_or_ollama():
    for alias, route in ROLE_ALIASES.items():
        assert alias.startswith("local-")
        assert route is not None


def test_write_creates_file(tmp_path):

    out = tmp_path / "model_list.yaml"
    written = write(path=out)
    assert written == out
    assert out.is_file()
    text = out.read_text()
    assert "model_list:" in text


def test_render_includes_cloud_block_when_provided():
    cloud_block = (
        "  - model_name: cloud-kimi-k3\n"
        "    litellm_params:\n"
        "      model: ollama/kimi-k3:cloud\n"
        "      api_base: http://127.0.0.1:11434\n"
    )
    text = render(cloud_block=cloud_block)
    assert "cloud-kimi-k3" in text


def test_default_path_under_local_ai_root():
    assert default_path().name == "model_list.yaml"
