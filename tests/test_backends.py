"""Tests for local inference backend probing."""

from __future__ import annotations

from unittest.mock import MagicMock

from sovereign_code.backends import Backend, BackendStatus, known_backends, probe, resolve
from sovereign_code.config import Settings


def test_known_backends_lists_all() -> None:
    backends = known_backends(Settings())
    keys = [b.key for b in backends]
    assert keys == ["gateway", "ollama", "jan", "lmstudio", "llamacpp", "mlx"]


def test_known_backends_strips_trailing_slash() -> None:
    settings = Settings(gateway_url="http://x:1234/", ollama_host="y:11434/")
    backends = {b.key: b for b in known_backends(settings)}
    assert backends["gateway"].url == "http://x:1234"
    assert backends["ollama"].url == "http://y:11434"


def test_probe_returns_offline_on_http_error(monkeypatch) -> None:
    import httpx

    backend = Backend("ollama", "Ollama", "http://127.0.0.1:11434")
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError("refused")
    monkeypatch.setattr("sovereign_code.backends.shared_client", lambda: client)
    status = probe(backend)
    assert status.online is False
    assert status.models == ()


def test_probe_returns_offline_on_bad_json(monkeypatch) -> None:
    backend = Backend("jan", "Jan", "http://127.0.0.1:1337")
    response = MagicMock()
    response.json.side_effect = ValueError("not json")
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = response
    monkeypatch.setattr("sovereign_code.backends.shared_client", lambda: client)
    status = probe(backend)
    assert status.online is False


def test_probe_returns_online_with_models(monkeypatch) -> None:
    backend = Backend("ollama", "Ollama", "http://127.0.0.1:11434")
    response = MagicMock()
    response.json.return_value = {
        "data": [
            {"id": "qwen3:8b"},
            {"id": "gemma4:12b"},
            {"id": None},
            "not-a-dict",
        ]
    }
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = response
    monkeypatch.setattr("sovereign_code.backends.shared_client", lambda: client)
    status = probe(backend)
    assert status.online is True
    assert status.models == ("qwen3:8b", "gemma4:12b")


def test_probe_handles_missing_data_key(monkeypatch) -> None:
    backend = Backend("jan", "Jan", "http://127.0.0.1:1337")
    response = MagicMock()
    response.json.return_value = {}
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = response
    monkeypatch.setattr("sovereign_code.backends.shared_client", lambda: client)
    status = probe(backend)
    assert status.online is True
    assert status.models == ()


def test_resolve_finds_by_key() -> None:
    settings = Settings()
    assert resolve(settings, "ollama") is not None
    assert resolve(settings, "ollama").key == "ollama"


def test_resolve_returns_none_for_unknown() -> None:
    assert resolve(Settings(), "nonexistent") is None


def test_backend_status_fields() -> None:
    backend = Backend("jan", "Jan", "http://127.0.0.1:1337")
    status = BackendStatus(backend, True, ("model-a", "model-b"))
    assert status.backend is backend
    assert status.online is True
    assert status.models == ("model-a", "model-b")
