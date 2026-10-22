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
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .config import LOCAL_AI_ROOT
from .stats import dir_size, human_size

DEFAULT_ENDPOINT = "https://huggingface.co"
DOWNLOAD_ROOT = LOCAL_AI_ROOT / "models" / "huggingface"
TOKEN_ENV_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


class HFError(RuntimeError):
    """A Hugging Face operation failed in a way the CLI can explain."""


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

    @property
    def gguf(self) -> bool:
        return "gguf" in {tag.lower() for tag in self.tags}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "downloads": self.downloads,
            "likes": self.likes,
            "pipeline_tag": self.pipeline_tag,
            "tags": list(self.tags),
            "gguf": self.gguf,
            "gated": self.gated,
            "private": self.private,
            "updated": self.updated,
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

    @property
    def total_file_size(self) -> int:
        return sum(item.size for item in self.files)

    @property
    def gguf_files(self) -> tuple[HFFile, ...]:
        return tuple(item for item in self.files if item.gguf)

    def to_dict(self, include_files: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
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
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
    try:
        path.chmod(0o600)
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


def validate_repo_id(repo_id: str) -> str:
    value = str(repo_id or "").strip()
    if not REPO_ID_RE.fullmatch(value):
        raise HFError("expected a repository id like `org/model`")
    return value


def repo_slug(repo_id: str) -> str:
    return validate_repo_id(repo_id).replace("/", "--")


def default_download_dir(repo_id: str) -> Path:
    return DOWNLOAD_ROOT / repo_slug(repo_id)


def _client(transport: httpx.BaseTransport | None = None, timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=5.0),
        follow_redirects=True,
        transport=transport,
    )


def _request_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 20.0,
) -> Any:
    url = f"{endpoint()}{path}"
    headers = {"Accept": "application/json", "User-Agent": "sovereign-code"}
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
    try:
        return response.json()
    except ValueError as exc:
        raise HFError("Hugging Face returned invalid JSON") from exc


def _gated_label(value: Any) -> str:
    if value is True:
        return "gated"
    if value in ("auto", "manual"):
        return str(value)
    return "gated" if value else ""


def _updated(item: dict[str, Any]) -> str:
    raw = item.get("lastModified") or item.get("created_at") or item.get("createdAt") or ""
    return str(raw)[:10]


def _model_from_api(item: dict[str, Any]) -> HFModel:
    return HFModel(
        id=str(item.get("id") or ""),
        downloads=int(item.get("downloads") or 0),
        likes=int(item.get("likes") or 0),
        pipeline_tag=str(item.get("pipeline_tag") or ""),
        tags=tuple(str(tag) for tag in (item.get("tags") or ())),
        gated=_gated_label(item.get("gated")),
        private=bool(item.get("private")),
        updated=_updated(item),
    )


def _file_from_api(item: dict[str, Any]) -> HFFile:
    lfs = item.get("lfs") if isinstance(item.get("lfs"), dict) else {}
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
) -> list[HFModel]:
    """Search the public Hub. A token adds private and gated results."""
    params: dict[str, Any] = {
        "limit": max(1, min(int(limit), 100)),
        "sort": sort,
        "direction": -1,
    }
    needle = str(query or "").strip()
    if needle:
        params["search"] = needle
    if gguf_only:
        params["filter"] = "gguf"
    if author:
        params["author"] = author.strip()
    data = _request_json("/api/models", params=params, token=token, transport=transport)
    if not isinstance(data, list):
        raise HFError("Hugging Face returned an unexpected search response")
    return [_model_from_api(item) for item in data if isinstance(item, dict)]


def info_model(
    repo_id: str,
    *,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> HFModelInfo:
    repo = validate_repo_id(repo_id)
    data = _request_json(
        f"/api/models/{quote(repo, safe='/')}",
        params={"blobs": "true"},
        token=token,
        transport=transport,
    )
    if not isinstance(data, dict):
        raise HFError("Hugging Face returned an unexpected model response")
    files = tuple(
        _file_from_api(item) for item in (data.get("siblings") or ()) if isinstance(item, dict)
    )
    gguf = data.get("gguf") if isinstance(data.get("gguf"), dict) else {}
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
    )


def build_download_command(
    repo_id: str,
    *,
    include: list[str] | None = None,
    all_files: bool = False,
    revision: str | None = None,
    local_dir: Path | str | None = None,
    cache_dir: Path | str | None = None,
    dry_run: bool = False,
    hf_cli: str | None = None,
) -> list[str]:
    """Build an ``hf download`` argv without putting a token in it."""
    repo = validate_repo_id(repo_id)
    patterns = [str(pattern).strip() for pattern in (include or []) if str(pattern).strip()]
    if not patterns and not all_files:
        raise HFError("choose files with --include PATTERN or pass --all")
    executable = hf_cli or hf_cli_path()
    if not executable:
        raise HFError("the `hf` CLI is not installed; run `brew install hf`")
    command = [executable, "download", repo]
    destination = Path(local_dir).expanduser() if local_dir else default_download_dir(repo)
    command.extend(["--local-dir", str(destination)])
    if cache_dir:
        command.extend(["--cache-dir", str(Path(cache_dir).expanduser())])
    for pattern in patterns:
        if pattern.startswith("-"):
            raise HFError("an include pattern cannot start with '-'")
        command.extend(["--include", pattern])
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
    include: list[str] | None = None,
    all_files: bool = False,
    revision: str | None = None,
    local_dir: Path | str | None = None,
    cache_dir: Path | str | None = None,
    dry_run: bool = False,
    token: str | None = None,
) -> tuple[Path, list[str]]:
    """Download a repository through ``hf``, resuming when files already exist."""
    repo = validate_repo_id(repo_id)
    destination = Path(local_dir).expanduser() if local_dir else default_download_dir(repo)
    command = build_download_command(
        repo,
        include=include,
        all_files=all_files,
        revision=revision,
        local_dir=destination,
        cache_dir=cache_dir,
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


def local_models() -> list[LocalHFModel]:
    """List visible downloads and the standard Hub cache, largest last."""
    rows: list[LocalHFModel] = []
    if DOWNLOAD_ROOT.is_dir():
        for child in sorted(DOWNLOAD_ROOT.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            rows.append(_local_row(child, child.name.replace("--", "/", 1), "download"))
    cache = hub_cache_dir()
    if cache.is_dir():
        for child in sorted(cache.glob("models--*")):
            if not child.is_dir():
                continue
            repo = child.name[len("models--") :].replace("--", "/", 1)
            rows.append(_local_row(child, repo, "cache"))
    return sorted(rows, key=lambda row: (row.repo_id.lower(), row.kind))


def _local_row(path: Path, repo_id: str, kind: str) -> LocalHFModel:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        modified = ""
    return LocalHFModel(
        repo_id=repo_id,
        path=path,
        kind=kind,
        bytes=dir_size(path),
        modified=modified,
    )
