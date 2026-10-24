"""Tests for the model-use wiring: select a model per client."""

from __future__ import annotations

import json

import pytest

from sovereign_code import model_use as mu


def test_set_opencode_model_writes_local_slash_tag(tmp_path) -> None:
    path = tmp_path / "opencode.json"
    mu.set_opencode_model("qwen3.8:27b", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "local/qwen3.8:27b"


def test_set_opencode_model_preserves_other_keys(tmp_path) -> None:
    path = tmp_path / "opencode.json"
    path.write_text(json.dumps({"providers": {"x": 1}}), encoding="utf-8")
    mu.set_opencode_model("m:1", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["providers"] == {"x": 1}
    assert data["model"] == "local/m:1"


def test_set_claude_model_writes_the_env_model(tmp_path) -> None:
    path = tmp_path / "settings.json"
    mu.set_claude_model("forensics/gguf", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_MODEL"] == "forensics/gguf"


def test_set_codex_model_writes_the_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mu, "codex_home_path", lambda: tmp_path)
    monkeypatch.setattr(mu, "write_codex_catalog", lambda: tmp_path / "catalog.json")
    path = mu.set_codex_model("qwen3.8:27b")
    text = path.read_text(encoding="utf-8")
    assert 'model = "qwen3.8:27b"' in text
    assert "model_provider" in text and "wire_api" in text


def test_model_use_all_wires_every_client(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mu, "opencode_model_path", lambda: tmp_path / "oc.json")
    monkeypatch.setattr(mu, "claude_settings_path", lambda: tmp_path / "cl.json")
    monkeypatch.setattr(mu, "codex_home_path", lambda: tmp_path)
    monkeypatch.setattr(mu, "write_codex_catalog", lambda: tmp_path / "cat.json")
    done = mu.model_use("qwen3.8:27b", "all")
    assert set(done) == {"opencode", "codex", "claude"}


def test_model_use_rejects_an_unknown_client(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown client"):
        mu.model_use("m:1", "not-a-client")


def test_current_models_reads_back_what_was_set(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mu, "opencode_model_path", lambda: tmp_path / "oc.json")
    monkeypatch.setattr(mu, "claude_settings_path", lambda: tmp_path / "cl.json")
    monkeypatch.setattr(mu, "codex_home_path", lambda: tmp_path)
    monkeypatch.setattr(mu, "write_codex_catalog", lambda: tmp_path / "cat.json")

    mu.set_opencode_model("qwen3.8:27b", tmp_path / "oc.json")
    mu.set_claude_model("legal/gguf", tmp_path / "cl.json")
    mu.set_codex_model("qwen3.8:27b")

    current = mu.current_models()
    assert current["opencode"] == "qwen3.8:27b"
    assert current["claude"] == "legal/gguf"
    assert current["codex"] == "qwen3.8:27b"


def test_model_use_cli_allows_list_without_a_model(monkeypatch) -> None:
    """`sovereign model-use --list` must not demand a positional model."""
    from sovereign_code import cli

    parser = cli.build_parser()
    args = parser.parse_args(["model-use", "--list"])
    assert args.list is True
    assert args.model is None
