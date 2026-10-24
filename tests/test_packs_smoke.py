from __future__ import annotations

from sovereign_code import packs
from sovereign_code.projectsetup import init_project


def test_packs_defined() -> None:
    assert packs.PACKS
    assert "pentest" in packs.PACKS


def test_security_packs_are_defined() -> None:
    assert {"pentest", "redteam", "blueteam", "soc", "threatintel", "risk"} <= set(packs.PACKS)
    for key in ("redteam", "blueteam", "soc", "threatintel"):
        pack = packs.get_pack(key)
        assert pack is not None
        assert pack.guardrails and pack.steps and pack.deliverables


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


def test_brief_block_lists_related_packs() -> None:
    pack = packs.get_pack("pentest")
    assert pack is not None
    block = packs.brief_block(pack, [])
    assert "### Related packs" in block
    for key in pack.related:
        assert f"- `{key}`" in block


def test_brief_block_skips_related_when_empty() -> None:
    pack = packs.Pack(
        key="solo",
        label="Solo",
        summary="No relatives.",
        domain="security",
        task=packs.Task.CODE,
        skill_queries=(),
        model_queries=(),
        guardrails=(),
        steps=(),
        deliverables=(),
    )
    block = packs.brief_block(pack, [])
    assert "### Related packs" not in block


def test_security_packs_never_suggest_legal_skills() -> None:
    for key in (
        "pentest",
        "redteam",
        "blueteam",
        "soc",
        "threatintel",
        "cloudsec",
        "appsec",
        "malware",
        "vulnerability",
    ):
        pack = packs.get_pack(key)
        assert pack is not None
        names = [name for name, _ in packs.pack_skills(pack, limit=8)]
        assert not [n for n in names if n.startswith(("legal--", "hr-legal-compliance--"))], key


def test_specific_packs_find_their_own_skills() -> None:
    wanted = {
        "soc": "x2--soc-analyst--5c244f",
        "cloudsec": "x2--cloud-security-defensive--86e5cf",
        "blueteam": "x2--blue-team-soc--cf7f76",
        "threatintel": "x2--threat-intelligence--7b2b6e",
    }
    for key, name in wanted.items():
        pack = packs.get_pack(key)
        assert pack is not None
        names = [n for n, _ in packs.pack_skills(pack, limit=8)]
        assert name in names, (key, names)
