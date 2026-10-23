"""Integrity manifest for the skill library.

Skills are Markdown that tells an agent what to run, so a changed file is a
change in behaviour. ``write_manifest`` records a sha256 for every skill file in
the standard ``sha256sum`` format; ``verify_manifest`` reports what changed,
disappeared, or appeared since.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_NAME = "MANIFEST.sha256"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Verification:
    checked: int
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.changed or self.missing or self.added)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _skill_files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.glob("*.md") if path.is_file())


def write_manifest(root: Path) -> Path:
    lines = [f"{digest(root / name)}  {name}\n" for name in _skill_files(root)]
    target = root / MANIFEST_NAME
    target.write_text("".join(lines), encoding="utf-8")
    return target


def read_manifest(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in (root / MANIFEST_NAME).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value, _, name = line.partition("  ")
        entries[name] = value
    return entries


def verify_manifest(root: Path) -> Verification:
    expected = read_manifest(root)
    present = set(_skill_files(root))
    changed = [
        name for name, value in expected.items() if name in present and digest(root / name) != value
    ]
    missing = sorted(name for name in expected if name not in present)
    added = sorted(present - set(expected))
    return Verification(
        checked=len(expected), changed=sorted(changed), missing=missing, added=added
    )
