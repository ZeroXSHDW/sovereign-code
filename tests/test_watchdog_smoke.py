from __future__ import annotations

from sovereign_code import watchdog


def test_runner_cpu() -> None:
    assert watchdog.runner_cpu() >= 0


def test_runner_count() -> None:
    assert watchdog.runner_count() >= 0


def test_parse_ps() -> None:
    parsed = watchdog.parse_ps({})
    assert isinstance(parsed, tuple)


def test_classify() -> None:
    before = watchdog.Sample(models=(), cpu=0.0, runners=0)
    after = watchdog.Sample(models=(), cpu=0.0, runners=0)
    verdict = watchdog.classify(True, before, after)
    assert isinstance(verdict, str)
