from __future__ import annotations

from sovereign_code import vetting


def test_assess_trusted() -> None:
    a = vetting.assess(license="MIT", downloads=5000)
    assert a.trusted is True


def test_assess_untrusted() -> None:
    a = vetting.assess(license="", downloads=0)
    assert a.trusted is False
    assert a.reasons
