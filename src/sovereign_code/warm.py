"""Model warm pool: keep the models engineers actually use resident in RAM.

Ollama unloads idle models after ``keep_alive``. A cold 27B model can take
30-60 s to load on Apple Silicon; a warm one answers in the first prefill.
This module preloads the tier's models and keeps them resident with periodic
no-op generate calls, so the first coding question of the session is fast.

It talks to Ollama natively (no LiteLLM translation, no cloud). Safe to run
from the tier gateway process or a standalone `sovereign warm` command.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import DATA_DIR
from .http import shared_client
from .models import CATALOG
from .router import Task

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
WARM_STATE = DATA_DIR / "warm_pool.json"


@dataclass
class WarmModel:
    tag: str
    task: str
    size_gb: float
    loaded: bool = False
    load_time_s: float = 0.0
    last_touched: float = 0.0
    touch_count: int = 0
    error: str = ""


class WarmPool:
    """Keep a set of models resident in Ollama.

    `warm()` loads each model once with a tiny prompt. `touch()` re-issues a
    keep_alive generate so Ollama does not unload it between coding turns.
    `status()` reports what is resident and what failed to load.
    """

    def __init__(self, ollama: str = DEFAULT_OLLAMA) -> None:
        self.ollama = ollama.rstrip("/")
        self._models: dict[str, WarmModel] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._interval = 60.0  # seconds between keep-alive touches

    # ---------------------------------------------------------------- setup

    def add(self, tag: str, task: str = "code") -> None:
        with self._lock:
            spec = CATALOG.get(tag)
            self._models[tag] = WarmModel(
                tag=tag,
                task=task,
                size_gb=spec.size_gb if spec else 0.0,
            )

    def add_task(self, task: Task, limit: int = 1) -> None:
        """Add the best model for one task (from the router's preference list)."""
        from .router import preferred_tags

        for tag in preferred_tags(task.value)[:limit]:
            self.add(tag, task.value)

    def add_defaults(self) -> None:
        """The models worth keeping warm on a 24 GB Mac: one coder, one chat."""
        self.add_task(Task.CODE, 1)  # qwen3.8:27b (or qwen2.5-coder:14b)
        self.add_task(Task.CHAT, 1)  # qwen3.5:9b or qwen3.8:27b
        self.add_task(Task.FAST, 1)  # qwen3.5:4b

    # ---------------------------------------------------------------- load/touch

    def _load_one(self, model: WarmModel, timeout: float = 300.0) -> float:
        """Load one model with a tiny prompt. Returns load time in seconds."""
        start = time.monotonic()
        try:
            shared_client().post(
                f"{self.ollama}/api/generate",
                json={
                    "model": model.tag,
                    "prompt": "Hello.",
                    "stream": False,
                    "options": {"num_predict": 8, "temperature": 0, "num_ctx": 4096},
                    "keep_alive": "15m",
                },
                timeout=httpx.Timeout(timeout, connect=5.0),
            )
        except httpx.HTTPError as exc:
            model.error = f"load failed: {exc.__class__.__name__}"
            return 0.0
        except Exception as exc:
            model.error = f"load failed: {exc}"
            return 0.0
        model.loaded = True
        model.error = ""
        model.load_time_s = round(time.monotonic() - start, 2)
        model.last_touched = time.monotonic()
        model.touch_count += 1
        return model.load_time_s

    def warm(self, tags: Iterable[str] | None = None) -> dict[str, float]:
        """Load the given tags (or everything in the pool) and return {tag: seconds}."""
        targets = list(tags) if tags is not None else list(self._models)
        results: dict[str, float] = {}
        for tag in targets:
            model = self._models.get(tag)
            if model is None:
                continue
            seconds = self._load_one(model)
            results[tag] = seconds
        return results

    def touch(self, tags: Iterable[str] | None = None) -> None:
        """Re-issue keep_alive for models so Ollama keeps them resident."""
        targets = (
            list(tags) if tags is not None else [m.tag for m in self._models.values() if m.loaded]
        )
        now = time.monotonic()
        for tag in targets:
            model = self._models.get(tag)
            if model is None or not model.loaded:
                continue
            try:
                shared_client().post(
                    f"{self.ollama}/api/generate",
                    json={
                        "model": tag,
                        "prompt": "",
                        "stream": False,
                        "options": {"num_predict": 0},
                        "keep_alive": "15m",
                    },
                    timeout=httpx.Timeout(10.0, connect=3.0),
                )
            except httpx.HTTPError:
                pass
            model.last_touched = now
            model.touch_count += 1

    def start(self, interval: float = 60.0) -> None:
        """Start the background keep-alive thread."""
        self._interval = interval
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sovereign-warm")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.touch()
            except Exception:
                pass

    # ---------------------------------------------------------------- status

    def status(self) -> list[WarmModel]:
        with self._lock:
            return list(self._models.values())

    def summary(self) -> str:
        lines = [f"{len(self._models)} model(s) in warm pool"]
        for model in self.status():
            mark = "[green]resident[/]" if model.loaded else "[dim]cold[/]"
            lines.append(
                f"  {model.tag:24s} {mark}  {model.size_gb:5.1f} GB  "
                f"{model.load_time_s}s load  {model.touch_count}x touched"
            )
            if model.error:
                lines.append(f"    [red]{model.error}[/]")
        return "\n".join(lines)

    def save_state(self) -> Path:
        WARM_STATE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            tag: {
                "task": m.task,
                "size_gb": m.size_gb,
                "loaded": m.loaded,
                "load_time_s": m.load_time_s,
                "touch_count": m.touch_count,
                "error": m.error,
            }
            for tag, m in self._models.items()
        }
        WARM_STATE.write_text(__import__("json").dumps(data, indent=2) + "\n", encoding="utf-8")
        return WARM_STATE


_pool: WarmPool | None = None
_pool_lock = threading.Lock()


def pool() -> WarmPool:
    """The process-wide warm pool."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = WarmPool()
            _pool.add_defaults()
        return _pool
