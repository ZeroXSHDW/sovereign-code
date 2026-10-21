# Changelog

All notable changes to Sovereign Code.

## [Unreleased]

### Added
- Hardware guardrails in `doctor`: Apple-silicon GPU-wired budget, swap pressure, stale model
  runners, and gateway-config drift (16 → 19 checks). These catch the failure mode where a model
  larger than the GPU budget makes Ollama **hang** instead of erroring.
- `status` shows the GPU-wired budget and the engine serving each loaded model (`mlx` / `llamacpp`).
- `sovereign models` de-aliases `foo` and `foo:latest` so no model is listed twice.
- `sovereign launch` frees GPU memory automatically: when the chosen model needs nearly the whole
  wired budget, resident models are unloaded first instead of letting Ollama hang.
- `sovereign launch --dry-run` shows the model, planned eviction and argv without launching.
- `sovereign tune` applies and verifies Ollama runtime tuning end-to-end: flash attention, q8 KV
  cache, keep-alive, and the app's stored context length, then fully restarts the app (the hidden UI
  process has to die too) and confirms the server inherited it. `--dry-run` shows the diff first.
- `sovereign verify --all` now reads the alias list from `gateway/config.yaml` instead of a
  hard-coded tuple, so it cannot go stale.
- `doctor` gained a **Generation liveness** check (20 checks): it sends a tiny embedding request,
  because a hung Ollama still answers `/api/version` while every generation queues behind it.
- `sovereign verify` runs the liveness probe first and fails in seconds instead of sitting through
  the per-alias timeout on a hung server.
- `sovereign doctor --fix` restarts a hung Ollama and confirms it serves again.
- The dashboard shows each loaded model's engine (`mlx` / `llamacpp`) and the GPU-wired budget.
- `sovereign watchdog` recovers a wedged Ollama while leaving a busy one alone: it samples `/api/ps`
  and runner CPU over an interval and only restarts when nothing is progressing. The login watchdog
  now calls a mirror of it from Application Support (launchd cannot read `~/Documents`).
- `sovereign warm` preloads the best model for a task (or `--model`) so the first prompt is not a
  6-7 s cold load.
- `sovereign prune` lists installed models that no alias, stack or task preference references
  (5.0 GB here), with `--apply` to delete and a dry run by default.
- `sovereign best` prints the effective model for every connected tool (Codex, ChatGPT, Claude Code,
  OpenCode, Qwen Code, VS Codium, Ollama chat) by reading their live configs, so "strongest first"
  can be checked rather than assumed.
- `claude-cloud` wrapper: the counterpart to `codex-chatgpt`, using the Claude subscription with no
  local gateway overrides.
- The catalog is curated to the strongest measured models; weaker/superseded ones (phi, mistral,
  gemma3:4b, qwen3:8b, llama3.1:8b, deepseek-coder:6.7b, qwen2.5:0.5b, qwen2.5-coder:3b) were
  pruned — 23.9 GB — and `prune --apply` now writes a restore list first.

### Fixed
- Large models no longer collapse to a 2048-token context when their weights exceed the free-RAM
  estimate; the router keeps a 16k working floor (verified with a 19 GB coder at 16k and 32k).
- Aliased model views were counted twice, inflating installed/loaded totals and double-counting
  resident memory in `potential_free_gb`.
- `doctor` "Best coder" now follows the router instead of a hard-coded 14B tag.
- Model ranking and stacks updated for the measured 2026-10-21 benchmark set.

## [0.1.0] - 2026-10-20

### Added
- Textual terminal dashboard (F2–F8, slash commands) with live model/memory/gateway status.
- Model routing across code/chat/reason/vision/agent tasks, with a vetted local catalog.
- LiteLLM gateway supervisor, watchdog (heals Ollama + gateway), and log rotation.
- Ollama environment agent: flash attention + q8 KV cache (14B coder at 32k context).
- `verify`, `bench`, `pull`, `consult`, and multi-model `pipeline` (plan → implement → review).
- Skills/prompt bank, per-project memory, and `AGENTS.md`/`CLAUDE.md` injection.
- Semantic code search (`index`/`search`) and local summarization (`summarize`).
- Compliant Playwright browser operator (`browse`) with policy, audit, screenshots, CAPTCHA handoff.
- Operations: `doctor` (16 checks + `--fix`), `logs`, `sessions` (search/export), `backup`, `config`, `stats`.
- `clone` for bootstrapping GitHub projects.
- 96 tests; GitHub Actions CI (Python 3.11/3.13) and linting.
