"""Decide whether Ollama is merely busy or actually wedged.

A model load that cannot fit the GPU budget does not fail — it waits, and with
parallel requests off every later completion queues behind it. The HTTP API
still answers, so a version check cannot tell the difference.

Two signals separate the cases:

* a runner process burning CPU means work is happening (loading or generating);
* a change in /api/ps between two samples means the scheduler is making progress.

Neither moving for a full interval means nothing is coming.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import httpx

SERVING = "serving"
BUSY = "busy"
PROGRESSING = "progressing"
STUCK = "stuck"


@dataclass(frozen=True)
class Sample:
    models: tuple[tuple[str, float], ...]
    cpu: float
    runners: int = 0


def parse_ps(payload: dict) -> tuple[tuple[str, float], ...]:
    """Stable (name, size_gb) pairs from an /api/ps response."""
    rows = []
    for item in payload.get("models", []):
        name = item.get("name") or item.get("model") or ""
        size = float(item.get("size") or 0) / (1024**3)
        if name:
            rows.append((str(name), round(size, 2)))
    return tuple(sorted(rows))


def runner_cpu() -> float:
    """Total %CPU across `ollama runner` processes."""
    try:
        out = subprocess.run(
            ["ps", "-Ao", "%cpu,command"], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return 0.0
    total = 0.0
    for line in out.splitlines():
        if "ollama runner" not in line:
            continue
        head = line.strip().split(None, 1)[0]
        try:
            total += float(head)
        except ValueError:
            continue
    return round(total, 1)


def runner_count() -> int:
    """Live runner processes; one exists while a model is loading, before /api/ps
    lists it — which is exactly when a restart would be harmful."""
    try:
        out = subprocess.run(
            ["ps", "-Ao", "command"], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return 0
    return sum(1 for line in out.splitlines() if "ollama runner" in line)


def sample(base_url: str, timeout: float = 8.0) -> Sample:
    base = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=3.0)) as client:
            payload = client.get(f"{base}/api/ps").json()
        models = parse_ps(payload)
    except (httpx.HTTPError, ValueError):
        models = ()
    return Sample(models=models, cpu=runner_cpu(), runners=runner_count())


def classify(live_ok: bool, before: Sample, after: Sample, cpu_threshold: float = 5.0) -> str:
    """One of SERVING / BUSY / PROGRESSING / STUCK."""
    if live_ok:
        return SERVING
    if after.runners or before.runners:
        return BUSY
    if after.cpu >= cpu_threshold or before.cpu >= cpu_threshold:
        return BUSY
    if before.models != after.models:
        return PROGRESSING
    return STUCK
