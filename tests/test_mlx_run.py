"""Tests for the MLX routing in `sovereign run`.

The bug: `sovereign run mlx-...` fell through to Ollama (which has no MLX
model) instead of the running mlx-lm server. These tests pin the MLX branch.
"""

from __future__ import annotations

import httpx as real_httpx

from sovereign_code import cli, mlx


class _Resp:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {"choices": [{"message": {"content": "hello from mlx"}}]}


def test_mlx_complete_posts_to_the_server(monkeypatch) -> None:
    seen: dict = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return _Resp()

    monkeypatch.setattr(real_httpx, "post", fake_post)
    monkeypatch.setattr(mlx, "mlx_url", lambda: "http://127.0.0.1:8081")
    monkeypatch.setattr(mlx, "forward_model", lambda tag: f"repo/{tag}")

    text = cli._mlx_complete("mlx-qwen3-4b-4bit", "hi", None, 512, 0.25)
    assert text == "hello from mlx"
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["json"]["model"] == "repo/mlx-qwen3-4b-4bit"


def test_mlx_complete_returns_none_on_http_error(monkeypatch, capsys) -> None:
    def fake_post(url, json=None, timeout=None):
        raise real_httpx.ConnectError("down")

    monkeypatch.setattr(real_httpx, "post", fake_post)
    monkeypatch.setattr(mlx, "mlx_url", lambda: "http://127.0.0.1:8081")
    monkeypatch.setattr(mlx, "forward_model", lambda tag: tag)
    # The helper prints an error then returns None.
    assert cli._mlx_complete("mlx-x", "hi", None, 64, 0.0) is None
    assert "unreachable" in capsys.readouterr().out
