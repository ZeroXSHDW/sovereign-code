# Roadmap

Prioritised work for Sovereign Code. This is the list the agent starts from
when asked "what next". Every item here must pass `make check` before it is
considered done.

## Now — v0.4.0: stabilise and release the unreleased pass

The last release is 0.3.0 (2026-10-22). The `[Unreleased]` changelog already
describes two landed bodies of work:

- **Hugging Face Hub integration** (`sovereign hf`): standard-token login,
  model/dataset search with licence/language/format/pipeline filters, repo
  inspection, file-selective resumable downloads, one-step `hf import` into
  Ollama, `hf remove`, and five MCP discovery tools.
- **Live monitor v2**: health verdict with reasons, five-minute RAM/load/VRAM
  sparklines, model inventory with resident/potential-free memory, aggregate
  gateway throughput, `p`/`y`/`--json`/`--demo`, and correctly sized skill/prompt
  cards.

Goal for 0.4.0: cut the release.

1. [ ] Run `make check` green (tests, ruff, mypy, format) — the gate for every
       change, including this roadmap's own examples.
2. [ ] Review `[Unreleased]` against the code; confirm every item is implemented
       and documented.
3. [ ] Bump `pyproject.toml` to `0.4.0`, write the `[0.4.0]` changelog entry,
       move `[Unreleased]` items into it, and open a fresh `[Unreleased]`.
4. [ ] Tag `v0.4.0` and release.

## Next — v0.4.1 / v0.5.0: finish the incomplete upgrade pass

The `feature/upgrades` branch is not safe to merge as-is. It removes
`packs.py`, `knowledge.py`, `warm.py`, `backends.py`, `safefile.py` and
`uv.lock`, but those modules are still imported by `cli.py` (`sovereign
backends`, `sovereign knowledge`), `cache.py`, `tier_gateway.py`,
`backup.py`, `client_setup.py` and `harness.py`. Merging it breaks the build.

Options, in priority order:

- [ ] Complete the removals properly: update every caller, drop the now-dead
      commands from `cli.py`, regenerate `uv.lock`, and re-run `make check`.
- [ ] Or close the branch and keep the modules, documenting that the upgrade
      pass was abandoned.

After that, verify end-to-end the surfaces documented in the README but not yet
exercised by tests:

- [ ] Task packs (`sovereign pack list/show/brief/models/install`) — pack
      brief writes into a project's `AGENTS.md`; SCOPE.md gating for pentest.
- [ ] MLX server integration (`sovereign mlx pull/start/status/stop`) —
      speculative decoding, 8-bit KV cache, tier aliases (`mlx-fast`,
      `mlx-code`), `sovereign gateway-config --apply`.
- [ ] Browser operator (`sovereign browse`) — Playwright Chromium, policy,
      confirmation gates, secret refusal, masked audit log; keep integration
      tests green.

## Later

- Python 3.15 support matrix (pyproject lists 3.11–3.15; CI verifies 3.11 and
  3.13).
- Coverage floor above the current 45%.
- Additional local stacks and model aliases as new hardware arrives.

## Principles

- Local-first by default: cloud/provider models are opt-in only, and
  `sovereign local --strict` must stay green.
- One model resident at a time (24 GB unified-memory guardrail).
- Every user-facing command has a headless path usable in CI and from the menu
  bar.
- `make check` is the definition of done.
