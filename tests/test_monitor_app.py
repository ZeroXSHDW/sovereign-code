"""Headless boot test for the read-only monitor dashboard."""

from sovereign_code.config import Settings
from sovereign_code.tui.monitor import MonitorApp


async def test_monitor_boots_with_banks_projects_and_system() -> None:
    app = MonitorApp(settings=Settings(), demo=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert app.report is not None
        assert app.query_one("#skill-panel") is not None
        assert app.query_one("#prompt-panel") is not None
        assert app.query_one("#project-panel") is not None
        assert app.query_one("#activity-panel") is not None
        assert app.query_one("#statusbar") is not None
        # The login dashboard must not be a chat client anymore.
        assert not app.query("#prompt")


async def test_free_ram_with_nothing_resident_is_a_noop() -> None:
    app = MonitorApp(settings=Settings(), demo=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await app.action_free()
        await pilot.pause()
        assert "nothing to unload" in app._notice
