"""Test isolation.

The package resolves its storage layout from the environment **at import
time**: ``sovereign_code.config`` reads ``SOVEREIGN_HOME`` and friends when
the module is first imported, and several modules create their SQLite
indexes or write their logs as they are imported.

Without this file the test suite read and wrote the developer's real
installation: it created ``~/Documents/local-ai/data/response_cache.db``,
and it opened the 471 MB skill index — which, now that the index migrates
itself on first open, meant every test run paid a full FTS rebuild.

pytest loads ``conftest.py`` before it imports any test module, so setting
the environment here is early enough.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# A per-session scratch directory, removed when the session ends.
_SESSION_ROOT = Path(tempfile.mkdtemp(prefix="sovereign-tests-"))

# Every path the package writes to is redirected into the scratch tree.
os.environ["SOVEREIGN_HOME"] = str(_SESSION_ROOT / "home")
os.environ["SOVEREIGN_CONFIG_DIR"] = str(_SESSION_ROOT / "home" / "config" / "sovereign")
os.environ["SOVEREIGN_DATA_DIR"] = str(_SESSION_ROOT / "home" / "data")

# The project root still points at the checkout, so the skills corpus and
# the docs are found; only the writable state is redirected.
os.environ.setdefault("SOVEREIGN_PROJECT_ROOT", str(Path(__file__).resolve().parents[1]))


def pytest_sessionfinish(session, exitstatus) -> None:
    """Remove the scratch tree once the session is over."""
    shutil.rmtree(_SESSION_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _close_global_disk_cache():
    """Reset the lazy global disk cache so tests do not leak its connection."""
    yield
    from sovereign_code.cache import _close_disk_cache

    _close_disk_cache()
    # Force cleanup of any objects whose __del__ closes sqlite connections,
    # so the next test does not inherit their ResourceWarning.
    import gc

    gc.collect()


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    """A Codex home with the local profile the launcher expects.

    ``plan_launch`` refuses to build a Codex plan without a local config,
    because it would otherwise launch Codex against the user's cloud
    account. With the storage redirected into the scratch tree the config
    does not exist, so the tests that need a Codex plan ask for this.
    """
    from sovereign_code.clients import codex_home_path

    home = codex_home_path()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text('model = "best"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home
