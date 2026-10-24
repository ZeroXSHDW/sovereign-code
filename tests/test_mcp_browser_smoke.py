from __future__ import annotations

from sovereign_code import mcp


def test_browser_task_tool_listed() -> None:
    names = {t["name"] for t in mcp.TOOLS}
    assert "browser_task" in names
    assert "browser_act" in names


def test_pdf_tools_listed() -> None:
    names = {t["name"] for t in mcp.TOOLS}
    assert "pdf_tables" in names
    assert "pdf_figures" in names


def test_browser_act_has_wait() -> None:
    tool = next(t for t in mcp.TOOLS if t["name"] == "browser_act")
    enum = tool["inputSchema"]["properties"]["action"]["enum"]
    assert "wait" in enum
    assert "seconds" in tool["inputSchema"]["properties"]
