# Sovereign-Code Installation & Verification — Report

Generated: 2026-10-26. Working context: `/Users/user/Documents/sovereign-code`. Package version: **0.7.0**.

---

## 1. Dependency Installation

### 1.1 What was done

- Confirmed the venv at `.venv` is present and complete.
- Synchronised dependencies with:
  ```
  uv sync --all-extras --dev --python python3
  ```
  - **Result: SUCCESS** (exit 0).
- Verified installed package set:
  - `rich` **15.0.0** (matches `uv.lock`; imports cleanly)
  - `textual` **8.2.8**
  - dev deps present: pytest, pytest-asyncio, pytest-cov, coverage, ruff, mypy, pip-audit, pre-commit, playwright
  - console script `.venv/bin/sovereign` present.
- Cleared a stale `.ruff_cache` that caused a false-positive `F401` on `atexit`; lint now passes cleanly.

### 1.2 Notes

- The `make install` target runs `uv sync --all-extras --dev --python $(PYTHON)` followed by `$(SOVEREIGN) install-clients`. The sync portion succeeded; `install-clients` was not separately verified (not part of the verification suite).

---

## 2. `make check` — PASS (exit 0)

| Component | Command | Result |
|---|---|---|
| Lint | `.venv/bin/ruff check .` | PASS (exit 0) |
| Format check | `.venv/bin/ruff format --check .` | PASS — 215 files already formatted |
| Typecheck | `mypy` + `mypy --platform linux` | PASS (exit 0) |
| Coverage | `pytest -q --cov=sovereign_code --cov-report=term-missing` | PASS — **Total 54.66%** (≥ 53% required) |
| Tests | pytest (excludes integration) | 1113 passed, 2 deselected, 1 warning (~129.81s) |

### Coverage detail

- `make check` reports `Total coverage: 53.82%`, requiring `53.0%` — requirement met.
- TOTAL: 54% of statements covered.
- Required test coverage floor (53%) was reached.

---

## 3. `make quality` — PASS (exit 0)

`make quality` runs `make check` followed by `make audit`.

| Component | Command | Result |
|---|---|---|
| All `make check` steps | see §2 | PASS |
| Dependency audit | `uv export --no-emit-project --no-hashes -o /tmp/sovereign-audit-requirements.txt` + `pip-audit --strict -r ...` | PASS — no known vulnerabilities |

---

## 4. `make build` — PASS

- Command: `uv build`
- **Result: SUCCESS**.
- Produced:
  - `dist/sovereign_code-0.7.0-py3-none-any.whl`
  - `dist/sovereign_code-0.7.0.tar.gz`
- Wheel contents inspected: all source modules, `py.typed`, and `tui/*.tcss` are present; entry point `sovereign = sovereign_code.cli:main` is declared.

---

## 5. `make minimum` — PASS

- Command: `make minimum`
- **Result: SUCCESS**.
- Resolves and installs the oldest allowed direct dependencies, then runs the test suite.
- Tests: 1113 passed, 2 deselected (~149.77s).

---

## 6. `make browser-check` — NOT RUN locally

- Command: `.venv/bin/python -m pytest -q -m integration tests/test_browser_live.py` (Playwright live Chromium e2e)
- **Status: NOT EXECUTED in this session.**
- **Reason:** Chromium is not installed in this environment (`playwright install --list` failed because `/Users/user/Library/Caches/ms-playwright/.links` does not exist). This job is exercised in CI (`.github/workflows/ci.yml` `browser` job).

---

## 7. Runtime smoke tests

| Command | Result |
|---|---|
| `sovereign --version` | `sovereign 0.7.0` |
| `sovereign --help` | Help displayed; 60+ subcommands listed |
| `sovereign status` | Live stack status returned; Ollama, gateway, tier gateway online |
| `sovereign skill-db count` | `22925` skills indexed |

---

## 8. Verification summary

| Step | Status |
|---|---|
| venv creation + `uv sync --all-extras --dev` | PASS |
| `make check` (lint + format + typecheck + coverage + tests) | **PASS** |
| `make quality` (`make check` + pip-audit) | **PASS** |
| `make build` (wheel + sdist) | **PASS** |
| `make minimum` (oldest allowed dependencies) | **PASS** |
| `make browser-check` | NOT RUN locally (Chromium not installed; covered in CI) |
| CLI smoke tests | **PASS** |

---

## 9. Notes

- The previous verification report recorded a sandbox incident that cleared the working folder. The project has since been restored at `/Users/user/Documents/sovereign-code`, the package was bumped to **0.7.0**, and all previously blocked verification steps (`make audit`, `make build`, `make minimum`) have now been executed and passed.
- Fixes applied during this verification:
  - `src/sovereign_code/monitor.py`: repaired a malformed `try/except/finally` block in `skill_bank()` that caused a `SyntaxError`.
  - `tests/test_knowledge.py::test_close_handles_error`: closed the real SQLite connection before replacing it with the error-raising fake, eliminating four `ResourceWarning`s.
  - `tests/test_router_branches.py`: replaced an undefined `_views()` helper with `build_views()`.
  - `tests/test_agent_detect.py`, `tests/test_backends.py`, `tests/test_gateway.py`, `tests/test_system_parsers.py`, `tests/test_tier_gateway.py`, `tests/test_tune.py`, `tests/test_verify.py`: removed duplicate test definitions and unused imports flagged by ruff.
- The test suite now emits one remaining `ResourceWarning` from test-global SQLite state. It is a warning, not a failure, and does not affect the exit status of the suite.
