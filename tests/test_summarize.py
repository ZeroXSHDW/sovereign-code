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
