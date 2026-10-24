from __future__ import annotations

from sovereign_code import domains


def test_domains_defined() -> None:
    assert domains.DOMAINS


def test_classify() -> None:
    result = domains.classify("python testing")
    assert isinstance(result, list)


def test_verdict() -> None:
    v = domains.verdict("hello")
    assert v is None or isinstance(v, str)


def test_confidence() -> None:
    c = domains.confidence("hello")
    assert c is None or isinstance(c, str)
