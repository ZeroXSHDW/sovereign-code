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


def _request(
    server,
    path: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
):
    port = server.server_address[1]
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        body_bytes = response.read()
        return response.status, body_bytes
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


def test_webchat_last_shot_404_when_none(server, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(webchat, "_LAST_SHOT", None)
    status, body = _request(server, "/api/last-shot", headers={"Host": "127.0.0.1"})
    assert status == 404
    assert json.loads(body)["error"] == "no screenshot"


def test_webchat_last_shot_serves_a_png(server, monkeypatch, tmp_path) -> None:
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(webchat, "_LAST_SHOT", shot)
    status, body = _request(server, "/api/last-shot", headers={"Host": "127.0.0.1"})
    assert status == 200
    assert body == b"\x89PNG\r\n\x1a\n"


def test_webchat_skill_404_for_unknown(server, monkeypatch) -> None:
    monkeypatch.setattr(webchat.Handler, "_reject_cross_origin", lambda self: False)
    status, _ = _request(server, "/api/skill?name=no-such-skill", headers={"Host": "127.0.0.1"})
    assert status == 404


def test_webchat_skills_lists_matches(server, monkeypatch) -> None:
    monkeypatch.setattr(webchat.Handler, "_reject_cross_origin", lambda self: False)

    def fake_search(query: str, limit: int):
        return [("react", "a react skill")] if query == "react" else []

    monkeypatch.setattr("sovereign_code.skills.search_skills", fake_search)
    status, body = _request(server, "/api/skills?q=react", headers={"Host": "127.0.0.1"})
    assert status == 200
    assert json.loads(body) == [{"name": "react", "description": "a react skill"}]


def test_webchat_rejects_a_too_large_body(server) -> None:
    # serverguard caps a declared body well before it is read.
    status, _ = _request(
        server,
        "/api/browse",
        method="POST",
        headers={"Host": "127.0.0.1", "Content-Length": str(64 * 1024 * 1024)},
    )
    assert status == 413


def test_webchat_rejects_invalid_json(server) -> None:
    raw = b"not json"
    status, _ = _request(
        server,
        "/api/browse",
        method="POST",
        headers={
            "Host": "127.0.0.1",
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        },
        body=raw,
    )
    assert status == 400


def test_webchat_unknown_route_is_404(server) -> None:
    status, body = _request(server, "/nope", headers={"Host": "127.0.0.1"})
    assert status == 404
    assert json.loads(body)["error"] == "not found"


def test_webchat_unknown_post_route_is_404(server) -> None:
    status, _ = _request(
        server,
        "/api/nope",
        method="POST",
        headers={"Host": "127.0.0.1", "Content-Length": "2"},
    )
    assert status == 404


def test_host_is_local_requires_a_host_header(server) -> None:
    handler = webchat.Handler.__new__(webchat.Handler)
    handler.headers = {}
    assert handler._host_is_local() is False
    handler.headers = {"Host": "attacker.example"}
    assert handler._host_is_local() is False
    handler.headers = {"Host": "localhost"}
    assert handler._host_is_local() is True


def test_origin_is_local_allows_a_same_origin_post(server) -> None:
    port = server.server_address[1]
    handler = webchat.Handler.__new__(webchat.Handler)
    handler.headers = {}
    handler.port = port
    assert handler._origin_is_local() is True
    handler.headers = {"Origin": f"http://127.0.0.1:{port}"}
    assert handler._origin_is_local() is True
    handler.headers = {"Origin": f"http://127.0.0.1:{port + 1}"}
    assert handler._origin_is_local() is False


def test_model_options_falls_back_without_a_catalog(monkeypatch) -> None:
    monkeypatch.setattr("sovereign_code.tier_gateway.catalog_models", lambda *_a, **_k: [])
    options = webchat.model_options()
    assert 'value="best"' in options


def test_pid_is_webchat_rejects_an_unrelated_process(monkeypatch) -> None:
    def fake_run(_cmd, **_kwargs):
        return webchat.subprocess.CompletedProcess(_cmd, 0, stdout="python -m http.server")

    monkeypatch.setattr(webchat.subprocess, "run", fake_run)
    assert webchat._pid_is_webchat(1234) is False
