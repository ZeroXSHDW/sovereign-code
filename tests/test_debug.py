"""Tests for the debugger utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from sovereign_code import debug as debug_mod


def test_run_under_pdb_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    with pytest.raises(FileNotFoundError):
        debug_mod.run_under_pdb(missing, [])


def test_run_under_pdb_runs_script(tmp_path: Path) -> None:
    script = tmp_path / "sample.py"
    script.write_text("x = 1 + 1\nprint(x)\n")
    with patch.object(debug_mod, "_write_debug_record") as write:
        with patch("pdb.run") as pdbg:
            code = debug_mod.run_under_pdb(script, ["--flag"])
    assert code == 0
    pdbg.assert_called_once()
    write.assert_any_call("pdb_start", {"script": str(script.resolve()), "args": ["--flag"]})


def test_run_under_pdb_system_exit(tmp_path: Path) -> None:
    script = tmp_path / "exit.py"
    script.write_text("raise SystemExit(42)\n")
    with patch.object(debug_mod, "_write_debug_record"):
        with patch("pdb.run", side_effect=SystemExit(42)):
            code = debug_mod.run_under_pdb(script, [])
    assert code == 42


def test_trace_http_records_request() -> None:
    debug_mod.DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    debug_mod.DEBUG_LOG.write_text("")
    response = httpx.Response(200, json={"ok": True}, headers={"x-test": "yes"})
    transport = httpx.MockTransport(lambda request: response)
    record = debug_mod.trace_http(
        "http://127.0.0.1:4010/v1/models",
        method="GET",
        headers={"Authorization": "Bearer token"},
        transport=transport,
    )
    assert record["status"] == 200
    assert record["response_headers"]["x-test"] == "yes"


def test_trace_http_error_recorded() -> None:
    debug_mod.DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    debug_mod.DEBUG_LOG.write_text("")

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(boom)
    with pytest.raises(httpx.ConnectError):
        debug_mod.trace_http(
            "http://127.0.0.1:4010/v1/models",
            transport=transport,
        )


def test_format_trace_record() -> None:
    record = {
        "method": "POST",
        "url": "http://127.0.0.1:4010/v1/chat/completions",
        "request_headers": {"Content-Type": "application/json"},
        "status": 200,
        "response_headers": {"Content-Type": "application/json"},
        "body_preview": '{"ok": true}',
        "duration_ms": 12.5,
    }
    text = debug_mod.format_trace_record(record)
    assert "POST" in text
    assert "200" in text
    assert "12.5 ms" in text


def test_recent_logs_and_swallowed(tmp_path: Path, monkeypatch: Any) -> None:
    from sovereign_code import logs as logs_mod

    monkeypatch.setattr(logs_mod, "LOCAL_AI_ROOT", tmp_path)
    monkeypatch.setattr(debug_mod, "LOCAL_AI_ROOT", tmp_path)
    log_dir = tmp_path / "data" / "logs"
    log_dir.mkdir(parents=True)
    tier_log = log_dir / "tier-gateway.log"
    tier_log.write_text("line1\nline2\nline3\n")
    swallowed_log = log_dir / "swallowed.log"
    swallowed_log.write_text("err1\nerr2\n")

    assert debug_mod.recent_logs("tier", count=2) == ["line2", "line3"]
    assert debug_mod.recent_swallowed(count=1) == ["err2"]


def test_recent_debug_records(tmp_path: Path, monkeypatch: Any) -> None:
    log_dir = tmp_path / "data" / "logs"
    log_dir.mkdir(parents=True)
    debug_log = log_dir / "debug.log"
    debug_log.write_text(json.dumps({"kind": "test", "ts": 1.0}) + "\n")
    monkeypatch.setattr(debug_mod, "DEBUG_LOG", debug_log)
    records = debug_mod.recent_debug_records(count=5)
    assert records == [{"kind": "test", "ts": 1.0}]


def test_debug_task_uses_gateway(monkeypatch: Any) -> None:
    complete = MagicMock(return_value="fix it")
    monkeypatch.setattr("sovereign_code.summarize.complete", complete)
    monkeypatch.setattr(
        "sovereign_code.config.Settings.load",
        MagicMock(return_value=MagicMock(router_url="http://x")),
    )
    answer = debug_mod.debug_task("my app crashes", model="best", max_tokens=100)
    assert answer == "fix it"
    complete.assert_called_once()
    messages = complete.call_args.kwargs.get("messages", complete.call_args[0][2])
    assert any("crashes" in m["content"] for m in messages)


def test_current_traceback_text() -> None:
    text = debug_mod.current_traceback_text()
    assert "test_current_traceback_text" in text
