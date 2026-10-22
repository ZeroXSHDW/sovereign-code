"""Tests for the inline local ChatGPT client."""

from __future__ import annotations

from sovereign_code import webchat


def test_webchat_is_self_contained_and_local() -> None:
    page = webchat.page()
    assert "ChatGPT" in page
    assert "127.0.0.1" in page
    assert "<script src=" not in page
    assert "cdn" not in page.lower()
    for model in ("best", "auto", "deep", "ultra", "balanced", "fast"):
        assert f'value="{model}"' in page
    assert "Run browser task" in page
    assert "/api/browse" in page


def test_webchat_health_endpoint_contract() -> None:
    # The UI polls this shape; keep it stable.
    assert webchat.DEFAULT_PORT == 4020
    assert webchat.DEFAULT_ROUTER.endswith(":4010")
