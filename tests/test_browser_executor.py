"""Integration test for the Playwright session against a local fixture site."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from sovereign_code.browser.actions import Action, BrowserPolicy
from sovereign_code.browser.executor import BrowserSession, SensitiveFieldError

FIXTURE = """<!doctype html>
<html>
  <head><title>Fixture page</title></head>
  <body>
    <h1>Fixture page</h1>
    <input id="name" placeholder="Your name">
    <input id="pw" type="password" placeholder="Password">
    <button id="greet"
      onclick="document.getElementById('out').textContent =
      'Hello ' + document.getElementById('name').value">Greet</button>
    <p id="out"></p>
    <a href="/next">Next page</a>
  </body>
</html>
"""

CAPTCHA = """<!doctype html>
<html><head><title>Human check</title></head>
<body><h1>Verify you are human</h1></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = CAPTCHA if self.path == "/captcha" else FIXTURE
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


@contextmanager
def _site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_observe_fill_click_password_and_captcha(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    with _site() as base:
        session = BrowserSession(
            profile_dir=tmp_path / "profile",
            policy=BrowserPolicy(allow_local=True),
            headless=True,
            timeout_ms=8000,
        )
        try:
            try:
                session.start(base)
            except Exception as exc:  # browser binary missing or launch failure
                pytest.skip(f"Chromium unavailable: {exc}")
            observation = session.observe()
            assert "Fixture" in observation["title"]
            inputs = [item for item in observation["elements"] if item["tag"] == "input"]
            name = next(item for item in inputs if item["type"] != "password")
            password = next(item for item in inputs if item["type"] == "password")
            button = next(item for item in observation["elements"] if item["tag"] == "button")

            session.perform(Action("fill", target=name["id"], text="Ada"))
            with pytest.raises(SensitiveFieldError):
                session.perform(Action("fill", target=password["id"], text="hunter2"))
            session.perform(Action("click", target=button["id"]))
            after = session.observe()
            assert "Hello Ada" in after["text"]
            assert after["captcha"] is False

            session.goto(base + "captcha")
            captcha = session.observe()
            assert captcha["captcha"] is True
        finally:
            session.close()


def test_chromium_path_detects_installed_browser() -> None:
    import importlib.util

    if importlib.util.find_spec("playwright") is None:
        pytest.skip("playwright not installed")
    from sovereign_code.browser.executor import chromium_path

    path = chromium_path()
    assert path is not None and path.exists()
