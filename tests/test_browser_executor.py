"""Executor policy, gate, and secret-handling tests.

The unit tests drive a fake Playwright page so the policy and confirmation
logic is checked on every machine. The integration tests at the bottom need
a real Chromium and skip when one is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from sovereign_code.browser.actions import Action, BrowserPolicy, PolicyError
from sovereign_code.browser.executor import (
    OBSERVE_JS,
    PRESS_RISK_JS,
    SENSITIVE,
    SENSITIVE_PATTERN,
    BrowserSession,
    SensitiveFieldError,
)

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

# A page with the shapes the audit was worried about: a one-time code typed
# as plain text, a button with no label at all, and a form holding a secret.
SECRETS = """<!doctype html>
<html>
  <head><title>Secrets</title></head>
  <body>
    <h1>Secrets</h1>
    <input id="otp" name="otp_code" type="text" placeholder="One-time code" value="123456">
    <form id="login" action="/submit" method="post">
      <input id="user" name="username" type="text">
      <input id="pw" name="password" type="password">
      <button id="icon" type="submit" style="width:40px;height:40px"></button>
    </form>
  </body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            port = self.server.server_address[1]
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{port}/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/secrets":
            body = SECRETS
        elif self.path == "/captcha":
            body = CAPTCHA
        else:
            body = FIXTURE
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


class FakeLocator:
    """Stands in for a Playwright locator."""

    def __init__(self, page: FakePage, info: dict) -> None:
        self.page = page
        self.info = info
        self.clicked = False
        self.filled: list[str] = []
        self.selected: list[str] = []

    @property
    def first(self) -> FakeLocator:
        return self

    def count(self) -> int:
        return 1

    def evaluate(self, script: str):
        if "innerText" in script:
            return {
                "tag": self.info.get("tag", ""),
                "type": self.info.get("type", ""),
                "label": self.info.get("label", ""),
            }
        return self.info.get("blob", "")

    def get_attribute(self, name: str) -> str | None:
        value = self.info.get(name)
        return str(value) if value is not None else None

    def inner_text(self) -> str:
        return str(self.info.get("text", "body text"))

    def scroll_into_view_if_needed(self) -> None:
        return None

    def click(self, timeout: int = 0) -> None:
        self.timeout = timeout
        self.clicked = True
        self.page.clicked.append(self.info)
        if self.page.navigate_to:
            self.page.url = self.page.navigate_to

    def fill(self, text: str) -> None:
        self.filled.append(text)

    def select_option(self, value: str) -> None:
        self.selected.append(value)


class FakeKeyboard:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def press(self, key: str) -> None:
        self.page.pressed.append(key)


class FakePage:
    """Stands in for a Playwright page."""

    def __init__(
        self,
        url: str = "https://example.com/",
        elements: dict | None = None,
        observation: dict | None = None,
        press_risk: dict | None = None,
    ) -> None:
        self.url = url
        self.elements = elements or {}
        self.observation = observation or {"url": url, "title": "T", "text": "", "elements": []}
        self.press_risk = press_risk or {"credential": False, "focusedSubmit": False}
        self.goto_calls: list[str] = []
        self.clicked: list[dict] = []
        self.pressed: list[str] = []
        self.navigate_to: str | None = None
        self.keyboard = FakeKeyboard(self)

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.goto_calls.append(url)
        self.wait_until = wait_until
        self.timeout = timeout
        if self.navigate_to:
            self.url = self.navigate_to

    def wait_for_timeout(self, ms: int) -> None:
        self.waited = ms

    def evaluate(self, script: str):
        if "focusedSubmit" in script:
            return self.press_risk
        if "sensitivePattern" in script:
            return self.observation
        return None

    def locator(self, selector: str) -> FakeLocator:
        target = int(selector.split('"')[1])
        return FakeLocator(self, self.elements.get(target, {}))

    def inner_text(self, selector: str) -> str:
        self.text_selector = selector
        return "body text"

    def mouse(self):
        raise AssertionError("mouse is not used by these tests")


def _session(tmp_path: Path, policy: BrowserPolicy, page: FakePage) -> BrowserSession:
    session = BrowserSession(profile_dir=tmp_path / "profile", policy=policy)
    session.page = page  # type: ignore[assignment]
    return session


def test_redirect_to_an_off_policy_host_is_rejected(tmp_path: Path) -> None:
    page = FakePage("https://example.com/")
    page.navigate_to = "https://evil.test/landing"
    session = _session(tmp_path, BrowserPolicy(allowed_domains=("example.com",)), page)
    with pytest.raises(PolicyError) as excinfo:
        session.goto("https://example.com/")
    assert "evil.test" in str(excinfo.value)


def test_navigation_to_an_allowed_host_is_accepted(tmp_path: Path) -> None:
    page = FakePage("https://example.com/")
    session = _session(tmp_path, BrowserPolicy(allowed_domains=("example.com",)), page)
    assert session.goto("https://example.com/page") == "https://example.com/page"


def test_click_that_lands_off_policy_is_rejected(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/",
        elements={0: {"tag": "a", "type": "", "label": "Next", "href": "/next"}},
    )
    page.navigate_to = "https://evil.test/landing"
    session = _session(tmp_path, BrowserPolicy(allowed_domains=("example.com",)), page)
    with pytest.raises(PolicyError):
        session.perform(Action("click", target=0))


def test_link_to_an_off_policy_host_is_refused_before_the_click(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/",
        elements={0: {"tag": "a", "type": "", "label": "Next", "href": "https://evil.test/x"}},
    )
    session = _session(tmp_path, BrowserPolicy(allowed_domains=("example.com",)), page)
    with pytest.raises(PolicyError):
        session.perform(Action("click", target=0))
    assert page.clicked == []


def test_icon_only_submit_button_requires_confirmation(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/", elements={0: {"tag": "button", "type": "", "label": ""}}
    )
    session = _session(tmp_path, BrowserPolicy(), page)
    asked: list[str] = []

    result = session.perform(Action("click", target=0), confirm=lambda q: asked.append(q) or False)
    assert result["cancelled"] is True
    assert asked and "unnamed" in asked[0]
    assert page.clicked == []


def test_icon_only_submit_button_proceeds_after_confirmation(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/", elements={0: {"tag": "button", "type": "", "label": ""}}
    )
    session = _session(tmp_path, BrowserPolicy(), page)
    result = session.perform(Action("click", target=0), confirm=lambda _question: True)
    assert result["ok"] is True
    assert len(page.clicked) == 1


def test_labelled_destructive_button_requires_confirmation(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/",
        elements={0: {"tag": "button", "type": "button", "label": "Delete account"}},
    )
    session = _session(tmp_path, BrowserPolicy(), page)
    asked: list[str] = []
    result = session.perform(Action("click", target=0), confirm=lambda q: asked.append(q) or False)
    assert result["cancelled"] is True
    assert asked and "Delete account" in asked[0]
    assert page.clicked == []


def test_harmless_button_does_not_ask(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/",
        elements={0: {"tag": "button", "type": "button", "label": "Read more"}},
    )
    session = _session(tmp_path, BrowserPolicy(), page)
    asked: list[str] = []
    result = session.perform(Action("click", target=0), confirm=lambda q: asked.append(q) or True)
    assert result["ok"] is True
    assert asked == []
    assert len(page.clicked) == 1


def test_press_enter_with_a_credential_form_requires_confirmation(tmp_path: Path) -> None:
    page = FakePage("https://example.com/", press_risk={"credential": True, "focusedSubmit": False})
    session = _session(tmp_path, BrowserPolicy(), page)
    asked: list[str] = []
    result = session.perform(
        Action("press", key="Enter"), confirm=lambda q: asked.append(q) or False
    )
    assert result["cancelled"] is True
    assert asked and "credential" in asked[0]
    assert page.pressed == []


def test_press_enter_on_a_focused_submit_control_requires_confirmation(tmp_path: Path) -> None:
    page = FakePage("https://example.com/", press_risk={"credential": False, "focusedSubmit": True})
    session = _session(tmp_path, BrowserPolicy(), page)
    asked: list[str] = []
    result = session.perform(
        Action("press", key="Enter"), confirm=lambda q: asked.append(q) or False
    )
    assert result["cancelled"] is True
    assert asked


def test_press_enter_on_a_safe_page_does_not_ask(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/", press_risk={"credential": False, "focusedSubmit": False}
    )
    session = _session(tmp_path, BrowserPolicy(), page)
    asked: list[str] = []
    result = session.perform(
        Action("press", key="Enter"), confirm=lambda q: asked.append(q) or True
    )
    assert result["ok"] is True
    assert asked == []
    assert page.pressed == ["Enter"]


def test_press_that_cannot_submit_never_asks(tmp_path: Path) -> None:
    page = FakePage("https://example.com/", press_risk={"credential": True, "focusedSubmit": True})
    session = _session(tmp_path, BrowserPolicy(), page)
    asked: list[str] = []
    result = session.perform(Action("press", key="Tab"), confirm=lambda q: asked.append(q) or False)
    assert result["ok"] is True
    assert asked == []
    assert page.pressed == ["Tab"]


def test_sensitive_values_are_blanked_in_the_observation(tmp_path: Path) -> None:
    observation = {
        "url": "https://example.com/",
        "title": "T",
        "text": "",
        "elements": [
            {
                "id": 0,
                "tag": "input",
                "type": "text",
                "name": "otp",
                "value": "123456",
                "sensitive": True,
            },
            {"id": 1, "tag": "input", "type": "text", "name": "city", "value": "Berlin"},
        ],
    }
    page = FakePage("https://example.com/", observation=observation)
    session = _session(tmp_path, BrowserPolicy(), page)
    result = session.observe()
    assert result["elements"][0]["value"] == ""
    assert result["elements"][0]["sensitive"] is True
    assert result["elements"][1]["value"] == "Berlin"


def test_filling_a_secret_field_is_refused(tmp_path: Path) -> None:
    page = FakePage(
        "https://example.com/",
        elements={0: {"tag": "input", "type": "text", "label": "Code", "blob": "text otp_code"}},
    )
    session = _session(tmp_path, BrowserPolicy(), page)
    with pytest.raises(SensitiveFieldError):
        session.perform(Action("fill", target=0, text="123456"))


def test_sensitive_pattern_covers_the_secret_field_names() -> None:
    for term in (
        "password",
        "passcode",
        "one-time",
        "otp",
        "otp_code",
        "pin",
        "pin_code",
        "cvv",
        "cvc",
        "card",
        "cardnumber",
        "card number",
        "iban",
        "ssn",
        "security code",
        "verification code",
    ):
        assert SENSITIVE.search(term), term
    for term in ("username", "email", "search", "company", "postcode", "shopping"):
        assert not SENSITIVE.search(term), term


def test_the_page_script_uses_the_same_sensitive_pattern() -> None:
    assert SENSITIVE_PATTERN in OBSERVE_JS
    assert SENSITIVE_PATTERN in PRESS_RISK_JS
    assert "sensitive ? ''" in OBSERVE_JS


# A tiny DOM so the page script can be run for real. Without this the
# JavaScript that decides what the model gets to see is never executed.
_JS_HARNESS = """
function makeEl(tag, attrs, text, value) {
  return {
    tagName: tag.toUpperCase(),
    attrs: attrs || {},
    innerText: text || '',
    value: value || '',
    name: (attrs || {}).name || '',
    id: (attrs || {}).id || '',
    disabled: false,
    href: '',
    getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; },
    setAttribute(n, v) { this.attrs[n] = v; },
    removeAttribute(n) { delete this.attrs[n]; },
    getBoundingClientRect() { return {width: 100, height: 20}; }
  };
}
const fields = [
  makeEl('input', {type: 'password', name: 'password'}, '', 'hunter2'),
  makeEl('input', {type: 'text', name: 'otp_code'}, '', '123456'),
  makeEl('input', {type: 'text', name: 'city'}, '', 'Berlin'),
  makeEl('input', {type: 'tel', id: 'cvv'}, '', '999'),
  makeEl('button', {type: 'submit'}, 'Subscribe'),
  makeEl('button', {type: 'submit'}, '')
];
global.window = {getComputedStyle: () => ({visibility: 'visible', display: 'block', opacity: '1'})};
global.location = {href: 'https://example.com/login'};
global.document = {
  title: 'Login',
  body: {innerText: 'Sign in'},
  forms: [],
  activeElement: null,
  querySelectorAll(sel) {
    if (sel.indexOf('data-sovereign-id') >= 0) {
      return fields.filter(e => 'data-sovereign-id' in e.attrs);
    }
    return fields;
  }
};
const observed = observe();
global.document.forms = [{querySelectorAll: () => [fields[0]]}];
global.document.activeElement = fields[4];
const risk = pressRisk();
console.log(JSON.stringify({elements: observed.elements, risk: risk}));
"""


def test_the_page_script_never_reports_a_secret(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "harness.js"
    script.write_text(
        "const observe = "
        + OBSERVE_JS
        + ";\nconst pressRisk = "
        + PRESS_RISK_JS
        + ";\n"
        + _JS_HARNESS,
        encoding="utf-8",
    )
    finished = subprocess.run(
        [node, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    payload = json.loads(finished.stdout)
    elements = payload["elements"]
    password, otp, city, cvv = elements[0], elements[1], elements[2], elements[3]
    assert password["value"] == ""
    assert password["sensitive"] is True
    assert otp["value"] == ""
    assert otp["sensitive"] is True
    assert cvv["value"] == ""
    assert cvv["sensitive"] is True
    assert city["value"] == "Berlin"
    assert city["sensitive"] is False
    # The icon-only button stays unlabelled, which is what makes the
    # confirmation gate fall back to the control's structure.
    assert elements[5]["name"] == ""
    assert "123456" not in finished.stdout
    assert "hunter2" not in finished.stdout
    assert payload["risk"] == {"credential": True, "focusedSubmit": True}


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


def _chromium(tmp_path: Path, policy: BrowserPolicy, base: str) -> BrowserSession:
    """Start a headless session against the local fixture site."""
    pytest.importorskip("playwright.sync_api")
    session = BrowserSession(
        profile_dir=tmp_path / "profile",
        policy=policy,
        headless=True,
        timeout_ms=8000,
    )
    try:
        session.start(base)
    except Exception as exc:  # browser binary missing or launch failure
        session.close()
        pytest.skip(f"Chromium unavailable: {exc}")
    return session


def test_redirect_to_another_host_is_blocked(tmp_path: Path) -> None:
    with _site() as base:
        policy = BrowserPolicy(allow_local=True, allowed_domains=("127.0.0.1",))
        session = _chromium(tmp_path, policy, base)
        try:
            with pytest.raises(PolicyError):
                session.goto(base + "redirect")
        finally:
            session.close()


def test_one_time_code_is_not_handed_to_the_model(tmp_path: Path) -> None:
    with _site() as base:
        policy = BrowserPolicy(allow_local=True, allowed_domains=("127.0.0.1",))
        session = _chromium(tmp_path, policy, base)
        try:
            session.goto(base + "secrets")
            observation = session.observe()
            otp = next(
                item
                for item in observation["elements"]
                if item.get("sensitive") and "one-time code" in (item.get("name") or "").lower()
            )
            assert otp["sensitive"] is True
            assert otp["value"] == ""
            assert "123456" not in str(observation)
        finally:
            session.close()


def test_unlabelled_submit_button_asks_before_it_is_clicked(tmp_path: Path) -> None:
    with _site() as base:
        policy = BrowserPolicy(allow_local=True, allowed_domains=("127.0.0.1",))
        session = _chromium(tmp_path, policy, base)
        try:
            session.goto(base + "secrets")
            observation = session.observe()
            button = next(
                item
                for item in observation["elements"]
                if item["tag"] == "button" and item.get("type") == "submit"
            )
            asked: list[str] = []
            result = session.perform(
                Action("click", target=button["id"]),
                confirm=lambda question: asked.append(question) or False,
            )
            assert result["cancelled"] is True
            assert asked
        finally:
            session.close()


def test_pressing_enter_on_a_form_with_a_secret_asks(tmp_path: Path) -> None:
    with _site() as base:
        policy = BrowserPolicy(allow_local=True, allowed_domains=("127.0.0.1",))
        session = _chromium(tmp_path, policy, base)
        try:
            session.goto(base + "secrets")
            # The harness refuses to type secrets, so a human fills it here.
            session.page.fill("#pw", "hunter2")
            asked: list[str] = []
            result = session.perform(
                Action("press", key="Enter"),
                confirm=lambda question: asked.append(question) or False,
            )
            assert result["cancelled"] is True
            assert asked and "credential" in asked[0]
        finally:
            session.close()
