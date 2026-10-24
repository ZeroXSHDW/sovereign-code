# Version Upgrades

A phased, check-gated plan for keeping Sovereign Code's dependency and
toolchain versions current and correct. Unlike `docs/ROADMAP.md` (features),
this file is the ordered list for version work only. Every phase passes
`make check` and `make quality` before it is complete; each phase is one
reviewable, revertible step.

**Scope decision (2026-10-24):** widen and verify — keep the Python 3.11 floor,
extend declared ranges to near-term ceilings, and prove the 3.11–3.15 matrix.
No Python-floor raise, no forced jump to unreleased major lines.

## Current state (locking snapshot 0.4.1)

Python `requires-python >=3.11`; CI runs 3.11–3.15. Build backend
`setuptools>=77`.

| Dependency | Declared | Locked | Status |
| --- | --- | --- | --- |
| textual | `>=8.2,<9` | 8.2.8 | current |
| httpx | `>=0.28,<1` | 0.28.1 | current |
| rich | `>=14.2,<16` | 15.0.0 | current |
| playwright (browser extra) | `>=1.64,<2` | 1.64.1 | current |
| pytest | `>=8.4,<10` | 9.1.1 | current |
| pytest-asyncio | `>=1.0,<2` | 1.4.0 | current |
| pytest-cov | `>=7` | 7.1.0 | current |
| coverage | `>=7` | 7.17.0 | current |
| ruff | `>=0.17,<0.18` | 0.17.2 | current (0.18.x next) |
| mypy | `>=1.11` | 2.4.0 | current |
| pip-audit | `>=2.7` | 2.10.1 | current |
| pre-commit | `>=4.0` | 4.7.0 | current |

## Phase 0 — Baseline and reproducibility

Freeze the paddle before moving it.

- [ ] Confirm `uv.lock` is committed and `make sync` is reproducible from a
      clean checkout (`uv sync --locked`). `scripts/bootstrap.sh` and
      `scripts/agent-connect.sh` already use `--locked`; verify both.
- [ ] Record a green baseline: `make check` and `make quality` on 3.11.
- [ ] Pin the toolchain versions this plan relies on (uv, Python) in the
      documentation; note that CI installs a pinned `uv`.

**Exit:** a reproducible build, a documented toolchain version set.

## Phase 1 — Python support matrix (no dependency bumps)

The classifiers already list 3.11–3.15 and CI runs all five. This phase makes
the *declared* surface match reality exactly.

- [ ] Verify `.github/workflows/ci.yml` matrix is `["3.11","3.12","3.13","3.14","3.15"]`.
- [ ] Reconcile `requires-python = ">=3.11"` with the classifiers: decide and
      record whether an upper bound (`<3.16`) is needed, and update
      `README.md`'s `Python 3.11+` badge if the floor changes.
- [ ] Confirm `tool.mypy.python_version` and `tool.ruff.target-version` agree
      with the floor (both `3.11` today).
- [ ] Run `make minimum` (lowest-direct resolution) to prove the *oldest*
      allowed versions still pass the suite — the floor's truth test.

**Exit:** matrix verified green on all five interpreters; `make minimum` green.

## Phase 2 — Widen declared ranges to verified ceilings

Raise upper bounds only where the currently-locked version is already proven
by the suite; this prevents future `pip install` failures without touching code.

- [ ] `ruff`: `>=0.17,<0.18` → `>=0.17,<0.19` (verify 0.18.x passes when
      released; the `skills`/`build`/`dist` `extend-exclude` must keep working).
- [ ] `coverage`: `>=7` → `>=7,<8` once 7.x is the moving line; same for
      `pytest-cov`.
- [ ] `pip-audit`, `pre-commit`, `mypy`: leave floors, confirm no upper
      ceiling is silently violated.
- [ ] Re-run `make check` after every bound change; regenerate and re-commit
      `uv.lock` (`uv lock`).

**Exit:** declared ranges match the versions already exercised; no oral
compatibility claims left to trust.

## Phase 3 — Continuous dependency drift control

The upgrade is never done; make drift visible instead of surprising.

- [ ] Keep the existing weekly CI schedule (push/PR + weekly) the single place
      dependency drift surfaces.
- [ ] Add a `uv lock --check` (or `--locked`) job so a lockfile that has
      fallen behind `pyproject.toml` fails CI loudly.
- [ ] Confirm `make quality` (`pip-audit --strict`) runs on every PR so a
      vulnerable resolve is caught before merge.

**Exit:** a stale lockfile or a vulnerable dependency cannot reach `main`
silently.

## Phase 4 — Chasing next major lines (deferred, gated)

Each item below is `skip until released`, and each becomes its own PR-sized
phase when it lands. Do **not** bundle them.

- [ ] `textual` 9.x — the TUI (`src/sovereign_code/tui/`) is the largest API
      surface; expect widget/event changes. Gate on a green suite + a manual
      dashboard smoke test.
- [ ] `httpx` 1.x — touches the tier gateway, bridge, and every HTTP client
      (`src/sovereign_code/*gateway*.py`, `webchat.py`).
- [ ] `rich` 16.x — used across CLI and TUI output.
- [ ] `playwright` 2.x — browser operator (`src/sovereign_code/browser/`) and
      integration tests.
- [ ] `pytest` 10.x / `pytest-asyncio` 2.x — run under
      `asyncio_default_fixture_loop_scope = "function"`.
- [ ] `python` 3.16 — add to the CI matrix and classifiers before claiming
      support; never before the interpreter is stable.

Each: bump the declared range, `uv lock`, `make check` + `make quality`,
manual smoke for the affected surface, then land.

## Phase 5 — Python floor review (decision point, not default)

The project targets 3.11 today. When macOS toolchain pressure or a dependency
*requires* a newer floor, re-open this — not before:

- [ ] Determine the oldest Python the CI matrix and dependencies actually
      need.
- [ ] If raising: drop the oldest entry from the CI matrix, bump
      `requires-python`, and remove the corresponding classifier in the same
      commit as the affected code.
- [ ] Update `README.md` (the `Python 3.11+` badge) and
      `docs/ARCHITECTURE.md` in the same change.

## Definition of done

- [ ] `make check` — lint + format + typecheck + test with coverage (≥50%).
- [ ] `make quality` — the above plus `pip-audit --strict`.
- [ ] `make minimum` — oldest allowed direct versions still pass.
- [ ] `uv.lock` regenerated and committed whenever `pyproject.toml` changes.
- [ ] No version claim in `pyproject.toml`, `README.md`, or the CI matrix that
      the suite has not actually run against.

## Principles (inherited from docs/ROADMAP.md)

- Prefer widening a proven range over chasing an unreleased major line.
- Every upgrade is one revertible commit; never bundle major-line jumps.
- `make check` is the definition of done.