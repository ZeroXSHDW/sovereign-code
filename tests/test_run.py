"""Model download/run command tests."""

from __future__ import annotations

import re

from sovereign_code.cli import _rm, _run
from sovereign_code.config import Settings
from sovereign_code.models import REMOTE_CATALOG

TAG = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?(:[A-Za-z0-9._-]+)?$")


def test_remote_catalog_tags_are_valid() -> None:
    for tag in REMOTE_CATALOG:
        assert TAG.fullmatch(tag), f"invalid tag: {tag}"


def test_run_rejects_invalid_tag() -> None:
    assert _run(Settings(), "bad tag!!", "hi", 4096, 0.25, None, True) == 1


def test_run_requires_a_prompt() -> None:
    assert _run(Settings(), "qwen3.5:4b", None, 4096, 0.25, None, True) == 1


def test_rm_rejects_invalid_tag() -> None:
    assert _rm(Settings(), "bad tag!!") == 1
