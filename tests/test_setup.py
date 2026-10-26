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


def test_migrate_reports_a_fresh_install_when_no_legacy_exists(tmp_path, monkeypatch):
    target = tmp_path / "runtime"
    monkeypatch.setattr(setup, "legacy_root", lambda: tmp_path / "never-existed")
    monkeypatch.setattr(setup, "runtime_target", lambda: target)
    step = setup.migrate_legacy(stop_services=False)
    assert step.ok and step.skipped
    assert "fresh install" in step.detail


def test_migrate_reports_a_failed_rename(tmp_path, monkeypatch):
    legacy = tmp_path / "local-ai"
    legacy.mkdir()
    # The target's parent is a file, so creating the target directory fails
    # and migrate_legacy must report a failure instead of crashing.
    blocker = tmp_path / "repo"
    blocker.write_text("not a directory", encoding="utf-8")
    target = blocker / "runtime"
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", legacy)
    monkeypatch.setattr(setup, "legacy_root", lambda: legacy)
    monkeypatch.setattr(setup, "runtime_target", lambda: target)
    step = setup.migrate_legacy(stop_services=False)
    assert not step.ok
    assert "could not move" in step.detail


def test_check_ollama_reports_a_missing_binary(monkeypatch):
    monkeypatch.setattr(setup, "_http_ok", lambda *_a, **_k: False)
    monkeypatch.setattr(setup, "system_binary", lambda _name: None)
    settings = config.Settings()
    step = setup.check_ollama(settings, dry_run=True)
    assert not step.ok
    assert "brew install ollama" in step.detail


def test_ensure_layout_dry_run_lists_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", tmp_path / "runtime")
    step = setup.ensure_layout(dry_run=True)
    assert step.ok
    assert "8 directories" in step.detail


def test_install_clients_dry_run_is_a_noop(monkeypatch):
    monkeypatch.setattr(setup.subprocess, "run", _fail_if_called)
    step = setup.install_clients(dry_run=True)
    assert step.ok
    assert "would write" in step.detail


def test_install_login_dry_run_is_a_noop(monkeypatch):
    monkeypatch.setattr(setup.subprocess, "run", _fail_if_called)
    step = setup.install_login(dry_run=True)
    assert step.ok
    assert "login" in step.detail


def test_install_services_dry_run_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", tmp_path / "runtime")
    settings = config.Settings()
    step = setup.install_services(settings, dry_run=True)
    assert step.ok
    assert "would install" in step.detail


def test_pull_models_skips_when_nothing_is_missing(monkeypatch):
    monkeypatch.setattr(setup, "missing_models", lambda _settings, _stack: [])
    settings = config.Settings()
    step = setup.pull_models(settings, ())
    assert step.ok and step.skipped


def test_pull_models_requires_yes_on_a_non_tty(monkeypatch):
    monkeypatch.setattr(setup, "missing_models", lambda _s, _stack: ["gemma4:12b"])
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: False)
    settings = config.Settings()
    step = setup.pull_models(settings, ("gemma4:12b",))
    assert not step.ok
    assert "--yes" in step.detail


def test_run_setup_dry_run_returns_one_step_per_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_AI_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(setup, "legacy_root", lambda: tmp_path / "no-legacy")
    monkeypatch.setattr(setup, "runtime_target", lambda: tmp_path / "runtime")
    monkeypatch.setattr(setup, "_http_ok", lambda *_a, **_k: True)
    settings = config.Settings()
    rows = setup.run_setup(settings, models="none", dry_run=True)
    names = [row.name for row in rows]
    assert names == [
        "runtime",
        "layout",
        "ollama",
        "gateway",
        "models",
        "clients",
        "services",
        "login",
    ]
    assert all(row.ok for row in rows)


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("subprocess must not run under dry_run")


def test_installed_tags_parses_the_ollama_payload(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"models": [{"name": "qwen3.5:4b"}, {"name": "gemma4:12b"}]}

    class FakeClient:
        def get(self, _url, timeout=3.0):
            return FakeResponse()

    monkeypatch.setattr(setup, "shared_client", lambda: FakeClient())
    assert setup._installed_tags(config.Settings()) == {"qwen3.5:4b", "gemma4:12b"}


def test_stop_services_never_raises(monkeypatch):
    from sovereign_code import services

    class Explodes:
        name = "boom"

    monkeypatch.setattr(services, "service_definitions", lambda: [Explodes()])
    monkeypatch.setattr(
        services, "unload_service", lambda _service: (_ for _ in ()).throw(RuntimeError())
    )
    assert setup._stop_services() == []
