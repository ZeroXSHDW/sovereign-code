"""Parsers behind the safety checks and the model scheduler.

These read `vm_stat`, `sysctl`, `ps` and `lsof` output and turn it into the
facts the dashboard, the router and the loopback warning rely on. A wrong
parse here is not cosmetic: it decides whether a model is evicted and whether
"nothing leaves this Mac" is reported as true.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sovereign_code import system


def _vm_stat(page_size: int = 16384, free: int = 1000, inactive: int = 500) -> str:
    return (
        f"Mach Virtual Memory Statistics: (page size of {page_size} bytes)\n"
        f"Pages free:                               {free}.\n"
        f"Pages active:                             2000.\n"
        f"Pages inactive:                           {inactive}.\n"
        f"Pages speculative:                        100.\n"
    )


def test_memory_label_distinguishes_unknown_from_zero():
    unknown = system.Memory(total_gb=24.0, free_gb=0.0, free_pct=0.0, known=False)
    empty = system.Memory(total_gb=24.0, free_gb=0.0, free_pct=0.0)
    assert unknown.label == "24 GB · free unknown"
    assert empty.label == "24 GB · 0% free"


def test_read_memory_sums_free_inactive_and_speculative(monkeypatch):
    monkeypatch.setattr(system, "total_memory_gb", lambda: 24.0)
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: _vm_stat(page_size=4096, free=1000))
    memory = system.read_memory()
    # (1000 free + 500 inactive + 100 speculative) * 4096 bytes
    assert memory.known
    assert memory.free_gb == pytest.approx(0.0, abs=0.1)
    assert memory.total_gb == 24.0


def test_read_memory_uses_the_reported_page_size(monkeypatch):
    monkeypatch.setattr(system, "total_memory_gb", lambda: 8.0)
    pages = 8 * 1024**3 // 16384
    output = _vm_stat(page_size=16384, free=pages - 600, inactive=0)
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: output)
    memory = system.read_memory()
    assert memory.free_gb <= memory.total_gb
    assert 0 <= memory.free_pct <= 100


def test_read_memory_reports_unknown_when_vm_stat_fails(monkeypatch):
    """A failed probe must not look like "0 GB free" and shrink every context."""
    monkeypatch.setattr(system, "total_memory_gb", lambda: 16.0)
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: "")
    memory = system.read_memory()
    assert not memory.known
    assert memory.total_gb == 16.0


def test_read_memory_clamps_free_to_total(monkeypatch):
    monkeypatch.setattr(system, "total_memory_gb", lambda: 1.0)
    huge = _vm_stat(page_size=16384, free=10**9, inactive=10**9)
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: huge)
    memory = system.read_memory()
    assert memory.free_gb == 1.0
    assert memory.free_pct == 100.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [("17179869184", 16.0), ("not-a-number", 0.0), ("0", 0.0)],
)
def test_total_memory_gb(monkeypatch, value, expected):
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: value)
    assert system.total_memory_gb() == expected


def test_wired_limit_uses_an_explicit_sysctl(monkeypatch):
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: "20480\n")
    assert system.wired_limit_gb(24.0) == 20.0


def test_wired_limit_defaults_to_three_quarters(monkeypatch):
    """macOS reports 0 when the default GPU policy applies."""
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: "0\n")
    assert system.wired_limit_gb(24.0) == 18.0
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: "garbage")
    assert system.wired_limit_gb(0.0) == 0.0


def test_swap_usage_parses_megabytes_and_gigabytes(monkeypatch):
    monkeypatch.setattr(
        system,
        "_run",
        lambda *_a, **_k: "vm.swapusage: total = 4096.00M  used = 1.50G  free = 2.50G",
    )
    used, total = system.swap_usage_gb()
    assert used == 1.5
    assert total == 4.0


def test_swap_usage_is_zero_when_unknown(monkeypatch):
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: "vm.swapusage: not there")
    assert system.swap_usage_gb() == (0.0, 0.0)


def test_ollama_runner_models_reads_ps_and_dedupes(monkeypatch):
    output = (
        "  PID COMMAND\n"
        " 1 /usr/local/bin/ollama runner --model qwen3.5:9b --port 1\n"
        " 2 /usr/local/bin/ollama runner --model qwen3.5:9b --port 2\n"
        " 3 /usr/local/bin/ollama serve\n"
        " 4 ollama runner --model glm-4.7-flash\n"
    )
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: output)
    assert system.ollama_runner_models() == ["qwen3.5:9b", "glm-4.7-flash"]


def test_models_to_evict_leaves_room_when_the_model_fits():
    residents = [("qwen3.5:4b", 3.0)]
    assert system.models_to_evict(8.0, residents, wired_gb=18.0) == []


def test_models_to_evict_unloads_residents_when_it_does_not_fit():
    residents = [("qwen3.8:27b", 18.0), ("glm-4.7-flash", 0.0)]
    assert system.models_to_evict(18.0, residents, wired_gb=18.0) == ["qwen3.8:27b"]


def test_loopback_hosts_accept_only_real_loopback_names():
    for host in ("127.0.0.1", "::1", "[::1]", "localhost", "0:0:0:0:0:0:0:1"):
        assert system.is_loopback_host(host), host
    for host in ("0.0.0.0", "192.168.1.5", "notlocalhost", "", "127.0.0.1.evil.test"):  # noqa: S104
        assert not system.is_loopback_host(host), host


def test_is_loopback_parses_urls_and_rejects_lookalikes():
    for url in (
        "http://127.0.0.1:4010",
        "http://localhost:11434/v1",
        "https://[::1]:4001",
        "127.0.0.1:4010",
    ):
        assert system.is_loopback(url), url
    for url in (
        "http://notlocalhost.example.com",
        "http://127.0.0.1.evil.test",
        "http://0.0.0.0:4010",
        "http://192.168.1.10",
        "",
        "http://",
    ):
        assert not system.is_loopback(url), url


def _lsof_output(*names: str) -> str:
    header = "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
    rows = "".join(f"python3.1 100 user 6u IPv4 0x1 0t0 TCP {name} (LISTEN)\n" for name in names)
    return header + rows


def test_probe_listening_parses_ipv4_and_ipv6(monkeypatch):
    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())
    monkeypatch.setattr(
        system.subprocess,
        "run",
        lambda *_a, **_k: type(
            "R", (), {"returncode": 0, "stdout": _lsof_output("127.0.0.1:4010", "[::1]:4010")}
        )(),
    )
    assert system._probe_listening(4010) == ["127.0.0.1", "::1"]


def test_probe_listening_returns_nothing_on_failure(monkeypatch):
    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())
    monkeypatch.setattr(
        system.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 1, "stdout": ""})()
    )
    assert system._probe_listening(4010) == []


def test_probe_listening_is_empty_off_macos(monkeypatch):
    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Linux"})())
    assert system._probe_listening(4010) == []


def test_listening_addresses_is_cached(monkeypatch):
    calls: list[int] = []

    def probe(port: int) -> list[str]:
        calls.append(port)
        return ["127.0.0.1"]

    system._LISTENING_CACHE.clear()
    monkeypatch.setattr(system, "_probe_listening", probe)
    assert system.listening_addresses(4010) == ["127.0.0.1"]
    assert system.listening_addresses(4010) == ["127.0.0.1"]
    assert calls == [4010]


def test_bound_to_loopback_needs_a_listener(monkeypatch):
    monkeypatch.setattr(system, "listening_addresses", lambda _p: [])
    assert not system.bound_to_loopback(4010)
    monkeypatch.setattr(system, "listening_addresses", lambda _p: ["127.0.0.1", "::1"])
    assert system.bound_to_loopback(4010)
    monkeypatch.setattr(system, "listening_addresses", lambda _p: ["127.0.0.1", "0.0.0.0"])  # noqa: S104
    assert not system.bound_to_loopback(4010)


def test_exposed_ports_reports_only_non_loopback_listeners(monkeypatch):
    listeners = {4010: ["127.0.0.1"], 4001: ["0.0.0.0"], 11434: []}  # noqa: S104
    monkeypatch.setattr(system, "listening_addresses", lambda port: listeners[port])
    assert system.exposed_ports(4010, 4001, 11434) == {4001: ["0.0.0.0"]}  # noqa: S104


def test_disk_free_gb_reports_zero_when_the_path_is_unreadable(monkeypatch):
    def boom(_path):
        raise OSError("no such path")

    monkeypatch.setattr(system.shutil, "disk_usage", boom)
    assert system.disk_free_gb(Path("/nonexistent")) == 0.0


def test_port_open_true_when_server_responds() -> None:
    import socket

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    try:
        assert system.port_open(host, port, timeout=1.0) is True
    finally:
        server.close()


def test_system_binary_prefers_path_then_prefixes(monkeypatch, tmp_path: Path) -> None:
    # shutil.which finds it first
    monkeypatch.setattr(system.shutil, "which", lambda name: f"/bin/{name}")
    assert system.system_binary("ls") == "/bin/ls"


def test_system_binary_returns_none_when_missing_everywhere(monkeypatch) -> None:
    monkeypatch.setattr(system.shutil, "which", lambda _name: None)
    monkeypatch.setattr(system, "BINARY_PREFIXES", ())
    assert system.system_binary("definitely-missing-tool") is None


def test_system_binary_skips_non_executable_prefix_file(monkeypatch, tmp_path: Path) -> None:
    prefix = tmp_path / "bin"
    prefix.mkdir()
    (prefix / "tool").write_text("x", encoding="utf-8")
    monkeypatch.setattr(system.shutil, "which", lambda _name: None)
    monkeypatch.setattr(system, "BINARY_PREFIXES", (str(prefix),))
    assert system.system_binary("tool") is None


def test_command_exists() -> None:
    assert isinstance(system.command_exists("ls"), bool)


def test_port_open_returns_false_on_failure() -> None:
    assert system.port_open("127.0.0.1", 1, timeout=0.01) is False


def test_probe_listening_skips_empty_host(monkeypatch):
    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())
    stdout = (
        "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
        "python3.1 100 user 6u IPv4 0x1 0t0 TCP 127.0.0.1:4010 (LISTEN)\n"
        "python3.1 100 user 6u IPv4 0x1 0t0 TCP :4010 (LISTEN)\n"
    )
    monkeypatch.setattr(
        system.subprocess,
        "run",
        lambda *_a, **_k: type("R", (), {"returncode": 0, "stdout": stdout})(),
    )
    assert system._probe_listening(4010) == ["127.0.0.1"]


def test_login_agent_installed() -> None:
    system.login_agent_installed()  # does not raise


def test_login_agent_loaded_off_macos(monkeypatch) -> None:
    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Linux"})())
    assert system.login_agent_loaded() is False


def test_login_agent_loaded_tolerates_subprocess_error(monkeypatch) -> None:
    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())

    def boom(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr(system.subprocess, "run", boom)
    assert system.login_agent_loaded() is False


def test_is_loopback_handles_urlsplit_error() -> None:
    # urlsplit does not raise on malformed ports, but a path-only url with bad chars can
    assert system.is_loopback("http://[::1") is False


def test_run_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(
        system.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
    )
    assert system._run(["sysctl", "-n", "hw.memsize"]) == ""


def test_read_memory_defaults_total_when_sysctl_fails(monkeypatch):
    monkeypatch.setattr(system, "total_memory_gb", lambda: 0.0)
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: _vm_stat())
    memory = system.read_memory()
    assert memory.total_gb == 24.0


def test_to_gb_handles_bad_number(monkeypatch):
    monkeypatch.setattr(system, "_run", lambda *_a, **_k: "total = 1.2.3G  used = 4.5.6M")
    assert system.swap_usage_gb() == (0.0, 0.0)


def test_probe_listening_handles_subprocess_error(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())
    monkeypatch.setattr(system.subprocess, "run", boom)
    assert system._probe_listening(4010) == []


def test_probe_listening_skips_short_lines(monkeypatch):
    monkeypatch.setattr(system.os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())
    monkeypatch.setattr(
        system.subprocess,
        "run",
        lambda *_a, **_k: type("R", (), {"returncode": 0, "stdout": "COMMAND PID\nshort line\n"})(),
    )
    assert system._probe_listening(4010) == []


def test_system_binary_finds_prefix_binary(monkeypatch, tmp_path: Path) -> None:
    prefix = tmp_path / "bin"
    prefix.mkdir()
    binary = prefix / "fake-tool"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setattr(system, "BINARY_PREFIXES", (str(prefix),))
    monkeypatch.setattr(system.shutil, "which", lambda _name: None)
    assert system.system_binary("fake-tool") == str(binary)


def test_login_agent_helpers() -> None:
    system.login_agent_installed()  # does not raise
    system.login_agent_loaded()  # does not raise


def test_qwen_paths() -> None:
    assert system.qwen_config_path().name == "settings.json"
    assert system.qwen_memory_path().name == "QWEN.md"
