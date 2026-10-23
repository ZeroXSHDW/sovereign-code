"""Per-project memory the chat injects automatically."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from .config import DATA_DIR


def project_slug(cwd: Path) -> str:
    return sha256(str(cwd.resolve()).encode("utf-8")).hexdigest()[:12]


def memory_path(cwd: Path | None = None) -> Path:
    """Where a project's memory file lives.

    This only computes the path. Creating the file is a write, so it happens
    in `ensure_memory` — a plain read used to leave an empty memory file
    behind in every directory the dashboard ever visited.
    """
    resolved = (cwd or Path.cwd()).resolve()
    return DATA_DIR / "projects" / project_slug(resolved) / "memory.md"


def ensure_memory(cwd: Path | None = None) -> Path:
    """The memory file, created with its header when it does not exist yet."""
    resolved = (cwd or Path.cwd()).resolve()
    path = memory_path(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# Project memory · {resolved.name}\n", encoding="utf-8")
    return path


PROJECT_CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md")


def project_context(cwd: Path | None = None, max_chars: int = 8000) -> str:
    """Concatenate AGENTS.md/CLAUDE.md and project memory for prompt injection."""
    resolved = (cwd or Path.cwd()).resolve()
    parts: list[str] = []
    for name in PROJECT_CONTEXT_FILES:
        path = resolved / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[truncated]"
        parts.append(f"# {name}\n{text}")
    body = "\n".join(read_memory(resolved).strip().splitlines()[1:]).strip()
    if body:
        parts.append(f"# Project memory\n{body}")
    return "\n\n".join(parts)


def read_memory(cwd: Path | None = None) -> str:
    try:
        return memory_path(cwd).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def add_memory(text: str, cwd: Path | None = None) -> Path:
    path = ensure_memory(cwd)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- {text.strip()}\n")
    return path


def clear_memory(cwd: Path | None = None) -> Path:
    path = ensure_memory(cwd)
    path.write_text(f"# Project memory · {(cwd or Path.cwd()).resolve().name}\n", encoding="utf-8")
    return path
