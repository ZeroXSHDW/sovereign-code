"""Hugging Face Hub: token storage, search, inspection, and downloads.

The token lives in the standard Hugging Face location rather than in
Sovereign's ``config.toml``: ``$HF_TOKEN_PATH`` when set, otherwise
``$HF_HOME/token``, otherwise ``~/.cache/huggingface/token``. That is the same
file the ``hf`` CLI and ``huggingface_hub`` read, so one login works everywhere.
The token is never printed, written to configuration, or passed on a command
line.

Search and model inspection use the public Hub API. Downloads are delegated to
the ``hf`` CLI, which handles LFS, resumable transfers, gated repositories, and
the Xet cache. A download can be pointed at the shared cache (the default for
the ``hf`` CLI) or at a visible local folder under
``~/Documents/local-ai/models/huggingface``.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .config import LOCAL_AI_ROOT
from .errors import HFError
from .safefile import write_private
from .stats import human_size

DEFAULT_ENDPOINT = "https://huggingface.co"
DOWNLOAD_ROOT = LOCAL_AI_ROOT / "models" / "huggingface"
DATASET_DOWNLOAD_ROOT = LOCAL_AI_ROOT / "datasets" / "huggingface"
TOKEN_ENV_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
REPO_TYPES = ("model", "dataset")
SPLIT_GGUF_RE = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.IGNORECASE)
QUANT_RE = re.compile(
    r"(?:^|[-_.])((?:iq|q)\d+(?:_[a-z0-9]+)*|f16|bf16|fp16|fp32)(?:[-_.]|$)",
    re.IGNORECASE,
)
OLLAMA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$")


def _tag_values(tags: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    """Values of tags such as ``license:mit`` in declaration order."""
    marker = f"{prefix}:"
    return tuple(dict.fromkeys(tag[len(marker) :] for tag in tags if tag.startswith(marker)))


def _first_tag(tags: tuple[str, ...], prefix: str) -> str:
    values = _tag_values(tags, prefix)
    return values[0] if values else ""


@dataclass(frozen=True)
class TokenStatus:
    source: str
    path: Path
    present: bool
    account: str = ""
    verified: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "path": str(self.path),
            "present": self.present,
            "account": self.account,
            "verified": self.verified,
            "error": self.error,
        }


@dataclass(frozen=True)
class HFModel:
    id: str
    downloads: int = 0
    likes: int = 0
    pipeline_tag: str = ""
    tags: tuple[str, ...] = ()
    gated: str = ""
    private: bool = False
    updated: str = ""
    repo_type: str = "model"
    description: str = ""

    @property
    def gguf(self) -> bool:
        return "gguf" in {tag.lower() for tag in self.tags}

    @property
    def license(self) -> str:
        return _first_tag(self.tags, "license")

    @property
    def languages(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "language")

    @property
    def formats(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "format")

    @property
    def tasks(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "task_categories")

    @property
    def base_models(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "base_model")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo_type": self.repo_type,
            "downloads": self.downloads,
            "likes": self.likes,
            "pipeline_tag": self.pipeline_tag,
            "tags": list(self.tags),
            "gguf": self.gguf,
            "gated": self.gated,
            "private": self.private,
            "updated": self.updated,
            "description": self.description,
            "license": self.license,
            "languages": list(self.languages),
            "formats": list(self.formats),
            "tasks": list(self.tasks),
            "base_models": list(self.base_models),
        }


@dataclass(frozen=True)
class HFFile:
    path: str
    size: int = 0

    @property
    def gguf(self) -> bool:
        return self.path.lower().endswith(".gguf")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "gguf": self.gguf}


@dataclass(frozen=True)
class HFModelInfo:
    id: str
    downloads: int = 0
    likes: int = 0
    pipeline_tag: str = ""
    tags: tuple[str, ...] = ()
    gated: str = ""
    private: bool = False
    updated: str = ""
    used_storage: int = 0
    files: tuple[HFFile, ...] = ()
    gguf: dict[str, Any] = field(default_factory=dict)
    repo_type: str = "model"
    description: str = ""

    @property
    def total_file_size(self) -> int:
        return sum(item.size for item in self.files)

    @property
    def gguf_files(self) -> tuple[HFFile, ...]:
        return tuple(item for item in self.files if item.gguf)

    @property
    def license(self) -> str:
        return _first_tag(self.tags, "license")

    @property
    def languages(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "language")

    @property
    def formats(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "format")

    @property
    def tasks(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "task_categories")

    @property
    def base_models(self) -> tuple[str, ...]:
        return _tag_values(self.tags, "base_model")

    def to_dict(self, include_files: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "repo_type": self.repo_type,
            "downloads": self.downloads,
            "likes": self.likes,
            "pipeline_tag": self.pipeline_tag,
            "tags": list(self.tags),
            "gated": self.gated,
            "private": self.private,
            "updated": self.updated,
            "used_storage": self.used_storage,
            "total_file_size": self.total_file_size,
            "gguf": dict(self.gguf),
            "description": self.description,
            "license": self.license,
            "languages": list(self.languages),
            "formats": list(self.formats),
            "tasks": list(self.tasks),
            "base_models": list(self.base_models),
        }
        if include_files:
            data["files"] = [item.to_dict() for item in self.files]
        return data


@dataclass(frozen=True)
class LocalHFModel:
    repo_id: str
    path: Path
    kind: str
    bytes: int
    modified: str
    repo_type: str = "model"

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_type": self.repo_type,
            "path": str(self.path),
            "kind": self.kind,
            "bytes": self.bytes,
            "human": human_size(self.bytes),
            "modified": self.modified,
        }


def hf_home() -> Path:
    value = os.environ.get("HF_HOME")
    if value:
        return Path(value).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "huggingface"


def token_path() -> Path:
    value = os.environ.get("HF_TOKEN_PATH")
    return Path(value).expanduser() if value else hf_home() / "token"


def hub_cache_dir() -> Path:
    for name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    return hf_home() / "hub"


def endpoint() -> str:
    return os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")


def _clean_token(value: str | None) -> str:
    return str(value or "").strip()


def _env_token() -> tuple[str, str]:
    for name in TOKEN_ENV_VARS:
        value = _clean_token(os.environ.get(name))
        if value:
            return value, name
    return "", ""


def _file_token() -> str:
    try:
        return _clean_token(token_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ""


def resolve_token() -> tuple[str, str]:
    """Return ``(token, source)`` without ever exposing the token in output."""
    token, source = _env_token()
    if token:
        return token, source
    token = _file_token()
    if token:
        return token, str(token_path())
    return "", ""


def token_status(
    *, verify: bool = False, transport: httpx.BaseTransport | None = None
) -> TokenStatus:
    token, source = resolve_token()
    path = token_path()
    if not token:
        return TokenStatus(source="", path=path, present=False)
    account = ""
    verified = False
    error = ""
    if verify:
        try:
            data = whoami(token=token, transport=transport)
            account = str(data.get("name") or data.get("fullname") or "")
            verified = True
        except HFError as exc:
            error = str(exc)
    return TokenStatus(
        source=source,
        path=path,
        present=True,
        account=account,
        verified=verified,
        error=error,
    )


def whoami(
    token: str | None = None, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    token = _clean_token(token) or resolve_token()[0]
    if not token:
        raise HFError("not logged in; run `sovereign hf login`")
    data = _request_json("/api/whoami-v2", token=token, transport=transport)
    if not isinstance(data, dict):
        raise HFError("Hugging Face returned an unexpected account response")
    return data


def save_token(
    token: str,
    *,
    verify: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> TokenStatus:
    """Save a token in the HF-standard file with owner-only permissions.

    ``verify`` checks the token against ``/api/whoami-v2`` before it replaces
    the current one, so a typo cannot silently break every Hub command.
    """
    value = _clean_token(token)
    if not value:
        raise HFError("empty token")
    if len(value) < 8:
        raise HFError("that token is too short to be a Hugging Face token")
    if any(char.isspace() for char in value):
        raise HFError("the token contains whitespace; copy it again without line breaks")
    account = ""
    verified = False
    if verify:
        data = whoami(token=value, transport=transport)
        account = str(data.get("name") or data.get("fullname") or "")
        verified = True

    path = token_path()
    # Atomic private write: a crash cannot truncate the token, and replacing
    # the path (instead of opening it) means a planted symlink cannot redirect
    # the credential into another file.
    write_private(path, value + "\n")
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    return TokenStatus(
        source=str(path),
        path=path,
        present=True,
        account=account,
        verified=verified,
    )


def forget_token() -> bool:
    """Remove the active HF token file. Returns False when none was stored."""
    path = token_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise HFError(f"could not remove {path}: {exc}") from exc


def hf_cli_path() -> str | None:
    return shutil.which("hf") or shutil.which("huggingface-cli")


def hf_cli_version() -> str:
    executable = hf_cli_path()
    if not executable:
        return ""
    try:
        result = subprocess.run(
            [executable, "version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (
        (result.stdout or result.stderr).strip().splitlines()[0]
        if result.stdout or result.stderr
        else ""
    )


def _validate_repo_type(repo_type: str) -> str:
    value = str(repo_type or "model").strip().lower()
    if value not in REPO_TYPES:
        raise HFError("repository type must be `model` or `dataset`")
    return value


def _api_repo_path(repo_type: str) -> str:
    return "/api/models" if repo_type == "model" else "/api/datasets"


def _search_path(repo_type: str) -> str:
    return _api_repo_path(repo_type)


def _raw_prefix(repo_type: str) -> str:
    return "" if repo_type == "model" else "/datasets"


def validate_repo_id(repo_id: str) -> str:
    value = str(repo_id or "").strip()
    if not REPO_ID_RE.fullmatch(value):
        raise HFError("expected a repository id like `org/model`")
    return value


def repo_slug(repo_id: str) -> str:
    return validate_repo_id(repo_id).replace("/", "--")


def default_download_dir(repo_id: str, repo_type: str = "model") -> Path:
    repo_type = _validate_repo_type(repo_type)
    root = DOWNLOAD_ROOT if repo_type == "model" else DATASET_DOWNLOAD_ROOT
    return root / repo_slug(repo_id)


def _client(transport: httpx.BaseTransport | None = None, timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=5.0),
        follow_redirects=True,
        transport=transport,
    )


def _request(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 20.0,
    accept: str = "application/json",
) -> httpx.Response:
    url = f"{endpoint()}{path}"
    headers = {"Accept": accept, "User-Agent": "sovereign-code"}
    token = _clean_token(token)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with _client(transport=transport, timeout=timeout) as client:
            response = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise HFError(f"could not reach {endpoint()}: {exc}") from exc
    if response.status_code in (401, 403):
        raise HFError(
            f"Hugging Face rejected the request (HTTP {response.status_code}). "
            "Check the token and whether you accepted the model's licence."
        )
    if response.status_code == 404:
        raise HFError(f"not found: {url} (check the repository id)")
    if response.status_code >= 400:
        raise HFError(f"Hugging Face returned HTTP {response.status_code}: {response.text[:300]}")
    return response


def _request_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 20.0,
) -> Any:
    response = _request(
        path,
        params=params,
        token=token,
        transport=transport,
        timeout=timeout,
    )
    try:
        return response.json()
    except ValueError as exc:
        raise HFError("Hugging Face returned invalid JSON") from exc


def _request_text(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 20.0,
) -> str:
    response = _request(
        path,
        params=params,
        token=token,
        transport=transport,
        timeout=timeout,
        accept="text/plain",
    )
    return response.text


def _gated_label(value: Any) -> str:
    if value is True:
        return "gated"
    if value in ("auto", "manual"):
        return str(value)
    return "gated" if value else ""


def _updated(item: dict[str, Any]) -> str:
    raw = item.get("lastModified") or item.get("created_at") or item.get("createdAt") or ""
    return str(raw)[:10]


def _description(item: dict[str, Any]) -> str:
    card_data = item.get("cardData")
    card: dict[str, Any] = card_data if isinstance(card_data, dict) else {}
    raw = item.get("description") or card.get("description") or ""
    return " ".join(str(raw).split())


def _model_from_api(item: dict[str, Any], repo_type: str = "model") -> HFModel:
    return HFModel(
        id=str(item.get("id") or ""),
        downloads=int(item.get("downloads") or 0),
        likes=int(item.get("likes") or 0),
        pipeline_tag=str(item.get("pipeline_tag") or ""),
        tags=tuple(str(tag) for tag in (item.get("tags") or ())),
        gated=_gated_label(item.get("gated")),
        private=bool(item.get("private")),
        updated=_updated(item),
        repo_type=repo_type,
        description=_description(item),
    )


def _file_from_api(item: dict[str, Any]) -> HFFile:
    lfs_raw = item.get("lfs")
    lfs: dict[str, Any] = lfs_raw if isinstance(lfs_raw, dict) else {}
    size = item.get("size") or lfs.get("size") or 0
    try:
        parsed = int(size)
    except (TypeError, ValueError):
        parsed = 0
    return HFFile(path=str(item.get("rfilename") or item.get("path") or ""), size=parsed)


def search_models(
    query: str,
    *,
    limit: int = 20,
    gguf_only: bool = False,
    author: str | None = None,
    sort: str = "downloads",
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    repo_type: str = "model",
    filters: list[str] | None = None,
    pipeline_tag: str | None = None,
) -> list[HFModel]:
    """Search the public Hub. A token adds private and gated results."""
    repo_type = _validate_repo_type(repo_type)
    if gguf_only and repo_type != "model":
        raise HFError("the GGUF filter applies to models, not datasets")
    params: dict[str, Any] = {
        "limit": max(1, min(int(limit), 100)),
        "sort": sort,
        "direction": -1,
    }
    needle = str(query or "").strip()
    if needle:
        params["search"] = needle
    wanted: list[str] = []
    if gguf_only:
        wanted.append("gguf")
    wanted.extend(str(item).strip() for item in (filters or []) if str(item).strip())
    if wanted:
        params["filter"] = wanted
    if pipeline_tag and repo_type == "model":
        params["pipeline_tag"] = str(pipeline_tag).strip()
    if author:
        params["author"] = author.strip()
    data = _request_json(_search_path(repo_type), params=params, token=token, transport=transport)
    if not isinstance(data, list):
        raise HFError("Hugging Face returned an unexpected search response")
    return [_model_from_api(item, repo_type) for item in data if isinstance(item, dict)]


def search_datasets(
    query: str,
    *,
    limit: int = 20,
    author: str | None = None,
    sort: str = "downloads",
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    filters: list[str] | None = None,
) -> list[HFModel]:
    """Search datasets with the same shape as model search."""
    return search_models(
        query,
        limit=limit,
        author=author,
        sort=sort,
        token=token,
        transport=transport,
        repo_type="dataset",
        filters=filters,
    )


def info_model(
    repo_id: str,
    *,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    repo_type: str = "model",
) -> HFModelInfo:
    repo = validate_repo_id(repo_id)
    repo_type = _validate_repo_type(repo_type)
    data = _request_json(
        f"{_api_repo_path(repo_type)}/{quote(repo, safe='/')}",
        params={"blobs": "true"},
        token=token,
        transport=transport,
    )
    if not isinstance(data, dict):
        raise HFError("Hugging Face returned an unexpected repository response")
    files = tuple(
        _file_from_api(item) for item in (data.get("siblings") or ()) if isinstance(item, dict)
    )
    gguf_raw = data.get("gguf")
    gguf: dict[str, Any] = gguf_raw if isinstance(gguf_raw, dict) else {}
    try:
        used_storage = int(data.get("usedStorage") or 0)
    except (TypeError, ValueError):
        used_storage = 0
    return HFModelInfo(
        id=str(data.get("id") or repo),
        downloads=int(data.get("downloads") or 0),
        likes=int(data.get("likes") or 0),
        pipeline_tag=str(data.get("pipeline_tag") or ""),
        tags=tuple(str(tag) for tag in (data.get("tags") or ())),
        gated=_gated_label(data.get("gated")),
        private=bool(data.get("private")),
        updated=_updated(data),
        used_storage=used_storage,
        files=files,
        gguf=dict(gguf),
        repo_type=repo_type,
        description=_description(data),
    )


def info_dataset(
    repo_id: str,
    *,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> HFModelInfo:
    return info_model(repo_id, token=token, transport=transport, repo_type="dataset")


def readme(
    repo_id: str,
    *,
    repo_type: str = "model",
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    limit: int = 6000,
) -> str:
    """Fetch the repository README without its YAML frontmatter."""
    repo = validate_repo_id(repo_id)
    repo_type = _validate_repo_type(repo_type)
    text = _request_text(
        f"{_raw_prefix(repo_type)}/{quote(repo, safe='/')}/raw/main/README.md",
        token=token,
        transport=transport,
    )
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    text = text.strip()
    return text[:limit]


def build_download_command(
    repo_id: str,
    *,
    repo_type: str = "model",
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    all_files: bool = False,
    revision: str | None = None,
    local_dir: Path | str | None = None,
    cache_dir: Path | str | None = None,
    max_workers: int | None = None,
    dry_run: bool = False,
    hf_cli: str | None = None,
) -> list[str]:
    """Build an ``hf download`` argv without putting a token in it."""
    repo = validate_repo_id(repo_id)
    repo_type = _validate_repo_type(repo_type)
    patterns = [str(pattern).strip() for pattern in (include or []) if str(pattern).strip()]
    if not patterns and not all_files:
        raise HFError("choose files with --include PATTERN or pass --all")
    executable = hf_cli or hf_cli_path()
    if not executable:
        raise HFError("the `hf` CLI is not installed; run `brew install hf`")
    command = [executable, "download", repo]
    if repo_type == "dataset":
        command.extend(["--repo-type", "dataset"])
    destination = (
        Path(local_dir).expanduser() if local_dir else default_download_dir(repo, repo_type)
    )
    command.extend(["--local-dir", str(destination)])
    if cache_dir:
        command.extend(["--cache-dir", str(Path(cache_dir).expanduser())])
    for pattern in patterns:
        if pattern.startswith("-"):
            raise HFError("an include pattern cannot start with '-'")
        command.extend(["--include", pattern])
    for pattern in exclude or []:
        value = str(pattern).strip()
        if not value:
            continue
        if value.startswith("-"):
            raise HFError("an exclude pattern cannot start with '-'")
        command.extend(["--exclude", value])
    if max_workers:
        workers = int(max_workers)
        if not 1 <= workers <= 32:
            raise HFError("--max-workers must be between 1 and 32")
        command.extend(["--max-workers", str(workers)])
    if revision:
        value = str(revision).strip()
        if not value or value.startswith("-"):
            raise HFError("invalid revision")
        command.extend(["--revision", value])
    if dry_run:
        command.append("--dry-run")
    return command


def download_model(
    repo_id: str,
    *,
    repo_type: str = "model",
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    all_files: bool = False,
    revision: str | None = None,
    local_dir: Path | str | None = None,
    cache_dir: Path | str | None = None,
    max_workers: int | None = None,
    dry_run: bool = False,
    token: str | None = None,
) -> tuple[Path, list[str]]:
    """Download a repository through ``hf``, resuming when files already exist."""
    repo = validate_repo_id(repo_id)
    repo_type = _validate_repo_type(repo_type)
    destination = (
        Path(local_dir).expanduser() if local_dir else default_download_dir(repo, repo_type)
    )
    command = build_download_command(
        repo,
        repo_type=repo_type,
        include=include,
        exclude=exclude,
        all_files=all_files,
        revision=revision,
        local_dir=destination,
        cache_dir=cache_dir,
        max_workers=max_workers,
        dry_run=dry_run,
    )
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    token = _clean_token(token)
    if token:
        env.setdefault("HF_TOKEN", token)
    try:
        result = subprocess.run(command, env=env, check=False)
    except OSError as exc:
        raise HFError(f"could not start hf: {exc}") from exc
    if result.returncode != 0:
        raise HFError(f"hf download exited with status {result.returncode}")
    return destination, command


def directory_size(path: Path) -> int:
    """Bytes in ``path`` without counting symlinked snapshot files twice.

    Hugging Face keeps the real LFS blobs in ``blobs/`` and exposes them as
    symlinks under ``snapshots/``. ``Path.stat()`` follows those links, which
    made the cache look twice as large. ``lstat`` plus ``followlinks=False``
    counts the bytes that actually occupy the disk.
    """
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            file_path = Path(dirpath) / name
            try:
                info = file_path.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            total += info.st_size
    return total


def local_repos(repo_type: str | None = None) -> list[LocalHFModel]:
    """List visible downloads and Hub cache entries, models first."""
    kinds = (repo_type,) if repo_type else REPO_TYPES
    rows: list[LocalHFModel] = []
    for kind in kinds:
        kind = _validate_repo_type(kind)
        root = DOWNLOAD_ROOT if kind == "model" else DATASET_DOWNLOAD_ROOT
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                rows.append(_local_row(child, child.name.replace("--", "/", 1), "download", kind))
        cache = hub_cache_dir()
        prefix = "models--" if kind == "model" else "datasets--"
        if cache.is_dir():
            for child in sorted(cache.glob(f"{prefix}*")):
                if not child.is_dir() or child.is_symlink():
                    continue
                repo = child.name[len(prefix) :].replace("--", "/", 1)
                rows.append(_local_row(child, repo, "cache", kind))
    return sorted(
        rows,
        key=lambda row: (
            0 if row.repo_type == "model" else 1,
            row.repo_id.lower(),
            row.kind,
        ),
    )


def local_models() -> list[LocalHFModel]:
    """Backwards-compatible model-only view."""
    return local_repos("model")


def local_repo_paths(repo_id: str, repo_type: str = "model") -> list[Path]:
    """Existing local directories for one repository: download and cache."""
    repo = validate_repo_id(repo_id)
    repo_type = _validate_repo_type(repo_type)
    prefix = "models--" if repo_type == "model" else "datasets--"
    candidates = [
        default_download_dir(repo, repo_type),
        hub_cache_dir() / f"{prefix}{repo_slug(repo)}",
    ]
    return [path for path in candidates if path.exists()]


def remove_local(repo_id: str, repo_type: str = "model") -> list[Path]:
    """Delete local downloads and cache for one repository, safely.

    Only paths directly under the configured download root or the Hub cache
    are removed. Returns the paths that were deleted.
    """
    repo_type = _validate_repo_type(repo_type)
    allowed_roots = [
        DOWNLOAD_ROOT if repo_type == "model" else DATASET_DOWNLOAD_ROOT,
        hub_cache_dir(),
    ]
    removed: list[Path] = []
    for path in local_repo_paths(repo_id, repo_type):
        if not _is_within(path, allowed_roots):
            continue
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(path)
    return removed


def _is_within(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def _local_row(path: Path, repo_id: str, kind: str, repo_type: str = "model") -> LocalHFModel:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        modified = ""
    return LocalHFModel(
        repo_id=repo_id,
        path=path,
        kind=kind,
        bytes=directory_size(path),
        modified=modified,
        repo_type=repo_type,
    )


def is_split_gguf(path: Path | str) -> bool:
    """True for one part of a multi-file GGUF (Ollama needs a single file)."""
    return bool(SPLIT_GGUF_RE.search(Path(path).name))


def quant_label(path: Path | str) -> str:
    """Extract a quantization tag such as ``q4_k_m`` from a GGUF filename."""
    match = QUANT_RE.search(Path(path).stem)
    if not match:
        return ""
    return match.group(1).lower().replace("-", "_").replace(".", "_")


def ollama_model_name(repo_id: str, gguf_path: Path | str) -> str:
    """Derive an Ollama-safe ``name:tag`` from a repository and file name."""
    base = str(repo_id).split("/")[-1]
    base = re.sub(r"[-_.]?gguf$", "", base, flags=re.IGNORECASE)
    base = re.sub(
        r"[-_.](?:iq|q)\d+(?:_[a-z0-9]+)*$",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-_.")
    if not base:
        base = "hf-model"
    base = base[:60].strip("-_.").lower()
    quant = quant_label(gguf_path)
    return f"{base}:{quant}" if quant else f"{base}:latest"


def valid_ollama_name(name: str) -> bool:
    return bool(OLLAMA_NAME_RE.fullmatch(str(name or "").strip()))


def modelfile_text(gguf_path: Path | str, context: int | None = None) -> str:
    """A minimal Ollama Modelfile pointing at one GGUF file."""
    source = str(Path(gguf_path).expanduser().resolve())
    if " " in source:
        source = f'"{source}"'
    lines = [f"FROM {source}"]
    if context:
        lines.append(f"PARAMETER num_ctx {int(context)}")
    return "\n".join(lines) + "\n"
