"""Tests for config parsing and saving, system probes, and the status snapshot."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.config import Settings
from sovereign_code.models import build_views
from sovereign_code.status import Snapshot
from sovereign_code.system import Memory, is_loopback, read_memory


def _write_config(tmp_path: Path, monkeypatch, body: str) -> Path:
    import sovereign_code.config as config

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    return path


def test_url_normalisation():
    assert Settings(ollama_host="127.0.0.1:11434").ollama_url == "http://127.0.0.1:11434"
    assert Settings(ollama_host="http://localhost:11434/").ollama_url == "http://localhost:11434"


def test_memory_probe_real_machine():
    memory = read_memory()
    assert memory.total_gb > 0
    assert 0 <= memory.free_gb <= memory.total_gb
    assert 0 <= memory.free_pct <= 100


def test_loopback_detection():
    assert is_loopback("http://127.0.0.1:11434")
    assert is_loopback("http://localhost:4000")
    assert is_loopback("127.0.0.1:11434")
    assert is_loopback("http://[::1]:4000")
    assert not is_loopback("http://0.0.0.0:11434")


def test_loopback_detection_is_not_a_substring_test():
    """A host that merely contains a loopback address is not loopback."""
    assert not is_loopback("http://notlocalhost.example.com")
    assert not is_loopback("http://127.0.0.1.evil.test")
    assert not is_loopback("http://192.168.1.10:11434")
    assert not is_loopback("")


def test_session_roundtrip(tmp_path, monkeypatch):
    import json

    import sovereign_code.sessions as sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    writer = sessions.SessionWriter.create("qwen3.5:4b", cwd="/tmp/project")
    writer.append("user", "hello")
    writer.append("assistant", "hi", model="qwen3.5:4b")

    records = sessions.read_session(writer.path)
    assert records[0]["type"] == "session"
    assert records[0]["model"] == "qwen3.5:4b"
    assert records[1]["role"] == "user"
    assert records[2]["content"] == "hi"
    assert writer.path.stat().st_mode & 0o777 == 0o600
    assert json.loads(writer.path.read_text().splitlines()[1])["content"] == "hello"


# --------------------------------------------------------------------- config


def test_settings_escape_every_string_field(tmp_path, monkeypatch):
    """A quote in any string field used to produce invalid TOML.

    The next load then silently fell back to the defaults, so the user's
    configuration vanished without a word.
    """
    _write_config(tmp_path, monkeypatch, "")
    settings = Settings(
        ollama_host='12"7.0.0.1',
        gateway_url="http://x\\y",
        default_task="code",
        theme='a"b',
        workspace='~/Some "Folder"',
    )
    settings.save()
    body = settings.config_path.read_text(encoding="utf-8")
    assert '\\"' in body

    import tomllib

    parsed = tomllib.loads(body)
    assert parsed["ollama_host"] == '12"7.0.0.1'
    assert parsed["gateway_url"] == "http://x\\y"
    assert parsed["theme"] == 'a"b'
    assert parsed["workspace"] == '~/Some "Folder"'


def test_settings_survive_a_bad_numeric_value(tmp_path, monkeypatch):
    """A hand-edited config must not raise out of `load()`."""
    _write_config(tmp_path, monkeypatch, 'max_context = "abc"\ntemperature = "hot"\n')
    settings = Settings.load()
    assert settings.max_context >= 2048
    assert 0.0 <= settings.temperature <= 2.0


def test_settings_report_a_malformed_config(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "this is not = = toml\n")
    settings = Settings.load()
    assert "TOML" in settings.parse_error


def test_settings_keep_an_unknown_task_out_of_the_router(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, 'default_task = "wat"\n')
    assert Settings.load().default_task == "code"


def test_settings_coerce_a_boolean(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, 'login_enabled = "false"\n')
    assert Settings.load().login_enabled is False
    _write_config(tmp_path, monkeypatch, "login_enabled = false\n")
    assert Settings.load().login_enabled is False
    _write_config(tmp_path, monkeypatch, "login_enabled = true\n")
    assert Settings.load().login_enabled is True


# --------------------------------------------------------------------- status


def test_potential_free_memory_is_unknown_when_the_probe_fails():
    """A failed vm_stat must not read as "0 GB free".

    Zero free RAM collapses every model's context to the 2k floor.
    """
    snap = Snapshot(settings=Settings(), memory=Memory(24.0, 0.0, 0.0, known=False))
    assert snap.potential_free_gb is None


def test_potential_free_memory_adds_the_resident_models():
    views = build_views(
        {"models": [{"name": "m:latest", "size": (4 * 1024**3), "details": {}}]},
        {"models": [{"name": "m:latest", "size": (4 * 1024**3), "context_length": 4096}]},
    )
    snap = Snapshot(settings=Settings(), views=views, memory=Memory(24.0, 5.0, 21.0))
    assert snap.potential_free_gb == 9.0


def test_recommended_coder_is_the_catalog_recommendation():
    from sovereign_code.models import CATALOG, recommended_tag

    snap = Snapshot(settings=Settings(), views=build_views({"models": []}, None))
    assert snap.recommended_coder is not None
    assert snap.recommended_coder.tag == recommended_tag()
    assert CATALOG[recommended_tag()].recommended is True
