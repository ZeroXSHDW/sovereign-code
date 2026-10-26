"""Tests for the warm pool module.

The warm pool talks to Ollama natively, so every test here mocks the HTTP
layer. No real model is loaded; no real Ollama is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from sovereign_code.warm import WarmPool, pool


def _mock_response(status_code: int = 200, body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body or {"done": True},
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/generate"),
    )


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.post.return_value = _mock_response()
    return client


def test_add_model_uses_catalog_size() -> None:
    p = WarmPool()
    p.add("qwen3.5:4b", task="fast")
    model = p.status()[0]
    assert model.tag == "qwen3.5:4b"
    assert model.task == "fast"
    assert model.size_gb > 0


def test_add_unknown_model_uses_zero_size() -> None:
    p = WarmPool()
    p.add("unknown:tag")
    assert p.status()[0].size_gb == 0.0


def test_warm_loads_each_model_once() -> None:
    p = WarmPool()
    p.add("a:1")
    p.add("b:1")
    with patch("sovereign_code.warm.shared_client", return_value=_mock_client()):
        result = p.warm()
    assert set(result) == {"a:1", "b:1"}
    models = {m.tag: m for m in p.status()}
    assert models["a:1"].loaded is True
    assert models["b:1"].loaded is True
    assert models["a:1"].error == ""


def test_warm_records_load_failure() -> None:
    p = WarmPool()
    p.add("fail:1")
    client = MagicMock()
    client.post.side_effect = httpx.ConnectError("boom")
    with patch("sovereign_code.warm.shared_client", return_value=client):
        result = p.warm()
    assert result == {"fail:1": 0.0}
    assert p.status()[0].loaded is False
    assert "load failed" in p.status()[0].error


def test_touch_only_for_loaded_models() -> None:
    p = WarmPool()
    p.add("a:1")
    client = _mock_client()
    with patch("sovereign_code.warm.shared_client", return_value=client):
        p.warm()
        client.post.reset_mock()
        p.touch()
    # One model was loaded, so touch should have been called once.
    assert client.post.call_count == 1


def test_touch_skips_when_nothing_loaded() -> None:
    p = WarmPool()
    p.add("a:1")
    client = _mock_client()
    with patch("sovereign_code.warm.shared_client", return_value=client):
        p.touch()
    assert client.post.call_count == 0


def test_start_stop_background_thread() -> None:
    p = WarmPool()
    p.add("a:1")
    client = _mock_client()
    with patch("sovereign_code.warm.shared_client", return_value=client):
        p.warm()
        p.start(interval=0.05)
        import time

        time.sleep(0.2)
        p.stop()
    # At least one touch happened in the background loop.
    assert p.status()[0].touch_count >= 2  # 1 from warm + >=1 from loop


def test_save_state_writes_json(tmp_path: Path) -> None:
    p = WarmPool(ollama="http://127.0.0.1:11434")
    p.add("a:1")
    with patch("sovereign_code.warm.WARM_STATE", tmp_path / "warm.json"):
        with patch("sovereign_code.warm.shared_client", return_value=_mock_client()):
            p.warm()
            path = p.save_state()
    data = json.loads(path.read_text())
    assert "a:1" in data
    assert data["a:1"]["loaded"] is True


def test_summary_lists_models() -> None:
    p = WarmPool()
    p.add("a:1")
    summary = p.summary()
    assert "a:1" in summary
    assert "cold" in summary


def test_summary_shows_error_when_load_failed() -> None:
    p = WarmPool()
    p.add("fail:1")
    client = MagicMock()
    client.post.side_effect = httpx.ConnectError("boom")
    with patch("sovereign_code.warm.shared_client", return_value=client):
        p.warm()
    summary = p.summary()
    assert "load failed" in summary


def test_singleton_pool_returns_same_instance() -> None:
    with patch("sovereign_code.warm._pool", None):
        a = pool()
        b = pool()
        assert a is b


def test_warm_records_non_http_error() -> None:
    p = WarmPool()
    p.add("fail:1")
    client = MagicMock()
    client.post.side_effect = ValueError("boom")
    with patch("sovereign_code.warm.shared_client", return_value=client):
        result = p.warm()
    assert result == {"fail:1": 0.0}
    assert "boom" in p.status()[0].error


def test_warm_skips_missing_models() -> None:
    p = WarmPool()
    result = p.warm(["not-added"])
    assert result == {}


def test_touch_handles_http_error_and_skips_unloaded() -> None:
    p = WarmPool()
    p.add("a:1")

    def make_client():
        client = MagicMock()
        client.post.return_value = _mock_response()
        return client

    warm_client = make_client()
    touch_client = MagicMock()
    touch_client.post.side_effect = httpx.ConnectError("boom")

    with patch("sovereign_code.warm.shared_client", return_value=warm_client):
        p.warm()
    with patch("sovereign_code.warm.shared_client", return_value=touch_client):
        p.touch()
    assert p.status()[0].touch_count >= 1


def test_touch_skips_unloaded_model() -> None:
    p = WarmPool()
    p.add("cold:1")
    client = _mock_client()
    with patch("sovereign_code.warm.shared_client", return_value=client):
        p.touch()
    assert client.post.call_count == 0


def test_stop_is_safe_when_not_started() -> None:
    p = WarmPool()
    p.stop()  # no thread; should not raise


def test_loop_exception_is_swallowed() -> None:
    p = WarmPool()
    p.add("a:1")

    def boom() -> None:
        raise RuntimeError("boom")

    p.touch = boom  # type: ignore[assignment]
    p._interval = 0.01
    p.start()
    import time

    time.sleep(0.05)
    p.stop()
