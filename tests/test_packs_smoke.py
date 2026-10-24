from __future__ import annotations

from sovereign_code import packs
from sovereign_code.projectsetup import init_project


def test_packs_defined() -> None:
    assert packs.PACKS
    assert "pentest" in packs.PACKS


def test_get_pack() -> None:
    pack = packs.get_pack("pentest")
    assert pack is not None
    assert pack.key == "pentest"
    assert pack.guardrails


def test_get_pack_without_a_key_returns_none() -> None:
    assert packs.get_pack(None) is None
    assert packs.get_pack("  ") is None


def test_pack_brief_writes_agents(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    pack = packs.get_pack("pentest")
    actions = init_project(root, pack=pack, dry_run=True)
    assert actions is not None
    assert any("AGENTS.md" in str(a[1]) for a in actions)
