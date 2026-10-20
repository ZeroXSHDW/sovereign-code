"""Per-project memory the chat injects automatically."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from .config import DATA_DIR


def project_slug(cwd: Path) -> str:
    return sha256(str(cwd.resolve()).encode("utf-8")).hexdigest()[:12]


def memory_path(cwd: Path | None = None) -> Path:
    resolved = (cwd or Path.cwd()).resolve()
    directory = DATA_DIR / "projects" / project_slug(resolved)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "memory.md"
    if not path.exists():
        path.write_text(f"# Project memory · {resolved.name}\n", encoding="utf-8")
    return path


PROJECT_CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md")


def project_context(cwd: Path | None = None, max_chars: int = 6000) -> str:
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
    except OSError:
        return ""


def add_memory(text: str, cwd: Path | None = None) -> Path:
    path = memory_path(cwd)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- {text.strip()}\n")
    return path


def clear_memory(cwd: Path | None = None) -> Path:
    path = memory_path(cwd)
    path.write_text(f"# Project memory · {(cwd or Path.cwd()).resolve().name}\n", encoding="utf-8")
    return path
