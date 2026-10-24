"""Supplementary coverage for config layout and coercion helpers."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.config import (
    Settings,
    dashboard_command_path,
    launch_agent_path,
)


def test_find_project_root_resolves_env(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    monkeypatch.setenv("SOVEREIGN_PROJECT_ROOT", str(tmp_path))
    assert config.find_project_root() == tmp_path.resolve()


def test_find_project_root_discovers_checkout(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    monkeypatch.delenv("SOVEREIGN_PROJECT_ROOT", raising=False)
    root = tmp_path / "checkout"
    (root / "src" / "sovereign_code").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "__file__", str(root / "src" / "sovereign_code" / "config.py"))
    assert config.find_project_root() == root


def test_find_project_root_falls_back_to_default(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    monkeypatch.delenv("SOVEREIGN_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(config, "_home", lambda: tmp_path)
    # __file__ points nowhere with a pyproject.toml -> fall back to ~/Documents/APP_NAME
    monkeypatch.setattr(config, "__file__", str(tmp_path / "none.py"))
    monkeypatch.setattr(config.Path, "cwd", lambda: tmp_path)
    expected = tmp_path / "Documents" / config.APP_NAME
    assert config.find_project_root() == expected


def test_runtime_root_env_override(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    monkeypatch.setenv("SOVEREIGN_HOME", str(tmp_path))
    assert config._runtime_root() == tmp_path


def test_runtime_root_prefers_existing_runtime(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    monkeypatch.delenv("SOVEREIGN_HOME", raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(config, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(config, "LEGACY_LOCAL_AI_ROOT", tmp_path / "legacy")
    (tmp_path / "legacy").mkdir()
    assert config._runtime_root() == runtime


def test_runtime_root_legacy_fallback(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    monkeypatch.delenv("SOVEREIGN_HOME", raising=False)
    monkeypatch.setattr(config, "RUNTIME_ROOT", tmp_path / "runtime-missing")
    monkeypatch.setattr(config, "LEGACY_LOCAL_AI_ROOT", tmp_path / "legacy")
    (tmp_path / "legacy").mkdir()
    assert config._runtime_root() == tmp_path / "legacy"


def test_runtime_root_returns_default_when_none_exist(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    monkeypatch.delenv("SOVEREIGN_HOME", raising=False)
    monkeypatch.setattr(config, "RUNTIME_ROOT", tmp_path / "runtime-missing")
    monkeypatch.setattr(config, "LEGACY_LOCAL_AI_ROOT", tmp_path / "legacy-missing")
    assert config._runtime_root() == tmp_path / "runtime-missing"


def test_load_reports_unreadable_config(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    real_read = Path.read_text

    def flaky(self, *a, **k):
        if self.name == "config.toml":
            raise OSError("unreadable")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    settings = Settings.load()
    assert "could not be read" in settings.parse_error


def test_load_applies_env_overrides(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import config

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setenv("SOVEREIGN_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("SOVEREIGN_GATEWAY_URL", "http://gw:4000")
    settings = Settings.load()
    assert settings.default_model == "qwen3.5:4b"
    assert settings.gateway_url == "http://gw:4000"


def test_as_int_and_float_coercion() -> None:
    from sovereign_code.config import _as_float, _as_int

    assert _as_int(True, 0) == 1
    assert _as_int("12", 0) == 12
    assert _as_int(object(), 7) == 7
    assert _as_int("abc", 7) == 7
    assert _as_float(True, 0.0) == 1.0
    assert _as_float("not-a-number", 0.5) == 0.5
    assert _as_float(object(), 3.0) == 3.0


def test_as_bool_variants() -> None:
    from sovereign_code.config import _as_bool

    assert _as_bool("yes") is True
    assert _as_bool("ON") is True
    assert _as_bool("1") is True
    assert _as_bool("0") is False
    assert _as_bool(1) is True
    assert _as_bool(None) is False


def test_write_default_config_idempotent(tmp_path: Path, monkeypatch) -> None:
    from sovereign_code import config

    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    first = config.write_default_config()
    assert first.is_file()
    second = config.write_default_config()
    assert second == first
    forced = config.write_default_config(force=True)
    assert forced == first


def test_path_helpers() -> None:
    assert launch_agent_path().name.endswith(".plist")
    assert launch_agent_path("custom.label").name == "custom.label.plist"
    assert dashboard_command_path().name == "sovereign-dashboard.command"


def test_bridge_url_hostless_router_falls_back(monkeypatch) -> None:
    from sovereign_code.config import DEFAULT_BRIDGE_PORT

    settings = Settings(router_url="localhost")  # no scheme -> hostname is None
    assert settings.bridge_url == f"http://127.0.0.1:{DEFAULT_BRIDGE_PORT}"
