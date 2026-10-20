"""Disk usage overview for the local AI stack."""

from __future__ import annotations

import os
from pathlib import Path

from .config import LOCAL_AI_ROOT

COMPONENTS = {
    "models": LOCAL_AI_ROOT / "models",
    "gateway venv": LOCAL_AI_ROOT / "gateway" / "venv",
    "data": LOCAL_AI_ROOT / "data",
    "browser profile": LOCAL_AI_ROOT / "data" / "browser",
    "search index": LOCAL_AI_ROOT / "data" / "index",
    "backups": LOCAL_AI_ROOT / "backups",
    "qwen state": LOCAL_AI_ROOT / "qwen",
    "legacy archive": LOCAL_AI_ROOT / "legacy",
}


def human_size(number: float) -> str:
    size = float(number)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def dir_size(path: Path) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames:
            file_path = Path(dirpath) / name
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    return total


def collect_stats() -> dict[str, dict[str, int | str]]:
    stats: dict[str, dict[str, int | str]] = {}
    for name, path in COMPONENTS.items():
        if path.exists():
            size = dir_size(path)
            stats[name] = {"path": str(path), "bytes": size, "human": human_size(size)}
        else:
            stats[name] = {"path": str(path), "bytes": 0, "human": "—"}
    return stats
