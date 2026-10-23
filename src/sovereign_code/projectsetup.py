"""Make a folder ready for an autonomous coding agent in one command.

Opening a repository in OpenCode or ChatGPT works best when the folder carries
its own instructions. This module detects the stack and the project's own
checks, then writes the two files a client reads automatically:

``AGENTS.md``
    purpose, detected stack, exact check commands, working rules, the curated
    skill block, and optionally a task pack (pentest, legal, forensics, ...).

``opencode.json``
    loads ``AGENTS.md``, starts the sovereign MCP server, and allows edit and
    bash so the agent is not asked to approve every step.

Existing files are never overwritten unless ``force`` is set, so a hand-written
brief survives.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .checks import detect_checks
from .packs import Pack, brief_block, scope_file
from .repomap import iter_files
from .skills_install import _index_block, brief_skills

ECOSYSTEMS = {
    "Python": "python",
    "TypeScript": "node",
    "JavaScript": "node",
    "Rust": "rust",
    "Go": "go",
}


@dataclass(frozen=True)
class ProjectProfile:
    root: Path
    name: str
    files: int
    languages: tuple[tuple[str, int], ...]
    ecosystem: str
    checks: tuple[str, ...]

    def summary(self) -> str:
        parts = [f"{name} {count}" for name, count in self.languages[:4]]
        return f"{self.files} code files · " + (", ".join(parts) or "no code detected")


def profile(root: Path) -> ProjectProfile:
    """Detect the languages, size and check command of a project."""
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"not a directory: {resolved}")
    files = iter_files(resolved, max_files=50_000)
    counted = Counter(item.language for item in files if item.language)
    code = Counter({name: count for name, count in counted.items() if name in ECOSYSTEMS})
    ecosystem = ECOSYSTEMS[code.most_common(1)[0][0]] if code else "other"
    return ProjectProfile(
        root=resolved,
        name=resolved.name,
        files=len(files),
        languages=tuple(counted.most_common(8)),
        ecosystem=ecosystem,
        checks=tuple(detect_checks(resolved)),
    )


def brief_text(project: ProjectProfile, pack: Pack | None = None) -> str:
    """The AGENTS.md body: stack, checks, rules, skills, and an optional pack."""
    check_block = "\n".join(project.checks) if project.checks else "# no test command was detected"
    parts = [
        f"# {project.name} — agent brief",
        "",
        "Read this file before changing anything. It is the project's single source",
        "of instructions for OpenCode, Codex/ChatGPT, Claude Code and Qwen Code.",
        "",
        "## Project",
        "",
        f"- Detected: {project.summary()}",
        f"- Ecosystem: {project.ecosystem}",
        "",
        "## Checks (run before reporting a task done)",
        "",
        "```sh",
        check_block,
        "```",
        "",
        "## Working rules",
        "",
        "1. Read the relevant module and its tests before editing.",
        "2. Make the smallest change that satisfies the request.",
        "3. Add or update a test for every behaviour change.",
        "4. Run the checks above before saying the task is done.",
        "5. Do not commit unless the user asks.",
        "6. Report results with file:line references.",
        "",
        _index_block(brief_skills()),
    ]
    body = "\n".join(parts).rstrip() + "\n"
    if pack is not None:
        body += "\n" + brief_block(pack, _pack_skills(pack)) + "\n"
    return body


def _pack_skills(pack: Pack) -> list[tuple[str, str]]:
    from .packs import pack_skills

    return pack_skills(pack, limit=8)


def _mcp_command() -> list[str]:
    """How this Mac should start the MCP server: installed entry point, else this Python."""
    entry = shutil.which("sovereign")
    if entry:
        return [entry, "mcp"]
    return [sys.executable, "-m", "sovereign_code", "mcp"]


def opencode_config() -> dict[str, object]:
    """The project OpenCode config: brief, MCP server, no approval prompts."""
    return {
        "$schema": "https://opencode.ai/config.json",
        "instructions": ["AGENTS.md"],
        "permission": {"edit": "allow", "bash": "allow"},
        "mcp": {
            "sovereign": {
                "type": "local",
                "command": _mcp_command(),
                "environment": {"SOVEREIGN_MCP_COMPUTER": "1"},
            }
        },
    }


def init_project(
    root: Path,
    *,
    pack: Pack | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[tuple[str, str]]:
    """Write the brief and client config. Returns (action, path) for each file."""
    project = profile(root)
    actions: list[tuple[str, str]] = []

    brief = project.root / "AGENTS.md"
    if brief.exists() and not force:
        actions.append(("skipped", str(brief)))
    else:
        actions.append(("updated" if brief.exists() else "created", str(brief)))
        if not dry_run:
            brief.write_text(brief_text(project, pack), encoding="utf-8")

    config = project.root / "opencode.json"
    if config.exists() and not force:
        actions.append(("skipped", str(config)))
    else:
        actions.append(("updated" if config.exists() else "created", str(config)))
        if not dry_run:
            config.write_text(json.dumps(opencode_config(), indent=2) + "\n", encoding="utf-8")

    if pack is not None and pack.key == "pentest" and not dry_run:
        created = scope_file(project.root)
        if created is not None:
            actions.append(("created", str(created)))
    return actions
