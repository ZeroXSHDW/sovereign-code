"""Tests for the debug overlay screen."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sovereign_code.tui.debug import DebugOverlay


def test_show_logs_updates_content() -> None:
    overlay = DebugOverlay()
    mock_title = MagicMock()
    mock_content = MagicMock()
    overlay.query_one = MagicMock(side_effect=[mock_title, mock_content])

    with patch("sovereign_code.tui.debug.recent_logs", return_value=["line1", "line2"]):
        overlay._show_logs()

    mock_title.update.assert_called_once()
    mock_content.update.assert_called_once()
    assert "line1" in mock_content.update.call_args[0][0]


def test_show_swallowed_updates_content() -> None:
    overlay = DebugOverlay()
    mock_title = MagicMock()
    mock_content = MagicMock()
    overlay.query_one = MagicMock(side_effect=[mock_title, mock_content])

    with patch("sovereign_code.tui.debug.recent_swallowed", return_value=["exc"]):
        overlay._show_swallowed()

    mock_content.update.assert_called_once()
    assert "exc" in mock_content.update.call_args[0][0]


def test_show_debug_records_updates_content() -> None:
    overlay = DebugOverlay()
    mock_title = MagicMock()
    mock_content = MagicMock()
    overlay.query_one = MagicMock(side_effect=[mock_title, mock_content])

    records = [{"kind": "test", "ts": 1_700_000_000.0, "raw": "hello"}]
    with patch("sovereign_code.tui.debug.recent_debug_records", return_value=records):
        overlay._show_debug()

    mock_content.update.assert_called_once()
    assert "hello" in mock_content.update.call_args[0][0]


def test_show_debug_records_empty() -> None:
    overlay = DebugOverlay()
    mock_title = MagicMock()
    mock_content = MagicMock()
    overlay.query_one = MagicMock(side_effect=[mock_title, mock_content])

    with patch("sovereign_code.tui.debug.recent_debug_records", return_value=[]):
        overlay._show_debug()

    mock_content.update.assert_called_once()
    assert "No debug traces" in mock_content.update.call_args[0][0]


def test_on_mount_shows_swallowed() -> None:
    overlay = DebugOverlay()
    mock_title = MagicMock()
    mock_content = MagicMock()
    overlay.query_one = MagicMock(side_effect=[mock_title, mock_content])

    with patch("sovereign_code.tui.debug.recent_swallowed", return_value=["swallowed"]):
        overlay.on_mount()

    mock_content.update.assert_called_once()


def test_action_methods_delegate() -> None:
    overlay = DebugOverlay()
    overlay._show_logs = MagicMock()
    overlay._show_swallowed = MagicMock()
    overlay._show_debug = MagicMock()

    overlay.action_logs()
    overlay.action_swallowed()
    overlay.action_debug()

    overlay._show_logs.assert_called_once()
    overlay._show_swallowed.assert_called_once()
    overlay._show_debug.assert_called_once()


def test_show_debug_records_with_timestamp_and_body() -> None:
    overlay = DebugOverlay()
    mock_title = MagicMock()
    mock_content = MagicMock()
    overlay.query_one = MagicMock(side_effect=[mock_title, mock_content])

    records = [{"kind": "test", "ts": 1_700_000_000.0, "field": "value"}]
    with patch("sovereign_code.tui.debug.recent_debug_records", return_value=records):
        overlay._show_debug()

    mock_content.update.assert_called_once()
    assert "test" in mock_content.update.call_args[0][0]
