"""Tests for the inline local ChatGPT client."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

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


# ------------------------------------------------------------------ a11y


def test_webchat_has_a_visible_focus_indicator() -> None:
    """WCAG 2.4.7: the focus ring must not be removed without a replacement."""
    page = webchat.page()
    assert "outline:none" not in page
    assert ":focus-visible" in page


def test_webchat_border_colour_meets_non_text_contrast() -> None:
    """WCAG 1.4.11: control boundaries need a 3:1 contrast ratio."""
    page = webchat.page()
    line = page.split("--line:", 1)[1].split(";", 1)[0].strip()

    def luminance(colour: str) -> float:
        raw = colour.lstrip("#")
        channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        adjusted = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]

    def ratio(a: str, b: str) -> float:
        la, lb = luminance(a), luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    for background in ("#0f141a", "#12161c", "#0b0d10"):
        assert ratio(line, background) >= 3.0, f"{line} on {background}"


def test_webchat_form_controls_are_labelled() -> None:
    page = webchat.page()
    assert '<label for="btask"' in page
    assert '<label for="burl"' in page
    assert '<label for="skillq"' in page
    assert '<label for="model"' in page


def test_webchat_screenshot_has_alt_text() -> None:
    page = webchat.page()
    assert 'id="bshot" alt="' in page


def test_webchat_log_has_a_live_region() -> None:
    """WCAG 4.1.3: a screen reader has to be told the answer arrived."""
    page = webchat.page()
    assert 'role="log"' in page
    assert 'aria-live="polite"' in page


def test_webchat_skill_items_are_keyboard_reachable() -> None:
    """WCAG 2.1.1: a skill must not be mouse-only."""
    page = webchat.page()
    assert "document.createElement('button')" in page
    assert "el.type='button'" in page


def test_webchat_sidebar_reflows_instead_of_disappearing() -> None:
    """WCAG 1.4.10: reflow must not remove function."""
    page = webchat.page()
    narrow = page.split("@media(max-width:760px)", 1)[1]
    assert "aside{display:none}" not in narrow


# -------------------------------------------------------------- security


@pytest.fixture
def server():
    """A webchat handler bound to an ephemeral port."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webchat.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _request(server, path: str, method: str = "GET", headers: dict[str, str] | None = None):
    port = server.server_address[1]
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        body = response.read()
        return response.status, body
    finally:
        conn.close()


def test_webchat_rejects_a_rebinding_host_header(server) -> None:
    """A page on another origin that resolves to 127.0.0.1 sends its own Host."""
    status, body = _request(server, "/api/health", headers={"Host": "attacker.example"})
    assert status == 403
    assert b"cross-origin" in body or b"loopback" in body


def test_webchat_rejects_a_cross_origin_post(server) -> None:
    status, _ = _request(
        server,
        "/api/chat",
        method="POST",
        headers={"Host": "127.0.0.1", "Origin": "http://attacker.example"},
    )
    assert status == 403


def test_webchat_accepts_its_own_origin(server) -> None:
    status, body = _request(server, "/api/health", headers={"Host": "127.0.0.1"})
    assert status == 200
    assert json.loads(body)["ok"] in (True, False)


def test_webchat_rejects_another_loopback_port(server) -> None:
    """Another local server must not drive /api/browse through a shared hostname."""
    port = server.server_address[1]
    previous = webchat.Handler.port
    webchat.Handler.port = port
    try:
        status, _ = _request(
            server,
            "/api/chat",
            method="POST",
            headers={
                "Host": "127.0.0.1",
                "Origin": f"http://127.0.0.1:{port + 1}",
                "Content-Length": "0",
            },
        )
        assert status == 403
    finally:
        webchat.Handler.port = previous


def test_webchat_rejects_a_malformed_content_length(server) -> None:
    status, _ = _request(
        server,
        "/api/chat",
        method="POST",
        headers={"Host": "127.0.0.1", "Content-Length": "not-a-number"},
    )
    assert status == 400


def test_webchat_sends_security_headers(server) -> None:
    port = server.server_address[1]
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/", headers={"Host": "127.0.0.1"})
        response = conn.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        response.read()
    finally:
        conn.close()
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in headers["content-security-policy"]
