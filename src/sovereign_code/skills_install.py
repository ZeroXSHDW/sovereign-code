"""Install the curated skill library into each client's native format.

The checkout carries a large flat library (``skills/*.md`` with YAML
frontmatter). Every client now understands the Agent Skills layout — a folder
per skill containing ``SKILL.md`` — except Continue, which uses prompt files.
This module turns one source of truth into each client's layout, plus a shared
index in the project's ``AGENTS.md`` / ``CLAUDE.md`` / ``QWEN.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import LOCAL_AI_ROOT, PROJECT_ROOT

SKILL_DIR = "skills"
INDEX_START = "<!-- sovereign-skills:start -->"
INDEX_END = "<!-- sovereign-skills:end -->"

# A deliberately small set: 22k skills would overwhelm every client's context.
CURATED_PATTERNS = (
    "addy--*.md",
    "sovereign--*.md",
    "accessibility-compliance--*.md",
    "agent--architect.md",
    "agent--architect-review.md",
    "agent--code-reviewer.md",
    "agent--debugger.md",
    "agent--docs-architect.md",
    "agent--performance-engineer.md",
    "agent--security-auditor.md",
    "agent--test-automator.md",
)

TARGETS = {
    "claude": lambda: Path.home() / ".claude" / "skills",
    "codex": lambda: Path.home() / ".codex" / "skills",
    "qwen": lambda: Path.home() / ".qwen" / "skills",
    "opencode": lambda: Path.home() / ".config" / "opencode" / "skills",
}

CONTINUE_PROMPTS = lambda: Path.home() / ".continue" / "prompts"  # noqa: E731


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    source: Path


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse the simple `key: value` frontmatter used by the library."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    header = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, body


def slugify(value: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return name[:64] or "skill"


def load_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = split_frontmatter(text)
    name = slugify(meta.get("name") or path.stem.split("--")[-1])
    description = meta.get("description") or meta.get("title") or f"Skill from {path.name}"
    description = " ".join(description.split())
    return Skill(name=name, description=description[:600], body=body.strip() + "\n", source=path)


def curated_paths(source: Path | None = None) -> list[Path]:
    root = source or PROJECT_ROOT / SKILL_DIR
    found: list[Path] = []
    for pattern in CURATED_PATTERNS:
        found.extend(sorted(root.glob(pattern)))
    # The eight local prompt templates are already curated and short.
    config = LOCAL_AI_ROOT / "config" / "skills"
    if config.is_dir():
        found.extend(sorted(config.glob("*.md")))
    return found


def load_curated(source: Path | None = None) -> list[Skill]:
    skills: list[Skill] = []
    seen: set[str] = set()
    for path in curated_paths(source):
        skill = load_skill(path)
        name = skill.name
        suffix = 2
        while name in seen:
            name = f"{skill.name}-{suffix}"
            suffix += 1
        if name != skill.name:
            skill = Skill(name, skill.description, skill.body, skill.source)
        seen.add(name)
        skills.append(skill)
    return skills


def render_skill(skill: Skill) -> str:
    return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n{skill.body}"


def install_skill(skill: Skill, target: Path) -> Path:
    folder = target / skill.name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(render_skill(skill), encoding="utf-8")
    return path


def install_continue_prompt(skill: Skill, target: Path | None = None) -> Path:
    folder = target or CONTINUE_PROMPTS()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{skill.name}.prompt"
    path.write_text(render_skill(skill), encoding="utf-8")
    return path


def install(
    targets: str | list[str] = "all",
    source: Path | None = None,
    names: list[str] | None = None,
    include_all: bool = False,
    project: Path | None = None,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Install skills. Returns target -> installed paths."""
    if include_all:
        root = source or PROJECT_ROOT / SKILL_DIR
        paths = sorted(root.glob("*.md"))
        skills = [load_skill(path) for path in paths]
    else:
        skills = load_curated(source)
    if names:
        wanted = {slugify(name) for name in names}
        skills = [skill for skill in skills if skill.name in wanted]
        found = {skill.name for skill in skills}
        for name in names:
            slug = slugify(name)
            if slug in found:
                continue
            for candidate in (
                PROJECT_ROOT / SKILL_DIR / f"{name}.md",
                PROJECT_ROOT / SKILL_DIR / f"{slug}.md",
            ):
                if candidate.is_file():
                    skills.append(load_skill(candidate))
                    found.add(slug)
                    break

    selected = (
        ["continue", *TARGETS]
        if targets == "all"
        else ([targets] if isinstance(targets, str) else list(targets))
    )
    result: dict[str, list[str]] = {}
    for key in selected:
        if key == "continue":
            continue
        if key not in TARGETS:
            continue
        folder = TARGETS[key]()
        installed: list[str] = []
        for skill in skills:
            if not dry_run:
                installed.append(str(install_skill(skill, folder)))
        result[key] = installed

    if "continue" in selected:
        installed = []
        for skill in skills:
            if not dry_run:
                installed.append(str(install_continue_prompt(skill)))
        result["continue"] = installed

    if project is not None:
        result["project"] = install_project(project, skills, dry_run=dry_run)
    return result


def _index_block(skills: list[Skill]) -> str:
    lines = [
        INDEX_START,
        "## Sovereign skills",
        "",
        "Curated skills installed by `sovereign skills install`. Invoke one by name",
        "or let the client pick it from the description.",
        "",
    ]
    for skill in skills:
        lines.append(f"- **{skill.name}** — {skill.description}")
    lines.append(INDEX_END)
    return "\n".join(lines)


def upsert_index(path: Path, skills: list[Skill]) -> Path:
    block = _index_block(skills)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    if INDEX_START in text and INDEX_END in text:
        start = text.index(INDEX_START)
        end = text.index(INDEX_END) + len(INDEX_END)
        updated = text[:start] + block + text[end:]
    else:
        updated = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    path.write_text(updated, encoding="utf-8")
    return path


def install_project(
    project: Path,
    skills: list[Skill] | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Project-level skills plus the shared index files clients read."""
    target = project.expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"not a directory: {target}")
    skills = skills or load_curated()
    written: list[str] = []
    for folder_name in ("claude", "codex", "qwen", "opencode"):
        for skill in skills:
            if not dry_run:
                written.append(str(install_skill(skill, target / f".{folder_name}" / "skills")))
    if not dry_run:
        for index_name in ("AGENTS.md", "CLAUDE.md", "QWEN.md"):
            written.append(str(upsert_index(target / index_name, skills)))
    return written


def installed_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, getter in TARGETS.items():
        folder = getter()
        counts[key] = len(list(folder.glob("*/SKILL.md"))) if folder.is_dir() else 0
    prompts = CONTINUE_PROMPTS()
    counts["continue"] = len(list(prompts.glob("*.prompt"))) if prompts.is_dir() else 0
    return counts


def get_skill(name: str) -> Skill | None:
    """Find a skill in the curated set or anywhere in the 22k library."""
    wanted = slugify(name)
    for skill in load_curated():
        if skill.name == wanted or skill.name == name:
            return skill
    for candidate in (
        PROJECT_ROOT / SKILL_DIR / f"{name}.md",
        PROJECT_ROOT / SKILL_DIR / f"{wanted}.md",
    ):
        if candidate.is_file():
            return load_skill(candidate)
    return None
