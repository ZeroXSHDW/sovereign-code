from __future__ import annotations

from sovereign_code import warm


def test_pool() -> None:
    p = warm.pool()
    assert p is not None


def test_warm_model_dataclass() -> None:
    wm = warm.WarmModel(tag="m", task="code", size_gb=1.0)
    assert wm.tag == "m"
