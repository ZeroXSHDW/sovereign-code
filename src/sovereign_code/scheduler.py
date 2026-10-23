"""Concurrency control for local models.

Ollama can answer many requests for the *same* loaded model in parallel, but it
cannot stream two different models at once on this hardware: loading the second
one evicts the first mid-stream. The gateway used one global lock for every
request, so two agent requests to the same model were serialized for no reason,
and one slow stream stalled the whole gateway.

The scheduler keeps the constraint that matters - one model at a time - and
drops the one that did not:

* any number of concurrent requests to the active model,
* a request for a different model waits until the active model is idle,
* a waiting model is not starved by a stream of same-model requests,
* ``exclusive`` is for loading or warming a model with no traffic in flight.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class SchedulerStats:
    active: str | None
    inflight: int
    waiting: dict[str, int]


class ModelScheduler:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._active: str | None = None
        self._inflight = 0
        self._exclusive = False
        self._waiting: Counter[str] = Counter()

    def _can_enter(self, model: str) -> bool:
        if self._exclusive:
            return False
        if not self._inflight:
            return True
        if self._active != model:
            return False
        # Another model is queued: let it have the slot instead of extending
        # the current model's run indefinitely.
        return not any(other != model for other in self._waiting)

    def enter(self, model: str) -> None:
        with self._cond:
            self._waiting[model] += 1
            try:
                while not self._can_enter(model):
                    self._cond.wait()
            finally:
                self._waiting[model] -= 1
                if not self._waiting[model]:
                    del self._waiting[model]
            self._active = model
            self._inflight += 1

    def exit(self, _model: str | None = None) -> None:
        with self._cond:
            if self._inflight:
                self._inflight -= 1
            if not self._inflight:
                self._active = None
            self._cond.notify_all()

    @contextmanager
    def request(self, model: str) -> Iterator[None]:
        self.enter(model)
        try:
            yield
        finally:
            self.exit(model)

    def enter_exclusive(self) -> None:
        with self._cond:
            while self._exclusive or self._inflight:
                self._cond.wait()
            self._exclusive = True

    def exit_exclusive(self) -> None:
        with self._cond:
            self._exclusive = False
            self._cond.notify_all()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        self.enter_exclusive()
        try:
            yield
        finally:
            self.exit_exclusive()

    def stats(self) -> SchedulerStats:
        with self._cond:
            return SchedulerStats(self._active, self._inflight, dict(self._waiting))
