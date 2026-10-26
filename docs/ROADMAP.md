# Roadmap

Prioritised work for Sovereign Code. This is the list the agent starts from
when asked "what next". Every item here must pass `make check` before it is
considered done.

## Delivered

- **v0.4.1–v0.5.2:** Streamable HTTP MCP, threaded-cache safety, fenced edits,
  atomic/private state writes, browser policy and locking, OpenCode V2 config,
  real client verification, service recovery, and the opt-in coding loop.
- **v0.6.0:** `model-use`, specialist task packs and domains, live-verified MLX
  lifecycle and speculative decoding, live browser tests, and MCP bearer auth.
- **v0.7.0:** `sovereign do`, `model-use --domain`, `summarize --dir`, chat
  `/resume`, MLX run routing, and no fast-tier preload at gateway startup.
- **Compatibility and quality:** Python 3.11–3.15 CI, strict mypy in macOS and
  Linux views, locked installs, a 53% coverage floor, and dependency auditing.

## Now — post-0.7.0 hardening

- [ ] Finish and verify the current gateway/MLX/installer hardening: batched
  `/v1/embeddings` with per-text reuse, MLX chat and fast-tier routing, saved
  MLX supervision, safer direct-mode undo, debug traces, and one maintained
  installer path. Release tags must run checks, audit dependencies, and match
  the package version.
- [ ] Make the wheel and sdist self-contained. They currently omit the skill
  library, launchers, and Swift menu-bar source that a checkout provides; add
  an isolated installed-artifact smoke test for those flows.
- [ ] Enforce the one-resident-model guard across Ollama and MLX, not only
  within Ollama. Verify model switches and active streams on a 24 GB Mac.
- [ ] Add macOS/Apple Silicon CI for launchd, installer, Swift compilation,
  codesigning, and native client smoke tests; Linux CI cannot cover these.

## Later

- [ ] Reuse unchanged text/model vector fingerprints across `sovereign index`
  rebuilds without re-embedding the whole tree or mixing embedding models.
- [ ] Raise the coverage floor after the installed-artifact and macOS gaps are
  covered. Prioritise CLI dispatch, MCP HTTP, MLX lifecycle, and browser flows
  over smoke-test count.
- [ ] Reconcile the richer chat prototypes (`tui/patch.py`, `tui/jump.py`) with
  the supported chat UI: wire and test them, or remove the unused prototypes.
- [ ] Add local stacks and model aliases as new hardware and measured model
  results arrive.

## Principles

- Local-first by default: cloud/provider models are opt-in only, and
  `sovereign local --strict` must stay green.
- One model resident at a time on a 24 GB unified-memory Mac.
- Every user-facing command has a headless path usable in CI and from the menu
  bar.
- `make check` is the definition of done.
