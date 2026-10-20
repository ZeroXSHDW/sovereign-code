"""Saved prompt templates ("skills") stored as Markdown files."""

from __future__ import annotations

from pathlib import Path

from .config import LOCAL_AI_ROOT

SKILLS_DIR = LOCAL_AI_ROOT / "config" / "skills"


def ensure_skills_dir() -> Path:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


def list_skills() -> list[tuple[str, str]]:
    """Return (name, one-line description) pairs, alphabetical."""
    if not SKILLS_DIR.is_dir():
        return []
    results: list[tuple[str, str]] = []
    for path in sorted(SKILLS_DIR.glob("*.md")):
        description = ""
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("# "):
                    description = line[2:].strip()
                    break
        except OSError:
            pass
        results.append((path.stem, description))
    return results


def read_skill(name: str) -> str | None:
    path = SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def render_skill(name: str, user_input: str) -> str:
    template = read_skill(name)
    if template is None:
        raise KeyError(name)
    return template.replace("{{prompt}}", user_input)
