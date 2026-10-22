"""Tests for the Hugging Face Hub integration."""

from __future__ import annotations

import stat
from pathlib import Path

import httpx
import pytest

from sovereign_code import hf


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/whoami-v2":
        assert request.headers["authorization"] == "Bearer hf_test_token"
        return httpx.Response(200, json={"name": "tester", "fullname": "Test User"})
    if request.url.path == "/api/models":
        assert request.url.params["search"] == "qwen coder"
        assert request.url.params["filter"] == "gguf"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                    "downloads": 1234,
                    "likes": 56,
                    "pipeline_tag": "text-generation",
                    "tags": ["gguf", "code"],
                    "gated": False,
                    "private": False,
                    "lastModified": "2026-01-02T03:04:05.000Z",
                }
            ],
        )
    if request.url.path == "/api/models/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF":
        return httpx.Response(
            200,
            json={
                "id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                "downloads": 1234,
                "likes": 56,
                "pipeline_tag": "text-generation",
                "tags": ["gguf", "text-generation"],
                "gated": False,
                "usedStorage": 9000,
                "lastModified": "2026-01-02T03:04:05.000Z",
                "gguf": {"context_length": 131072, "architecture": "qwen2"},
                "siblings": [
                    {"rfilename": "README.md", "size": 100},
                    {"rfilename": "model-Q4_K_M.gguf", "size": 4500},
                    {"rfilename": "model-Q8_0.gguf", "lfs": {"size": 8500}},
                ],
            },
        )
    return httpx.Response(404)


@pytest.fixture
def hf_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    return tmp_path / "hf"


def test_save_and_verify_token_is_owner_only(hf_home: Path) -> None:
    status = hf.save_token("  hf_test_token\n", transport=httpx.MockTransport(_handler))
    assert status.present
    assert status.verified
    assert status.account == "tester"
    token_file = hf.token_path()
    assert token_file.read_text() == "hf_test_token\n"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert hf.resolve_token() == ("hf_test_token", str(token_file))
    checked = hf.token_status(verify=True, transport=httpx.MockTransport(_handler))
    assert checked.verified
    assert checked.account == "tester"
    assert "token" not in checked.to_dict()


def test_environment_token_takes_precedence(hf_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hf.token_path().parent.mkdir(parents=True, exist_ok=True)
    hf.token_path().write_text("hf_from_file\n")
    monkeypatch.setenv("HF_TOKEN", "hf_from_environment")
    assert hf.resolve_token() == ("hf_from_environment", "HF_TOKEN")
    assert hf.token_status().source == "HF_TOKEN"


def test_search_and_info_parse_the_hub_response() -> None:
    transport = httpx.MockTransport(_handler)
    rows = hf.search_models(
        "qwen coder",
        gguf_only=True,
        limit=5,
        token="hf_test_token",
        transport=transport,
    )
    assert len(rows) == 1
    assert rows[0].gguf
    assert rows[0].downloads == 1234
    assert rows[0].updated == "2026-01-02"

    info = hf.info_model(
        "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        token="hf_test_token",
        transport=transport,
    )
    assert info.gguf["context_length"] == 131072
    assert info.total_file_size == 13100
    assert [item.path for item in info.gguf_files] == [
        "model-Q4_K_M.gguf",
        "model-Q8_0.gguf",
    ]
    assert info.to_dict()["files"][1]["size"] == 4500


def test_build_download_command_requires_explicit_files(tmp_path: Path) -> None:
    with pytest.raises(hf.HFError, match="--include"):
        hf.build_download_command("org/model", hf_cli="/usr/bin/hf")

    command = hf.build_download_command(
        "org/model-GGUF",
        include=["*Q4_K_M.gguf"],
        local_dir=tmp_path / "model",
        hf_cli="/usr/bin/hf",
    )
    assert command[:3] == ["/usr/bin/hf", "download", "org/model-GGUF"]
    assert "--include" in command
    assert "*Q4_K_M.gguf" in command
    assert "--local-dir" in command
    assert "hf_" not in " ".join(command)


def test_local_models_lists_downloads_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = tmp_path / "downloads"
    model_dir = downloads / "org--demo"
    model_dir.mkdir(parents=True)
    (model_dir / "weights.gguf").write_bytes(b"x" * 32)
    cache = tmp_path / "cache"
    blob = cache / "models--org--cached" / "blobs" / "deadbeef"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"y" * 16)
    snapshot = cache / "models--org--cached" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "weights.safetensors").symlink_to(blob)
    monkeypatch.setattr(hf, "DOWNLOAD_ROOT", downloads)
    monkeypatch.setattr(hf, "hub_cache_dir", lambda: cache)
    rows = hf.local_models()
    assert {row.repo_id for row in rows} == {"org/demo", "org/cached"}
    assert {row.kind for row in rows} == {"download", "cache"}
    cached = next(row for row in rows if row.kind == "cache")
    assert cached.bytes == 16


def test_directory_size_does_not_follow_symlinks(tmp_path: Path) -> None:
    blob = tmp_path / "blobs" / "abc"
    blob.parent.mkdir()
    blob.write_bytes(b"x" * 64)
    snapshot = tmp_path / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "weights").symlink_to(blob)
    (tmp_path / "config.json").write_bytes(b"{}")
    assert hf.directory_size(tmp_path) == 66


def test_invalid_repo_id_is_rejected() -> None:
    with pytest.raises(hf.HFError):
        hf.validate_repo_id("../etc/passwd")
    with pytest.raises(hf.HFError):
        hf.validate_repo_id("not-a-repo")
