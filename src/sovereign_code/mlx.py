"""Apple Silicon MLX backend helpers.

MLX models are served by Apple's ``mlx-lm`` OpenAI-compatible server on
loopback, separately from Ollama. This module is the single place that knows
where that server lives, which MLX models exist, and which stable aliases a
coding client may ask for, so the tier gateway, client writers, dashboard and
doctor all agree.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from .models import CATALOG, MLX_PREFERENCE, ModelView, mlx_installed_tags

DEFAULT_MLX_URL = "http://127.0.0.1:8081"
DEFAULT_MLX_PORT = 8081

# How long a freshly started server may take to download/load weights before
# the guardian treats "not answering yet" as a failure.
START_GRACE = 1800.0

# How long a liveness probe is trusted. The dashboard refreshes every few
# seconds, and this keeps it from opening a socket on every widget tick.
PROBE_TTL = 10.0

# Stable aliases exposed by the tier gateway and the client configs. Every
# alias maps to a task preference list; the first installed/served MLX model
# wins, so a client can keep one name while the weights underneath change.
MLX_ALIASES: dict[str, str] = {
    "mlx": "code",
    "mlx-code": "code",
    "mlx-fast": "fast",
    "mlx-balanced": "code",
    "mlx-chat": "chat",
    "mlx-reason": "reason",
    "mlx-agent": "agent",
    "local-mlx": "code",
    "local-mlx-code": "code",
    "local-mlx-fast": "fast",
    "local-mlx-chat": "chat",
}

# The alias a client should use for each role.
ROLE_ALIASES: dict[str, str] = {
    "code": "mlx-code",
    "fast": "mlx-fast",
    "chat": "mlx-chat",
    "reason": "mlx-reason",
    "agent": "mlx-agent",
}

_ONLINE_CACHE: tuple[float, bool, tuple[str, ...]] | None = None
_INSTALLED_CACHE: tuple[float, tuple[str, ...]] | None = None
INSTALLED_TTL = 30.0


def mlx_url() -> str:
    """Loopback URL of the MLX server, including the OpenAI ``/v1`` suffix."""
    return os.environ.get("SOVEREIGN_MLX_URL", DEFAULT_MLX_URL).rstrip("/")


def mlx_port() -> int:
    text = mlx_url()
    match = re.search(r":(\d+)(?:/|$)", text)
    return int(match.group(1)) if match else DEFAULT_MLX_PORT


def disabled() -> bool:
    return os.environ.get("SOVEREIGN_MLX_DISABLE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def catalog_tags() -> tuple[str, ...]:
    """Every MLX model in the curated catalog, strongest first per task."""
    seen: dict[str, None] = {}
    for preference in MLX_PREFERENCE.values():
        for tag in preference:
            seen.setdefault(tag, None)
    for tag in CATALOG:
        if tag.startswith("mlx-"):
            seen.setdefault(tag, None)
    return tuple(seen)


def installed_tags(refresh: bool = False) -> tuple[str, ...]:
    """MLX catalog tags whose weights are already downloaded.

    Scanning the Hugging Face download tree is cheap but not free, and the
    dashboard and the gateway model list both ask for it on a timer. The
    result is cached briefly; a new download is visible within 30 seconds.
    """
    global _INSTALLED_CACHE
    now = time.monotonic()
    if not refresh and _INSTALLED_CACHE and now - _INSTALLED_CACHE[0] < INSTALLED_TTL:
        return _INSTALLED_CACHE[1]
    found = tuple(mlx_installed_tags())
    _INSTALLED_CACHE = (now, found)
    return found


def _normalize(name: str) -> str:
    text = name.lower().replace("--", "/")
    if "/" in text:
        text = text.split("/", 1)[1]
    return re.sub(r"[^a-z0-9]", "", text)


_TAG_HINTS: dict[str, str] = {
    "mlx-qwen3-4b-4bit": "qwen34b",
    "mlx-qwen3-8b-4bit": "qwen38b",
    "mlx-qwen3-14b-4bit": "qwen314b",
    "mlx-qwen2.5-coder-7b-4bit": "qwen25coder7b",
    "mlx-llama-3.1-8b-instruct-4bit": "llama318binstruct",
}

# Hugging Face repositories `sovereign mlx start` can load when the weights
# are not downloaded yet. mlx-lm downloads them on first use.
REPO_IDS: dict[str, str] = {
    "mlx-qwen3-4b-4bit": "mlx-community/Qwen3-4B-4bit",
    "mlx-qwen3-8b-4bit": "mlx-community/Qwen3-8B-4bit",
    "mlx-qwen3-14b-4bit": "mlx-community/Qwen3-14B-4bit",
    "mlx-qwen2.5-coder-7b-4bit": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "mlx-llama-3.1-8b-instruct-4bit": "mlx-community/Llama-3.1-8B-Instruct-4bit",
}

# A small same-tokenizer model used for speculative decoding. It is only
# enabled when its weights are already downloaded, so starting a model never
# surprises the user with a second download.
DRAFT_REPOS: dict[str, str] = {
    "mlx-qwen3-4b-4bit": "mlx-community/Qwen3-0.6B-4bit",
    "mlx-qwen3-8b-4bit": "mlx-community/Qwen3-0.6B-4bit",
    "mlx-qwen3-14b-4bit": "mlx-community/Qwen3-0.6B-4bit",
}


def local_path(tag: str) -> str:
    """A downloaded weight directory for a catalog tag, if there is one.

    Checks both the visible download folder and the Hugging Face hub cache,
    including the ``snapshots/<revision>`` directory that holds the weights.
    """
    from .hf import DOWNLOAD_ROOT, hub_cache_dir

    hint = _TAG_HINTS.get(tag, "")
    if not hint:
        return ""
    for root in (DOWNLOAD_ROOT, hub_cache_dir()):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or hint not in _normalize(child.name):
                continue
            if child.name.startswith("models--"):
                snapshots = child / "snapshots"
                if not snapshots.is_dir():
                    continue
                for snapshot in sorted(snapshots.iterdir(), reverse=True):
                    if snapshot.is_dir() and any(snapshot.iterdir()):
                        return str(snapshot)
                continue
            return str(child)
    return ""


def start_target(tag: str) -> str:
    """What to pass to ``mlx_lm.server --model`` for a catalog tag."""
    return local_path(tag) or REPO_IDS.get(tag) or tag


def warm(model: str = "", timeout: float = 180.0, wait: float = 0.0) -> bool:
    """Send a one-token completion so Metal kernels and the prompt cache compile.

    The first real request to a freshly loaded mlx-lm server spends several
    seconds compiling. Doing that during/after `start` turns it into a warm
    server instead of a surprise latency spike. ``wait`` retries while the
    server is still downloading/loading and has not published a model yet.
    """
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        if online(refresh=wait > 0):
            available = available_tags()
            tag = model if model in available else _first(MLX_PREFERENCE.get("code", ()), available)
            served = served_models()
            if tag and any(tag_for_served(name) for name in served):
                payload = {
                    "model": forward_model(tag),
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "stream": False,
                }
                try:
                    response = httpx.post(
                        f"{mlx_url()}/v1/chat/completions",
                        json=payload,
                        timeout=httpx.Timeout(timeout, connect=5),
                    )
                except httpx.HTTPError:
                    response = None
                if response is not None and response.status_code == 200:
                    return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)


def _warm_when_ready(model: str, timeout: float = 900.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if online(refresh=True):
            warm(model)
            return
        time.sleep(2.0)


def download_model(
    model: str, python: str | None = None, with_draft: bool = True
) -> tuple[bool, str]:
    """Pre-download a catalog model (and its speculative draft) from the Hub."""
    if model not in REPO_IDS:
        return False, f"{model} is not in the MLX catalog (see: sovereign mlx models)"
    repos = [REPO_IDS[model]]
    if with_draft and model in DRAFT_REPOS:
        draft = DRAFT_REPOS[model]
        if draft not in repos:
            repos.append(draft)
    downloaded: list[str] = []
    for repo in repos:
        if _downloaded(repo):
            downloaded.append(f"{repo} (already present)")
            continue
        command = [
            python or python_executable(),
            "-c",
            (
                "import sys\n"
                "from huggingface_hub import snapshot_download\n"
                "snapshot_download(repo_id=sys.argv[1])\n"
            ),
            repo,
        ]
        try:
            result = subprocess.run(command, check=False)
        except OSError as exc:
            return False, str(exc)
        if result.returncode != 0:
            return False, f"download failed for {repo}"
        downloaded.append(repo)
    reset_probe()
    return True, "downloaded " + ", ".join(downloaded)


def _downloaded(repo: str) -> bool:
    """True when a Hugging Face repo id has a snapshot with weight files."""
    from .hf import DOWNLOAD_ROOT, hub_cache_dir

    marker = repo.replace("/", "--").lower()
    for root in (DOWNLOAD_ROOT, hub_cache_dir()):
        candidate = root / f"models--{marker}"
        if not candidate.is_dir():
            continue
        snapshots = candidate / "snapshots"
        if not snapshots.is_dir():
            continue
        for snapshot in snapshots.iterdir():
            if snapshot.is_dir() and any(snapshot.glob("*.safetensors")):
                return True
    return False


def draft_target(model: str, requested: str | None = None) -> str:
    """The speculative-decoding draft model for a catalog tag, or ``""``.

    ``requested`` comes from ``--draft``/``SOVEREIGN_MLX_DRAFT``. ``auto`` (and
    the default) enables a draft only when it is already on disk. ``off``/``0``
    disables speculative decoding.
    """
    choice = (requested or os.environ.get("SOVEREIGN_MLX_DRAFT") or "auto").strip()
    if choice.lower() in {"0", "off", "false", "no", "none"}:
        return ""
    if choice.lower() == "auto":
        repo = DRAFT_REPOS.get(model, "")
        return repo if repo and _downloaded(repo) else ""
    if choice in REPO_IDS:
        return REPO_IDS[choice]
    return choice


def preferred_start_model() -> str:
    """The strongest downloaded MLX model, or the small default to download."""
    available = set(installed_tags())
    for tag in MLX_PREFERENCE.get("code", ()):
        if tag in available:
            return tag
    return "mlx-qwen3-4b-4bit"


def server_command(
    model: str,
    port: int = DEFAULT_MLX_PORT,
    max_tokens: int = 4096,
    draft: str = "",
    kv_bits: int = 8,
    draft_tokens: int = 4,
    python: str | None = None,
    decode_concurrency: int = 4,
) -> list[str]:
    """Build the ``mlx_lm.server`` argv (separate for testing and logging)."""
    target = start_target(model)
    command = [
        python or python_executable(),
        "-m",
        "mlx_lm.server",
        "--model",
        target,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--max-tokens",
        str(max_tokens),
        "--log-level",
        "WARNING",
    ]
    if draft:
        command.extend(
            [
                "--draft-model",
                draft,
                "--num-draft-tokens",
                str(max(1, int(draft_tokens))),
            ]
        )
    # mlx-lm disables batching when the KV cache is quantized, so the two are
    # an either/or: 0 bits means plain KV plus parallel decode. Measured on
    # Qwen3-4B with the 0.6B draft: four simultaneous 24-token completions
    # finish in 0.95 s with parallel decode and 1.26 s with an 8-bit KV cache.
    if kv_bits:
        command.extend(["--kv-bits", str(max(4, min(8, int(kv_bits))))])
        command.extend(["--prompt-cache-size", "1" if draft else "4"])
    else:
        command.extend(
            [
                "--decode-concurrency",
                str(max(1, int(decode_concurrency))),
                "--prompt-concurrency",
                str(max(1, min(4, int(decode_concurrency)))),
                "--prompt-cache-size",
                "1" if draft else "4",
            ]
        )
    if model.startswith(("mlx-qwen3-", "mlx-qwen2.5-")):
        command.extend(["--chat-template-args", '{"enable_thinking": false}'])
    return command


def tag_for_served(name: str) -> str:
    """Map a server model id (often an HF repo path) to a catalog tag."""
    if name in CATALOG:
        return name
    norm = _normalize(name)
    for tag, hint in _TAG_HINTS.items():
        if hint in norm:
            return tag
    return ""


def probe(timeout: float = 0.6, refresh: bool = False) -> tuple[bool, tuple[str, ...]]:
    """Whether the MLX server answers, and the model ids it serves.

    The answer is cached briefly because callers include the model catalog and
    the dashboard, which are polled far more often than the server changes.
    """
    global _ONLINE_CACHE
    if disabled():
        return False, ()
    now = time.monotonic()
    if not refresh and _ONLINE_CACHE and now - _ONLINE_CACHE[0] < PROBE_TTL:
        return _ONLINE_CACHE[1], _ONLINE_CACHE[2]
    try:
        response = httpx.get(f"{mlx_url()}/v1/models", timeout=timeout)
        response.raise_for_status()
        data = response.json().get("data") or []
        models = tuple(
            str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")
        )
        online = True
    except (httpx.HTTPError, ValueError, AttributeError):
        models = ()
        online = False
    _ONLINE_CACHE = (now, online, models)
    return online, models


def online(refresh: bool = False) -> bool:
    return probe(refresh=refresh)[0]


def served_models(refresh: bool = False) -> tuple[str, ...]:
    return probe(refresh=refresh)[1]


def reset_probe() -> None:
    """Drop the cached probe. Used by tests and after start/stop."""
    global _ONLINE_CACHE, _INSTALLED_CACHE
    _ONLINE_CACHE = None
    _INSTALLED_CACHE = None


def available_tags() -> tuple[str, ...]:
    """Catalog tags that can actually be served right now (weights + server)."""
    if disabled():
        return ()
    live, served = probe()
    on_disk = installed_tags()
    if not live and not on_disk:
        return ()
    found: dict[str, None] = {}
    for tag in on_disk:
        found.setdefault(tag, None)
    for name in served:
        tag = tag_for_served(name)
        if tag:
            found.setdefault(tag, None)
    return tuple(found)


def _first(preference: tuple[str, ...], available: tuple[str, ...]) -> str:
    for tag in preference:
        if tag in available:
            return tag
    return available[0] if available else ""


def resolve_alias(name: str) -> tuple[str, str] | None:
    """Resolve a stable MLX alias to (catalog tag, task).

    Returns ``None`` when there is no MLX model to serve, so callers can fall
    back instead of advertising a route that cannot answer.
    """
    task = MLX_ALIASES.get(name)
    if not task:
        return None
    available = available_tags()
    if not available:
        return None
    return _first(MLX_PREFERENCE.get(task, MLX_PREFERENCE["code"]), available), task


def fast_loaded_tag(max_size_gb: float = 12.0) -> str:
    """The MLX model to use for `fast`, but only if it is already servable.

    A warm MLX model in front of autocomplete avoids a cold Ollama load and
    reuses the speculative-decoding speedup. Any loaded MLX model up to 12 GB
    (4B/8B/14B) is preferred to loading a second engine's model next to it.
    """
    if not online():
        return ""
    available = available_tags()
    if not available:
        return ""
    tag = _first(MLX_PREFERENCE.get("fast", ()), available)
    spec = CATALOG.get(tag)
    return tag if spec and spec.size_gb <= max_size_gb else ""


def resolve_model(name: str) -> tuple[str, str] | None:
    """Resolve an alias or a concrete MLX catalog tag to (tag, task).

    A stable alias resolves even when nothing is downloaded yet, so the tier
    gateway can answer an explicit `mlx-code` request with the start command
    instead of proxying an unknown name to LiteLLM. The model catalog still
    lists MLX only when something can serve it.
    """
    alias = resolve_alias(name)
    if alias is not None:
        return alias
    task = MLX_ALIASES.get(name)
    if task:
        return name, task
    if name in CATALOG and name.startswith("mlx-") and name in available_tags():
        return name, "code"
    return None


def forward_model(tag: str) -> str:
    """The model id to send to the server for a catalog tag.

    ``mlx-lm`` reports the loaded model as the HF repo path it was started
    with. If that path maps to the tag, send it back verbatim so the server
    never sees a name it did not load.
    """
    for served in served_models():
        if tag_for_served(served) == tag:
            return served
    return tag


def context_for(tag: str, default: int = 32768) -> int:
    spec = CATALOG.get(tag)
    return int(spec.max_context) if spec and spec.max_context else default


def views() -> dict[str, ModelView]:
    """ModelView objects for the downloaded MLX tags, cached like the tags."""
    built: dict[str, ModelView] = {}
    for tag in installed_tags():
        spec = CATALOG.get(tag)
        if spec is not None:
            built[tag] = ModelView(spec=spec, installed=True, size_gb=spec.size_gb, runner="mlx")
    return built


def catalog_models() -> list[dict[str, object]]:
    """Model-list entries for every MLX alias and available MLX model.

    Nothing is advertised while the server is offline: a client should not see
    a route that only answers with a 503. `sovereign mlx models` and `status`
    still show downloaded weights.
    """
    if not online():
        return []
    available = available_tags()
    if not available:
        return []
    entries: list[dict[str, object]] = []
    seen: set[str] = set()

    def add(model_id: str, target: str) -> None:
        if model_id in seen:
            return
        seen.add(model_id)
        entries.append(
            {
                "id": model_id,
                "object": "model",
                "owned_by": "mlx",
                "tier": "mlx",
                "model": target,
                "context": context_for(target),
                "installed": True,
            }
        )

    for alias, task in MLX_ALIASES.items():
        target = _first(MLX_PREFERENCE.get(task, MLX_PREFERENCE["code"]), available)
        if target:
            add(alias, target)
    for tag in available:
        add(tag, tag)
    return entries


# --------------------------------------------------------------- server control


def state_path() -> Path:
    from .config import LOCAL_AI_ROOT

    return LOCAL_AI_ROOT / "data" / "mlx-server.json"


def log_path() -> Path:
    from .config import LOCAL_AI_ROOT

    return LOCAL_AI_ROOT / "logs" / "mlx-server.log"


def read_state() -> dict[str, object]:
    """The model/port/PID of the server the user asked us to run."""
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(
    model: str,
    port: int,
    max_tokens: int,
    pid: int,
    target: str,
    draft: str = "",
    kv_bits: int = 8,
    draft_tokens: int = 4,
    decode_concurrency: int = 4,
) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": model,
                "target": target,
                "port": port,
                "max_tokens": max_tokens,
                "pid": pid,
                "started": time.time(),
                "draft": draft,
                "kv_bits": kv_bits,
                "draft_tokens": draft_tokens,
                "decode_concurrency": decode_concurrency,
                "log": str(log_path()),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def clear_state() -> None:
    try:
        state_path().unlink()
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def supervised() -> bool:
    """True when a model was started and should stay up."""
    return bool(read_state().get("model"))


def starting(grace: float = START_GRACE) -> bool:
    """The process is alive and still inside its download/load window."""
    data = read_state()
    try:
        pid = int(str(data.get("pid") or 0))
        started = float(str(data.get("started") or 0))
    except (TypeError, ValueError):
        return False
    return _pid_alive(pid) and (time.time() - started) < grace


def supervised_ok() -> bool:
    """Running, or still inside the load window (so the guardian leaves it)."""
    return online() or starting()


def python_executable() -> str:
    """The interpreter that has mlx-lm, preferring the dedicated venv."""
    explicit = os.environ.get("SOVEREIGN_MLX_PYTHON", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    from .config import LOCAL_AI_ROOT

    candidates = (
        LOCAL_AI_ROOT / "mlx-venv" / "bin" / "python3",
        LOCAL_AI_ROOT / "mlx-venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def module_available(python: str | None = None) -> bool:
    try:
        result = subprocess.run(
            [python or python_executable(), "-c", "import mlx_lm"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def start_server(
    model: str = "mlx-qwen3-4b-4bit",
    port: int = DEFAULT_MLX_PORT,
    max_tokens: int = 4096,
    draft: str | None = None,
    kv_bits: int = 8,
    draft_tokens: int = 4,
    decode_concurrency: int = 4,
    auto_install: bool = False,
) -> tuple[bool, str]:
    """Start mlx-lm detached for a catalog tag. Returns (started, detail)."""
    if disabled():
        return False, "MLX is disabled (SOVEREIGN_MLX_DISABLE=1)"
    if online(refresh=True) and mlx_port() == port:
        return True, "already online"
    python = python_executable()
    if not module_available(python):
        if auto_install:
            import subprocess as _sp

            try:
                result = _sp.run(
                    [python, "-m", "pip", "install", "mlx", "mlx-lm"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except (OSError, _sp.SubprocessError) as exc:
                return False, f"install failed: {exc}"
            if result.returncode != 0:
                return False, (f"mlx-lm install failed: {result.stderr.strip()[:200]}")
        else:
            return False, (
                f"mlx-lm is not installed for {python}; run: {python} -m pip install mlx mlx-lm"
            )
    target = start_target(model)
    draft = draft_target(model, draft)
    # Auto-download the model (and its speculative draft) if the weights are not
    # on disk yet, so `sovereign mlx start` is a single self-contained step.
    if model in REPO_IDS and not local_path(model):
        ok, detail = download_model(model)
        if not ok:
            return False, f"download failed: {detail}"
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = server_command(
        model,
        port,
        max_tokens,
        draft=draft,
        kv_bits=kv_bits,
        draft_tokens=draft_tokens,
        python=python,
        decode_concurrency=decode_concurrency,
    )
    try:
        with log.open("ab") as handle:
            process = subprocess.Popen(
                cmd,
                stdout=handle,
                stderr=handle,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as exc:
        return False, str(exc)
    write_state(
        model,
        port,
        max_tokens,
        process.pid,
        target,
        draft=draft,
        kv_bits=kv_bits,
        draft_tokens=draft_tokens,
        decode_concurrency=decode_concurrency,
    )
    reset_probe()
    threading.Thread(
        target=_warm_when_ready,
        args=(model,),
        name="sovereign-mlx-warm",
        daemon=True,
    ).start()
    display = REPO_IDS.get(model, target)
    if display != target:
        display += " (cached)"
    detail = f"starting {model} → {display} on port {port}"
    if draft:
        detail += f" · speculative draft {draft}"
    return True, detail


def _listener_pids(port: int) -> set[int]:
    try:
        result = subprocess.run(
            ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(line) for line in result.stdout.split() if line.isdigit()}


def stop_server(port: int = DEFAULT_MLX_PORT) -> bool:
    """Stop the server on a port and forget the supervised model."""
    pids = _listener_pids(port)
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            continue
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline and _listener_pids(port):
        time.sleep(0.2)
    for pid in _listener_pids(port):
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    clear_state()
    reset_probe()
    return bool(pids)
