"""Configuration, memory, and session tests."""

import json

from sovereign_code.config import Settings
from sovereign_code.system import is_loopback, read_memory


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
    assert not is_loopback("http://0.0.0.0:11434")


def test_session_roundtrip(tmp_path, monkeypatch):
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
