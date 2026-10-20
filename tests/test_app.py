"""Headless boot test for the Textual dashboard."""

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
