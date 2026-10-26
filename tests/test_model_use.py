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


def test_domain_selects_the_gateway_provider_in_opencode(tmp_path) -> None:
    """A domain key routes through the gateway, not raw Ollama."""
    mu.set_opencode_model("legal", tmp_path / "oc.json")
    data = json.loads((tmp_path / "oc.json").read_text(encoding="utf-8"))
    assert data["model"] == "sovereign/legal"


def test_a_real_tag_still_uses_the_local_provider(tmp_path) -> None:
    mu.set_opencode_model("qwen3.8:27b", tmp_path / "oc.json")
    data = json.loads((tmp_path / "oc.json").read_text(encoding="utf-8"))
    assert data["model"] == "local/qwen3.8:27b"


def test_resolve_domain_validates() -> None:
    assert mu.resolve_domain("legal") == "legal"
    with pytest.raises(ValueError, match="unknown domain"):
        mu.resolve_domain("not-a-domain")


def test_opencode_and_claude_default_paths_return_home_paths() -> None:
    assert mu.opencode_model_path().name == "opencode.json"
    assert mu.claude_settings_path().name == "settings.json"


def test_set_opencode_model_overwrites_non_dict_data(tmp_path) -> None:
    path = tmp_path / "opencode.json"
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    mu.set_opencode_model("m:1", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "local/m:1"


def test_set_claude_model_overwrites_non_dict_env(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": "nope"}), encoding="utf-8")
    mu.set_claude_model("m:1", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_MODEL"] == "m:1"


def test_model_use_wires_claude_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mu, "claude_settings_path", lambda: tmp_path / "cl.json")
    done = mu.model_use("m:1", "claude")
    assert set(done) == {"claude"}


def test_current_models_returns_empty_on_missing_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mu, "opencode_model_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(mu, "claude_settings_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(mu, "codex_home_path", lambda: tmp_path)
    current = mu.current_models()
    assert current == {"opencode": "", "codex": "", "claude": ""}


def test_is_installed_reflects_installed_models(monkeypatch) -> None:
    monkeypatch.setattr(mu, "installed_models", lambda: {"m:1"})
    assert mu.is_installed("m:1") is True
    assert mu.is_installed("m:2") is False
