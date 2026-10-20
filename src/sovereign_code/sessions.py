"""Append-only JSONL session history."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import SESSIONS_DIR, ensure_layout


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-")[:60] or "model"


@dataclass
class SessionWriter:
    path: Path
    model: str
    cwd: str
    started_at: str = field(default_factory=_now)
    messages: int = 0

    @classmethod
    def create(cls, model: str, cwd: str | None = None) -> "SessionWriter":
        ensure_layout()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = SESSIONS_DIR / f"{stamp}-{_slug(model)}.jsonl"
        writer = cls(path=path, model=model, cwd=cwd or str(Path.cwd()))
        writer._append_record(
            {
                "type": "session",
                "started_at": writer.started_at,
                "model": model,
                "cwd": writer.cwd,
            }
        )
        return writer

    def _append_record(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def append(self, role: str, content: str, **extra: object) -> None:
        self.messages += 1
        self._append_record(
            {
                "type": "message",
                "ts": _now(),
                "role": role,
                "content": content,
                **extra,
            }
        )


def recent_sessions(limit: int = 10) -> list[Path]:
    ensure_layout()
    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def read_session(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return records
    return records
