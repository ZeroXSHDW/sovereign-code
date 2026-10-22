"""Headless boot test for the read-only monitor dashboard."""

from sovereign_code.config import Settings
from sovereign_code.tui.monitor import MonitorApp


async def test_monitor_boots_with_banks_projects_and_system() -> None:
    app = MonitorApp(settings=Settings(), demo=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert app.report is not None
        assert app.query_one("#health-panel") is not None
        assert app.query_one("#skill-panel") is not None
        assert app.query_one("#prompt-panel") is not None
        assert app.query_one("#project-panel") is not None
        assert app.query_one("#model-panel") is not None
        assert app.query_one("#activity-summary") is not None
        assert app.query_one("#activity-panel") is not None
        assert app.query_one("#hint-line") is not None
        assert app.query_one("#statusbar") is not None
        assert "Health:" in app._summary_text()
        # The login dashboard must not be a chat client anymore.
        assert not app.query("#prompt")


async def test_free_ram_with_nothing_resident_is_a_noop() -> None:
    app = MonitorApp(settings=Settings(), demo=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await app.action_free()
        await pilot.pause()
        assert "nothing to unload" in app._notice


async def test_pause_stops_live_refresh() -> None:
    app = MonitorApp(settings=Settings(), demo=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        app.action_pause()
        assert app.paused is True
        assert "paused" in app._notice
        app.action_pause()
        assert app.paused is False
        assert "resumed" in app._notice


async def test_help_is_a_modal_overlay() -> None:
    from sovereign_code.tui.monitor import MonitorHelp

    app = MonitorApp(settings=Settings(), demo=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, MonitorHelp)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, MonitorHelp)
