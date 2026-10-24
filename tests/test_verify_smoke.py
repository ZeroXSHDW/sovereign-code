from __future__ import annotations

from sovereign_code import verify


def test_configured_aliases() -> None:
    aliases = verify.configured_aliases(__import__("pathlib").Path("/nonexistent"))
    assert isinstance(aliases, tuple)


def test_probe_liveness() -> None:
    result = verify.probe_liveness("http://127.0.0.1:9", timeout=1.0)
    assert result is not None
