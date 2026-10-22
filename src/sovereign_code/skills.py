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


def search_skills(query: str, limit: int = 30) -> list[tuple[str, str]]:
    """Search names and the first screen of every skill in both directories."""
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return []
    matches: list[tuple[int, str, str]] = []
    for directory in _skill_dirs():
        if not directory.is_dir():
            continue
        for path in directory.glob("*.md"):
            name = path.stem
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:4000]
            except OSError:
                continue
            description = ""
            for line in text.splitlines():
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
                if line.startswith("# "):
                    description = line[2:].strip()
                    break
            haystack = f"{name}\n{description}\n{text}".lower()
            if not all(term in haystack for term in terms):
                continue
            score = 0
            if all(term in name.lower() for term in terms):
                score += 10
            if all(term in description.lower() for term in terms):
                score += 5
            matches.append((-score, name, description))
    matches.sort()
    return [(name, description) for _score, name, description in matches[: max(1, limit)]]
