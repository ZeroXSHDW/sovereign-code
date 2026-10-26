"""Tests for the LiteLLM gateway probe."""

from __future__ import annotations

import httpx
import pytest

from sovereign_code.gateway import check, parse_aliases


def _mock_client(response: httpx.Response):
    class AsyncClient:
        async def get(self, *a, **k):
            return response

        async def aclose(self):
            pass

    return AsyncClient()


@pytest.mark.asyncio
async def test_gateway_check_up(monkeypatch) -> None:
    response = httpx.Response(200, json={"data": [{"id": "m1"}]})
    monkeypatch.setattr(
        "sovereign_code.gateway.async_client", lambda *a, **k: _mock_client(response)
    )
    status = await check("http://127.0.0.1:4000")
    assert status.up is True
    assert "m1" in status.models


@pytest.mark.asyncio
async def test_gateway_check_bad_status(monkeypatch) -> None:
    response = httpx.Response(503)
    monkeypatch.setattr(
        "sovereign_code.gateway.async_client", lambda *a, **k: _mock_client(response)
    )
    status = await check("http://127.0.0.1:4000")
    assert status.up is False
    assert "503" in status.detail


@pytest.mark.asyncio
async def test_gateway_check_malformed_json(monkeypatch) -> None:
    response = httpx.Response(200, text="not-json")
    monkeypatch.setattr(
        "sovereign_code.gateway.async_client", lambda *a, **k: _mock_client(response)
    )
    status = await check("http://127.0.0.1:4000")
    assert status.up is True
    assert status.models == []


def test_parse_aliases_returns_empty_for_plain_yaml() -> None:
    assert parse_aliases("") == []
