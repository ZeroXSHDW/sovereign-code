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
    is_submit_control,
    needs_confirmation,
    parse_action,
)


def test_parse_navigate_and_clicks() -> None:
    assert (
        parse_action('{"action":"navigate","url":"https://example.com"}').url
        == "https://example.com"
    )
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


def test_destructive_word_list_covers_the_obvious_bypasses() -> None:
    for label in (
        "OK",
        "ok",
        "Yes",
        "Continue",
        "Upgrade",
        "Apply",
        "Submit",
        "Confirm",
        "Purchase",
        "Pay",
        "Subscribe",
        "Remove",
        "Uninstall",
        "Terminate",
        "Send",
        "Post",
        "Publish",
        "Revoke",
        "Reset",
        "Delete",
        "Drop",
        "Destroy",
        "Cancel",
        "Close account",
        "Sign out",
    ):
        assert is_destructive(label), label


def test_bare_ok_is_destructive_but_ok_inside_a_label_is_not() -> None:
    assert is_destructive("OK")
    assert is_destructive("  OK!  ")
    # "OK Google" is a search button, not a confirmation.
    assert not is_destructive("OK Google")


def test_submit_controls_are_recognised() -> None:
    assert is_submit_control("button", "")
    assert is_submit_control("button", "submit")
    assert not is_submit_control("button", "button")
    assert not is_submit_control("button", "reset")
    assert is_submit_control("input", "submit")
    assert is_submit_control("input", "image")
    assert not is_submit_control("input", "text")
    assert not is_submit_control("a", "")


def test_unlabelled_submit_control_needs_confirmation() -> None:
    # An icon-only button submits the form it sits in by default.
    assert needs_confirmation("", "button", "")
    assert needs_confirmation("", "button", "submit")
    assert needs_confirmation("", "input", "submit")
    assert needs_confirmation("", "input", "image")
    # A control that cannot submit a form is harmless without a label.
    assert not needs_confirmation("", "button", "button")
    assert not needs_confirmation("", "input", "text")
    assert not needs_confirmation("", "a", "")


def test_labelled_control_uses_the_label() -> None:
    assert needs_confirmation("Delete account", "button", "button")
    assert needs_confirmation("OK", "button", "button")
    assert not needs_confirmation("Read more", "button", "button")
    assert not needs_confirmation("", "a", "")


def test_as_dict_keeps_valid_target_and_amount() -> None:
    assert parse_action('{"action":"click","id":1}').as_dict() == {"action": "click", "id": 1}
    assert parse_action('{"action":"click","id":0}').as_dict() == {"action": "click", "id": 0}
    assert parse_action('{"action":"scroll","amount":3}').as_dict() == {
        "action": "scroll",
        "amount": 3,
    }
    assert parse_action('{"action":"scroll"}').as_dict() == {"action": "scroll"}
