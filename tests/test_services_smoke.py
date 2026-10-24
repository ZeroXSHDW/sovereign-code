from __future__ import annotations

from sovereign_code import services


def test_gateway_root() -> None:
    assert services.gateway_root() is not None


def test_service_definitions() -> None:
    defs = services.service_definitions()
    assert isinstance(defs, list)


def test_plist_text() -> None:
    defs = services.service_definitions()
    if defs:
        text = services.plist_text(defs[0])
        assert isinstance(text, str)
