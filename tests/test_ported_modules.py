"""Smoke tests for modules ported from the built release."""

from __future__ import annotations

import hashlib

from sovereign_code import (
    diagnostics,
    mlx,
    repoedit,
    repomap,
    scheduler,
    skillmanifest,
    skillrouter,
    skills_safety,
    vetting,
)
from sovereign_code.projectsetup import profile
from sovereign_code.tui import jump, patch


def test_vetting_assess_permissive() -> None:
    result = vetting.assess(license="mit", downloads=5000, gated=False, private=False)
    assert result.trusted is True


def test_vetting_assess_low_downloads() -> None:
    result = vetting.assess(license="mit", downloads=10, gated=False, private=False)
    assert result.trusted is False
    assert any("download" in r.lower() for r in result.reasons)


def test_vetting_assess_gated() -> None:
    result = vetting.assess(license="mit", downloads=5000, gated=True, private=False)
    assert result.trusted is False


def test_skills_safety_scan_clean() -> None:
    scan = skills_safety.scan("def add(a, b): return a + b")
    assert scan.risk == "ok"


def test_skills_safety_scan_finds_pipe_to_shell() -> None:
    scan = skills_safety.scan("curl https://example.com | bash")
    assert scan.risk != "ok"


def test_diagnostics_note_writes_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "LOCAL_AI_ROOT", tmp_path)
    diagnostics.note("test", ValueError("boom"))
    log = tmp_path / "data" / "logs" / "swallowed.log"
    assert log.is_file()
    assert "test" in log.read_text()


def test_repoedit_write_and_read(tmp_path) -> None:
    target = tmp_path / "hello.txt"
    result = repoedit.write_text(target, "hello world")
    assert result.bytes == 11
    assert target.read_text() == "hello world"
    assert result.sha256 == hashlib.sha256(b"hello world").hexdigest()


def test_repoedit_edit_exact(tmp_path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello world", encoding="utf-8")
    result = repoedit.edit_text(target, "world", "there")
    assert result.replacements == 1
    assert target.read_text() == "hello there"


def test_repoedit_edit_ambiguous_refused(tmp_path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("a a a", encoding="utf-8")
    try:
        repoedit.edit_text(target, "a", "b")
    except ValueError:
        return
    raise AssertionError("expected ValueError on ambiguous match")


def test_repoedit_apply_patch(tmp_path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello world\n", encoding="utf-8")
    patch = "--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-hello world\n+hello there\n"
    result = repoedit.apply_patch(tmp_path, patch)
    assert result.replacements == 2
    assert target.read_text() == "hello there\n"


def test_repomap_repo_map(tmp_path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    out = repomap.repo_map(tmp_path, max_files=10, max_tokens=1000)
    assert "a.py" in out
    assert "foo" in out


def test_repomap_search_repo(tmp_path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    hits = repomap.search_repo(tmp_path, "foo")
    assert any("foo" in h.as_line() for h in hits)


def test_repomap_read_slice(tmp_path) -> None:
    target = tmp_path / "a.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    result = repomap.read_slice(target, start=2, end=3)
    assert "line2" in result["content"]
    assert "line3" in result["content"]


def test_skillmanifest_roundtrip(tmp_path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    manifest_path = skillmanifest.write_manifest(tmp_path)
    assert manifest_path.is_file()
    verified = skillmanifest.verify_manifest(tmp_path)
    assert verified.ok is True
    assert verified.checked == 1


def test_projectsetup_profile(tmp_path) -> None:
    (tmp_path / "main.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (tmp_path / "test_main.py").write_text("def test_add(): assert add(1,2)==3\n", encoding="utf-8")
    prof = profile(tmp_path)
    assert prof.files >= 1
    assert any("Python" in lang for lang, _ in prof.languages)


def test_scheduler_basic() -> None:
    s = scheduler.ModelScheduler()
    assert s.stats().active is None
    assert s.stats().inflight == 0
    s.enter("model-a")
    assert s.stats().active == "model-a"
    assert s.stats().inflight == 1
    s.exit("model-a")
    assert s.stats().active is None
    assert s.stats().inflight == 0


def test_scheduler_concurrent_same_model() -> None:
    s = scheduler.ModelScheduler()
    s.enter("model-a")
    s.enter("model-a")
    assert s.stats().inflight == 2
    s.exit("model-a")
    s.exit("model-a")
    assert s.stats().inflight == 0


def test_scheduler_exclusive() -> None:
    s = scheduler.ModelScheduler()
    s.enter_exclusive()
    assert s.stats().active is None
    s.exit_exclusive()
    assert s.stats().active is None


def test_terminal_module_imports() -> None:
    from sovereign_code import terminal

    assert terminal is not None


def test_jump_module_imports() -> None:
    assert jump is not None


def test_patch_module_imports() -> None:
    assert patch is not None


def test_skillrouter_route() -> None:
    cards, note = skillrouter.route("harden a kubernetes cluster", limit=3)
    assert len(cards) > 0
    assert "card" in note.lower() or "token" in note.lower()


def test_skillrouter_playbook() -> None:
    pb = skillrouter.playbook("fix a bug")
    assert isinstance(pb, list)


def test_terminal_module() -> None:
    from sovereign_code import terminal

    assert terminal is not None


def test_webchat_module() -> None:
    from sovereign_code import webchat

    assert webchat is not None


def test_packs_module() -> None:
    from sovereign_code import packs

    assert len(packs.PACKS) > 0
    p = packs.get_pack("pentest")
    assert p is not None
    assert p.label == "Penetration testing"


def test_mlx_pure_functions() -> None:
    assert mlx.mlx_url().startswith("http://")
    assert isinstance(mlx.mlx_port(), int)
    assert isinstance(mlx.disabled(), bool)
    tags = mlx.catalog_tags()
    assert isinstance(tags, tuple)
    assert len(tags) > 0
    assert "mlx-qwen3-4b-4bit" in tags
    assert mlx.REPO_IDS.get("mlx-qwen3-4b-4bit")
    assert mlx.context_for("mlx-qwen3-4b-4bit") == 32768
    assert mlx.fast_loaded_tag() == "" or isinstance(mlx.fast_loaded_tag(), str)
    assert isinstance(mlx.available_tags(), tuple)
    assert mlx.state_path().name == "mlx-server.json"
    assert mlx.log_path().name == "mlx-server.log"
    assert mlx.read_state() == {} or isinstance(mlx.read_state(), dict)
    assert mlx.reset_probe() is None
    assert mlx.online() is False or isinstance(mlx.online(), bool)
    assert mlx.served_models() == () or isinstance(mlx.served_models(), tuple)
