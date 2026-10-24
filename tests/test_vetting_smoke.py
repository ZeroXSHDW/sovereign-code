from __future__ import annotations

from sovereign_code import vetting


def test_assess_trusted() -> None:
    a = vetting.assess(license="MIT", downloads=5000)
    assert a.trusted is True


def test_assess_untrusted() -> None:
    a = vetting.assess(license="", downloads=0)
    assert a.trusted is False
    assert a.reasons


def test_assess_unrecognised_licence() -> None:
    a = vetting.assess(license="proprietary", downloads=5000)
    assert not a.trusted
    assert any("not on the permissive list" in r for r in a.reasons)


def test_assess_gated_and_private() -> None:
    a = vetting.assess(license="mit", downloads=5000, gated="true", private=True)
    assert not a.trusted
    assert any("gated" in r for r in a.reasons)
    assert any("private" in r for r in a.reasons)


def test_assess_summary() -> None:
    assert vetting.assess(license="mit", downloads=5000).summary() == "trusted"
    bad = vetting.assess(license="", downloads=0)
    assert bad.summary() == "; ".join(bad.reasons)
