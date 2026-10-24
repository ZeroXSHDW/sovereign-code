from __future__ import annotations

from sovereign_code import serverguard


def test_loopback_host_ok() -> None:
    assert serverguard.loopback_host_ok("127.0.0.1") is True
    assert serverguard.loopback_host_ok("example.com") is False


def test_content_length() -> None:
    assert serverguard.content_length("12") == 12
    assert serverguard.content_length(None) == 0
