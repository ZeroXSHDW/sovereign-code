"""Action parsing and browser policy tests."""

from __future__ import annotations

import pytest

from sovereign_code.browser.actions import (
    Action,
    ActionError,
    BrowserPolicy,
    PolicyError,
    check_url,
    is_destructive,
    parse_action,
)


def test_parse_navigate_and_clicks() -> None:
    assert parse_action('{"action":"navigate","url":"https://example.com"}').url == "https://example.com"
    assert parse_action({"action": "click", "id": 4}) == Action("click", target=4)
    assert parse_action('```json\n{"action":"click","id":0}\n```').target == 0


def test_parse_fill_select_and_keys() -> None:
    fill = parse_action('{"action":"fill","id":2,"text":"Ada"}')
    assert (fill.target, fill.text) == (2, "Ada")
    select = parse_action('{"action":"select","id":3,"value":"CA"}')
    assert (select.target, select.value) == (3, "CA")
    assert parse_action('{"action":"press","key":"Enter"}').key == "Enter"
    with pytest.raises(ActionError):
        parse_action('{"action":"press","key":"Meta+Q"}')


def test_parse_terminal_actions() -> None:
    assert parse_action('{"action":"done","summary":"found it"}').summary == "found it"
    assert parse_action('{"action":"handoff","reason":"login"}').reason == "login"
    assert parse_action('{"action":"extract"}').target is None
    assert parse_action('{"action":"scroll","direction":"bottom"}').direction == "bottom"


def test_parse_rejects_bad_payloads() -> None:
    with pytest.raises(ActionError):
        parse_action("no json here")
    with pytest.raises(ActionError):
        parse_action('{"action":"fly"}')
    with pytest.raises(ActionError):
        parse_action('{"action":"click","id":"one"}')
    with pytest.raises(ActionError):
        parse_action('{"action":"navigate"}')


def test_private_and_credentialed_urls_are_blocked() -> None:
    policy = BrowserPolicy()
    with pytest.raises(PolicyError):
        check_url("http://127.0.0.1:8000/", policy)
    with pytest.raises(PolicyError):
        check_url("http://192.168.1.5/", policy)
    with pytest.raises(PolicyError):
        check_url("http://user:pass@example.com/", policy)
    with pytest.raises(PolicyError):
        check_url("file:///etc/passwd", policy)
    assert check_url("http://127.0.0.1:8000/", BrowserPolicy(allow_local=True))


def test_domain_allowlist() -> None:
    policy = BrowserPolicy(allowed_domains=("example.com",))
    assert check_url("https://docs.example.com/page", policy) == "https://docs.example.com/page"
    with pytest.raises(PolicyError):
        check_url("https://example.org/", policy)


def test_destructive_labels() -> None:
    assert is_destructive("Delete account")
    assert is_destructive("Buy now")
    assert not is_destructive("Read more")


def test_as_dict_keeps_valid_target_and_amount() -> None:
    assert parse_action('{"action":"click","id":1}').as_dict() == {"action": "click", "id": 1}
    assert parse_action('{"action":"click","id":0}').as_dict() == {"action": "click", "id": 0}
    assert parse_action('{"action":"scroll","amount":3}').as_dict() == {
        "action": "scroll",
        "amount": 3,
    }
    assert parse_action('{"action":"scroll"}').as_dict() == {"action": "scroll"}
