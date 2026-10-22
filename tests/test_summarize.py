"""Summary helper tests."""

from __future__ import annotations

import httpx
import pytest

from sovereign_code.summarize import SourceError, read_text_source, summarize_text


def test_read_file_source(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("first line\nsecond line\n", encoding="utf-8")
    text = read_text_source(path=str(source))
    assert "second line" in text


def test_read_truncates_long_text(tmp_path) -> None:
    source = tmp_path / "big.txt"
    source.write_text("x" * 100, encoding="utf-8")
    text = read_text_source(path=str(source), max_chars=10)
    assert text.endswith("[truncated]")
    assert len(text) <= 10 + len("\n…[truncated]")


def test_read_requires_source() -> None:
    with pytest.raises(SourceError):
        read_text_source()


def test_read_refuses_private_addresses() -> None:
    """`--url` must not become an SSRF probe for the machine's own services."""
    for url in (
        "http://127.0.0.1:4010/v1/models",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.5/admin",
        "file:///etc/passwd",
    ):
        with pytest.raises(SourceError):
            read_text_source(url=url)


def test_read_refuses_a_redirect_into_a_private_address(monkeypatch) -> None:
    """A public URL that bounces to loopback is still a private fetch."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:4010/v1/models"})
        return httpx.Response(200, text="secret")

    class FakeClient:
        def get(self, url, **kwargs):
            return handler(httpx.Request("GET", url))

    monkeypatch.setattr("sovereign_code.summarize.shared_client", lambda *a, **k: FakeClient())
    with pytest.raises(SourceError):
        read_text_source(url="http://public.example/start")
    assert seen == ["http://public.example/start"]


def test_summarize_returns_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer local"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "the gist"}}]},
        )

    summary = summarize_text(
        "http://gw", "local-chat", "content", transport=httpx.MockTransport(handler)
    )
    assert summary == "the gist"


def test_summarize_malformed_reply() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="nope"))
    with pytest.raises(SourceError):
        summarize_text("http://gw", "local-chat", "content", transport=transport)
