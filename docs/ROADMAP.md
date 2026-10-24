# Roadmap

Prioritised work for Sovereign Code. This is the list the agent starts from
when asked "what next". Every item here must pass `make check` before it is
considered done.

## Now — v0.5.0: client compatibility

`v0.5.0` (2026-10-24) is the release where the three agent clients are verified
rather than assumed: Codex, Claude Code and OpenCode each answer a real turn
(`sovereign verify --clients`), the gateway is proved to complete a request
instead of only opening a port, and the generated configs validate against the
clients' current schemas.

- [x] Tag `v0.4.1` (55626c8e) and `v0.5.0`, and publish both.
- [x] `sovereign verify --clients`: one real turn per client, PASS/FAIL table.
- [x] Doctor probe for gateway completions, so a wedged gateway cannot pass.
- [x] Recover a stale tier gateway via `router --stop/--restart`; a losing bind
      exits cleanly instead of crash-looping launchd.
- [x] OpenCode 2.x schema-valid config (no `enabled`, no `small_model`, V1
      `mcp` map migrated into `mcp.servers`).
- [x] Honest OpenCode launch note (2.x ignores `OPENCODE_CONFIG_CONTENT`).
- [x] Claude Code 2.1 Fable slot and current model ids; drop the removed
      `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` knob.
- [x] Bound client-config backups at five per file.

### 0.4.1 hardening (released with v0.5.0)

`v0.4.0` is tagged (2026-10-23). A post-release review produced the
`[0.4.1]` changelog entry. The repairs are complete and covered by
`tests/test_upgrade_repairs.py`; `make check`, coverage (≈50%, floor 50) and
`uv build` are green.

- [x] Implement the Streamable HTTP MCP transport the launchd service names.
- [x] Make the tier-gateway disk cache safe on `ThreadingHTTPServer` threads.
- [x] Fix the model catalog so every alias reports its real tier/model.
- [x] Fence PDF downloads and make PDF parsing/ordering resilient.
- [x] Stop session/backup collisions and corrupt-line data loss.
- [x] Refuse lossy edits of non-UTF-8 files and preserve CRLF.
- [x] Keep undo, prompt search and the old search index intact on failure.
- [x] Close browser-policy gaps for legacy numeric hosts, subframes and
      glued destructive labels.
- [x] Harden loopback origins, private file permissions and config errors.
- [x] Add an opt-in 24/7 coding loop (`sovereign loop`) that discovers work,
      routes skills, runs `opencode run --auto`, verifies, and pauses on
      repeated failure; it is a separate launchd job, not part of autostart.
- [x] Bump `pyproject.toml`/`__init__.py` to `v0.4.1` after a live run of
      `sovereign doctor` (24 pass · 3 warn · 0 fail) and `sovereign mcp --http`
      (initialize and tools/list over loopback).

## Next — v0.6.0

Surfaces documented in the README but not yet exercised end-to-end on live
hardware. The code is written and CLI-wired; what remains is a real run:

- [x] Task packs (`sovereign pack list/show/brief/models/install/verify`) —
      pack brief writes into a project's `AGENTS.md`; SCOPE.md gating for pentest.
      Remaining: a live `pack brief` + `pack verify` run against a model.
- [x] MLX server integration (`sovereign mlx pull/start/status/stop`) —
      speculative decoding, 8-bit KV cache, tier aliases (`mlx-fast`,
      `mlx-code`), `sovereign gateway-config --apply`.
      Remaining: a live `mlx start` run recording the tok/s gains.
- [x] Browser operator (`sovereign browse`) — Playwright Chromium, policy,
      confirmation gates, secret refusal, masked audit log; keep integration
      tests green.
- [x] Live Chromium end-to-end tests (`tests/test_browser_live.py`,
      `make browser-check`, CI job) cover the operator, the profile lock and
      the MCP browser tools against a real headless browser.
- [x] Cross-process browser session locking so `browse`, MCP and web chat cannot
      open the same Chromium profile at once (`ProfileLock`).
- [x] Give the HTTP MCP endpoint an explicit authentication story: a bearer
      token (`--token`/`SOVEREIGN_MCP_TOKEN`) is required for any non-loopback
      bind, and authenticated requests bypass the loopback `Host` guard.

## Later

- Python 3.15 support matrix (pyproject lists 3.11–3.15; CI verifies all five).
- Coverage floor above the current 50%.
- Additional local stacks and model aliases as new hardware arrives.

## Principles

- Local-first by default: cloud/provider models are opt-in only, and
  `sovereign local --strict` must stay green.
- One model resident at a time (24 GB unified-memory guardrail).
- Every user-facing command has a headless path usable in CI and from the menu
  bar.
- `make check` is the definition of done.
