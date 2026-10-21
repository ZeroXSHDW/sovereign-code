"""Append-only JSONL session history."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import SESSIONS_DIR, ensure_layout


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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
    def create(cls, model: str, cwd: str | None = None) -> SessionWriter:
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
    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=_mtime, reverse=True)
    return files[:limit]


def _mtime(path: Path) -> float:
    """Sort key that survives a file disappearing mid-scan."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def search_sessions(query: str, directory: Path | None = None) -> list[dict]:
    """Return message records whose content matches the query (case-insensitive)."""
    needle = query.lower()
    matches: list[dict] = []
    for info in scan_sessions(directory):
        for record in read_session(info.path):
            if record.get("type") != "message":
                continue
            content = str(record.get("content") or "")
            if needle in content.lower():
                matches.append(
                    {
                        "path": info.path.name,
                        "role": record.get("role"),
                        "ts": record.get("ts", ""),
                        "snippet": content[:240],
                    }
                )
    return matches


def export_sessions(dest: Path, directory: Path | None = None) -> int:
    """Write every session record to a single JSONL file; returns the record count."""
    records = 0
    with dest.open("w", encoding="utf-8") as output:
        for info in scan_sessions(directory):
            for record in read_session(info.path):
                record["_session"] = info.path.name
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                records += 1
    return records


def read_session(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return records
    return records


@dataclass(frozen=True)
class SessionInfo:
    path: Path
    model: str
    messages: int
    size_kb: float
    modified: float


def scan_sessions(directory: Path | None = None) -> list[SessionInfo]:
    """Summarise every session file, newest first."""
    root = directory or SESSIONS_DIR
    infos: list[SessionInfo] = []
    try:
        paths = list(root.glob("*.jsonl"))
    except OSError:
        return infos
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        model = "unknown"
        messages = 0
        for record in read_session(path):
            if record.get("type") == "session":
                model = str(record.get("model") or model)
            elif record.get("type") == "message":
                messages += 1
        infos.append(
            SessionInfo(
                path=path,
                model=model,
                messages=messages,
                size_kb=round(stat.st_size / 1024, 1),
                modified=stat.st_mtime,
            )
        )
    return sorted(infos, key=lambda info: info.modified, reverse=True)


def select_prunable(
    sessions: list[SessionInfo],
    days: float = 30,
    keep: int = 50,
    now: float | None = None,
) -> list[SessionInfo]:
    """Keep the newest `keep` files; prune the rest once older than `days`."""
    if days <= 0:
        return []
    cutoff = (now if now is not None else datetime.now().timestamp()) - days * 86400
    ordered = sorted(sessions, key=lambda info: info.modified, reverse=True)
    return [info for info in ordered[max(0, int(keep)) :] if info.modified < cutoff]


def prune_sessions(sessions: list[SessionInfo]) -> int:
    removed = 0
    for info in sessions:
        try:
            info.path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
