# Changelog

All notable changes to Sovereign Code.

## [Unreleased]

### Added
- **Ollama Cloud models**: Kimi K3, Kimi K2.6, DeepSeek V4.1 Flash, DeepSeek V4 Pro,
  GLM-5.3, GLM-5.3 Flash, and GLM-5.2 are registered as `:cloud` models, plus local
  Qwen 3.8 27B. `sovereign cloud` shows the mapping and readiness; `--enable` flips
  `server.json` + `OLLAMA_NO_CLOUD`, updates the login agent and restarts Ollama;
  `--install-aliases` writes `cloud-*` gateway aliases; `--pull` registers the tags;
  `--probe` reports disabled / signed-out / Pro-plan states instead of a raw HTTP error.
- Cloud-aware `models`, `status`, `model-info`, `pull`, and `run`: cloud tags are marked
  `☁`, never counted as local disk use, and 402 "not in the Free plan" replies are
  explained with the upgrade link. The local-first router never picks a cloud model.
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
- `pipeline` now runs **verification**, not just plan → implement → review: it auto-detects the
  project's checks (`make test`, pytest, npm, cargo, go), runs them, and feeds a failure back to the
  implementer for bounded repair rounds (`--fix`, `--checks`, `--no-verify`, `--agent-timeout`).
  The reviewer sees the real `git diff` and the check output, and every run is archived under
  `~/Documents/local-ai/data/runs/<timestamp>/` with a summary and an explicit verdict.
- `pipeline` fails fast when the agent changed nothing (`No files were changed by the implementer`)
  instead of running checks against an empty tree, and clears resident models between stages so a
  19 GB planner and an 18 GB coder never fight over the wired budget.
- `local-review` gateway alias: gemma4:12b as the independent reviewer (different family from the
  Qwen implementer). gpt-oss spends its whole budget on hidden reasoning and returns empty content.
- `tune` now sets `OLLAMA_MAX_LOADED_MODELS=1`: with 2, Ollama keeps the old model and waits for
  memory instead of evicting, which wedges the server on a 24 GB machine.
- The watchdog is now runner-aware and uses a two-strike rule, so it no longer restarts Ollama
  during a legitimate cold load (which was killing active pipeline runs).
- `doctor` gained a **Client models** check: every model referenced by the gateway, OpenCode, Qwen
  Code and Continue must still be installed, which catches a pruning pass or another agent's edit
  leaving a dangling reference (20 checks).
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
