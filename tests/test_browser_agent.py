"""Browser agent loop tests with a fake session and planner."""

from __future__ import annotations

from typing import Any

from sovereign_code.browser.actions import BrowserPolicy
from sovereign_code.browser.agent import AuditLog, BrowserAgent, ModelPlanner, _redact_url
from sovereign_code.browser.executor import SensitiveFieldError

OK_OBSERVATION: dict[str, Any] = {
    "url": "https://example.com/",
    "title": "Example",
    "text": "Example Domain",
    "elements": [{"id": 0, "tag": "a", "name": "More information", "href": "https://example.com"}],
    "captcha": False,
}

CAPTCHA_OBSERVATION = {
    "url": "https://example.com/check",
    "title": "Human check",
    "text": "Verify you are human",
    "elements": [],
    "captcha": True,
}


class FakeSession:
    def __init__(self, observations, results=None, errors=None) -> None:
        self.observations = observations
        self.results = list(results or [])
        self.errors = list(errors or [])
        self.index = 0
        self.actions = []
        self.confirm = None

    def observe(self):
        observation = self.observations[min(self.index, len(self.observations) - 1)]
        self.index += 1
        return dict(observation)

    def perform(self, action, confirm=None):
        self.actions.append(action)
        self.confirm = confirm
        if self.errors:
            raise self.errors.pop(0)
        if self.results:
            return self.results.pop(0)
        return {"ok": True, "detail": "ok"}


class FakePlanner:
    def __init__(self, replies) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.corrections = []
        self.seen: list[tuple] = []

    def plan(self, task, observation, history, correction=""):
        self.seen.append((task, observation, history))
        self.corrections.append(correction)
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


def _agent(session, planner, **kwargs):
    return BrowserAgent(
        session=session,
        planner=planner,
        policy=BrowserPolicy(allow_local=True),
        **kwargs,
    )


def test_done_is_terminal() -> None:
    session = FakeSession([OK_OBSERVATION])
    planner = FakePlanner(['{"action":"done","summary":"the page says Example Domain"}'])
    result = _agent(session, planner).run("summarize")
    assert result.stopped == "done"
    assert result.steps == 1
    assert "Example Domain" in result.summary


def test_invalid_json_is_retried_once() -> None:
    session = FakeSession([OK_OBSERVATION])
    planner = FakePlanner(["not json", '{"action":"done","summary":"recovered"}'])
    result = _agent(session, planner).run("summarize")
    assert result.stopped == "done"
    assert planner.calls == 2
    assert "invalid" in planner.corrections[1].lower()


def test_captcha_pauses_without_consuming_a_step() -> None:
    session = FakeSession([CAPTCHA_OBSERVATION, OK_OBSERVATION])
    planner = FakePlanner(['{"action":"done","summary":"finished"}'])
    pauses: list[str] = []
    result = _agent(session, planner, pause=pauses.append).run("read")
    assert result.stopped == "done"
    assert result.steps == 1
    assert len(pauses) == 1
    assert "CAPTCHA" in pauses[0]


def test_captcha_in_headless_stops() -> None:
    session = FakeSession([CAPTCHA_OBSERVATION])
    planner = FakePlanner(['{"action":"done","summary":"never"}'])
    result = _agent(session, planner, headless=True).run("read")
    assert result.stopped == "captcha"
    assert not planner.calls


def test_sensitive_field_hands_off_then_continues() -> None:
    session = FakeSession(
        [OK_OBSERVATION, OK_OBSERVATION],
        errors=[SensitiveFieldError("refusing to fill a password")],
    )
    planner = FakePlanner(
        ['{"action":"fill","id":0,"text":"secret"}', '{"action":"done","summary":"ok"}']
    )
    pauses: list[str] = []
    result = _agent(session, planner, pause=pauses.append).run("log in")
    assert result.stopped == "done"
    assert len(pauses) == 1
    assert "password" in pauses[0].lower()


def test_cancelled_confirmation_stops() -> None:
    session = FakeSession(
        [OK_OBSERVATION],
        results=[{"ok": False, "cancelled": True, "detail": "cancelled"}],
    )
    planner = FakePlanner(['{"action":"click","id":0}'])
    result = _agent(session, planner).run("delete")
    assert result.stopped == "cancelled"


def test_step_limit_is_reported() -> None:
    session = FakeSession([OK_OBSERVATION])
    planner = FakePlanner(['{"action":"click","id":0}'])
    result = _agent(session, planner, max_steps=2).run("loop")
    assert result.stopped == "max-steps"
    assert result.steps == 2
    assert len(session.actions) == 2


def test_screenshots_captured_on_done(tmp_path) -> None:
    class ShotSession(FakeSession):
        def screenshot(self, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"png")
            return dest

    session = ShotSession([OK_OBSERVATION])
    planner = FakePlanner(['{"action":"done","summary":"ok"}'])
    agent = _agent(session, planner, screenshots_dir=tmp_path)
    result = agent.run("summarize")
    assert result.stopped == "done"
    assert len(agent.screenshots) == 1
    assert agent.screenshots[0].endswith(".png")


def test_redact_url_keeps_the_host_and_the_path() -> None:
    redacted = _redact_url("https://example.com/orders?token=abc123&page=2#frag")
    assert redacted.startswith("https://example.com/orders?")
    assert "abc123" not in redacted
    assert "page=2" not in redacted
    assert "frag" not in redacted
    assert "<redacted>" in redacted
    assert _redact_url("https://example.com/plain") == "https://example.com/plain"


def test_audit_log_keeps_secrets_out(tmp_path) -> None:
    observation = {
        "url": "https://example.com/login?session=abc123",
        "title": "Example",
        "text": "Example Domain",
        "elements": [],
        "captcha": False,
    }
    session = FakeSession(
        [observation, observation],
        results=[
            {"ok": True, "detail": "navigated to https://example.com/?token=abc123"},
            {"ok": True, "detail": "selected an option in element 1"},
        ],
    )
    planner = FakePlanner(
        [
            '{"action":"navigate","url":"https://example.com/?token=abc123"}',
            '{"action":"select","id":1,"value":"hunter2"}',
            '{"action":"done","summary":"ok"}',
        ]
    )
    audit = AuditLog(path=tmp_path / "audit.jsonl")
    agent = _agent(session, planner, audit=audit)
    result = agent.run("log in")
    audit.close()
    assert result.stopped == "done"
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "abc123" not in text
    assert "hunter2" not in text
    assert "example.com" in text
    assert "<redacted>" in text


def test_observation_never_carries_a_secret_value() -> None:
    planner = ModelPlanner(gateway_url="http://localhost:1")
    observation = {
        "url": "https://example.com/",
        "title": "Example",
        "text": "",
        "elements": [
            {"id": 0, "tag": "input", "type": "text", "name": "otp", "value": "123456"},
            {"id": 1, "tag": "input", "type": "text", "name": "city", "value": "Berlin"},
        ],
    }
    payload = planner._observation(observation)
    assert payload["elements"][0].get("value") is None
    assert payload["elements"][1]["value"] == "Berlin"
