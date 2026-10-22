# Changelog

All notable changes to Sovereign Code.

## [Unreleased]

### Added
- **Hugging Face Hub integration** (`sovereign hf`): secure token login in the
  standard `~/.cache/huggingface/token` (mode 0600), public/private model
  search, repository inspection with GGUF metadata and file sizes, and
  file-selective, resumable downloads through the `hf` CLI. MCP adds
  `hf_status`, `search_hf_models`, and `hf_model_info`; the `sovereign-huggingface`
  skill documents the workflow and the on-disk layout.

## [0.3.0] - 2026-10-22

### Added
- Read-only live monitor (`sovereign monitor` / default dashboard): skill and prompt banks, live projects, system activity.
- Structured prompt database (`sovereign prompts`) and skill database (`sovereign skill-db`).
- Agent detection (`sovereign agents`) and one-command connect (`sovereign connect`).
- LiteLLM gateway config generator (`sovereign gateway-config`).

### Changed
- `rich` upgraded to 15.x.

### Changed
- **The login dashboard is now a read-only live monitor.** It shows the total
  skill bank and prompt bank, which project is using a model now (running
  agents + recent session cwd/model), resident models with context, recent
  gateway requests, services, RAM/swap/disk/load, and `F9` unloads models to
  free RAM. It no longer contains a chat prompt or streams Qwen replies.
  Chat remains available explicitly with `sovereign chat`.
- **The 24/7 chat/guardian stack is gone.** `sovereign autostart` now installs
  only the LiteLLM gateway, tier gateway and Anthropic bridge. The `webchat`
  and `guardian` launchd jobs are stopped and removed on upgrade, so no chat
  server and no 30-second restart loop run when nobody is using them.
  `sovereign guardian` still works as a one-shot check.

### Added
- `sovereign monitor` as an explicit alias for the login monitor.

## [0.2.1] - 2026-10-22

### Changed
- Bumped `rich` dependency to `<16` (15.x) and verified the full test suite.

### Added
- **Codex streams local answers**: `/v1/responses` now consumes the tier
  gateway's chat stream and emits `response.output_text.delta` events as the
  model generates, instead of waiting for the whole completion and replaying it
  in one burst. Tool calls still arrive as complete `function_call` items, and
  an upstream failure becomes `response.failed` instead of a silent stall.
- **Claude Code streams local answers**: the Anthropic bridge used to wait for
  the whole completion before sending anything, so a long answer looked like a
  hung connection. It now asks the tier gateway for a stream, forwards text
  deltas as `text_delta` events, and turns the buffered tool calls into complete
  `tool_use` blocks at the end of the turn. A stream error before or during the
  reply is reported as an Anthropic `error` event instead of an empty answer.
- **`sovereign autostart`**: the local stack as a set of launchd services.
  `sovereign autostart --install` writes and loads one agent per service
  (LiteLLM gateway, tier gateway, Anthropic bridge, ChatGPT Local web, and a
  guardian), each with `RunAtLoad` so it starts at login and `KeepAlive` so
  it comes back after a crash. `sovereign autostart` shows what survives a
  reboot, `--restart` restarts every service, `--repair` rewrites the plists
  and reloads them, `--uninstall` removes them and puts the retired jobs back.
- **The stack survives a reboot**: the tier gateway, the Anthropic bridge and
  the local chat web UI used to be started by hand, so after a restart ChatGPT
  and Claude had no gateway to talk to. They are services now.
- **The ChatGPT app is local from the first launch after a reboot**:
  `launchctl setenv` publishes `CODEX_APP_SERVER_OPENAI_BASE_URL` and
  `SOVEREIGN_API_KEY` to the login session, so an app opened from the Dock
  inherits them without a sign-in.
- **The guardian keeps the client configs local**: the ChatGPT app rewrites
  its own config when a setting changes in its UI, which silently sends it
  back to the cloud. The guardian puts the config and Claude's settings back
  — but only while the local mode is the current one, so
  `sovereign chatgpt --cloud` and `sovereign claude --cloud` are not undone.
- **The guardian supervises the LiteLLM gateway too**, and restarts a service
  through launchd when the job is loaded, so the job launchd supervises is
  the one that gets restarted.
- **One model catalog for both clients**: the tier gateway (4010) and the
  Anthropic bridge (4001) now serve the same model list, built from the
  routing tables and the models Ollama has installed: the tiers, the quality
  routes (`auto`, `best`), the local aliases (`local-claude`, `local-glm`,
  `local-review`, …) and every installed local model by name. A name in that
  list can be asked for: naming `qwen3-coder:30b` gets exactly that model.
  Cloud and embedding models are left out, because the local-only gateway
  refuses them and they cannot answer a chat turn.
- **`sovereign doctor` checks the ChatGPT and Claude models**: the models every
  client config points at are now compared with the catalog, so a config that
  names a model the gateway cannot route is reported instead of failing at the
  first prompt.
- **`sovereign claude` and `sovereign chatgpt` show the model in use**: the
  status tables name the model each client asks for and where it lands.
- **`sovereign chatgpt --verify`**: an end-to-end proof that the ChatGPT app is
  local and sign-in free. It checks the app config, that no OpenAI account is
  required, that the running app-server points at the tier gateway, and it
  sends a live turn through the app's *own* provider config (same base URL,
  same token command) so a pass means the app would answer as-is.
- **`sovereign claude --local` / `--cloud`**: the same reversible switch for
  Claude Code/Cowork. The cloud settings are kept in
  `~/.claude/settings.json.sovereign-cloud`; `--cloud` puts them back, or strips
  the local bridge keys when there is no saved copy.
- **`sovereign status --json`**: machine-readable status (services, memory,
  resident models, and whether the desktop apps are local) for scripts and for
  the menu bar app.
- **`sovereign local --json`**: the same local-only audit, machine-readable, with
  a non-zero exit code when a path is not local.
- **`sovereign chatgpt --repair`**: rewrites the app config when it drifts back
  to the cloud (the app rewrites its own config when its settings change) and
  leaves the app running.
- **MCP `local_status`**: the desktop apps can ask their own MCP server whether
  this machine is running the local stack only, and whether they need a
  sign-in.
- **LocalBar upgrades**: tier latency, resident model and free memory in the
  menu; *Open ChatGPT desktop*, *Point Claude at local bridge*, *Restore cloud
  Claude*, *Unload resident models*, *Repair ChatGPT local config* and
  *Verify ChatGPT is local* actions, plus a drift warning when the app's own
  settings moved it off the local path.
- **Tier headers on `/v1/responses`**: `x-sovereign-tier`, `x-sovereign-model`,
  `x-sovereign-reason` and `x-sovereign-fallback` now reach Responses clients,
  so a client can tell which model actually served the request.
- **Forced-local ChatGPT desktop**: `sovereign chatgpt --local` pins
  `~/.codex/config.toml` to `model_provider = "sovereign-tier"` with
  `openai_base_url` on the tier gateway, so the app's Codex side runs entirely
  on this Mac **with no OpenAI sign-in**. The provider takes its token from
  `[model_providers.sovereign-tier.auth]` (a command), not from an environment
  variable, so the app works when launched from Finder or the Dock. The
  untouched config is kept in `~/.codex/config.toml.sovereign-cloud` and
  `sovereign chatgpt --cloud` puts it back.
- **LocalBar actions**: *Force local ChatGPT (no sign-in)* and *Restore cloud
  ChatGPT*, with the app's current mode in the menu.
- The local-only audit now checks the ChatGPT desktop app instead of assuming
  it is cloud, and `sovereign local --fix` forces it local.

### Changed
- **A stalled model can no longer hold the stack for ten minutes**:
  non-streaming calls give each fallback model 300 s (`SOVEREIGN_REQUEST_TIMEOUT`)
  and streaming calls fail after 180 s without a byte
  (`SOVEREIGN_STREAM_IDLE_TIMEOUT`). The gateway emits a clear
  `upstream_timeout` error and releases the single-resident lock, so the next
  queued request can run instead of waiting behind a wedged model.
- **The tier gateway listens before it warms**: the fast model used to load
  before the port opened, so every restart refused connections for up to a
  minute. The server binds first and warms the 4B in a background thread;
  health answers immediately and chat requests wait on the model lock instead
  of failing to connect.
- **The stack is a set of launchd services** instead of hand-started
  processes: one agent for the LiteLLM gateway, the tier gateway, the
  Anthropic bridge, the ChatGPT Local web UI and the guardian. The two
  Terminal-based jobs that used to start and watch the gateway are retired
  (their plists are kept as `.superseded` and restored by
  `sovereign autostart --uninstall`), so no window opens at login any more.
- **The gateway runs under launchd without Terminal**: a launchd job may read
  a file in `~/Documents` and may run a program by its full path, but it may
  not *execute* a script there and may not *list* a directory there. The
  gateway is therefore started through its interpreter, and every service uses
  a log file of its own — launchd cannot open a log file another app created,
  and the job then fails to spawn with `EX_CONFIG` instead of starting.
- **Claude Code's launcher uses the same model slots as the settings file**,
  so `sovereign launch claude` and the `claude-local` wrapper no longer pin
  every slot to one model.
- **Claude Code's model slots are mapped to local routes**: the default turn
  follows the quality route (`best`), and the picker slots land on the local
  models — Sonnet on `deep` (30B coder), Opus on `ultra` (27B), Haiku on `fast`
  (4B). The slots carry the model ids Claude Code knows, so it stops logging
  an unrecognised model, and the mapping lives in one table that the bridge and
  the client setup share.
- **A request that does not fit the model the route picked** is answered by the
  64k 9B instead of being truncated. A 30k Claude Code prompt used to be sent
  to a 16k or 32k model.
- **The ChatGPT app asks for `best`**, like every other client, instead of the
  latency-first `auto`.
- `chatgpt-cloud` and `codex-chatgpt` put the saved cloud config in place for the
  run and restore the local one on exit, like `claude-cloud` does for Claude.
- The tier-gateway provider in every Codex config uses the command-backed token
  instead of `env_key`; a missing environment variable used to put the sign-in
  gate straight back.
- A client config that is already local is never saved as the "cloud" copy, so
  `--cloud` cannot hand back a local config as if it were the original.
- `sovereign doctor --fix` puts the desktop apps back on the local path when
  their configs have drifted.

## [0.2.0] - 2026-10-21

### Added
- **Sovereign Local menu bar**: native Swift/AppKit menu bar app with gateway/UI
  status, ChatGPT Local/Codex/Claude launchers, stack restart, and local-only audit.
  `sovereign local-bar --install --open`.
- **Ollama-only OS config**: `OLLAMA_NO_CLOUD=1` and `SOVEREIGN_LOCAL_ONLY=1` are
  persisted in the login profile; `sovereign local --strict` verifies Ollama Cloud
  is off and the gateway is local-only.
- **Browser control for ChatGPT/Claude and the local UI**: MCP tools
  `browser_open/observe/act/screenshot/close` drive a visible Chromium session;
  the local ChatGPT web app has a browser task panel. Destructive actions require
  explicit `confirm=true`; password/OTP/payment fields are refused.
- **Fully local ChatGPT UI**: `sovereign chat-web` serves an inline, loopback-only
  ChatGPT-style client on 4020 with streaming, six local model choices, local
  session storage, 22k-skill search, and no external assets. `--install-app`
  creates `~/Applications/ChatGPT Local.app`.
- **Long-session guards**: tool outputs are truncated, old turns are compacted
  with the task anchor preserved, orphan tool results are removed, and three
  identical tool calls trigger a stop instruction instead of an endless loop.
- **Local-only by default**: the tier gateway returns HTTP 403 for cloud/provider
  aliases unless started with `SOVEREIGN_LOCAL_ONLY=0`. Health reports
  `local_only`, `sovereign local --strict` verifies it, and the watchdog restarts
  the gateway if it dies.
- **Quality-first `best` route**: OpenCode, Codex, Qwen, Continue, and MCP `ask`
  default to `best` (30B coder for code, GLM for reasoning, 9B for trivial or
  very large prompts). `auto` remains the latency-first choice.
- **MCP `delegate`**: ChatGPT/Claude can run a real local Codex or Claude agent on
  a project, read-only by default (`write=true` for edits), with a bounded timeout.
- **Claude quality path**: nontrivial Claude turns use GLM-4.7-Flash; simple or
  very large-context turns use the 65k 9B. Verified real file creation.
- **`sovereign local` audit**: reports Claude Code settings, bridge, Codex local
  profile/provider, local wrappers, OpenCode default, tier gateway, and explicitly
  marks the closed desktop chat windows as cloud. `--fix` rewrites the local
  settings; `--strict` exits non-zero if any local agent path is not local.
- Removed stale references to uninstalled `deepseek-r1:8b`/`qwen2.5-coder:7b`
  from OpenCode/Qwen/Continue configs; `sovereign doctor` now reports all
  referenced client models installed.
- **Searchable 22k skill library**: `sovereign skills search <words>` and
  `sovereign skills install --name <skill>` work beyond the 44 curated skills.
  The MCP `list_skills(query)`/`get_skill(name)` tools search the whole library,
  so ChatGPT/Claude can pull a specialized workflow on demand.
- **Deep tier split and ultra tier**: `deep` now sends coding/tool work to
  `qwen3-coder:30b` (12.7 s on the standard coding prompt) and reasoning to
  `glm-4.7-flash` (13.4 s), instead of always using the dense 27B (45.1 s).
  `ultra` keeps `qwen3.8:27b` for the hardest reasoning. Non-streaming local
  calls fall back through the tier's model list on an upstream error and expose
  `x-sovereign-fallback`.
- **Local Claude by default**: `install-clients` writes `~/.claude/settings.json` env
  pointing at the local bridge, so plain `claude` and `claude-local` run locally;
  `claude-cloud` moves that settings file aside for the subscription run and restores it.
- **Local ChatGPT wrappers**: `chatgpt-local` launches the tier-routed local Codex,
  `chatgpt-cloud` uses the ChatGPT login. `sovereign chatgpt --local` restarts the
  desktop app with its app-server base pointed at 4010 (chat remains cloud);
  `--cloud` restores normal behaviour.
- **Claude status command**: `sovereign claude [--fix|--restart]` reports the local
  settings, bridge, CLI, and desktop app; `sovereign chatgpt` does the same for ChatGPT.
- `sovereign launch codex|claude --cloud` uses the real ChatGPT/Claude subscription
  login and skips local overrides; local launches still use the tier gateway/bridge.
- ChatGPT desktop discovery: `install-clients` writes the `sovereign` MCP server to
  `~/.codex/config.toml`, `~/.mcp.json`, `~/.codex/.mcp.json`, and the ChatGPT app's
  `claude_desktop_config.json` path, and the server publishes usage instructions.
- OpenCode defaults to `sovereign/auto`; real file edits through the tier gateway were
  verified (8.3 s cold, 0.4–0.8 s warm on a 24 GB M5 Pro).
- **Tier gateway** (`sovereign router`, port 4010): classifies each request and routes
  short/simple work to `qwen3.5:4b`, tool/multi-turn work to `qwen3.5:9b` (65k), and
  code/reasoning to `qwen3.8:27b`. It streams correct OpenAI tool calls directly from
  Ollama, caches short responses, exposes tier/model/reason headers, logs latency, and
  enforces a one-resident-model policy so big and small models do not OOM each other.
  `sovereign router --status/--stats`, `sovereign status`, and `openai` clients use it;
  `sovereign env` now exports `OPENAI_BASE_URL` as the tier gateway and `OPENAI_MODEL=auto`.
- OpenCode defaults to `sovereign/auto` with `sovereign/balanced` as its small model;
  Continue gains `Sovereign Auto`/`Deep`; Qwen Code gets a tier provider with default
  `auto`; the Claude bridge points at the tier gateway.
- **Ollama Cloud models**: Kimi K3, Kimi K2.6, DeepSeek V4.1 Flash, DeepSeek V4 Pro,
  GLM-5.3, GLM-5.3 Flash, and GLM-5.2 are registered as `:cloud` models, plus local
  Qwen 3.8 27B. `sovereign cloud` shows the mapping and readiness; `--enable` flips
  `server.json` + `OLLAMA_NO_CLOUD`, updates the login agent and restarts Ollama;
  `--install-aliases` writes `cloud-*` gateway aliases; `--pull` registers the tags;
  `--probe` reports disabled / signed-out / Pro-plan states instead of a raw HTTP error.
- **Provider routes for the same models**: `sovereign cloud --set-key openrouter` (or
  `deepseek`, `zai`, `moonshot`, `dashscope`) stores a key in `cloud.env` (mode 0600);
  `--install-aliases` then routes `cloud-*` through the first configured provider and
  falls back to Ollama Cloud. One OpenRouter key covers all eight, and
  `cloud-deepseek-v4-flash` uses the exact retired-from-Ollama V4 Flash model when a
  key is present. `--probe` tests whichever route will actually serve the request.
- `--enable` also updates the sourced `~/.config/sovereign-ai-os/profile.env`, which
  previously re-exported `OLLAMA_NO_CLOUD=1` in every new shell.
- **Claude Code is a real local agent**: `sovereign bridge` translates Anthropic
  Messages to a non-streaming gateway completion and back to Anthropic SSE with
  `tool_use` blocks. LiteLLM's streamed Ollama path returns tool calls as text;
  the bridge avoids it. `sovereign launch claude` starts the bridge automatically.
- **Codex is a real local agent through the tier gateway**: `tier_gateway.py`
  implements `/v1/responses` with Codex-compatible SSE events (`response.created`,
  `response.output_item.added`, `response.function_call_arguments.delta`,
  `response.completed`). Codex's local profile points at 4010, so it gets
  fast/balanced/deep routing; `--cloud` keeps the ChatGPT subscription path.
  Verified: Codex created a file in 2.4 s, second turn 0.55 s.
- **OpenCode is a real local agent**: the generated config uses a custom `local/`
  OpenAI-compatible provider instead of the built-in `ollama` provider (which
  streams tool calls as text), plus OpenRouter models and MCP.
- **MCP server** (`sovereign mcp`): models, best-model routing, skills, project
  memory, checks, and completions over stdio. `install-clients` registers it with
  Codex (shared by the ChatGPT app), Claude Desktop, Claude Code, OpenCode, and
  Qwen Code.
- **Skills everywhere**: `sovereign skills install --target all` converts the
  curated library into per-client `SKILL.md` folders and Continue prompt files;
  `--project` writes project skills plus a marker-managed index into `AGENTS.md`,
  `CLAUDE.md`, and `QWEN.md`.
- `sovereign launch` gained `--model TAG` and a `codium` client (VS Codium +
  Continue). `sovereign install-clients` now performs the whole client setup.
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
- **Direct mode** (`pipeline --mode direct|auto`, now the default): one request returns whole files in
  `<<<FILE: path>>> … <<<END>>>` blocks, which are parsed, path-checked (no `..`, no absolute
  paths, inside the project only) and written. Implement time dropped from **250–300 s to 17 s**
  on the same task, with the same verification and review. `auto` falls back to the agent loop when
  no blocks are produced; `--mode agent` keeps the old behaviour for complex multi-step refactors.
- `checks` prefer the project's venv interpreter (`.venv/bin/python`) when detecting pytest; the
  system python usually has no pytest, which made auto-detection fail on real projects.
- `pipeline` gained `--dry-run` (resolved models, checks and limits in under a second, no side
  effects), per-stage timings in `summary.txt`, and pre-loads the implementer so an 18 GB cold load
  is not mistaken for a provider failure.
- Agent runs are bounded with `--max-wall-time` / `--max-tool-calls`, and Qwen's exit code 55 is
  treated like our own timeout: keep the edits, let the checks decide. Measured on this Mac:
  `qwen` client ~4–5 min per implement step but reliable; `opencode` ~1 min but wrote no files.
- If a local agent hits `--agent-timeout` *after* writing files, the run continues to
  verification instead of discarding the work — Qwen Code frequently edits correctly and then
  fails to exit.
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

### Added
- **`sovereign launch codex --cloud`** runs the real ChatGPT models instead of the local stack.
  It refuses unless `codex login status` reports a session, prints a warning that prompts, code
  and diffs leave the Mac, launches Codex against the account's own `CODEX_HOME` with no local
  `--model`, and skips local GPU eviction. `chatgpt_login_status()` exposes the check, and the
  README documents all three auth routes (`codex login`, `--device-auth`, `--with-api-key`).
  Local mode remains the default; nothing switches to cloud on its own.

### Changed
- **Qwen 3.8 27B is now the primary local model** for every task it can serve: `CODING`,
  `AGENT`, `REASON`, `CHAT`, `VISION`, and `GENERAL`. `FAST` stays on the 4–9 GB models because
  it exists to answer before an 18 GB load finishes. With one model doing nearly everything,
  switching tasks no longer costs a reload.
- **One model resident at a time.** `OLLAMA_MAX_LOADED_MODELS` is 1 (was 2) in
  `com.user.ollama.env.plist`: two 18–20 GB models on 24 GB produced half-spilled runners
  (13%/87% CPU/GPU) and a reload per switch. The 27B now loads at 16k and reports **100% GPU**.
- **Gateway aliases follow the same model**: `local-chat`, `local-vision`, `local-vision-deep`,
  `local-thinking`, `local-reasoning`, `local-reasoning-deep`, and `local-browser-nav` all point
  at `qwen3.8:27b` (16k). `local-review` stays on `gemma4:12b` so the pipeline reviewer is still
  a different family from the implementer, and `local-claude` stays on `qwen3.5:9b` because
  Claude Code's tool prompt needs 64k. New `local-code-fast` keeps the 30B MoE one alias away.
- **Removed superseded weights**: `glm4`, `qwen2.5-coder:7b`, and `deepseek-r1:8b` (14 GB) plus
  their now-dangling `local-glm4` and `local-deepseek` aliases and fallbacks. `OPENCODE_MODELS`
  is untouched — it is a pick-list, not a live config.
- Qwen3.8-Flash-Next is documented as out of reach instead of being a silent dead end: it is
  125B-A6B with a 105 GB minimum artifact and needs `H100_X8`/`H200_X4` to serve, so it is
  deliberately absent from both `CATALOG` and `REMOTE_CATALOG`. The 27B is the largest Qwen 3.8
  that runs here.

### Fixed
- **Codex/“ChatGPT” goal runs actually execute tools now.** LiteLLM's *streaming* `/v1/responses`
  path returns a model tool call as plain `output_text` (the raw `{"name":…,"arguments":…}` blob)
  instead of a `function_call` item; Codex always streams, so it rendered the JSON as prose and
  never ran anything. Verified non-streaming works, so this was a translation bug, not the model.
  The Codex profile now points at Ollama's own `/v1/responses` (which streams a real
  `function_call`), and `sovereign launch codex` passes the same model.
- **Codex gets a 32k-capable model.** Its system + tool prompt is ~12.7k tokens, so the 18 GB
  27B — which cannot allocate 32k on 24 GB and dies with a Metal OOM — is the wrong pick. Codex
  now resolves through `CODEX_PREFERENCE` to `qwen3-coder:30b` (falling back to `qwen3.5:9b`),
  and `model_context_window` matches.
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
