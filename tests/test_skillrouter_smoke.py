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


def test_category_collection_prefix() -> None:
    assert skillrouter.category("x--code--python") == "code"


def test_variants_plural_and_singular() -> None:
    assert skillrouter._variants("forensics") == ["forensics", "forensic"]
    assert skillrouter._variants("class") == ["class"]


def test_description_line_truncates() -> None:
    long = "x" * 300
    assert skillrouter._description_line(long).endswith("…")
    assert len(skillrouter._description_line(long)) <= 200


def test_playbook_branches() -> None:
    assert "security" in " ".join(skillrouter.playbook("security threat")).lower()
    assert "debug" in " ".join(skillrouter.playbook("debug bug")).lower()
    assert "benchmark" in " ".join(skillrouter.playbook("slow performance")).lower()
