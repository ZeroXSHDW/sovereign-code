"""Headless boot test for the Textual dashboard."""

from pathlib import Path

from sovereign_code.config import Settings
from sovereign_code.tui.app import SovereignApp


async def test_dashboard_boots_offline():
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert app.query_one("#prompt") is not None
        assert app.query_one("#model-list") is not None
        assert app.query_one("#statusbar") is not None
        assert app.snapshot is not None
        assert app.selected_model in app.snapshot.views


async def test_help_command_renders():
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.handle_command("/help")
        await pilot.pause()
        assert len(app.history) == 0


async def test_verify_action_records_results(monkeypatch):
    from sovereign_code.verify import AliasResult

    monkeypatch.setattr(
        "sovereign_code.tui.app.probe_aliases",
        lambda *args, **kwargs: [AliasResult("local-chat", True, 0.1, "OK")],
    )
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app.snapshot.gateway.up = True
        await app.action_verify()
        await pilot.pause()
        assert app.last_verify
        assert app.last_verify[0].alias == "local-chat"


async def test_verify_action_handles_offline_gateway():
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.action_verify()
        await pilot.pause()
        assert app.last_verify == []


async def test_browse_action_prefills_prompt():
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.action_browse()
        prompt = app.query_one("#prompt")
        assert prompt.value == "/browse "
        assert prompt.cursor_position == len("/browse ")


async def test_session_retention_prunes_on_start(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr("sovereign_code.sessions.SESSIONS_DIR", tmp_path)
    stale = tmp_path / "20200101-000000-old.jsonl"
    stale.write_text(
        '{"type":"session","model":"m"}\n{"type":"message","role":"user","content":"x"}\n',
        encoding="utf-8",
    )
    os.utime(stale, (1, 1))
    settings = Settings(session_retention_days=30, session_keep=0)
    app = SovereignApp(settings=settings, demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
    assert not stale.exists()


async def test_session_retention_disabled_by_default(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr("sovereign_code.sessions.SESSIONS_DIR", tmp_path)
    keep = tmp_path / "20200101-000000-old.jsonl"
    keep.write_text('{"type":"session","model":"m"}\n', encoding="utf-8")
    os.utime(keep, (1, 1))
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
    assert keep.exists()


async def test_search_command_delegates_inline(monkeypatch):
    calls = []

    async def fake_search(query, root):
        calls.append((query, root))

    app = SovereignApp(settings=Settings(), demo=True)
    app._search_inline = fake_search
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.handle_command("/search gateway restart")
        await pilot.pause()
    assert calls
    assert calls[0][0] == "gateway restart"


async def test_backup_command_delegates(monkeypatch):
    calls = []

    async def fake_run_cli(*args):
        calls.append(args)

    app = SovereignApp(settings=Settings(), demo=True)
    app._run_cli = fake_run_cli
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.handle_command("/backup")
        await pilot.pause()
    assert calls == [("backup",)]


async def test_pdf_command_delegates(monkeypatch):
    calls = []

    async def fake_run_cli(*args):
        calls.append(args)

    app = SovereignApp(settings=Settings(), demo=True)
    app._run_cli = fake_run_cli
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.handle_command("/pdf /tmp/a.pdf")
        await pilot.pause()
    assert calls == [("pdf", "/tmp/a.pdf")]


async def test_config_coercion_helpers():
    from sovereign_code.cli import _coerce_setting

    assert _coerce_setting("true", False) is True
    assert _coerce_setting("5", 0) == 5
    assert _coerce_setting("2.5", 0.0) == 2.5
    assert _coerce_setting("hello", "") == "hello"
    assert _coerce_setting("", None) is None
    assert _coerce_setting("x", None) == "x"


async def test_project_memory_notes(monkeypatch, tmp_path):
    import sovereign_code.memory as memory_module

    monkeypatch.setattr(memory_module, "DATA_DIR", tmp_path)
    cwd = tmp_path / "proj"
    cwd.mkdir()
    from sovereign_code.memory import add_memory

    add_memory("always run ruff", cwd)
    settings = Settings(workspace=str(cwd))
    app = SovereignApp(settings=settings, demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
    assert "always run ruff" in app._project_memory()


async def test_resume_command_loads_the_last_session(monkeypatch, tmp_path):
    """`/resume` restores the previous conversation's turns into history."""
    from sovereign_code.tui import app as app_module

    fake_path = Path("/nonexistent-session.jsonl")
    monkeypatch.setattr(app_module, "recent_sessions", lambda limit=1: [fake_path])
    monkeypatch.setattr(
        app_module,
        "read_session",
        lambda _p: [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
    )
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._resume_session()
        await pilot.pause()
    roles = [item["role"] for item in app.history]
    assert roles == ["user", "assistant"]


async def test_resume_with_no_session_is_a_noop(monkeypatch):
    from sovereign_code.tui import app as app_module

    monkeypatch.setattr(app_module, "recent_sessions", lambda limit=1: [])
    app = SovereignApp(settings=Settings(), demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._resume_session()
        await pilot.pause()
    assert app.history == []
