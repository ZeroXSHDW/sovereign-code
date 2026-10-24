"""Tests for the live client probes and the gateway restart path.

The unit tests above describe the generated configs. These describe the two
things that config cannot prove: that a client answers a real turn, and that a
stale gateway can be stopped instead of blocking its own restart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from sovereign_code import clients, tier_gateway, verify
from sovereign_code.config import Settings


def _fake_cli(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_probe_router_accepts_a_served_completion() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "p"}}]})

    result = verify.probe_router("http://127.0.0.1:4010", transport=httpx.MockTransport(handler))
    assert result.ok
    assert "served" in result.detail
    # No model is named, so the probe works on a machine without the 4B tier.
    assert "model" not in seen


def test_probe_router_rejects_an_empty_reply() -> None:
    """A 200 with no choices is what a wedged gateway returns."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    result = verify.probe_router("http://127.0.0.1:4010", transport=httpx.MockTransport(handler))
    assert not result.ok
    assert result.detail == "empty reply"


def test_probe_clients_runs_each_client(monkeypatch, tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    for name in verify.CLIENT_PROBES:
        _fake_cli(bin_dir, name, f"echo {verify.PROBE_MARKER}")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(
        clients,
        "plan_launch",
        lambda *_args, **_kwargs: clients.LaunchPlan([], tmp_path, os.environ.copy(), "test"),
    )
    results = verify.probe_clients(tmp_path, Settings())
    assert [result.client for result in results] == list(verify.CLIENT_PROBES)
    assert all(result.ok for result in results)


def test_probe_clients_reports_a_silent_client(monkeypatch, tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in verify.CLIENT_PROBES:
        body = (
            "echo 'model not found'; exit 1" if name == "claude" else f"echo {verify.PROBE_MARKER}"
        )
        _fake_cli(bin_dir, name, body)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(
        clients,
        "plan_launch",
        lambda *_args, **_kwargs: clients.LaunchPlan([], tmp_path, os.environ.copy(), "test"),
    )
    results = {result.client: result for result in verify.probe_clients(tmp_path, Settings())}
    assert results["codex"].ok and results["opencode"].ok
    assert not results["claude"].ok
    assert "model not found" in results["claude"].detail


def test_probe_clients_reports_a_missing_binary(monkeypatch, tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_cli(bin_dir, "codex", f"echo {verify.PROBE_MARKER}")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(
        clients,
        "plan_launch",
        lambda *_args, **_kwargs: clients.LaunchPlan([], tmp_path, os.environ.copy(), "test"),
    )
    results = {result.client: result for result in verify.probe_clients(tmp_path, Settings())}
    assert not results["claude"].ok
    assert "not installed" in results["claude"].detail


def test_probe_clients_uses_the_launch_environment(monkeypatch, tmp_path) -> None:
    """The probe must run with the same env the interactive launcher writes."""
    seen: dict[str, str] = {}

    def runner(argv, **kwargs):  # type: ignore[no-untyped-def]
        seen["marker"] = kwargs["env"].get("ANTHROPIC_BASE_URL", "")
        return __import__("subprocess").CompletedProcess(argv, 0, verify.PROBE_MARKER, "")

    plan_env = {**os.environ, "ANTHROPIC_BASE_URL": "http://127.0.0.1:4001"}
    monkeypatch.setattr(
        clients,
        "plan_launch",
        lambda *_args, **_kwargs: clients.LaunchPlan([], tmp_path, plan_env, "test"),
    )
    results = verify.probe_clients(tmp_path, Settings(), runner=runner)
    assert all(result.ok for result in results)
    assert seen["marker"] == "http://127.0.0.1:4001"


def test_stop_refuses_a_process_it_does_not_own(monkeypatch, tmp_path) -> None:
    """Never signal whatever happens to hold the port."""
    pid_file = tmp_path / "tier.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(tier_gateway, "pid_path", lambda: pid_file)
    monkeypatch.setattr(tier_gateway, "_listener_pid", lambda _port: None)
    assert tier_gateway.stop(port=59999) is False
    assert pid_file.exists()


def test_stop_falls_back_to_the_port_owner(monkeypatch, tmp_path) -> None:
    """A gateway started before its pid file existed must still be stoppable."""
    killed: list[int] = []
    monkeypatch.setattr(tier_gateway, "pid_path", lambda: tmp_path / "tier.pid")
    monkeypatch.setattr(tier_gateway, "_listener_pid", lambda _port: 4242)
    monkeypatch.setattr(tier_gateway, "_is_gateway_process", lambda pid: pid == 4242)
    monkeypatch.setattr(tier_gateway.os, "kill", lambda pid, _sig: killed.append(pid))
    monkeypatch.setattr(tier_gateway, "port_open", lambda **_kwargs: False)
    assert tier_gateway.stop(port=59999) is True
    assert killed == [4242]


def test_a_losing_bind_does_not_crash(monkeypatch) -> None:
    """Two instances racing for the port: the loser exits quietly."""
    import sovereign_code.tier_gateway as gateway

    monkeypatch.setattr(gateway, "port_open", lambda **_kwargs: False)
    monkeypatch.setattr(gateway, "pid_path", lambda: Path("/nonexistent/tier.pid"))

    def busy(_host: str, _port: int, _ollama: str, _upstream: str) -> object:
        raise OSError(48, "Address already in use")

    monkeypatch.setattr(gateway, "make_server", busy)
    monkeypatch.setattr(gateway.threading, "Thread", lambda *_a, **_k: pytest.fail("warmed"))
    gateway.serve("127.0.0.1", 4010, "http://127.0.0.1:11434", "http://127.0.0.1:4000")


def test_stop_reports_a_gateway_that_stays_up(monkeypatch, tmp_path) -> None:
    """A process that ignores SIGTERM is not reported as stopped."""
    pid_file = tmp_path / "tier.pid"
    pid_file.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(tier_gateway, "pid_path", lambda: pid_file)
    monkeypatch.setattr(tier_gateway, "STOP_WAIT", 0.0)
    monkeypatch.setattr(tier_gateway, "_is_gateway_process", lambda _pid: True)
    monkeypatch.setattr(tier_gateway.os, "kill", lambda *_args: None)
    monkeypatch.setattr(tier_gateway, "port_open", lambda **_kwargs: True)
    assert tier_gateway.stop(port=59999) is False
    assert pid_file.exists()
