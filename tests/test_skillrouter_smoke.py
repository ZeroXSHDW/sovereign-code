from __future__ import annotations

from sovereign_code import skillrouter


def test_route_basic() -> None:
    cards, text = skillrouter.route("python testing", limit=3, max_tokens=500)
    assert isinstance(cards, list)
    assert isinstance(text, str)


def test_route_empty_raises() -> None:
    try:
        skillrouter.route("   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_playbook() -> None:
    steps = skillrouter.playbook("code review")
    assert isinstance(steps, list)


def test_category() -> None:
    assert isinstance(skillrouter.category("python"), str)
