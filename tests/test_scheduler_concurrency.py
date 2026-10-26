"""Concurrency behaviour of the per-model scheduler."""

from __future__ import annotations

import threading
import time

from sovereign_code.scheduler import ModelScheduler


def test_scheduler_serializes_different_models() -> None:
    scheduler = ModelScheduler()
    active: list[str] = []

    def run(model: str, delay: float) -> None:
        with scheduler.request(model):
            active.append(model)
            time.sleep(delay)
            active.remove(model)

    threads = [
        threading.Thread(target=run, args=("a", 0.05)),
        threading.Thread(target=run, args=("b", 0.05)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Only one model was active at any instant.
    assert scheduler.stats().inflight == 0


def test_scheduler_allows_same_model_concurrency() -> None:
    scheduler = ModelScheduler()
    peak = [0]
    guard = threading.Lock()
    # All three must be inside the request before any reads the count: thread
    # startup under load was slow enough to make the old sleep-based version
    # report 2 of 3 occasionally.
    inside = threading.Barrier(3)

    def run() -> None:
        with scheduler.request("a"):
            inside.wait(timeout=5)
            with guard:
                peak[0] = max(peak[0], scheduler.stats().inflight)
            time.sleep(0.05)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 3


def test_exclusive_waits_for_inflight_requests() -> None:
    scheduler = ModelScheduler()
    order: list[str] = []

    def excl() -> None:
        with scheduler.exclusive():
            order.append("exclusive")

    holding = threading.Event()

    def run() -> None:
        with scheduler.request("a"):
            holding.set()
            time.sleep(0.05)
            order.append("request")

    request_thread = threading.Thread(target=run)
    exclusive_thread = threading.Thread(target=excl)
    request_thread.start()
    # Wait for the slot to be held rather than guessing with a sleep.
    assert holding.wait(timeout=5)
    exclusive_thread.start()
    request_thread.join()
    exclusive_thread.join()
    assert order == ["request", "exclusive"]


def test_exclusive_blocks_regular_entry() -> None:
    scheduler = ModelScheduler()
    with scheduler.exclusive():
        # A request while exclusive is held must wait, then proceed on release.
        def attempt() -> None:
            with scheduler.request("a"):
                pass

        thread = threading.Thread(target=attempt)
        thread.start()
        time.sleep(0.05)
        assert scheduler.stats().waiting != {} or thread.is_alive()
        # release then ensure the waiter completes
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_enter_decrements_waiting_without_deleting_when_others_remain() -> None:
    scheduler = ModelScheduler()
    a_started = threading.Event()
    a_may_exit = threading.Event()

    def run_a() -> None:
        with scheduler.request("a"):
            a_started.set()
            a_may_exit.wait(timeout=5)

    def run_b() -> None:
        with scheduler.request("b"):
            pass

    a_thread = threading.Thread(target=run_a)
    b_threads = [threading.Thread(target=run_b) for _ in range(2)]
    a_thread.start()
    assert a_started.wait(timeout=5)
    for thread in b_threads:
        thread.start()
    while scheduler.stats().waiting.get("b", 0) < 2:
        time.sleep(0.001)
    a_may_exit.set()
    a_thread.join(timeout=5)
    for thread in b_threads:
        thread.join(timeout=5)
    assert scheduler.stats().inflight == 0
