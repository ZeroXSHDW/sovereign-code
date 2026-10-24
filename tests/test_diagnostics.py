"""Diagnostics note survival tests."""

from __future__ import annotations

from pathlib import Path

from sovereign_code.diagnostics import LOG_NAME, note


def test_note_writes_a_line(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import diagnostics

    logs = tmp_path / "data" / "logs"
    monkeypatch.setattr(diagnostics, "LOCAL_AI_ROOT", tmp_path)
    try:
        raise ValueError("multi\nline message")
    except ValueError as exc:
        note("gateway.tags", exc)
    log_file = logs / LOG_NAME
    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "gateway.tags" in content
    assert "ValueError" in content
    assert "multi line message" in content


def test_note_swallows_oserror(monkeypatch, tmp_path: Path) -> None:
    from sovereign_code import diagnostics

    monkeypatch.setattr(diagnostics, "LOCAL_AI_ROOT", tmp_path)
    monkeypatch.setattr(
        diagnostics, "ensure_private_dir", lambda *a, **k: (_ for _ in ()).throw(OSError("no"))
    )
    note("probe", ValueError("boom"))  # must not raise
