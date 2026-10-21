"""Find installed models that nothing references.

The machine accumulates models: experiments, superseded coder versions, and
whatever another agent pulled. Removing them is safe only if no alias, stack or
task preference points at them, so this module computes that set and never
deletes anything itself.
"""

from __future__ import annotations

from .gateway import alias_targets


def base_tag(tag: str) -> str:
    """`foo:latest` and `foo` are the same model for comparison purposes."""
    return tag.removesuffix(":latest")


def parse_alias_targets(config_text: str) -> set[str]:
    """Ollama tags referenced by gateway aliases (`model: ollama/<tag>`)."""
    return {base_tag(tag) for tag in alias_targets(config_text).values()}


def referenced_tags(
    alias_targets: set[str],
    stacks: dict[str, dict[str, object]],
    preferences: dict[str, tuple[str, ...]],
) -> set[str]:
    """Every model some part of the app would pick or route to."""
    tags = {base_tag(tag) for tag in alias_targets}
    for stack in stacks.values():
        for tag in stack.get("models", ()):  # type: ignore[union-attr]
            tags.add(base_tag(str(tag)))
    for tags_for_task in preferences.values():
        for tag in tags_for_task:
            tags.add(base_tag(tag))
    return tags


def prune_candidates(
    installed: list[tuple[str, float]], referenced: set[str]
) -> list[tuple[str, float]]:
    """(tag, size_gb) for installed models nothing references, largest first."""
    refs = {base_tag(tag) for tag in referenced}
    return sorted(
        ((tag, size) for tag, size in installed if base_tag(tag) not in refs),
        key=lambda item: item[1],
        reverse=True,
    )
