"""Tests for the one-command setup and the self-contained runtime root."""

from __future__ import annotations

from sovereign_code import config, setup


def test_migrate_moves_legacy_into_the_checkout(tmp_path, monkeypatch):
    legacy = tmp_path / "local-ai"
    legacy.mkdir()
    (legacy / "config").mkdir()
    (legacy / "config" / "keep.toml").write_text("ok\n", encoding="utf-8")
    target = tmp_path / "repo" / "runtime"
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", legacy)
    monkeypatch.setattr(config, "RUNTIME_ROOT", target)
    monkeypatch.setattr(config, "LEGACY_LOCAL_AI_ROOT", legacy)
    monkeypatch.setattr(setup, "legacy_root", lambda: legacy)
    monkeypatch.setattr(setup, "runtime_target", lambda: target)

    step = setup.migrate_legacy(stop_services=False)
    assert step.ok
    assert target.is_dir()
    assert (target / "config" / "keep.toml").read_text(encoding="utf-8") == "ok\n"
    assert legacy.is_symlink()
    assert (legacy / "config" / "keep.toml").is_file()


def test_migrate_dry_run_changes_nothing(tmp_path, monkeypatch):
    legacy = tmp_path / "local-ai"
    legacy.mkdir()
    target = tmp_path / "runtime"
    monkeypatch.setattr(setup, "legacy_root", lambda: legacy)
    monkeypatch.setattr(setup, "runtime_target", lambda: target)

    step = setup.migrate_legacy(dry_run=True, stop_services=False)
    assert step.ok
    assert "would move" in step.detail
    assert legacy.is_dir() and not target.exists()


def test_migrate_is_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "runtime"
    target.mkdir()
    monkeypatch.setattr(setup, "legacy_root", lambda: tmp_path / "missing")
    monkeypatch.setattr(setup, "runtime_target", lambda: target)
    step = setup.migrate_legacy(stop_services=False)
    assert step.skipped
    assert "already" in step.detail


def test_missing_models_normalises_latest(monkeypatch):
    monkeypatch.setattr(
        setup,
        "_installed_tags",
        lambda settings: {"qwen3.5:4b", "nomic-embed-text:latest"},
    )
    missing = setup.missing_models(
        object(),
        ("qwen3.5:4b", "nomic-embed-text", "qwen2.5-coder:14b"),
    )
    assert missing == ["qwen2.5-coder:14b"]


def test_ensure_gateway_dry_run_names_both_pieces(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", root)
    step = setup.ensure_gateway(dry_run=True)
    assert step.ok
    assert "config.yaml" in step.detail
    assert "litellm" in step.detail


def test_ready_summary_points_at_the_live_views(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", tmp_path / "runtime")
    text = "\n".join(setup.ready_summary())
    assert "sovereign harness" in text
    assert "sovereign orchestrate" in text
    assert "live monitor" in text


def test_root_is_self_contained_compares_resolved_paths(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", runtime)
    monkeypatch.setattr(config, "RUNTIME_ROOT", runtime)
    assert setup.root_is_self_contained()

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", other)
    assert not setup.root_is_self_contained()
