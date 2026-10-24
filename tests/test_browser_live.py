"""Live Chromium end-to-end tests for the browser operator.

These launch a real headless Chromium against a local HTTP page. They are
marked ``integration`` and are skipped when Playwright or its browser is not
installed, so the normal unit suite stays fast.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sovereign_code.browser.actions import Action, BrowserPolicy
from sovereign_code.browser.executor import BrowserSession
from sovereign_code.errors import BrowserError, PolicyError, SensitiveFieldError

pytestmark = pytest.mark.integration

PAGE = b"""<!doctype html>
<html><head><title>Live browser test</title></head>
<body>
<h1>Live browser test</h1>
<label for="name">Name</label><input id="name" name="name">
<button id="hi" onclick="document.getElementById('out').textContent='Hi '+document.getElementById('name').value">Say hi</button>
<div id="out"></div>
<button id="del" onclick="document.getElementById('out').textContent='deleted'">Delete account</button>
<button id="hover" onmouseover="this.textContent='hovered'" onmouseout="this.textContent='Hover me'">Hover me</button>
<input id="pw" type="password" name="password" value="secret">
</body></html>
"""


class _Page(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        body = PAGE if self.path in {"/", "/index.html"} else b"\x89PNG\r\n\x1a\n"
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/html; charset=utf-8" if self.path == "/" else "image/png"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def page_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module", autouse=True)
def chromium_installed() -> None:
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"Chromium is not installed: {exc}")


def _find(observation: dict, needle: str) -> int:
    for element in observation["elements"]:
        if needle.lower() in str(element["name"]).lower():
            return int(element["id"])
    raise AssertionError(f"{needle!r} not in {observation['elements']}")


def test_live_browser_operator_end_to_end(tmp_path: Path, page_url: str) -> None:
    profile = tmp_path / "profile"
    session = BrowserSession(
        profile_dir=profile, policy=BrowserPolicy(allow_local=True), headless=True
    )
    session.start(page_url)
    try:
        observation = session.observe()
        assert "Live browser test" in observation["text"]

        name_id = _find(observation, "Name")
        hi_id = _find(observation, "Say hi")
        delete_id = _find(observation, "Delete account")
        hover_id = _find(observation, "Hover me")
        password_id = _find(observation, "password")

        assert session.perform(Action("fill", target=name_id, text="Ada"))["ok"] is True
        assert session.perform(Action("click", target=hi_id))["ok"] is True
        assert "Hi Ada" in session.observe()["text"]

        cancelled = session.perform(Action("click", target=delete_id))
        assert cancelled.get("cancelled") is True
        assert session.observe()["text"].count("deleted") == 0

        confirmed = session.perform(Action("click", target=delete_id), confirm=lambda _q: True)
        assert confirmed["ok"] is True
        assert "deleted" in session.observe()["text"]

        assert session.perform(Action("hover", target=hover_id))["ok"] is True

        with pytest.raises(SensitiveFieldError):
            session.perform(Action("fill", target=password_id, text="x"))

        extracted = session.perform(Action("extract"))
        assert "Live browser test" in str(extracted.get("extract"))

        shot = tmp_path / "shot.png"
        assert session.screenshot(shot) is not None
        assert shot.read_bytes().startswith(b"\x89PNG")

        session.goto(page_url)
        session.reload()
        session.back()
        session.forward()

        with pytest.raises(BrowserError):
            BrowserSession(
                profile_dir=profile, policy=BrowserPolicy(allow_local=True), headless=True
            ).start(page_url)
    finally:
        session.close()

    # close() must release the profile lock.
    second = BrowserSession(
        profile_dir=profile, policy=BrowserPolicy(allow_local=True), headless=True
    )
    second.start(page_url)
    second.close()

    blocked = BrowserSession(
        profile_dir=tmp_path / "blocked", policy=BrowserPolicy(), headless=True
    )
    with pytest.raises(PolicyError):
        blocked.start(page_url)
    blocked.close()


def test_live_mcp_browser_tools(
    tmp_path: Path, page_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sovereign_code import config, mcp

    monkeypatch.setattr(config, "LOCAL_AI_ROOT", tmp_path)
    mcp._browser_close()
    try:
        opened = mcp._browser_open(page_url, allow_local=True, headless=True)
        assert opened["url"].startswith("http://127.0.0.1:")

        observation = mcp._browser_observe()
        name_id = _find(observation, "Name")
        hi_id = _find(observation, "Say hi")
        mcp._browser_act({"action": "fill", "id": name_id, "text": "MCP"})
        mcp._browser_act({"action": "click", "id": hi_id})
        assert "Hi MCP" in mcp._browser_observe()["text"]
        assert mcp._browser_screenshot()
    finally:
        mcp._browser_close()
