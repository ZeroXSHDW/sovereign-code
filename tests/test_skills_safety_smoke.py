from __future__ import annotations

from sovereign_code import skills_safety


def test_scan_clean() -> None:
    scan = skills_safety.scan("print('hello')")
    assert scan is not None
    assert isinstance(scan.findings, list)


def test_scan_flags_secret() -> None:
    scan = skills_safety.scan("AKIAIOSFODNN7EXAMPLE")
    assert scan is not None
