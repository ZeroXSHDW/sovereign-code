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
        assert request.url.params.get_list("filter") == ["gguf"]
        return httpx.Response(
            200,
            json=[
                {
                    "id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                    "downloads": 1234,
                    "likes": 56,
                    "pipeline_tag": "text-generation",
                    "tags": ["gguf", "code", "license:apache-2.0", "language:en"],
                    "gated": False,
                    "private": False,
                    "lastModified": "2026-01-02T03:04:05.000Z",
                }
            ],
        )
    if request.url.path == "/api/datasets":
        assert request.url.params["search"] == "ultrachat"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "HuggingFaceH4/ultrachat_200k",
                    "downloads": 89497,
                    "likes": 1174,
                    "tags": [
                        "task_categories:text-generation",
                        "language:en",
                        "license:mit",
                        "format:parquet",
                    ],
                    "gated": False,
                    "private": False,
                    "lastModified": "2024-10-16T11:52:27.000Z",
                    "description": "A filtered chat dataset.",
                }
            ],
        )
    if request.url.path == "/api/datasets/HuggingFaceH4/ultrachat_200k":
        return httpx.Response(
            200,
            json={
                "id": "HuggingFaceH4/ultrachat_200k",
                "downloads": 89497,
                "likes": 1174,
                "tags": [
                    "task_categories:text-generation",
                    "language:en",
                    "license:mit",
                    "format:parquet",
                ],
                "gated": False,
                "usedStorage": 50166748444,
                "lastModified": "2024-10-16T11:52:27.000Z",
                "siblings": [
                    {"rfilename": "README.md", "size": 100},
                    {"rfilename": "data/train.parquet", "size": 2048},
                ],
            },
        )
    if request.url.path == "/datasets/HuggingFaceH4/ultrachat_200k/raw/main/README.md":
        return httpx.Response(
            200,
            text="---\nlicense: mit\n---\n\n# UltraChat 200k\n\nA filtered chat dataset.\n",
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


def test_dataset_search_info_and_readme() -> None:
    transport = httpx.MockTransport(_handler)
    rows = hf.search_datasets("ultrachat", limit=5, transport=transport)
    assert len(rows) == 1
    row = rows[0]
    assert row.repo_type == "dataset"
    assert row.license == "mit"
    assert row.languages == ("en",)
    assert row.formats == ("parquet",)
    assert row.tasks == ("text-generation",)
    assert row.description == "A filtered chat dataset."

    info = hf.info_dataset("HuggingFaceH4/ultrachat_200k", transport=transport)
    assert info.repo_type == "dataset"
    assert info.used_storage == 50166748444
    assert info.license == "mit"
    assert [item.path for item in info.files] == ["README.md", "data/train.parquet"]
    assert info.to_dict()["formats"] == ["parquet"]

    text = hf.readme(
        "HuggingFaceH4/ultrachat_200k",
        repo_type="dataset",
        transport=transport,
    )
    assert text.startswith("# UltraChat 200k")
    assert "license: mit" not in text


def test_search_passes_tag_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert set(request.url.params.get_list("filter")) == {"gguf", "license:mit"}
        return httpx.Response(200, json=[])

    assert (
        hf.search_models(
            "coder",
            gguf_only=True,
            filters=["license:mit"],
            transport=httpx.MockTransport(handler),
        )
        == []
    )


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

    dataset = hf.build_download_command(
        "org/data",
        repo_type="dataset",
        include=["*.parquet"],
        exclude=["*.bin"],
        max_workers=4,
        hf_cli="/usr/bin/hf",
    )
    assert dataset[dataset.index("--repo-type") + 1] == "dataset"
    assert dataset[dataset.index("--exclude") + 1] == "*.bin"
    assert dataset[dataset.index("--max-workers") + 1] == "4"


def test_local_models_lists_downloads_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = tmp_path / "downloads"
    model_dir = downloads / "org--demo"
    model_dir.mkdir(parents=True)
    (model_dir / "weights.gguf").write_bytes(b"x" * 32)
    datasets = tmp_path / "datasets"
    dataset_dir = datasets / "org--demo-data"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "train.parquet").write_bytes(b"d" * 8)
    cache = tmp_path / "cache"
    blob = cache / "models--org--cached" / "blobs" / "deadbeef"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"y" * 16)
    snapshot = cache / "models--org--cached" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "weights.safetensors").symlink_to(blob)
    dataset_snapshot = cache / "datasets--org--cached-data" / "snapshots" / "abc"
    dataset_snapshot.mkdir(parents=True)
    (dataset_snapshot / "train.parquet").write_bytes(b"z" * 4)
    monkeypatch.setattr(hf, "DOWNLOAD_ROOT", downloads)
    monkeypatch.setattr(hf, "DATASET_DOWNLOAD_ROOT", datasets)
    monkeypatch.setattr(hf, "hub_cache_dir", lambda: cache)
    rows = hf.local_repos()
    assert {(row.repo_type, row.repo_id) for row in rows} == {
        ("model", "org/demo"),
        ("model", "org/cached"),
        ("dataset", "org/demo-data"),
        ("dataset", "org/cached-data"),
    }
    cached = next(row for row in rows if row.repo_id == "org/cached")
    assert cached.repo_type == "model"
    assert cached.kind == "cache"
    assert cached.bytes == 16
    assert {row.repo_id for row in hf.local_models()} == {"org/demo", "org/cached"}
    assert {row.repo_id for row in hf.local_repos("dataset")} == {
        "org/demo-data",
        "org/cached-data",
    }


def test_remove_local_removes_download_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = tmp_path / "downloads"
    model_dir = downloads / "org--demo"
    model_dir.mkdir(parents=True)
    (model_dir / "weights.gguf").write_bytes(b"x" * 32)
    cache = tmp_path / "cache"
    cache_dir = cache / "models--org--demo"
    cache_dir.mkdir(parents=True)
    (cache_dir / "blob").write_bytes(b"y" * 16)
    monkeypatch.setattr(hf, "DOWNLOAD_ROOT", downloads)
    monkeypatch.setattr(hf, "hub_cache_dir", lambda: cache)
    assert set(hf.local_repo_paths("org/demo")) == {model_dir, cache_dir}
    removed = hf.remove_local("org/demo")
    assert set(removed) == {model_dir, cache_dir}
    assert not model_dir.exists()
    assert not cache_dir.exists()
    assert hf.local_repo_paths("org/demo") == []


def test_ollama_import_helpers(tmp_path: Path) -> None:
    gguf = tmp_path / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
    gguf.write_bytes(b"")
    assert hf.ollama_model_name("Qwen/Qwen2.5-Coder-7B-Instruct-GGUF", gguf) == (
        "qwen2.5-coder-7b-instruct:q4_k_m"
    )
    assert hf.ollama_model_name(gguf.stem, gguf) == "qwen2.5-coder-7b-instruct:q4_k_m"
    assert hf.quant_label(gguf) == "q4_k_m"
    assert hf.is_split_gguf("model-00001-of-00004.gguf")
    assert not hf.is_split_gguf(gguf)
    assert hf.valid_ollama_name("qwen2.5-coder-7b-instruct:q4_k_m")
    assert not hf.valid_ollama_name("-bad:name")
    modelfile = hf.modelfile_text(gguf, context=32768)
    assert modelfile.startswith("FROM ")
    assert "PARAMETER num_ctx 32768" in modelfile


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
