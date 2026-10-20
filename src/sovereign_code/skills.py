"""Saved prompt templates ("skills") stored as Markdown files.

Skills ship with the repo under ``skills/`` and can be overridden or extended
per-machine under ``~/Documents/local-ai/config/skills/``.
"""

from __future__ import annotations

from pathlib import Path

from .config import LOCAL_AI_ROOT, PROJECT_ROOT

REPO_SKILLS_DIR = PROJECT_ROOT / "skills"
USER_SKILLS_DIR = LOCAL_AI_ROOT / "config" / "skills"


def _skill_dirs() -> list[Path]:
    # User dir first so local edits win over the shipped defaults.
    return [USER_SKILLS_DIR, REPO_SKILLS_DIR]


def ensure_skills_dir() -> Path:
    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return USER_SKILLS_DIR


def list_skills() -> list[tuple[str, str]]:
    """Return (name, one-line description) pairs, alphabetical."""
    seen: dict[str, str] = {}
    for directory in _skill_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.stem in seen:
                continue
            description = ""
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("# "):
                        description = line[2:].strip()
                        break
            except OSError:
                pass
            seen[path.stem] = description
    return sorted(seen.items())


def read_skill(name: str) -> str | None:
    for directory in _skill_dirs():
        path = directory / f"{name}.md"
        if not path.is_file():
            continue
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def render_skill(name: str, user_input: str) -> str:
    template = read_skill(name)
    if template is None:
        raise KeyError(name)
    return template.replace("{{prompt}}", user_input)
