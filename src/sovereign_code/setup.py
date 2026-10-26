"""One-command, self-contained setup for the whole local stack.

The goal is that ``sovereign setup`` is the only command a new machine needs:
it puts every runtime file inside this checkout, migrates an older
``~/Documents/local-ai`` install without duplicating gigabytes of model
weights, checks Ollama, creates the gateway configuration and venv, installs
the model stack, writes every client integration, and installs the login
services.

Nothing here is destructive unless the user asked for it. Every step reports a
row so a dry run shows exactly what would happen.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import config
from .http import shared_client
from .system import system_binary

DEFAULT_STACK = ("qwen3.5:4b", "qwen2.5-coder:14b", "gemma4:12b", "nomic-embed-text")
# Rough installed size, used before anything is downloaded.
STACK_SIZES_GB = {
    "qwen3.5:4b": 3.3,
    "qwen2.5-coder:14b": 9.0,
    "gemma4:12b": 7.7,
    "nomic-embed-text": 0.3,
    "qwen2.5-coder:7b": 4.7,
    "qwen3-coder:30b": 19.0,
    "qwen3.8:27b": 18.0,
}


@dataclass(frozen=True)
class Step:
    name: str
    ok: bool
    detail: str
    skipped: bool = False

    @property
    def mark(self) -> str:
        if self.skipped:
            return "skip"
        return "ok" if self.ok else "fail"


def runtime_target() -> Path:
    """Where the checkout keeps its own state."""
    return getattr(config, "RUNTIME_ROOT", config.PROJECT_ROOT / "runtime")


def legacy_root() -> Path:
    return getattr(
        config,
        "LEGACY_LOCAL_AI_ROOT",
        Path.home() / "Documents" / "local-ai",
    )


def root_is_self_contained() -> bool:
    try:
        return config.LOCAL_AI_ROOT.resolve() == runtime_target().resolve()
    except OSError:
        return False


# ------------------------------------------------------------------ migrate


def _stop_services() -> list[str]:
    """Stop the launchd jobs so their files can be renamed safely."""
    rows: list[str] = []
    try:
        from . import services

        for service in services.service_definitions():
            try:
                services.unload_service(service)
                rows.append(service.name)
            except Exception:
                continue
    except Exception:
        return rows
    return rows


def migrate_legacy(
    *,
    dry_run: bool = False,
    stop_services: bool = True,
) -> Step:
    """Move ``~/Documents/local-ai`` into the checkout and leave a symlink.

    The rename is atomic and instantaneous on the same volume. The old path is
    replaced by a symlink so an already-installed launch agent or shell alias
    keeps working until setup rewrites it. Nothing is copied, so the 91 GB
    model store is not duplicated.
    """
    target = runtime_target()
    legacy = legacy_root()
    if target.exists():
        return Step("runtime", True, f"already in {target}", skipped=True)
    if not legacy.exists() or legacy.is_symlink():
        return Step("runtime", True, f"fresh install at {target}", skipped=True)
    if dry_run:
        return Step("runtime", True, f"would move {legacy} → {target} and leave a symlink")
    stopped = _stop_services() if stop_services else []
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(target)
        try:
            legacy.symlink_to(target, target_is_directory=True)
        except OSError:
            # The move succeeded; a missing compatibility link is not fatal.
            pass
        detail = f"moved {legacy} → {target}"
        if stopped:
            detail += f" · stopped {len(stopped)} service(s)"
        return Step("runtime", True, detail)
    except OSError as exc:
        return Step("runtime", False, f"could not move {legacy}: {exc}")


# ------------------------------------------------------------------- ollama


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        response = shared_client().get(url.rstrip("/") + "/api/version", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def ensure_layout(*, dry_run: bool = False) -> Step:
    dirs = [
        config.LOCAL_AI_ROOT / "config" / "sovereign",
        config.LOCAL_AI_ROOT / "config" / "skills",
        config.LOCAL_AI_ROOT / "data" / "logs",
        config.LOCAL_AI_ROOT / "data" / "sessions",
        config.LOCAL_AI_ROOT / "data" / "runs",
        config.LOCAL_AI_ROOT / "gateway",
        config.LOCAL_AI_ROOT / "bin",
        config.LOCAL_AI_ROOT / "models",
    ]
    if dry_run:
        return Step(
            "layout", True, f"would create {len(dirs)} directories under {config.LOCAL_AI_ROOT}"
        )
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
    path = Path(config.CONFIG_DIR) / "config.toml"
    if not path.is_file():
        config.write_default_config()
    return Step("layout", True, f"{config.LOCAL_AI_ROOT}")


def check_ollama(settings: config.Settings, *, dry_run: bool = False) -> Step:
    if _http_ok(settings.ollama_url):
        return Step("ollama", True, f"serving at {settings.ollama_url}")
    binary = system_binary("ollama")
    if not binary:
        return Step(
            "ollama",
            False,
            "not installed — run: brew install ollama",
        )
    if dry_run:
        return Step("ollama", True, "would start the local model server")
    subprocess.run(["open", "-a", "Ollama"], check=False, capture_output=True)
    for _ in range(30):
        if _http_ok(settings.ollama_url):
            return Step("ollama", True, f"started at {settings.ollama_url}")
        time.sleep(1)
    return Step(
        "ollama",
        False,
        "installed but not serving — run: ollama serve",
    )


def ensure_gateway(*, dry_run: bool = False) -> Step:
    """Create the LiteLLM config and venv the gateway service needs."""
    root = config.LOCAL_AI_ROOT / "gateway"
    config_path = root / "config.yaml"
    litellm = root / "venv" / "bin" / "litellm"
    if not config_path.is_file():
        if dry_run:
            return Step("gateway", True, f"would write {config_path} and install litellm[proxy]")
        root.mkdir(parents=True, exist_ok=True)
        from .gateway_config import write as write_gateway_config

        write_gateway_config(path=config_path)
    if litellm.is_file():
        return Step("gateway", True, f"LiteLLM ready · {config_path}")
    if dry_run:
        return Step("gateway", True, "would create gateway/venv and install litellm[proxy]")
    venv = root / "venv"
    try:
        venv.parent.mkdir(parents=True, exist_ok=True)
        if not (venv / "bin" / "python3").is_file():
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        python = venv / "bin" / "python3"
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "litellm[proxy]"],
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Step("gateway", False, f"LiteLLM install failed: {exc}")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-1:]
        return Step(
            "gateway",
            False,
            "LiteLLM install failed" + (f": {tail[0]}" if tail else ""),
        )
    return Step("gateway", True, f"LiteLLM installed · {config_path}")


# ------------------------------------------------------------------- models


def _installed_tags(settings: config.Settings) -> set[str]:

    try:
        response = shared_client().get(settings.ollama_url.rstrip("/") + "/api/tags", timeout=3.0)
        data = response.json()
    except Exception:
        return set()
    return {str(item.get("name") or "") for item in data.get("models", [])}


def missing_models(settings: config.Settings, stack: tuple[str, ...] | None = None) -> list[str]:
    installed = {item.removesuffix(":latest") for item in _installed_tags(settings)}
    wanted = stack or DEFAULT_STACK
    return [tag for tag in wanted if tag.removesuffix(":latest") not in installed]


def pull_models(
    settings: config.Settings,
    stack: tuple[str, ...] | None = None,
    *,
    yes: bool = False,
    dry_run: bool = False,
) -> Step:
    missing = missing_models(settings, stack)
    if not missing:
        return Step("models", True, "the role stack is already installed", skipped=True)
    size = sum(STACK_SIZES_GB.get(tag, 0.0) for tag in missing)
    label = ", ".join(missing) + (f" · ~{size:.0f} GB" if size else "")
    if dry_run:
        return Step("models", True, f"would pull {label}")
    if not yes:
        if not sys.stdin.isatty():
            return Step("models", False, f"missing {label}; re-run with --yes")
        answer = input(f"Download {label}? [Y/n] ").strip().lower()
        if answer not in {"", "y", "yes"}:
            return Step("models", True, f"skipped {label}", skipped=True)
    failures: list[str] = []
    for tag in missing:
        result = subprocess.run(
            [sys.executable, "-m", "sovereign_code", "pull", tag],
            check=False,
        )
        if result.returncode != 0:
            failures.append(tag)
    if failures:
        return Step("models", False, "could not pull " + ", ".join(failures))
    return Step("models", True, "installed " + ", ".join(missing))


# ------------------------------------------------------------------ clients


def install_clients(*, dry_run: bool = False) -> Step:
    if dry_run:
        return Step("clients", True, "would write Codex/OpenCode/Continue/Claude configs")
    result = subprocess.run(
        [sys.executable, "-m", "sovereign_code", "install-clients"],
        check=False,
    )
    if result.returncode != 0:
        return Step("clients", False, "install-clients failed — see the output above")
    return Step("clients", True, "client configs and wrappers written")


def install_services(settings: config.Settings, *, dry_run: bool = False) -> Step:
    if dry_run:
        return Step("services", True, "would install the gateway, tier gateway and bridge")
    try:
        from . import services

        rows = services.install_services(settings)
        env = services.set_session_env(settings)
    except Exception as exc:
        return Step("services", False, f"service install failed: {exc}")
    failed = [name for name, result in rows if "could not" in result]
    if failed:
        return Step("services", False, "not loaded: " + ", ".join(failed))
    return Step(
        "services",
        True,
        f"{len(rows)} service(s) installed · {', '.join(sorted(env))}",
    )


def install_login(*, dry_run: bool = False) -> Step:
    if dry_run:
        return Step("login", True, "would open the monitor in Terminal at login")
    result = subprocess.run(
        [sys.executable, "-m", "sovereign_code", "install-login"],
        check=False,
    )
    if result.returncode != 0:
        return Step("login", False, "login agent was not installed")
    return Step("login", True, "Terminal opens the live monitor at login")


# --------------------------------------------------------------------- all


def run_setup(
    settings: config.Settings,
    *,
    models: str = "recommended",
    yes: bool = False,
    clients: bool = True,
    services: bool = True,
    login: bool = True,
    migrate: bool = True,
    dry_run: bool = False,
) -> list[Step]:
    """Run every step in order, returning one row per step."""
    from .models import MODEL_STACKS

    rows: list[Step] = []
    if migrate:
        rows.append(migrate_legacy(dry_run=dry_run))
    rows.append(ensure_layout(dry_run=dry_run))
    rows.append(check_ollama(settings, dry_run=dry_run))
    rows.append(ensure_gateway(dry_run=dry_run))

    stack: tuple[str, ...] | None
    if models == "none":
        stack = ()
    elif models in MODEL_STACKS:
        stack = tuple(str(tag) for tag in cast(list[Any], MODEL_STACKS[models]["models"]))
    else:
        stack = DEFAULT_STACK
    if stack:
        rows.append(pull_models(settings, stack, yes=yes, dry_run=dry_run))
    else:
        rows.append(Step("models", True, "not requested", skipped=True))

    if clients:
        rows.append(install_clients(dry_run=dry_run))
    else:
        rows.append(Step("clients", True, "not requested", skipped=True))
    if services:
        rows.append(install_services(settings, dry_run=dry_run))
    else:
        rows.append(Step("services", True, "not requested", skipped=True))
    if login:
        rows.append(install_login(dry_run=dry_run))
    else:
        rows.append(Step("login", True, "not requested", skipped=True))
    return rows


def ready_summary() -> list[str]:
    """The commands to show once setup has finished."""
    return [
        "sovereign                   live monitor (models, downloads, runs)",
        "sovereign harness           role plan + resident models right now",
        'sovereign orchestrate "…"    plan → implement → verify → review',
        "sovereign chat              opt-in streaming chat",
        "sovereign code [path]       hand the project to the local agent",
        "sovereign status            one-shot health check",
    ]


__all__ = [
    "DEFAULT_STACK",
    "Step",
    "check_ollama",
    "ensure_gateway",
    "ensure_layout",
    "install_clients",
    "install_login",
    "install_services",
    "legacy_root",
    "migrate_legacy",
    "missing_models",
    "pull_models",
    "ready_summary",
    "root_is_self_contained",
    "run_setup",
    "runtime_target",
]
