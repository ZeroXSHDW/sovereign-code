"""Model download/run command tests."""

from __future__ import annotations

import re

from sovereign_code.cli import _model_info, _rm, _run
from sovereign_code.config import Settings
from sovereign_code.models import MODEL_STACKS, REMOTE_CATALOG

TAG = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?$")


def test_remote_catalog_tags_are_valid() -> None:
    for tag in REMOTE_CATALOG:
        assert TAG.fullmatch(tag), f"invalid tag: {tag}"


def test_remote_catalog_sizes_are_nonnegative() -> None:
    for tag, (_desc, size_gb) in REMOTE_CATALOG.items():
        assert isinstance(size_gb, (int, float)) and size_gb >= 0, tag


def test_model_stacks_reference_valid_tags() -> None:
    for stack in MODEL_STACKS.values():
        for tag in stack["models"]:
            assert TAG.fullmatch(tag), f"invalid stack tag: {tag}"


def test_run_rejects_invalid_tag() -> None:
    assert _run(Settings(), "bad tag!!", "hi", 4096, 0.25, None, True, "15m", None) == 1


def test_run_requires_a_prompt() -> None:
    assert _run(Settings(), "qwen3.5:4b", None, 4096, 0.25, None, True, "15m", None) == 1


def test_rm_rejects_invalid_tag() -> None:
    assert _rm(Settings(), "bad tag!!") == 1


def test_model_info_rejects_invalid_tag() -> None:
    assert _model_info(Settings(), "bad tag!!") == 1
