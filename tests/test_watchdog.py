"""Tests for the busy-vs-wedged watchdog."""

from __future__ import annotations

from sovereign_code.watchdog import BUSY, PROGRESSING, SERVING, STUCK, Sample, classify, parse_ps

A = Sample(models=(("qwen3.5:9b", 7.1),), cpu=0.0)
B = Sample(models=(("qwen3.5:9b", 7.1), ("gpt-oss:20b", 13.0)), cpu=0.0)


def test_parse_ps_normalises_and_sorts() -> None:
    payload = {
        "models": [
            {"name": "b:latest", "size": 2 * 1024**3},
            {"model": "a:latest", "size": 1024**3},
        ]
    }
    assert parse_ps(payload) == (("a:latest", 1.0), ("b:latest", 2.0))


def test_serving_wins_even_with_odd_samples() -> None:
    assert classify(True, A, A) == SERVING


def test_cpu_activity_means_busy_not_stuck() -> None:
    assert classify(False, A, A, cpu_threshold=5.0) == STUCK
    busy = Sample(models=A.models, cpu=42.0)
    assert classify(False, busy, busy) == BUSY


def test_changing_models_mean_progress() -> None:
    assert classify(False, A, B) == PROGRESSING


def test_nothing_moving_is_stuck() -> None:
    assert classify(False, A, A) == STUCK
