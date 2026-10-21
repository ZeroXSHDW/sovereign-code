# Changelog

All notable changes to Sovereign Code.

## [Unreleased]

### Added
- Hardware guardrails in `doctor`: Apple-silicon GPU-wired budget, swap pressure, stale model
  runners, and gateway-config drift (16 → 19 checks). These catch the failure mode where a model
  larger than the GPU budget makes Ollama **hang** instead of erroring.
- `status` shows the GPU-wired budget and the engine serving each loaded model (`mlx` / `llamacpp`).
- `sovereign models` de-aliases `foo` and `foo:latest` so no model is listed twice.

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
