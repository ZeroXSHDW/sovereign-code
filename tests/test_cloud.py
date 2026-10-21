"""Tests for Ollama Cloud readiness and gateway wiring."""

from __future__ import annotations

import json

from sovereign_code import cloud
from sovereign_code.models import (
    CATALOG,
    CLOUD_PREFERENCE,
    CLOUD_TAG_ALIASES,
    CLOUD_TAGS,
    REQUESTED_CLOUD_MODELS,
)


def test_every_requested_model_is_registered() -> None:
    names = {name for name, _tag, _note in REQUESTED_CLOUD_MODELS}
    assert {
        "Kimi K3",
        "DeepSeek Flash V4.1",
        "DeepSeek Flash V4 Pro",
        "DeepSeek V4 Flash",
        "GLM 5.3 FL",
        "GLM 5.2",
        "QWEN 3.8",
        "Kimi K2.6",
    } <= names
    for _name, tag, _note in REQUESTED_CLOUD_MODELS:
        assert tag in CATALOG, tag
        assert CATALOG[tag].max_context >= 262_144


def test_cloud_tags_are_remote_and_never_recommended() -> None:
    assert set(CLOUD_TAGS) == set(CLOUD_PREFERENCE)
    assert CLOUD_TAGS
    for tag in CLOUD_TAGS:
        spec = CATALOG[tag]
        assert spec.cloud is True
        assert spec.size_gb == 0.0
        assert spec.recommended is False


def test_qwen38_is_local_not_cloud() -> None:
    spec = CATALOG["qwen3.8:27b"]
    assert spec.cloud is False
    assert spec.size_gb > 0
    assert spec.max_context == 262_144


def test_bare_cloud_names_resolve_to_real_tags() -> None:
    for bare, tag in CLOUD_TAG_ALIASES.items():
        assert tag in CATALOG, (bare, tag)
        assert CATALOG[tag].cloud is True
    # The retired DeepSeek V4 Flash tag follows to the current Flash.
    assert CLOUD_TAG_ALIASES["deepseek-v4-flash:cloud"] == "deepseek-v4.1-flash:cloud"


def test_is_cloud_tag() -> None:
    assert cloud.is_cloud_tag("kimi-k3:cloud")
    assert cloud.is_cloud_tag("deepseek-v4.1-flash:1017-cloud")
    assert not cloud.is_cloud_tag("qwen3.8:27b")
    assert not cloud.is_cloud_tag("cloud-kimi-k3")  # an alias, not a tag


def test_cloud_disabled_hint_only_touches_cloud_errors() -> None:
    hinted = cloud.cloud_disabled_hint("ollama cloud is disabled: remote details unavailable")
    assert "sovereign cloud --enable" in hinted
    plain = cloud.cloud_disabled_hint("connection refused")
    assert plain == "connection refused"


def test_plan_errors_are_explained() -> None:
    free = '{"error":"This model is not in the Free plan. Pro is $20/month"}'
    assert cloud.plan_required(free) is True
    assert "ollama.com/upgrade" in cloud.plan_hint(free)
    assert cloud.plan_required("connection refused") is False
    assert cloud.plan_hint("connection refused") == "connection refused"
    both = cloud.ollama_error_hint("ollama cloud is disabled; not in the Free plan")
    assert "sovereign cloud --enable" in both
    assert "ollama.com/upgrade" in both


def test_server_cloud_toggle_roundtrip(tmp_path) -> None:
    path = tmp_path / "server.json"
    path.write_text(json.dumps({"integrations": {"chatgpt": True}}), encoding="utf-8")
    assert cloud.server_cloud_disabled(path) is False

    assert cloud.set_server_cloud(False, path) is True
    assert cloud.server_cloud_disabled(path) is True
    data = json.loads(path.read_text())
    assert data["disable_ollama_cloud"] is True
    assert data["integrations"] == {"chatgpt": True}

    assert cloud.set_server_cloud(False, path) is False  # already disabled
    assert cloud.set_server_cloud(True, path) is True
    assert cloud.server_cloud_disabled(path) is False


def test_cloud_enabled_requires_both_switches(tmp_path) -> None:
    path = tmp_path / "server.json"
    path.write_text('{"disable_ollama_cloud": true}', encoding="utf-8")
    assert cloud.read_cloud_status(path, lambda _name: "").server_disabled is True
    assert cloud.cloud_enabled(path, lambda _name: "") is False

    path.write_text('{"disable_ollama_cloud": false}', encoding="utf-8")
    assert cloud.cloud_enabled(path, lambda _name: "") is True
    assert cloud.cloud_enabled(path, lambda _name: "0") is True
    assert cloud.cloud_enabled(path, lambda _name: "1") is False
    assert cloud.cloud_enabled(path, lambda _name: "true") is False
    status = cloud.read_cloud_status(path, lambda _name: "1")
    assert status.enabled is False
    assert "OLLAMA_NO_CLOUD" in status.detail


def test_gateway_block_covers_every_alias() -> None:
    block = cloud.gateway_block()
    for alias, tag in cloud.ALIAS_TARGETS.items():
        assert f"model_name: {alias}" in block
        assert f"ollama/{tag}" in block
    assert block.count("- model_name:") == len(cloud.ALIAS_TARGETS)
    assert block.index(cloud.BLOCK_START) < block.index(cloud.BLOCK_END)


def test_merge_gateway_text_is_idempotent_and_stays_in_model_list() -> None:
    original = """model_list:
  - model_name: local-chat
    litellm_params:
      model: ollama/qwen3.5:9b

router_settings:
  num_retries: 3
"""
    merged = cloud.merge_gateway_text(original)
    assert "local-chat" in merged
    assert merged.count(cloud.BLOCK_START) == 1
    assert merged.index("cloud-kimi-k3") < merged.index("router_settings:")
    # Running the installer twice must not duplicate the block.
    assert cloud.merge_gateway_text(merged) == merged
    # A hand-removed block is restored without damaging the rest.
    removed = cloud.merge_gateway_text(merged.replace(cloud.gateway_block(), ""))
    assert "cloud-kimi-k3" in removed


def test_gateway_aliases_have_sane_contexts() -> None:
    rows = {row.alias: row for row in cloud.gateway_aliases()}
    assert rows["cloud-kimi-k3"].context == cloud.DEFAULT_ALIAS_CONTEXT
    assert rows["local-qwen3.8"].context == cloud.LOCAL_ALIAS_CONTEXT
    assert rows["local-qwen3.8"].cloud is False
    assert rows["cloud-deepseek-v4-flash"].tag == "deepseek-v4.1-flash:cloud"
