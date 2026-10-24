from __future__ import annotations

import tempfile
from pathlib import Path

from sovereign_code import skillmanifest


def test_digest_and_manifest_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.md").write_text("hello", encoding="utf-8")
        manifest_path = skillmanifest.write_manifest(root)
        assert manifest_path.exists()
        data = skillmanifest.read_manifest(root)
        assert isinstance(data, dict)
        v = skillmanifest.verify_manifest(root)
        assert v is not None


def test_read_manifest_skips_blank_lines() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / skillmanifest.MANIFEST_NAME).write_text(
            "abc123  a.md\n\n\nbeef00  b.md\n", encoding="utf-8"
        )
        data = skillmanifest.read_manifest(root)
        assert data == {"a.md": "abc123", "b.md": "beef00"}
